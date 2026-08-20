from __future__ import annotations

from datetime import date
from typing import Any, Iterable

import pandas as pd

from ashare_review.data import HttpClient, fetch_eastmoney_kline
from ashare_review.indicators import finite
from ashare_review.sector_config import FocusConcept

BOARD_LIST_HOSTS = (
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://17.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
BOARD_CONSTITUENT_HOSTS = (
    "https://29.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)


def _as_int(value: Any) -> int:
    numeric = finite(value, 0.0) or 0.0
    return int(numeric)


def normalize_board_overview(
    rows: Iterable[dict[str, Any]],
    board_type: str,
    target_date: date,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in rows:
        code = str(item.get("board_code") or item.get("f12") or "").strip()
        name = str(item.get("board_name") or item.get("f14") or "").strip()
        if not code or not name:
            continue
        output.append(
            {
                "board_code": code,
                "board_name": name,
                "board_type": board_type,
                "latest": finite(item.get("latest", item.get("f2"))),
                "pct_change": finite(item.get("pct_change", item.get("f3"))),
                "amount": finite(item.get("amount", item.get("f6"))),
                "turnover_rate": finite(item.get("turnover_rate", item.get("f8"))),
                "market_cap": finite(item.get("market_cap", item.get("f20"))),
                "up_count": _as_int(item.get("up_count", item.get("f104"))),
                "down_count": _as_int(item.get("down_count", item.get("f105"))),
                "limit_up_count": _as_int(item.get("limit_up_count", 0)),
                "leader_name": str(item.get("leader_name") or item.get("f128") or "").strip(),
                "leader_pct_change": finite(
                    item.get("leader_pct_change", item.get("f136"))
                ),
                "data_date": target_date.isoformat(),
                "source": str(item.get("source") or "东方财富板块行情"),
            }
        )
    return output


def normalize_board_constituents(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in rows:
        code = str(item.get("code") or item.get("f12") or "").strip().zfill(6)
        name = str(item.get("name") or item.get("f14") or "").strip()
        if not code or not name:
            continue
        output.append(
            {
                "code": code,
                "name": name,
                "close": finite(item.get("close", item.get("f2"))),
                "pct_change": finite(item.get("pct_change", item.get("f3"))),
                "volume": finite(item.get("volume", item.get("f5"))),
                "amount": finite(item.get("amount", item.get("f6"))),
                "turnover_rate": finite(item.get("turnover_rate", item.get("f8"))),
                "high": finite(item.get("high", item.get("f15"))),
                "low": finite(item.get("low", item.get("f16"))),
                "open": finite(item.get("open", item.get("f17"))),
                "previous_close": finite(item.get("previous_close", item.get("f18"))),
                "market_cap": finite(item.get("market_cap", item.get("f20"))),
                "float_market_cap": finite(
                    item.get("float_market_cap", item.get("f21"))
                ),
                "source": str(item.get("source") or "东方财富板块成份"),
            }
        )
    return output


def _fetch_paginated(
    client: HttpClient,
    hosts: tuple[str, ...],
    params: dict[str, Any],
    *,
    max_pages: int,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for host in hosts:
        collected: list[dict[str, Any]] = []
        try:
            for page in range(1, max_pages + 1):
                page_params = dict(params)
                page_params["pn"] = page
                payload = client.get_json(host, params=page_params)
                data = payload.get("data")
                rows = data.get("diff") if isinstance(data, dict) else None
                if not isinstance(rows, list) or not rows:
                    break
                collected.extend(item for item in rows if isinstance(item, dict))
                total = _as_int(data.get("total")) if isinstance(data, dict) else 0
                if len(collected) >= total or len(rows) < int(page_params["pz"]):
                    break
            if collected:
                return collected
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def fetch_board_overview(
    client: HttpClient,
    board_type: str,
    target_date: date,
) -> list[dict[str, Any]]:
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"unsupported board type: {board_type}")
    board_filter = "m:90 t:2 f:!50" if board_type == "industry" else "m:90 t:3 f:!50"
    rows = _fetch_paginated(
        client,
        BOARD_LIST_HOSTS,
        {
            "pz": 500,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": board_filter,
            "fields": "f2,f3,f6,f8,f12,f14,f20,f104,f105,f128,f136",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        },
        max_pages=4,
    )
    return normalize_board_overview(rows, board_type, target_date)


def fetch_board_history(
    client: HttpClient,
    board_code: str,
    target_date: date,
    *,
    limit: int = 45,
) -> pd.DataFrame:
    return fetch_eastmoney_kline(
        client,
        f"90.{board_code}",
        period=101,
        limit=limit,
        target_date=target_date,
    )


def fetch_board_constituents(
    client: HttpClient,
    board_code: str,
) -> list[dict[str, Any]]:
    rows = _fetch_paginated(
        client,
        BOARD_CONSTITUENT_HOSTS,
        {
            "pz": 500,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f6",
            "fs": f"b:{board_code} f:!50",
            "fields": "f2,f3,f5,f6,f8,f12,f14,f15,f16,f17,f18,f20,f21",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        },
        max_pages=6,
    )
    return normalize_board_constituents(rows)


def _focus_match_score(board_name: str, focus: FocusConcept) -> int:
    if board_name == focus.label:
        return 100
    score = 0
    for alias in focus.aliases:
        if board_name == alias:
            score = max(score, 90)
        elif alias and alias in board_name:
            score = max(score, 70 + min(len(alias), 10))
        elif board_name and board_name in alias:
            score = max(score, 50 + min(len(board_name), 10))
    return score


def match_focus_concepts(
    boards: Iterable[dict[str, Any]],
    focus_concepts: Iterable[FocusConcept],
) -> list[dict[str, Any]]:
    concept_rows = [row for row in boards if row.get("board_type") == "concept"]
    matched: list[dict[str, Any]] = []
    used_codes: set[str] = set()
    for focus in focus_concepts:
        candidates = []
        for row in concept_rows:
            code = str(row.get("board_code") or "")
            score = _focus_match_score(str(row.get("board_name") or ""), focus)
            if score > 0 and code not in used_codes:
                candidates.append(
                    (
                        score,
                        finite(row.get("pct_change"), -999.0) or -999.0,
                        row,
                    )
                )
        if not candidates:
            matched.append(
                {
                    "focus_label": focus.label,
                    "status": "data_unavailable",
                    "board_type": "concept",
                    "board_code": None,
                    "board_name": None,
                }
            )
            continue
        _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
        selected_copy = dict(selected)
        selected_copy["focus_label"] = focus.label
        selected_copy["status"] = "ready"
        matched.append(selected_copy)
        used_codes.add(str(selected.get("board_code") or ""))
    return matched
