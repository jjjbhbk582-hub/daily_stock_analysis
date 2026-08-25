from __future__ import annotations

from copy import deepcopy
from typing import Any

from ashare_review.indicators import finite


def _outcome(
    plan: dict[str, Any],
    bar_date: str,
    reason: str,
    *,
    return_pct: float | None = None,
    included: bool,
) -> dict[str, Any]:
    return {
        "plan_id": plan.get("plan_id"),
        "code": plan.get("code"),
        "name": plan.get("name"),
        "setup": plan.get("setup"),
        "recommendation_type": plan.get("recommendation_type"),
        "fundamental_status": plan.get("fundamental_status"),
        "market_regime": plan.get("market_regime"),
        "entry_date": plan.get("entry_date"),
        "entry_price": plan.get("entry_price"),
        "exit_date": bar_date,
        "exit_reason": reason,
        "return_pct": None if return_pct is None else round(return_pct, 2),
        "mfe_pct": round(float(plan.get("mfe_pct") or 0.0), 2),
        "mae_pct": round(float(plan.get("mae_pct") or 0.0), 2),
        "holding_sessions": int(plan.get("holding_sessions") or 0),
        "included_in_statistics": included,
    }


def _finish(
    plan: dict[str, Any],
    bar_date: str,
    status: str,
    *,
    return_pct: float | None = None,
    included: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan["lifecycle_status"] = status
    plan["closed_date"] = bar_date
    return plan, _outcome(plan, bar_date, status, return_pct=return_pct, included=included)


def _pending_triggered(plan: dict[str, Any], bar: dict[str, Any]) -> bool:
    entry = plan.get("entry") or {}
    reference = finite(entry.get("reference"))
    if reference is None:
        return False
    if plan.get("setup") == "breakout":
        threshold = finite((plan.get("trigger") or {}).get("minimum_volume_ratio"), 1.3) or 1.3
        close = finite(bar.get("close"))
        volume_ratio = finite(bar.get("volume_ratio"), 0.0) or 0.0
        return close is not None and close >= reference and volume_ratio >= threshold
    low = finite(bar.get("low"))
    close = finite(bar.get("close"))
    zone_high = finite(entry.get("high"))
    confirmation = finite((plan.get("trigger") or {}).get("confirmation_level"), reference)
    return (
        low is not None
        and close is not None
        and zone_high is not None
        and confirmation is not None
        and low <= zone_high
        and close >= confirmation
    )


def _update_excursions(plan: dict[str, Any], bar: dict[str, Any]) -> None:
    entry = finite(plan.get("entry_price"))
    high = finite(bar.get("high"))
    low = finite(bar.get("low"))
    if entry in (None, 0) or high is None or low is None:
        return
    favorable = (high - entry) / entry * 100.0
    adverse = (low - entry) / entry * 100.0
    plan["mfe_pct"] = round(max(float(plan.get("mfe_pct") or 0.0), favorable), 2)
    plan["mae_pct"] = round(min(float(plan.get("mae_pct") or 0.0), adverse), 2)


def evaluate_plan(
    original: dict[str, Any],
    daily_bar: dict[str, Any],
    *,
    intraday: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    plan = deepcopy(original)
    status = str(plan.get("lifecycle_status") or "pending")
    bar_date = str(daily_bar.get("date") or "")
    if status in {
        "target2",
        "stopped",
        "timed_exit",
        "expired",
        "cancelled_gap",
        "unfilled",
        "ambiguous",
    }:
        return plan, None

    open_price = finite(daily_bar.get("open"))
    high = finite(daily_bar.get("high"))
    low = finite(daily_bar.get("low"))
    close = finite(daily_bar.get("close"))
    if None in (open_price, high, low, close):
        return plan, None

    if status == "pending":
        if bar_date < str(plan.get("valid_for") or bar_date):
            return plan, None
        if not daily_bar.get("tradable", True) or daily_bar.get("limit_locked", False):
            return _finish(plan, bar_date, "unfilled", included=False)
        no_chase = finite(plan.get("no_chase_above"))
        stop = finite(plan.get("stop"))
        if no_chase is not None and open_price > no_chase:
            return _finish(plan, bar_date, "cancelled_gap", included=False)
        if stop is not None and open_price <= stop:
            return _finish(plan, bar_date, "cancelled_gap", included=False)
        if _pending_triggered(plan, daily_bar):
            entry_reference = float((plan.get("entry") or {})["reference"])
            plan.update(
                {
                    "lifecycle_status": "triggered",
                    "entry_date": bar_date,
                    "entry_price": entry_reference,
                    "holding_sessions": 0,
                    "mfe_pct": round(max(0.0, (high - entry_reference) / entry_reference * 100.0), 2),
                    "mae_pct": round(min(0.0, (low - entry_reference) / entry_reference * 100.0), 2),
                    "remaining_weight_fraction": 1.0,
                    "realized_return_pct": 0.0,
                }
            )
            return plan, None
        if bar_date >= str(plan.get("expires_after") or plan.get("valid_for") or bar_date):
            return _finish(plan, bar_date, "expired", included=False)
        return plan, None

    entry = finite(plan.get("entry_price"))
    stop = finite(plan.get("protective_stop"), finite(plan.get("stop")))
    target_1 = finite(plan.get("target_1"))
    target_2 = finite(plan.get("target_2"))
    if None in (entry, stop, target_1, target_2):
        return plan, None
    plan["holding_sessions"] = int(plan.get("holding_sessions") or 0) + 1
    _update_excursions(plan, daily_bar)

    active_target = target_2 if status == "target1" else target_1
    hit_stop = low <= stop
    hit_target = high >= active_target
    if hit_stop and hit_target and not intraday:
        return _finish(plan, bar_date, "ambiguous", included=False)

    realized = float(plan.get("realized_return_pct") or 0.0)
    if hit_stop:
        fraction = float(plan.get("remaining_weight_fraction") or 1.0)
        total = realized + (stop - entry) / entry * 100.0 * fraction
        return _finish(plan, bar_date, "stopped", return_pct=total, included=True)

    if status == "triggered" and high >= target_2:
        total = (target_2 - entry) / entry * 100.0
        return _finish(plan, bar_date, "target2", return_pct=total, included=True)
    if status == "triggered" and hit_target:
        plan["lifecycle_status"] = "target1"
        plan["remaining_weight_fraction"] = 0.5
        plan["protective_stop"] = round(entry, 2)
        plan["realized_return_pct"] = round((target_1 - entry) / entry * 100.0 * 0.5, 2)
        return plan, None
    if status == "target1" and hit_target:
        total = realized + (target_2 - entry) / entry * 100.0 * 0.5
        return _finish(plan, bar_date, "target2", return_pct=total, included=True)

    if plan["holding_sessions"] >= int(plan.get("max_holding_sessions") or 5):
        fraction = float(plan.get("remaining_weight_fraction") or 1.0)
        total = realized + (close - entry) / entry * 100.0 * fraction
        return _finish(plan, bar_date, "timed_exit", return_pct=total, included=True)
    return plan, None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["return_pct"]) for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    consecutive = 0
    max_consecutive = 0
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        if value <= 0:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    return {
        "sample_count": len(returns),
        "win_rate_pct": round(len(wins) / len(returns) * 100.0, 2) if returns else 0.0,
        "average_win_pct": round(average_win, 2),
        "average_loss_pct": round(average_loss, 2),
        "average_win_loss_ratio": (
            round(average_win / abs(average_loss), 2) if average_loss < 0 else None
        ),
        "expectancy_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
        "max_consecutive_losses": max_consecutive,
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "confidence": "sufficient" if len(returns) >= 30 else "insufficient",
    }


def calculate_trade_statistics(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        row
        for row in outcomes
        if row.get("included_in_statistics") and finite(row.get("return_pct")) is not None
    ]
    result = _summary(rows)
    for output_key, field in (
        ("by_setup", "setup"),
        ("by_regime", "market_regime"),
        ("by_recommendation_type", "recommendation_type"),
    ):
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(str(row.get(field) or "unknown"), []).append(row)
        result[output_key] = {key: _summary(group) for key, group in sorted(groups.items())}
    return result
