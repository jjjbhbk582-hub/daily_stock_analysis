from __future__ import annotations

from ashare_review.trade_tracking import calculate_trade_statistics, evaluate_plan


def pending_plan(**overrides):
    plan = {
        "plan_id": "2026-08-24:600938:pullback:v1",
        "code": "600938",
        "name": "中国海油",
        "setup": "pullback",
        "recommendation_type": "technical_only",
        "fundamental_status": "missing",
        "market_regime": "neutral",
        "lifecycle_status": "pending",
        "valid_for": "2026-08-25",
        "expires_after": "2026-08-25",
        "entry": {"low": 9.9, "high": 10.1, "reference": 10.0},
        "trigger": {"kind": "pullback_reclaim", "confirmation_level": 10.0},
        "stop": 9.5,
        "target_1": 11.0,
        "target_2": 12.0,
        "no_chase_above": 10.5,
        "max_holding_sessions": 5,
        "model_weight_pct": 7.5,
    }
    plan.update(overrides)
    return plan


def triggered_plan(**overrides):
    plan = pending_plan(
        lifecycle_status="triggered",
        entry_date="2026-08-25",
        entry_price=10.0,
        holding_sessions=0,
        mfe_pct=0.0,
        mae_pct=0.0,
        remaining_weight_fraction=1.0,
        realized_return_pct=0.0,
    )
    plan.update(overrides)
    return plan


def bar(**overrides):
    payload = {
        "date": "2026-08-25",
        "open": 10.0,
        "high": 10.2,
        "low": 9.9,
        "close": 10.1,
        "volume_ratio": 1.0,
        "tradable": True,
        "limit_locked": False,
    }
    payload.update(overrides)
    return payload


def test_open_above_no_chase_cancels_pending_plan() -> None:
    updated, outcome = evaluate_plan(
        pending_plan(no_chase_above=10.5),
        bar(open=10.6, high=10.8, low=10.55, close=10.7),
    )

    assert updated["lifecycle_status"] == "cancelled_gap"
    assert outcome["exit_reason"] == "cancelled_gap"
    assert outcome["included_in_statistics"] is False


def test_plan_is_not_evaluated_before_its_valid_session() -> None:
    updated, outcome = evaluate_plan(
        pending_plan(valid_for="2026-08-26", expires_after="2026-08-26"),
        bar(date="2026-08-25", open=10.6, high=10.8, low=10.55, close=10.7),
    )

    assert updated["lifecycle_status"] == "pending"
    assert outcome is None


def test_trigger_day_cannot_stop_out_under_t_plus_one() -> None:
    updated, outcome = evaluate_plan(
        pending_plan(entry={"low": 9.9, "high": 10.1, "reference": 10.0}, stop=9.5),
        bar(open=10.1, high=10.2, low=9.4, close=10.05),
    )

    assert updated["lifecycle_status"] == "triggered"
    assert updated["entry_date"] == "2026-08-25"
    assert outcome is None


def test_target1_reduces_half_and_moves_stop_for_the_next_session() -> None:
    updated, outcome = evaluate_plan(
        triggered_plan(target_1=11.0, stop=9.5),
        bar(date="2026-08-26", open=10.4, high=11.1, low=10.2, close=10.9),
    )

    assert updated["lifecycle_status"] == "target1"
    assert updated["remaining_weight_fraction"] == 0.5
    assert updated["protective_stop"] == 10.0
    assert updated["realized_return_pct"] == 5.0
    assert outcome is None


def test_same_day_stop_and_target_without_intraday_order_is_ambiguous() -> None:
    updated, outcome = evaluate_plan(
        triggered_plan(target_1=11.0, stop=9.5),
        bar(date="2026-08-26", open=10.0, high=11.1, low=9.4, close=10.2),
    )

    assert updated["lifecycle_status"] == "ambiguous"
    assert outcome["included_in_statistics"] is False


def test_statistics_use_only_closed_non_ambiguous_trades() -> None:
    outcomes = [
        {"plan_id": "1", "included_in_statistics": True, "return_pct": 10.0, "setup": "pullback", "market_regime": "risk_on", "recommendation_type": "comprehensive"},
        {"plan_id": "2", "included_in_statistics": True, "return_pct": -5.0, "setup": "pullback", "market_regime": "risk_on", "recommendation_type": "technical_only"},
        {"plan_id": "3", "included_in_statistics": True, "return_pct": 5.0, "setup": "breakout", "market_regime": "neutral", "recommendation_type": "technical_only"},
        {"plan_id": "4", "included_in_statistics": False, "return_pct": -99.0, "setup": "breakout", "market_regime": "risk_off", "recommendation_type": "technical_only"},
    ]

    stats = calculate_trade_statistics(outcomes)

    assert stats["sample_count"] == 3
    assert stats["win_rate_pct"] == 66.67
    assert stats["average_win_pct"] == 7.5
    assert stats["average_loss_pct"] == -5.0
    assert stats["expectancy_pct"] == 3.33
    assert stats["max_consecutive_losses"] == 1
    assert stats["confidence"] == "insufficient"
    assert stats["by_setup"]["pullback"]["sample_count"] == 2
