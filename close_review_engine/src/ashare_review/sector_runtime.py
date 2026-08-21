from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from threading import Lock
from typing import Any

import pandas as pd

from ashare_review import sector_review as _base
from ashare_review.calendar import last_completed_trading_day
from ashare_review.indicators import finite
from ashare_review.sector_completeness import (
    FOCUS_PROXY_BASKETS,
    aggregate_proxy_history,
    build_focus_proxy_rows,
    enrich_board_from_constituents,
    fetch_tencent_histories,
)
from ashare_review.sector_data import fetch_board_constituents
from ashare_review.sector_integrity import (
    current_snapshot_matches_target,
    filter_overlapping_industry_conflicts,
)

_BaseLiveBoardProvider = _base.LiveBoardProvider
CONCEPT_BREADTH_LIMIT = 40
HISTORY_PROXY_COMPONENTS = 5
_SEMANTIC_CONFLICTS: list[dict[str, Any]] = []
_SEMANTIC_CONFLICT_LOCK = Lock()


class CrossSourceLiveBoardProvider(_BaseLiveBoardProvider):
    """Bridge current Sina boards to breadth and transparent proxy history.

    Sina is used only when its current snapshot corresponds to the requested
    completed session. Historical replays never relabel a newer live snapshot
    as the target date. Sina taxonomy conflicts are removed when an unrelated
    smaller first-level industry is almost entirely contained in another node.
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self._boards: dict[tuple[str, str], dict[str, Any]] = {}
        self._constituents: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._cache_lock = Lock()
        self._latest_completed = last_completed_trading_day()

    def _current_snapshot_allowed(self, target_date: date) -> bool:
        return current_snapshot_matches_target(
            target_date,
            latest_completed=self._latest_completed,
        )

    def _remember(self, board_type: str, row: dict[str, Any]) -> tuple[str, str]:
        key = (board_type, str(row.get("board_code") or ""))
        if key[1]:
            with self._cache_lock:
                self._boards[key] = dict(row)
        return key

    def _constituents_for(
        self,
        board_type: str,
        board_code: str,
        target_date: date,
    ) -> list[dict[str, Any]]:
        key = (board_type, board_code)
        with self._cache_lock:
            cached = self._constituents.get(key)
            board = dict(self._boards.get(key) or {})
        if cached is not None:
            return cached
        if not self._current_snapshot_allowed(target_date) and not board_code.upper().startswith("BK"):
            raise ValueError(
                f"新浪板块成份仅代表{self._latest_completed.isoformat()}，"
                f"不能用于历史目标日{target_date.isoformat()}"
            )
        rows = fetch_board_constituents(
            self.client,
            board_code,
            board_type=board_type,
            board_name=str(board.get("board_name") or ""),
            target_date=target_date,
        )
        if not self._current_snapshot_allowed(target_date) and any(
            "新浪" in str(row.get("source") or "") for row in rows
        ):
            raise ValueError(
                f"新浪板块成份日期与历史目标日{target_date.isoformat()}不一致"
            )
        with self._cache_lock:
            self._constituents.setdefault(key, rows)
            return self._constituents[key]

    def overview(self, board_type: str, target_date: date) -> list[dict[str, Any]]:
        rows = super().overview(board_type, target_date)
        if not self._current_snapshot_allowed(target_date):
            live_rows = [
                row for row in rows if "新浪" in str(row.get("source") or "")
            ]
            if live_rows:
                rows = [
                    row for row in rows if "新浪" not in str(row.get("source") or "")
                ]
                if not rows:
                    raise ValueError(
                        f"新浪板块快照属于{self._latest_completed.isoformat()}，"
                        f"不能冒充历史目标日{target_date.isoformat()}"
                    )
        for row in rows:
            self._remember(board_type, row)

        candidates = rows
        if board_type == "concept":
            candidates = sorted(
                rows,
                key=lambda row: (
                    finite(row.get("pct_change"), -999.0) or -999.0,
                    finite(row.get("amount"), 0.0) or 0.0,
                ),
                reverse=True,
            )[:CONCEPT_BREADTH_LIMIT]
        candidates = [
            row
            for row in candidates
            if int(row.get("up_count") or 0) + int(row.get("down_count") or 0) == 0
        ]
        if not candidates:
            return rows

        enriched: dict[tuple[str, str], dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(
                    self._constituents_for,
                    board_type,
                    str(row.get("board_code") or ""),
                    target_date,
                ): row
                for row in candidates
            }
            for future in as_completed(futures):
                row = futures[future]
                key = (board_type, str(row.get("board_code") or ""))
                try:
                    enriched[key] = enrich_board_from_constituents(row, future.result())
                except Exception:  # noqa: BLE001
                    continue

        output: list[dict[str, Any]] = []
        for row in rows:
            key = (board_type, str(row.get("board_code") or ""))
            current = enriched.get(key, row)
            output.append(current)
            self._remember(board_type, current)

        if board_type == "industry":
            with self._cache_lock:
                membership = {
                    str(row.get("board_code") or ""): list(
                        self._constituents.get(
                            (board_type, str(row.get("board_code") or "")),
                            (),
                        )
                    )
                    for row in output
                }
            output, conflicts = filter_overlapping_industry_conflicts(
                output,
                membership,
            )
            with _SEMANTIC_CONFLICT_LOCK:
                _SEMANTIC_CONFLICTS.clear()
                _SEMANTIC_CONFLICTS.extend(conflicts)
        return output

    def history(self, board_type: str, board_code: str, target_date: date) -> pd.DataFrame:
        try:
            native = super().history(board_type, board_code, target_date)
        except Exception:  # noqa: BLE001
            native = pd.DataFrame()
        if len(native) >= 21:
            native.attrs["source"] = "东方财富板块历史K线"
            native.attrs["component_count"] = None
            return native

        try:
            rows = self._constituents_for(board_type, board_code, target_date)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
        liquid = sorted(
            rows,
            key=lambda row: finite(row.get("amount"), 0.0) or 0.0,
            reverse=True,
        )
        codes = [
            str(row.get("code") or "").zfill(6)
            for row in liquid[:HISTORY_PROXY_COMPONENTS]
            if row.get("code")
        ]
        histories = fetch_tencent_histories(
            self.client,
            codes,
            target_date=target_date,
            max_workers=1,
        )
        return aggregate_proxy_history(histories, target_date=target_date)

    def constituents(
        self,
        board_type: str,
        board_code: str,
        target_date: date,
    ) -> list[dict[str, Any]]:
        return self._constituents_for(board_type, board_code, target_date)


_base_score_board = _base.score_board


def _score_board_with_provenance(
    board: dict[str, Any],
    history: pd.DataFrame,
    *,
    market_median: float,
) -> dict[str, Any]:
    result = _base_score_board(board, history, market_median=market_median)
    history_source = str(history.attrs.get("source") or "")
    component_count = history.attrs.get("component_count")
    if history_source:
        result["history_source"] = history_source
        result["history_component_count"] = component_count
    if "代理" in history_source:
        total = int(result.get("up_count") or 0) + int(result.get("down_count") or 0)
        result["confidence"] = "medium" if len(history) >= 21 and total > 0 else "partial"
        flags = list(result.get("risk_flags") or [])
        if "板块历史为成份股等权代理" not in flags:
            flags.append("板块历史为成份股等权代理")
        result["risk_flags"] = flags
    return result


# build_sector_review resolves these globals at call time. Replace them once so
# production, manual runs and smoke tests share identical integrity gates.
_base.LiveBoardProvider = CrossSourceLiveBoardProvider
_base.score_board = _score_board_with_provenance
_base_build_sector_review = _base.build_sector_review


def build_sector_review(
    source: Any,
    market: dict[str, Any],
    *,
    target_date: date,
    previous_snapshot: dict[str, Any] | None,
    max_workers: int,
    config_path: str = "config/sector_monitor.yml",
) -> dict[str, Any]:
    result = _base_build_sector_review(
        source,
        market,
        target_date=target_date,
        previous_snapshot=previous_snapshot,
        max_workers=max_workers,
        config_path=config_path,
    )
    with _SEMANTIC_CONFLICT_LOCK:
        conflicts = [dict(row) for row in _SEMANTIC_CONFLICTS]
    if conflicts:
        result.setdefault("source_status", []).append(
            {
                "source": "新浪行业分类一致性校验",
                "ok": True,
                "dropped": len(conflicts),
                "conflicts": conflicts,
                "date": target_date.isoformat(),
            }
        )

    if not hasattr(source, "client"):
        return result

    focus_rows = list(result.get("focus_concepts") or [])
    missing_labels = {
        str(row.get("focus_label") or "")
        for row in focus_rows
        if row.get("status") != "ready"
    }
    proxy_codes = tuple(
        dict.fromkeys(
            code
            for label in missing_labels
            for code in FOCUS_PROXY_BASKETS.get(label, ())
        )
    )
    if not proxy_codes:
        return result
    histories = fetch_tencent_histories(
        source.client,
        proxy_codes,
        target_date=target_date,
        max_workers=max_workers,
        max_price=100.0,
    )
    market_median = float((market.get("breadth") or {}).get("median_pct") or 0.0)
    result["focus_concepts"] = build_focus_proxy_rows(
        focus_rows,
        histories,
        target_date=target_date,
        market_median=market_median,
    )
    result.setdefault("source_status", []).append(
        {
            "source": "现代主题主板代理篮子",
            "ok": bool(histories),
            "rows": len(histories),
            "date": target_date.isoformat(),
            "note": "仅补充新浪旧概念分类缺失项，明确标注为非官方概念指数",
        }
    )
    return result


__all__ = ["CrossSourceLiveBoardProvider", "build_sector_review"]
