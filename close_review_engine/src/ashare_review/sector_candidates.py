from __future__ import annotations

import math
from typing import Any, Iterable

from ashare_review.config import StockConfig
from ashare_review.indicators import finite
from ashare_review.sector_config import SectorMonitorConfig, is_eligible_main_board

ROLE_LABELS = {
    "capacity_leader": "资金容量龙头",
    "momentum_leader": "弹性龙头",
    "pullback_potential": "缩量回踩潜力",
    "breakout_potential": "放量突破潜力",
}
TREND_RANK = {
    "强势多头": 7,
    "多头": 6,
    "偏多震荡": 5,
    "震荡": 4,
    "偏空震荡": 3,
    "空头": 2,
    "强势空头": 1,
    "数据不足": 0,
}


def _percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    return sum(item <= value for item in values) / len(values)


def shortlist_constituents(
    rows: Iterable[dict[str, Any]],
    config: SectorMonitorConfig,
) -> list[dict[str, Any]]:
    eligible = [dict(row) for row in rows if is_eligible_main_board(row, config)]
    if not eligible:
        return []
    amounts = [finite(row.get("amount"), 0.0) or 0.0 for row in eligible]
    pcts = [finite(row.get("pct_change"), 0.0) or 0.0 for row in eligible]
    turnovers = [finite(row.get("turnover_rate"), 0.0) or 0.0 for row in eligible]
    for row in eligible:
        amount = finite(row.get("amount"), 0.0) or 0.0
        pct = finite(row.get("pct_change"), 0.0) or 0.0
        turnover = finite(row.get("turnover_rate"), 0.0) or 0.0
        row["shortlist_score"] = round(
            _percentile(amounts, amount) * 55
            + _percentile(pcts, pct) * 25
            + _percentile(turnovers, turnover) * 20,
            2,
        )
    eligible.sort(
        key=lambda row: (
            finite(row.get("shortlist_score"), 0.0) or 0.0,
            finite(row.get("amount"), 0.0) or 0.0,
        ),
        reverse=True,
    )
    return eligible[: config.shortlist_per_board]


def make_dynamic_stock_config(
    row: dict[str, Any],
    board: dict[str, Any],
) -> StockConfig:
    code = str(row.get("code") or "").zfill(6)
    exchange = "SH" if code.startswith(("600", "601", "603", "605")) else "SZ"
    board_name = str(board.get("board_name") or "动态板块")
    board_type = str(board.get("board_type") or "concept")
    industry = board_name if board_type == "industry" else "动态概念"
    themes = (board_name,) if board_type == "concept" else ()
    industry_logic = max(50.0, min(95.0, finite(board.get("score"), 70.0) or 70.0))
    return StockConfig(
        code=code,
        name=str(row.get("name") or code),
        exchange=exchange,
        industry=industry,
        themes=themes,
        industry_logic=industry_logic,
    )


def _candidate_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row.get("candidate_snapshot") or {})


def _capacity_score(row: dict[str, Any], all_rows: list[dict[str, Any]]) -> float:
    snapshot = _candidate_snapshot(row)
    amounts = [finite(_candidate_snapshot(item).get("amount"), 0.0) or 0.0 for item in all_rows]
    caps = [finite(_candidate_snapshot(item).get("float_market_cap"), 0.0) or 0.0 for item in all_rows]
    amount = finite(snapshot.get("amount"), 0.0) or 0.0
    cap = finite(snapshot.get("float_market_cap"), 0.0) or 0.0
    return (
        _percentile(amounts, amount) * 55
        + _percentile(caps, cap) * 20
        + TREND_RANK.get(str(row.get("daily_trend")), 0) * 2
        + TREND_RANK.get(str(row.get("weekly_trend")), 0)
        + (8 if row.get("data_confidence") == "high" else 3)
    )


def _momentum_score(row: dict[str, Any], all_rows: list[dict[str, Any]]) -> float:
    snapshot = _candidate_snapshot(row)
    pcts = [finite(item.get("pct_change"), 0.0) or 0.0 for item in all_rows]
    turns = [finite(_candidate_snapshot(item).get("turnover_rate"), 0.0) or 0.0 for item in all_rows]
    pct = finite(row.get("pct_change"), 0.0) or 0.0
    turnover = finite(snapshot.get("turnover_rate"), 0.0) or 0.0
    score = _percentile(pcts, pct) * 45 + _percentile(turns, turnover) * 25
    score += TREND_RANK.get(str(row.get("trend_60m")), 0) * 3
    if "放量突破" in row.get("patterns", []):
        score += 12
    if any("顶背离" in flag for flag in row.get("patterns", [])):
        score -= 15
    return score


def _pullback_score(row: dict[str, Any]) -> float | None:
    levels = row.get("levels") or {}
    if levels.get("status") != "ready":
        return None
    # A potential setup may still be in a neutral daily structure. It is not
    # labelled a buy signal and still rejects strong 60-minute deterioration.
    if TREND_RANK.get(str(row.get("daily_trend")), 0) < TREND_RANK["震荡"]:
        return None
    if row.get("trend_60m") == "强势空头":
        return None
    rel_volume = finite((row.get("metrics") or {}).get("rel_volume_20"))
    if rel_volume is None or rel_volume > 1.20:
        return None
    close = finite(row.get("close"))
    low = finite(levels.get("pullback_low"))
    high = finite(levels.get("pullback_high"))
    if None in (close, low, high):
        return None
    zone_mid = (float(low) + float(high)) / 2
    distance = abs(float(close) - zone_mid) / max(zone_mid, 0.01)
    if distance > 0.12 and "缩量回踩" not in row.get("patterns", []):
        return None
    return (
        100
        - min(distance * 450, 45)
        + (15 if "缩量回踩" in row.get("patterns", []) else 0)
        + (1.20 - rel_volume) * 18
        + TREND_RANK.get(str(row.get("trend_60m")), 0)
    )


def _breakout_score(row: dict[str, Any]) -> float | None:
    levels = row.get("levels") or {}
    if levels.get("status") != "ready":
        return None
    if TREND_RANK.get(str(row.get("daily_trend")), 0) < TREND_RANK["震荡"]:
        return None
    if row.get("trend_60m") == "强势空头":
        return None
    close = finite(row.get("close"))
    trigger = finite(levels.get("breakout_trigger"))
    if close in (None, 0) or trigger is None:
        return None
    distance = trigger / close - 1
    if not 0 <= distance <= 0.08:
        return None
    rel_volume = finite((row.get("metrics") or {}).get("rel_volume_20"), 1.0) or 1.0
    if rel_volume > 2.5:
        return None
    return (
        100
        - distance * 800
        + min(rel_volume, 1.8) * 10
        + TREND_RANK.get(str(row.get("trend_60m")), 0) * 2
    )


def _pick_payload(role: str, row: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "role": role,
        "role_label": ROLE_LABELS[role],
        "status": "ready",
        "code": row.get("code"),
        "name": row.get("name"),
        "close": row.get("close"),
        "pct_change": row.get("pct_change"),
        "daily_trend": row.get("daily_trend"),
        "weekly_trend": row.get("weekly_trend"),
        "trend_60m": row.get("trend_60m"),
        "patterns": row.get("patterns") or [],
        "levels": row.get("levels") or {},
        "metrics": row.get("metrics") or {},
        "data_confidence": row.get("data_confidence"),
        "reason": reason,
    }


def _missing_payload(role: str) -> dict[str, Any]:
    return {
        "role": role,
        "role_label": ROLE_LABELS[role],
        "status": "no_qualified_stock",
        "code": None,
        "name": None,
        "close": None,
        "reason": "无足够的沪深主板100元以下合格标的，不强行补足。",
    }


def assign_roles(
    board: dict[str, Any],
    analyzed_rows: Iterable[dict[str, Any]],
    config: SectorMonitorConfig,
) -> dict[str, dict[str, Any]]:
    del board, config
    rows = [row for row in analyzed_rows if row.get("data_valid")]
    used: set[str] = set()
    picks: dict[str, dict[str, Any]] = {}

    role_scorers = (
        ("capacity_leader", lambda row: _capacity_score(row, rows), "成交承载力、流通规模和中期结构领先"),
        ("momentum_leader", lambda row: _momentum_score(row, rows), "板块相对强度、换手和60分钟弹性领先"),
        ("pullback_potential", _pullback_score, "接近回踩结构，仍需止跌和量价确认"),
        ("breakout_potential", _breakout_score, "距有效突破触发价较近，仍需放量确认"),
    )
    for role, scorer, reason in role_scorers:
        scored = []
        for row in rows:
            code = str(row.get("code") or "")
            if not code or code in used:
                continue
            score = scorer(row)
            if score is None or not math.isfinite(float(score)):
                continue
            scored.append((float(score), row))
        if not scored:
            picks[role] = _missing_payload(role)
            continue
        _, selected = max(scored, key=lambda item: item[0])
        code = str(selected.get("code"))
        used.add(code)
        picks[role] = _pick_payload(role, selected, reason)
    return picks
