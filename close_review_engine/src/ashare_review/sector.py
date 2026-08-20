from __future__ import annotations

import math
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
DEFAULT_MAX_PRICE = 100.0
DEFAULT_MIN_AMOUNT = 300_000_000.0

FIXED_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "AI算力": ("算力", "东数西算", "数据中心", "服务器"),
    "CPO": ("CPO", "光模块", "光通信"),
    "PCB": ("PCB", "印制电路板", "覆铜板"),
    "半导体": ("半导体", "芯片"),
    "存储": ("存储芯片", "存储器", "存储"),
    "稀土": ("稀土永磁", "稀土"),
}

ROLE_LABELS = {
    "capacity_leader": "资金容量龙头",
    "elasticity_leader": "弹性龙头",
    "pullback_candidate": "缩量回踩型高潜力",
    "breakout_candidate": "放量突破型高潜力",
}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _safe_rank(values: list[float]) -> list[float]:
    if not values:
        return []
    series = pd.Series(values, dtype=float)
    if len(series) == 1:
        return [1.0]
    ranked = series.rank(method="average", pct=True)
    return [float(value) for value in ranked]


def _rating(score: float) -> str:
    if score >= 90:
        return "S"
    if score >= 87:
        return "A+"
    if score >= 83:
        return "A"
    if score >= 80:
        return "A-"
    if score >= 75:
        return "B+"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def is_main_board_code(code: Any) -> bool:
    text = str(code or "").strip()
    return len(text) == 6 and text.isdigit() and text.startswith(MAIN_BOARD_PREFIXES)


def _is_risk_name(name: Any) -> bool:
    text = str(name or "").strip().upper().replace(" ", "")
    if not text:
        return True
    return (
        "ST" in text
        or "退" in text
        or text.startswith("N")
        or text.startswith("C")
    )


def _is_one_price_limit(row: pd.Series) -> bool:
    close = _number(row.get("close"))
    high = _number(row.get("high"))
    low = _number(row.get("low"))
    pct_change = _number(row.get("pct_change"), 0.0) or 0.0
    if close in (None, 0) or high is None or low is None:
        return False
    return abs(high - low) <= max(abs(close) * 0.0001, 0.001) and pct_change >= 9.5


def filter_eligible_candidates(
    source: pd.DataFrame,
    *,
    max_price: float = DEFAULT_MAX_PRICE,
    min_amount: float = DEFAULT_MIN_AMOUNT,
) -> pd.DataFrame:
    """Apply the user's hard short-term universe constraints.

    Only Shanghai/Shenzhen main-board ordinary A shares with completed close
    not above RMB 100 are retained. ST/delisting/new-listing names, suspended
    rows, one-price limit-ups and materially illiquid rows are rejected.
    """
    if source.empty:
        return source.copy()
    frame = source.copy()
    if "code" not in frame.columns:
        return frame.iloc[0:0].copy()
    frame["code"] = frame["code"].astype(str).str.extract(r"(\d{6})", expand=False)
    for column in (
        "close",
        "pct_change",
        "amount",
        "turnover_rate",
        "open",
        "high",
        "low",
        "volume",
        "market_cap",
        "float_market_cap",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "name" not in frame.columns:
        frame["name"] = ""
    mask = frame["code"].map(is_main_board_code)
    mask &= ~frame["name"].map(_is_risk_name)
    mask &= frame.get("close", pd.Series(index=frame.index, dtype=float)).gt(0)
    mask &= frame.get("close", pd.Series(index=frame.index, dtype=float)).le(max_price)
    mask &= frame.get("amount", pd.Series(index=frame.index, dtype=float)).ge(min_amount)
    if "volume" in frame.columns:
        mask &= frame["volume"].fillna(0).gt(0)
    filtered = frame.loc[mask].copy()
    if not filtered.empty:
        filtered = filtered.loc[~filtered.apply(_is_one_price_limit, axis=1)].copy()
    return filtered.sort_values(
        [column for column in ("amount", "turnover_rate", "pct_change") if column in filtered.columns],
        ascending=False,
        na_position="last",
    ).reset_index(drop=True)


def _normalise_sector_row(row: dict[str, Any], kind: str) -> dict[str, Any]:
    label = str(row.get("label") or row.get("sector_code") or row.get("board_code") or "").strip()
    name = str(
        row.get("sector_name")
        or row.get("industry")
        or row.get("board")
        or row.get("name")
        or label
    ).strip()
    return {
        **row,
        "kind": kind,
        "label": label,
        "sector_name": name,
        "sector_id": f"{kind}:{label or name}",
        "pct_change": _number(row.get("pct_change"), 0.0) or 0.0,
        "amount": _number(row.get("amount"), 0.0) or 0.0,
        "count": int(_number(row.get("count"), 0.0) or 0),
        "leader_pct_change": _number(
            row.get("leader_pct_change", row.get("leader_pct")),
            0.0,
        )
        or 0.0,
    }


def rank_sector_rows(
    rows: Iterable[dict[str, Any]],
    *,
    kind: str,
    market_median_pct: float | None = None,
) -> list[dict[str, Any]]:
    """Rank industry or concept boards with the agreed six-part 100-point model.

    When 5/20-day history or constituent breadth is unavailable, the model uses
    a neutral midpoint and explicitly marks the field unverified rather than
    inventing persistence.
    """
    normalised = [_normalise_sector_row(dict(row), kind) for row in rows]
    if not normalised:
        return []
    day_values = [float(row["pct_change"]) for row in normalised]
    amount_values = [float(row["amount"]) for row in normalised]
    leader_values = [float(row["leader_pct_change"]) for row in normalised]
    day_ranks = _safe_rank(day_values)
    amount_ranks = _safe_rank(amount_values)
    leader_ranks = _safe_rank(leader_values)
    median_pct = _number(market_median_pct, 0.0) or 0.0

    ranked: list[dict[str, Any]] = []
    for index, row in enumerate(normalised):
        day_rank = day_ranks[index]
        relative_bonus = float(np.clip((row["pct_change"] - median_pct) / 5.0, -0.2, 0.2))
        relative_strength = float(np.clip(20 * (day_rank + relative_bonus), 0, 20))

        return_5d = _number(row.get("return_5d"))
        return_20d = _number(row.get("return_20d"))
        if return_5d is None or return_20d is None:
            persistence = 10.0
            persistence_status = "unverified"
        else:
            persistence = float(
                np.clip(10 + return_5d * 0.7 + return_20d * 0.25, 0, 20)
            )
            persistence_status = "verified"

        liquidity = float(np.clip(amount_ranks[index] * 20, 0, 20))
        up = _number(row.get("up"))
        down = _number(row.get("down"))
        limit_up = _number(row.get("limit_up"), 0.0) or 0.0
        if up is None or down is None or up + down <= 0:
            breadth = 7.5
            breadth_status = "unverified"
        else:
            up_ratio = up / (up + down)
            breadth = float(np.clip(up_ratio * 12 + min(limit_up, 6) * 0.5, 0, 15))
            breadth_status = "verified"

        leadership = float(np.clip(leader_ranks[index] * 15, 0, 15))
        event_score = _number(row.get("event_score"), 5.0) or 5.0
        catalyst_risk = float(np.clip(event_score, 0, 10))
        components = {
            "relative_strength": round(relative_strength, 1),
            "persistence": round(persistence, 1),
            "liquidity": round(liquidity, 1),
            "breadth": round(breadth, 1),
            "leadership": round(leadership, 1),
            "catalyst_risk": round(catalyst_risk, 1),
        }
        score = round(sum(components.values()), 1)
        ranked.append(
            {
                **row,
                "score": score,
                "rating": _rating(score),
                "score_components": components,
                "persistence_status": persistence_status,
                "breadth_status": breadth_status,
                "relative_market_pct": round(float(row["pct_change"]) - median_pct, 3),
            }
        )
    ranked.sort(
        key=lambda row: (
            float(row.get("score") or 0),
            float(row.get("pct_change") or 0),
            float(row.get("amount") or 0),
        ),
        reverse=True,
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked


def _previous_sector_map(previous_snapshot: dict[str, Any] | None) -> dict[str, int]:
    if not previous_snapshot:
        return {}
    sector_analysis = previous_snapshot.get("sector_analysis") or {}
    rows = list(sector_analysis.get("industry_ranking") or [])
    rows.extend(sector_analysis.get("concept_ranking") or [])
    output: dict[str, int] = {}
    for row in rows:
        sector_id = str(row.get("sector_id") or "")
        rank = _number(row.get("rank"))
        if sector_id and rank is not None:
            output[sector_id] = int(rank)
    return output


def select_key_sectors(
    industry_ranking: Iterable[dict[str, Any]],
    concept_ranking: Iterable[dict[str, Any]],
    *,
    previous_snapshot: dict[str, Any] | None = None,
    top_n: int = 5,
    max_risers: int = 2,
) -> list[dict[str, Any]]:
    combined = [dict(row) for row in industry_ranking]
    combined.extend(dict(row) for row in concept_ranking)
    combined.sort(
        key=lambda row: (
            float(row.get("score") or 0),
            float(row.get("pct_change") or 0),
        ),
        reverse=True,
    )
    selected = combined[: max(0, top_n)]
    selected_ids = {str(row.get("sector_id")) for row in selected}
    previous = _previous_sector_map(previous_snapshot)
    risers: list[tuple[int, dict[str, Any]]] = []
    for row in combined:
        sector_id = str(row.get("sector_id") or "")
        if not sector_id or sector_id in selected_ids or sector_id not in previous:
            continue
        current_rank = int(_number(row.get("rank"), 999) or 999)
        improvement = previous[sector_id] - current_rank
        if improvement >= 3:
            risers.append((improvement, row))
    risers.sort(
        key=lambda item: (
            item[0],
            float(item[1].get("score") or 0),
        ),
        reverse=True,
    )
    for improvement, row in risers[: max(0, max_risers)]:
        candidate = dict(row)
        candidate["selection_reason"] = f"较上次排名提升{improvement}位"
        selected.append(candidate)
        selected_ids.add(str(candidate.get("sector_id")))
    for row in selected:
        row.setdefault("selection_reason", "当日板块综合评分领先")
    return selected


def match_fixed_concepts(concept_ranking: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in concept_ranking]
    output: list[dict[str, Any]] = []
    for display_name, aliases in FIXED_CONCEPT_ALIASES.items():
        matches = [
            row
            for row in rows
            if any(alias.upper() in str(row.get("sector_name") or "").upper() for alias in aliases)
        ]
        if not matches:
            output.append(
                {
                    "display_name": display_name,
                    "status": "not_found",
                    "sector_name": None,
                    "pct_change": None,
                    "score": None,
                }
            )
            continue
        best = max(matches, key=lambda row: float(row.get("score") or 0))
        output.append({"display_name": display_name, "status": "matched", **best})
    return output


def _candidate_metric(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if key == "relative_volume_20" and value is None:
        value = (row.get("volume") or {}).get("relative_to_20d") if isinstance(row.get("volume"), dict) else None
    return float(_number(value, default) or default)


def _decorate_role(row: dict[str, Any], role: str, reason: str) -> dict[str, Any]:
    return {
        **row,
        "role": role,
        "role_label": ROLE_LABELS[role],
        "selection_reason": reason,
    }


def assign_sector_roles(candidates: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    """Assign distinct 2+2 roles without padding low-quality names."""
    rows = [dict(row) for row in candidates if _number(row.get("close"), 0) and _number(row.get("close"), 0) <= 100]
    roles: dict[str, dict[str, Any] | None] = {key: None for key in ROLE_LABELS}
    used: set[str] = set()
    if not rows:
        return roles

    capacity = max(rows, key=lambda row: _candidate_metric(row, "amount"))
    roles["capacity_leader"] = _decorate_role(
        capacity,
        "capacity_leader",
        "板块内成交额和承载力最高，作为资金容量锚。",
    )
    used.add(str(capacity.get("code")))

    remaining = [row for row in rows if str(row.get("code")) not in used]
    if remaining:
        elasticity = max(
            remaining,
            key=lambda row: (
                _candidate_metric(row, "pct_change") * 0.55
                + _candidate_metric(row, "turnover_rate") * 0.25
                + _candidate_metric(row, "relative_volume_20") * 2.0
            ),
        )
        roles["elasticity_leader"] = _decorate_role(
            elasticity,
            "elasticity_leader",
            "板块内涨幅、换手和相对量能组合最强，作为短线弹性锚。",
        )
        used.add(str(elasticity.get("code")))

    remaining = [row for row in rows if str(row.get("code")) not in used]
    pullback_rows: list[tuple[float, dict[str, Any]]] = []
    for row in remaining:
        patterns = {str(item) for item in row.get("patterns", [])}
        levels = row.get("levels") or {}
        close = _candidate_metric(row, "close")
        low = _number(levels.get("pullback_low"))
        high = _number(levels.get("pullback_high"))
        in_zone = low is not None and high is not None and low <= close <= high
        rel_volume = _candidate_metric(row, "relative_volume_20", 1.0)
        pct_change = _candidate_metric(row, "pct_change")
        if "缩量回踩" not in patterns and not in_zone:
            continue
        if rel_volume > 1.25 or not -3.5 <= pct_change <= 4.0:
            continue
        score = (2 if "缩量回踩" in patterns else 1) + max(0, 1.25 - rel_volume)
        pullback_rows.append((score, row))
    if pullback_rows:
        pullback = max(pullback_rows, key=lambda item: item[0])[1]
        roles["pullback_candidate"] = _decorate_role(
            pullback,
            "pullback_candidate",
            "趋势未失效且处于缩量回踩/支撑区，等待止跌确认。",
        )
        used.add(str(pullback.get("code")))

    remaining = [row for row in rows if str(row.get("code")) not in used]
    breakout_rows: list[tuple[float, dict[str, Any]]] = []
    for row in remaining:
        patterns = {str(item) for item in row.get("patterns", [])}
        levels = row.get("levels") or {}
        close = _candidate_metric(row, "close")
        trigger = _number(levels.get("breakout_trigger"))
        if close <= 0 or trigger is None:
            continue
        gap = trigger / close - 1
        rel_volume = _candidate_metric(row, "relative_volume_20", 1.0)
        pct_change = _candidate_metric(row, "pct_change")
        if "放量突破" not in patterns and not 0 <= gap <= 0.03:
            continue
        if rel_volume < 1.05 or pct_change > 8.0:
            continue
        score = (2 if "放量突破" in patterns else 1) + max(0, 0.03 - gap) * 20 + rel_volume * 0.2
        breakout_rows.append((score, row))
    if breakout_rows:
        breakout = max(breakout_rows, key=lambda item: item[0])[1]
        roles["breakout_candidate"] = _decorate_role(
            breakout,
            "breakout_candidate",
            "距结构突破位较近且量能改善，仅在放量确认后考虑。",
        )
    return roles


def compact_dynamic_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Keep only report-relevant fields for the persisted dynamic pool."""
    fields = (
        "code",
        "name",
        "close",
        "pct_change",
        "amount",
        "turnover_rate",
        "score",
        "rating",
        "daily_trend",
        "weekly_trend",
        "trend_60m",
        "patterns",
        "levels",
        "data_date",
        "data_confidence",
        "role",
        "role_label",
        "selection_reason",
    )
    return {field: row.get(field) for field in fields if field in row}


def sector_rank_changes(
    current: Iterable[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    previous = _previous_sector_map(previous_snapshot)
    changes: list[dict[str, Any]] = []
    for row in current:
        sector_id = str(row.get("sector_id") or "")
        if sector_id not in previous:
            continue
        current_rank = int(_number(row.get("rank"), 999) or 999)
        delta = previous[sector_id] - current_rank
        if abs(delta) >= 3:
            changes.append(
                {
                    "sector_id": sector_id,
                    "sector_name": row.get("sector_name"),
                    "previous_rank": previous[sector_id],
                    "current_rank": current_rank,
                    "change": delta,
                }
            )
    return sorted(changes, key=lambda row: abs(int(row["change"])), reverse=True)
