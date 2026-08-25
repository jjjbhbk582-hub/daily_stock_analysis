from __future__ import annotations

from copy import deepcopy

from ashare_review.report import render_report


def _plan(setup: str, status: str = "waiting_trigger"):
    entry = 10.0 if setup == "pullback" else 10.8
    stop = 9.5 if setup == "pullback" else 10.2
    return {
        "plan_id": f"2026-08-24:600938:{setup}:v1",
        "code": "600938",
        "name": "中国海油",
        "industry": "石油和天然气开采",
        "setup": setup,
        "decision_status": status,
        "lifecycle_status": "pending",
        "recommendation_type": "technical_only",
        "fundamental_status": "missing",
        "fundamental_missing_fields": ["report_date", "revenue_yoy", "net_profit_yoy", "roe"],
        "technical_trade_score": 76.0,
        "composite_score": 82.0,
        "valid_for": "2026-08-25",
        "entry": {"low": entry, "high": entry + 0.1, "reference": entry},
        "trigger": {"description": "等待量价确认"},
        "stop": stop,
        "target_1": 11.5 if setup == "pullback" else 11.88,
        "target_2": 12.5 if setup == "pullback" else 12.6,
        "risk_reward_1": 3.0 if setup == "pullback" else 1.8,
        "risk_reward_2": 5.0 if setup == "pullback" else 3.0,
        "no_chase_above": 10.7 if setup == "pullback" else 11.1,
        "model_weight_pct": 7.5,
        "reasons": ["基本面缺失", "等待收盘站上突破价且量比达到1.30倍"],
        "rejection_reasons": [],
    }


def snapshot_with_waiting_technical_only_plan():
    pullback = _plan("pullback")
    breakout = _plan("breakout")
    return {
        "target_date": "2026-08-24",
        "generated_at": "2026-08-24T15:30:00+08:00",
        "valid_count": 0,
        "universe_count": 0,
        "market": {"breadth": {}, "trade_regime": {"label": "neutral", "score": 52.0}},
        "sectors": {},
        "stocks": [],
        "comparison": {"baseline": True},
        "alerts": [],
        "trade_decision": {
            "status": "ready",
            "valid_for": "2026-08-25",
            "market_regime": {
                "label": "neutral",
                "score": 52.0,
                "max_total_weight_pct": 50.0,
                "evidence": ["市场中性"],
            },
            "executable": [],
            "ready_next_session": [],
            "waiting_trigger": [pullback, breakout],
            "watch_only": [],
            "rejected": [],
            "all_plans": [pullback, breakout],
            "errors": [],
        },
        "previous_trade_review": [],
        "trade_statistics": {
            "sample_count": 0,
            "win_rate_pct": 0.0,
            "average_win_pct": 0.0,
            "average_loss_pct": 0.0,
            "average_win_loss_ratio": None,
            "expectancy_pct": 0.0,
            "max_consecutive_losses": 0,
            "max_drawdown_pct": 0.0,
            "confidence": "insufficient",
            "by_setup": {},
            "by_regime": {},
            "by_recommendation_type": {},
        },
    }


def test_report_marks_missing_fundamentals_without_calling_waiting_plan_buyable() -> None:
    report = render_report(snapshot_with_waiting_technical_only_plan())

    assert "技术交易｜基本面缺失" in report
    assert "缺失字段：report_date、revenue_yoy、net_profit_yoy、roe" in report
    assert "等待触发" in report
    assert "现在可以买" not in report
    assert "今日无可执行交易" in report


def test_report_renders_independent_pullback_and_breakout_risk_controls() -> None:
    report = render_report(snapshot_with_waiting_technical_only_plan())

    assert "回踩计划明细" in report
    assert "突破计划明细" in report
    assert "10.00—10.10元" in report
    assert "10.80—10.90元" in report
    assert "9.50" in report
    assert "10.20" in report
    assert "突破第一目标必须严格高于突破入场" in report
    assert "统计置信度不足" in report
    assert "模型仓位上限" in report


def test_rejected_missing_fundamental_plan_is_not_mislabeled_as_a_technical_trade() -> None:
    snapshot = snapshot_with_waiting_technical_only_plan()
    rejected = deepcopy(_plan("pullback", "rejected"))
    rejected.update({"code": "000001", "name": "拒绝样本", "rejection_reasons": ["60分钟趋势为空头"]})
    snapshot["trade_decision"]["rejected"] = [rejected]
    snapshot["trade_decision"]["all_plans"].append(rejected)

    report = render_report(snapshot)
    missing_section = report.split("### 4. 技术交易但基本面缺失", 1)[1].split("### 5. 观察与回避", 1)[0]

    assert "拒绝样本" not in missing_section
    assert "拒绝样本" in report
