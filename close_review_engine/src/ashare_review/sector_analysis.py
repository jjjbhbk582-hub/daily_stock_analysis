from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ashare_review.indicators import finite


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _history_metrics(history: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    if history.empty or "close" not in history:
        return None, None, None
    frame = history.sort_values("date").reset_index(drop=True)
    latest_close = finite(frame.iloc[-1].get("close"))
    if latest_close is None:
        return None, None, None
    return_5d = None
    return_20d = None
    if len(frame) >= 6:
        base = finite(frame.iloc[-6].get("close"))
        if base not in (None, 0):
            return_5d = (latest_close / base - 1) * 100
    if len(frame) >= 21:
        base = finite(frame.iloc[-21].get("close"))
        if base not in (None, 0):
            return_20d = (latest_close / base - 1) * 100
    amount_ratio = None
    if "amount" in frame and len(frame) >= 21:
        latest_amount = finite(frame.iloc[-1].get("amount"))
        prior = pd.to_numeric(frame.iloc[-21:-1]["amount"], errors="coerce").dropna()
        if latest_amount is not None and not prior.empty and float(prior.mean()) > 0:
            amount_ratio = latest_amount / float(prior.mean())
    return return_5d, return_20d, amount_ratio


def score_board(
    board: dict[str, Any],
    history: pd.DataFrame,
    *,
    market_median: float,
) -> dict[str, Any]:
    pct = finite(board.get("pct_change"), 0.0) or 0.0
    up = max(0, int(finite(board.get("up_count"), 0.0) or 0))
    down = max(0, int(finite(board.get("down_count"), 0.0) or 0))
    total = up + down
    breadth_ratio = up / total if total else 0.5
    limit_up_count = max(0, int(finite(board.get("limit_up_count"), 0.0) or 0))
    leader_pct = finite(board.get("leader_pct_change"), 0.0) or 0.0
    amount = finite(board.get("amount"), 0.0) or 0.0
    return_5d, return_20d, amount_ratio = _history_metrics(history)

    relative = pct - market_median
    daily_score = _clamp(10 + relative * 2.2 + pct * 0.7, 0, 20)
    trend_score = 8.0
    if return_5d is not None:
        trend_score += _clamp(return_5d * 0.75, -5, 6)
    if return_20d is not None:
        trend_score += _clamp(return_20d * 0.28, -5, 7)
    if return_5d is not None and return_20d is not None and return_5d > 0 and return_20d > 0:
        trend_score += 2
    trend_score = _clamp(trend_score, 0, 20)

    amount_score = 7.0 + _clamp(math.log10(max(amount, 1.0)) - 9.0, 0, 4)
    if amount_ratio is not None:
        amount_score += _clamp((amount_ratio - 1) * 8, -4, 9)
    amount_score = _clamp(amount_score, 0, 20)

    breadth_score = _clamp(breadth_ratio * 12 + min(limit_up_count, 5) * 0.8, 0, 15)
    leadership_score = _clamp(
        _clamp(leader_pct, -5, 10) * 0.6
        + min(limit_up_count, 6) * 1.3
        + breadth_ratio * 4,
        0,
        15,
    )

    risk_flags: list[str] = []
    risk_score = 5.0
    if return_5d is not None and return_20d is not None and return_5d > 0 and return_20d > 0:
        risk_score += 1.5
    if breadth_ratio >= 0.65:
        risk_score += 1.5
    if amount_ratio is not None and 1.05 <= amount_ratio <= 2.2:
        risk_score += 1
    if pct >= 5 and breadth_ratio < 0.45:
        risk_score -= 4
        risk_flags.append("单日脉冲但板块广度不足")
    if amount_ratio is not None and amount_ratio > 2.5 and pct < 1:
        risk_score -= 2
        risk_flags.append("异常放量但涨幅有限")
    if return_5d is not None and return_20d is not None and return_5d < 0 and return_20d < 0:
        risk_score -= 2
        risk_flags.append("中短期趋势均偏弱")
    risk_score = _clamp(risk_score, 0, 10)

    score = round(
        daily_score
        + trend_score
        + amount_score
        + breadth_score
        + leadership_score
        + risk_score,
        1,
    )
    result = dict(board)
    result.update(
        {
            "score": score,
            "return_5d": None if return_5d is None else round(return_5d, 2),
            "return_20d": None if return_20d is None else round(return_20d, 2),
            "amount_ratio_20": None if amount_ratio is None else round(amount_ratio, 2),
            "breadth_ratio": round(breadth_ratio, 4),
            "confidence": "high" if len(history) >= 21 and total > 0 else "partial",
            "risk_flags": risk_flags,
            "score_breakdown": {
                "daily_strength": round(daily_score, 1),
                "trend": round(trend_score, 1),
                "amount": round(amount_score, 1),
                "breadth": round(breadth_score, 1),
                "leadership": round(leadership_score, 1),
                "catalyst_risk_proxy": round(risk_score, 1),
            },
        }
    )
    return result


def rank_boards(boards: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in boards]
    rows.sort(
        key=lambda row: (
            finite(row.get("score"), 0.0) or 0.0,
            finite(row.get("pct_change"), 0.0) or 0.0,
            finite(row.get("amount"), 0.0) or 0.0,
        ),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _rank_map(sectors: dict[str, Any] | None) -> dict[tuple[str, str], int]:
    output: dict[tuple[str, str], int] = {}
    for key in ("industry_ranking", "concept_ranking"):
        for row in (sectors or {}).get(key, []):
            output[(str(row.get("board_type")), str(row.get("board_code")))] = int(
                row.get("rank") or 999
            )
    return output


def select_detailed_boards(
    current: list[dict[str, Any]],
    previous: dict[str, Any] | None,
    config: Any,
) -> dict[str, Any]:
    top_boards = [dict(row) for row in current[:5]]
    old_ranks = _rank_map(previous)
    risers: list[dict[str, Any]] = []
    for row in current:
        key = (str(row.get("board_type")), str(row.get("board_code")))
        old_rank = old_ranks.get(key)
        if old_rank is None:
            continue
        improvement = old_rank - int(row.get("rank") or 999)
        if improvement > 2:
            item = dict(row)
            item["rank_improvement"] = improvement
            risers.append(item)
    risers.sort(
        key=lambda row: (
            int(row.get("rank_improvement") or 0),
            finite(row.get("score"), 0.0) or 0.0,
        ),
        reverse=True,
    )
    rising_boards = risers[:2]
    detailed: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in [*top_boards, *rising_boards]:
        key = (str(row.get("board_type")), str(row.get("board_code")))
        if key in seen:
            continue
        seen.add(key)
        detailed.append(dict(row))
        if len(detailed) >= int(config.max_detailed_boards):
            break
    weak_boards = [dict(row) for row in current[-3:]][::-1]
    return {
        "top_boards": top_boards,
        "rising_boards": rising_boards,
        "weak_boards": weak_boards,
        "detailed_boards": detailed,
    }


def compare_sector_rankings(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    if not previous:
        return {
            "baseline": True,
            "new_top_boards": [
                {"board_type": row.get("board_type"), "board_code": row.get("board_code")}
                for row in current.get("top_boards", [])
            ],
            "dropped_top_boards": [],
            "rank_moves": [],
            "score_moves": [],
            "role_changes": [],
            "material": True,
        }
    old_rows = {}
    new_rows = {}
    for source, target in ((previous, old_rows), (current, new_rows)):
        for list_name in ("industry_ranking", "concept_ranking"):
            for row in source.get(list_name, []):
                target[(str(row.get("board_type")), str(row.get("board_code")))] = row
    old_top = {
        (str(row.get("board_type")), str(row.get("board_code")))
        for row in previous.get("top_boards", [])
    }
    new_top = {
        (str(row.get("board_type")), str(row.get("board_code")))
        for row in current.get("top_boards", [])
    }
    result: dict[str, Any] = {
        "baseline": False,
        "new_top_boards": [
            {"board_type": item[0], "board_code": item[1]}
            for item in sorted(new_top - old_top)
        ],
        "dropped_top_boards": [
            {"board_type": item[0], "board_code": item[1]}
            for item in sorted(old_top - new_top)
        ],
        "rank_moves": [],
        "score_moves": [],
        "role_changes": [],
    }
    for key in sorted(old_rows.keys() & new_rows.keys()):
        before = old_rows[key]
        after = new_rows[key]
        if abs(int(after.get("rank") or 999) - int(before.get("rank") or 999)) > 2:
            result["rank_moves"].append(
                {
                    "board_type": key[0],
                    "board_code": key[1],
                    "board_name": after.get("board_name"),
                    "before": before.get("rank"),
                    "after": after.get("rank"),
                }
            )
        if abs((finite(after.get("score"), 0.0) or 0.0) - (finite(before.get("score"), 0.0) or 0.0)) >= 5:
            result["score_moves"].append(
                {
                    "board_type": key[0],
                    "board_code": key[1],
                    "board_name": after.get("board_name"),
                    "before": before.get("score"),
                    "after": after.get("score"),
                }
            )
    old_details = {
        (str(row.get("board_type")), str(row.get("board_code"))): row
        for row in previous.get("detailed_boards", [])
    }
    new_details = {
        (str(row.get("board_type")), str(row.get("board_code"))): row
        for row in current.get("detailed_boards", [])
    }
    for key in sorted(old_details.keys() & new_details.keys()):
        old_picks = {
            role: (item or {}).get("code")
            for role, item in (old_details[key].get("picks") or {}).items()
        }
        new_picks = {
            role: (item or {}).get("code")
            for role, item in (new_details[key].get("picks") or {}).items()
        }
        changed = [role for role in sorted(set(old_picks) | set(new_picks)) if old_picks.get(role) != new_picks.get(role)]
        if changed:
            result["role_changes"].append(
                {
                    "board_type": key[0],
                    "board_code": key[1],
                    "board_name": new_details[key].get("board_name"),
                    "roles": changed,
                }
            )
    result["material"] = any(
        result[key]
        for key in (
            "new_top_boards",
            "dropped_top_boards",
            "rank_moves",
            "score_moves",
            "role_changes",
        )
    )
    return result
