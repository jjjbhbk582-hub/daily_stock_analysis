from __future__ import annotations

from copy import deepcopy
from datetime import date

from ashare_review.trade_plans import build_breakout_plan, build_pullback_plan, build_trade_decision
from ashare_review.trade_policy import DEFAULT_POLICY

TARGET = date(2026, 8, 24)
NEXT_DAY = date(2026, 8, 25)


def make_row(**overrides):
    row = {
        "code": "600938",
        "name": "中国海油",
        "rank": 1,
        "industry": "石油和天然气开采",
        "data_valid": True,
        "data_confidence": "high",
        "close": 10.0,
        "daily_trend": "多头",
        "weekly_trend": "多头",
        "trend_60m": "多头",
        "technical_trade_score": 75.0,
        "score": 82.0,
        "fundamental_status": "verified",
        "fundamental_missing_fields": [],
        "fundamental_risk_flags": [],
        "patterns": [],
        "metrics": {"atr_14": 0.5, "rel_volume_20": 1.0},
        "levels": {
            "status": "ready",
            "pullback_low": 9.4,
            "pullback_high": 9.6,
            "breakout_trigger": 10.2,
            "no_chase_above": 10.8,
            "invalidation": 8.9,
            "target_1": 10.8,
            "target_2": 11.5,
        },
        "sector_link": {
            "board_name": "石油和天然气开采",
            "match_quality": 105,
            "match_kind": "industry_exact_or_alias",
            "eligible_for_trade_gate": True,
        },
    }
    for key, value in overrides.items():
        if key == "technical_score":
            row["technical_trade_score"] = value
        elif key == "pullback":
            row["levels"]["pullback_low"], row["levels"]["pullback_high"] = value
        elif key == "breakout":
            row["levels"]["breakout_trigger"] = value
        elif key == "atr":
            row["metrics"]["atr_14"] = value
        else:
            row[key] = value
    return row


def market_fixture():
    return {
        "indices": [{"pct_change": 0.5}, {"pct_change": 0.4}, {"pct_change": 0.6}],
        "breadth": {"up": 2600, "down": 1600, "median_pct": 0.3},
        "industry_table": [
            {"industry": "石油和天然气开采", "pct_change": 0.8},
            {"industry": "银行", "pct_change": 0.2},
            {"industry": "电子", "pct_change": -0.1},
        ],
    }


def test_breakout_plan_has_its_own_stop_targets_and_rr() -> None:
    row = make_row(close=10.0, pullback=(9.4, 9.6), breakout=10.2, atr=0.5)

    pullback = build_pullback_plan(row, TARGET, NEXT_DAY, DEFAULT_POLICY)
    breakout = build_breakout_plan(row, TARGET, NEXT_DAY, DEFAULT_POLICY)

    assert pullback["entry"]["reference"] == 9.5
    assert breakout["entry"]["reference"] == 10.2
    assert breakout["stop"] == 9.6
    assert breakout["target_1"] == 11.28
    assert breakout["target_1"] > breakout["entry"]["reference"]
    assert breakout["risk_reward_1"] == 1.8
    assert pullback["stop"] != breakout["stop"]


def test_absolute_gate_allows_an_empty_executable_list() -> None:
    row = make_row(technical_score=69.9)

    decision = build_trade_decision([row], market_fixture(), TARGET, NEXT_DAY)

    assert decision["executable"] == []
    assert decision["watch_only"][0]["code"] == row["code"]
    assert "技术交易评分低于70" in decision["watch_only"][0]["rejection_reasons"]


def test_score_below_watch_floor_is_rejected_instead_of_soft_observation() -> None:
    decision = build_trade_decision(
        [make_row(technical_score=64.9)],
        market_fixture(),
        TARGET,
        NEXT_DAY,
    )

    assert decision["watch_only"] == []
    assert len(decision["rejected"]) == 2


def test_explicit_daily_bear_trend_is_rejected() -> None:
    decision = build_trade_decision(
        [make_row(technical_score=75.0, daily_trend="空头")],
        market_fixture(),
        TARGET,
        NEXT_DAY,
    )

    assert decision["watch_only"] == []
    assert len(decision["rejected"]) == 2


def test_missing_fundamentals_do_not_hide_a_technical_setup() -> None:
    row = make_row(
        technical_score=75,
        fundamental_status="missing",
        fundamental_missing_fields=["report_date", "revenue_yoy", "net_profit_yoy", "roe"],
        daily_trend="多头",
    )

    decision = build_trade_decision([row], market_fixture(), TARGET, NEXT_DAY)
    plans = decision["ready_next_session"] + decision["waiting_trigger"]

    assert plans
    assert all(plan["recommendation_type"] == "technical_only" for plan in plans)
    assert all(plan["model_weight_pct"] <= 7.5 for plan in plans)
    assert all("基本面缺失" in plan["reasons"] for plan in plans)


def test_hard_risk_rejects_both_setups() -> None:
    row = make_row(fundamental_risk_flags=["监管立案"])

    decision = build_trade_decision([row], market_fixture(), TARGET, NEXT_DAY)

    assert decision["ready_next_session"] == []
    assert decision["waiting_trigger"] == []
    assert len(decision["rejected"]) == 2
    assert all("硬风险：监管立案" in plan["rejection_reasons"] for plan in decision["rejected"])


def test_breakout_waits_when_close_and_volume_have_not_confirmed() -> None:
    row = make_row(close=10.0)
    row["metrics"]["rel_volume_20"] = 1.1

    decision = build_trade_decision([deepcopy(row)], market_fixture(), TARGET, NEXT_DAY)
    breakout = next(plan for plan in decision["all_plans"] if plan["setup"] == "breakout")

    assert breakout["decision_status"] == "waiting_trigger"
    assert "等待收盘站上突破价且量比达到1.30倍" in breakout["reasons"]
