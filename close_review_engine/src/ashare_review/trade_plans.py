from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from ashare_review.indicators import finite
from ashare_review.trade_policy import DEFAULT_POLICY, TradePolicy

FUNDAMENTAL_CAPS = {
    "verified": 15.0,
    "partial": 10.0,
    "missing": 7.5,
    "stale": 7.5,
}


def _price(value: float) -> float:
    return round(max(0.01, value), 2)


def _rr(target: float, entry: float, stop: float) -> float:
    risk = entry - stop
    return 0.0 if risk <= 0 else round((target - entry) / risk, 2)


def _base_plan(
    row: dict[str, Any],
    target_date: date,
    valid_for: date,
    setup: str,
    policy: TradePolicy,
) -> dict[str, Any]:
    status = str(row.get("fundamental_status") or "missing")
    recommendation_type = "comprehensive" if status == "verified" else "technical_only"
    reasons: list[str] = []
    if status == "missing":
        reasons.append("基本面缺失")
    elif status == "stale":
        reasons.append("基本面过期")
    elif status == "partial":
        reasons.append("基本面字段不完整")
    return {
        "plan_id": f"{target_date.isoformat()}:{row.get('code')}:{setup}:{policy.version}",
        "code": str(row.get("code") or ""),
        "name": str(row.get("name") or ""),
        "industry": str(row.get("industry") or "未分类"),
        "setup": setup,
        "decision_status": "watch_only",
        "lifecycle_status": "pending",
        "recommendation_type": recommendation_type,
        "fundamental_status": status,
        "fundamental_missing_fields": list(row.get("fundamental_missing_fields") or []),
        "technical_trade_score": finite(row.get("technical_trade_score"), 0.0) or 0.0,
        "composite_score": finite(row.get("score"), 0.0) or 0.0,
        "valid_for": valid_for.isoformat(),
        "expires_after": valid_for.isoformat(),
        "max_holding_sessions": policy.max_holding_sessions,
        "fundamental_position_cap_pct": FUNDAMENTAL_CAPS.get(status, 7.5),
        "model_weight_pct": 0.0,
        "reasons": reasons,
        "rejection_reasons": [],
    }


def build_pullback_plan(
    row: dict[str, Any],
    target_date: date,
    valid_for: date,
    policy: TradePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    plan = _base_plan(row, target_date, valid_for, "pullback", policy)
    levels = row.get("levels") or {}
    low = finite(levels.get("pullback_low"))
    high = finite(levels.get("pullback_high"))
    stop = finite(levels.get("invalidation"))
    atr = finite((row.get("metrics") or {}).get("atr_14"))
    if None in (low, high, stop, atr) or atr <= 0:
        plan["rejection_reasons"].append("回踩关键价位或ATR不完整")
        return plan
    low, high = sorted((float(low), float(high)))
    entry = (low + high) / 2
    if stop >= entry:
        plan["rejection_reasons"].append("回踩止损不低于入场参考")
        return plan
    risk = entry - stop
    nearest_resistance = max(
        finite(levels.get("breakout_trigger"), 0.0) or 0.0,
        finite(levels.get("target_1"), 0.0) or 0.0,
    )
    prior_high = finite(levels.get("target_2"), 0.0) or 0.0
    target_1 = max(nearest_resistance, entry + policy.min_rr1 * risk)
    target_2 = max(prior_high, entry + 3.0 * risk, target_1 + 0.5 * atr)
    no_chase = finite(levels.get("no_chase_above"), high + risk) or high + risk
    plan.update(
        {
            "entry": {"low": _price(low), "high": _price(high), "reference": _price(entry)},
            "trigger": {
                "kind": "pullback_reclaim",
                "description": "进入回踩区后，30或60分钟K线收回区间中枢且不再创新低",
                "confirmation_level": _price(entry),
            },
            "stop": _price(stop),
            "target_1": _price(target_1),
            "target_2": _price(target_2),
            "risk_reward_1": _rr(target_1, entry, stop),
            "risk_reward_2": _rr(target_2, entry, stop),
            "no_chase_above": _price(no_chase),
        }
    )
    return plan


def build_breakout_plan(
    row: dict[str, Any],
    target_date: date,
    valid_for: date,
    policy: TradePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    plan = _base_plan(row, target_date, valid_for, "breakout", policy)
    levels = row.get("levels") or {}
    entry = finite(levels.get("breakout_trigger"))
    pullback_high = finite(levels.get("pullback_high"))
    atr = finite((row.get("metrics") or {}).get("atr_14"))
    if None in (entry, pullback_high, atr) or atr <= 0:
        plan["rejection_reasons"].append("突破关键价位或ATR不完整")
        return plan
    entry = float(entry)
    atr = float(atr)
    candidate_stop = max(float(pullback_high), entry - 1.2 * atr)
    stop = min(entry - 0.4 * atr, candidate_stop)
    risk = entry - stop
    resistance = finite(levels.get("target_1"), 0.0) or 0.0
    target_1 = max(resistance if resistance > entry else 0.0, entry + policy.min_rr1 * risk)
    target_2 = max(
        finite(levels.get("target_2"), 0.0) or 0.0,
        target_1 + 0.8 * atr,
        entry + 3.0 * risk,
    )
    no_chase = entry + 0.5 * risk
    plan.update(
        {
            "entry": {"low": _price(entry), "high": _price(entry), "reference": _price(entry)},
            "trigger": {
                "kind": "volume_breakout",
                "description": "60分钟或日线收盘站上突破价，成交量不低于20期均量1.30倍",
                "minimum_volume_ratio": policy.breakout_volume_ratio,
            },
            "stop": _price(stop),
            "target_1": _price(target_1),
            "target_2": _price(target_2),
            "risk_reward_1": _rr(target_1, entry, stop),
            "risk_reward_2": _rr(target_2, entry, stop),
            "no_chase_above": _price(no_chase),
        }
    )
    return plan


def _bounded_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def build_trade_regime(market: dict[str, Any]) -> dict[str, Any]:
    index_values = [finite(item.get("pct_change")) for item in market.get("indices", [])]
    index_values = [float(value) for value in index_values if value is not None]
    index_average = float(np.mean(index_values)) if index_values else 0.0
    index_score = _bounded_score(50.0 + index_average * 25.0)

    breadth = market.get("breadth") or {}
    up = int(breadth.get("up") or 0)
    down = int(breadth.get("down") or 0)
    breadth_score = 50.0 if up + down == 0 else up / (up + down) * 100.0
    median_pct = finite(breadth.get("median_pct"), 0.0) or 0.0
    median_score = _bounded_score(50.0 + median_pct * 25.0)

    industries = [
        finite(item.get("pct_change"))
        for item in market.get("industry_table", [])
        if finite(item.get("pct_change")) is not None
    ]
    industry_score = (
        50.0 if not industries else sum(float(value) > 0 for value in industries) / len(industries) * 100.0
    )
    score = round(
        index_score * 0.35 + breadth_score * 0.35 + median_score * 0.20 + industry_score * 0.10,
        1,
    )
    if score >= 60:
        label, cap = "risk_on", 70.0
    elif score >= 45:
        label, cap = "neutral", 50.0
    else:
        label, cap = "risk_off", 30.0
    return {
        "score": score,
        "label": label,
        "max_total_weight_pct": cap,
        "evidence": [
            f"三大指数均值{index_average:+.2f}%（分项{index_score:.1f}）",
            f"上涨家数占比{breadth_score:.1f}%",
            f"市场中位涨跌幅{median_pct:+.2f}%（分项{median_score:.1f}）",
            f"行业上涨比例{industry_score:.1f}%",
        ],
    }


def model_weight_pct(
    entry: float,
    stop: float,
    fundamental_status: str,
    remaining_market_cap: float,
    remaining_sector_cap: float,
    policy: TradePolicy = DEFAULT_POLICY,
) -> float:
    if entry <= 0 or stop >= entry:
        return 0.0
    stop_distance_pct = (entry - stop) / entry * 100.0
    raw = policy.risk_budget_pct / stop_distance_pct * 100.0
    fundamental_cap = FUNDAMENTAL_CAPS.get(fundamental_status, 7.5)
    return round(max(0.0, min(raw, fundamental_cap, remaining_market_cap, remaining_sector_cap)), 2)


def _gate_plan(row: dict[str, Any], plan: dict[str, Any], policy: TradePolicy) -> str:
    reasons = plan["rejection_reasons"]
    technical_score = finite(row.get("technical_trade_score"), 0.0) or 0.0
    close = finite(row.get("close"))
    if not row.get("data_valid"):
        reasons.append("当日完整日线未通过校验")
    if row.get("data_confidence") != "high":
        reasons.append("行情数据置信度不是high")
    if technical_score < policy.min_technical_score:
        reasons.append("技术交易评分低于70")
    if row.get("daily_trend") not in {"多头", "强势多头"}:
        reasons.append("日线未达到多头门槛")
    if row.get("trend_60m") in {"空头", "强势空头"}:
        reasons.append("60分钟趋势为空头")
    if not (row.get("sector_link") or {}).get("eligible_for_trade_gate", True):
        reasons.append("板块匹配置信度不足")
    hard_risks = list(row.get("fundamental_risk_flags") or [])
    reasons.extend(f"硬风险：{flag}" for flag in hard_risks)
    no_chase = finite(plan.get("no_chase_above"))
    if close is None or no_chase is None:
        reasons.append("现价或追高线缺失")
    elif close >= no_chase:
        reasons.append("现价已进入禁止追高区")
    if (finite(plan.get("risk_reward_1"), 0.0) or 0.0) < policy.min_rr1:
        reasons.append("第一目标风险收益比低于1.80")

    hard_reject = (
        technical_score < policy.watch_technical_score
        or row.get("daily_trend") in {"偏空震荡", "空头", "强势空头"}
        or row.get("data_confidence") == "low"
        or any(
        text.startswith("硬风险")
        or text in {
            "当日完整日线未通过校验",
            "60分钟趋势为空头",
            "现价已进入禁止追高区",
            "现价或追高线缺失",
            "回踩关键价位或ATR不完整",
            "突破关键价位或ATR不完整",
            "回踩止损不低于入场参考",
        }
        for text in reasons
        )
    )
    if hard_reject:
        return "rejected"
    if reasons:
        return "watch_only"

    if plan["setup"] == "pullback":
        low = plan["entry"]["low"]
        high = plan["entry"]["high"]
        return "ready_next_session" if low <= close <= high else "waiting_trigger"
    rel_volume = finite((row.get("metrics") or {}).get("rel_volume_20"), 0.0) or 0.0
    entry = plan["entry"]["reference"]
    if close >= entry and rel_volume >= policy.breakout_volume_ratio:
        return "ready_next_session"
    plan["reasons"].append(
        f"等待收盘站上突破价且量比达到{policy.breakout_volume_ratio:.2f}倍"
    )
    return "waiting_trigger"


def build_trade_decision(
    rows: list[dict[str, Any]],
    market: dict[str, Any],
    target_date: date,
    valid_for: date,
    policy: TradePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    regime = build_trade_regime(market)
    buckets: dict[str, list[dict[str, Any]]] = {
        "ready_next_session": [],
        "waiting_trigger": [],
        "watch_only": [],
        "rejected": [],
    }
    errors: list[dict[str, str]] = []
    all_plans: list[dict[str, Any]] = []
    remaining_market = float(regime["max_total_weight_pct"])
    sector_used: dict[str, float] = {}
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            -(finite(row.get("technical_trade_score"), 0.0) or 0.0),
            int(row.get("rank") or 999),
        ),
    )
    for row in ordered_rows:
        try:
            plans = (
                build_pullback_plan(row, target_date, valid_for, policy),
                build_breakout_plan(row, target_date, valid_for, policy),
            )
            for plan in plans:
                plan["market_regime"] = regime["label"]
                status = _gate_plan(row, plan, policy)
                plan["decision_status"] = status
                if status in {"ready_next_session", "waiting_trigger"}:
                    entry = float(plan["entry"]["reference"])
                    stop = float(plan["stop"])
                    industry = plan["industry"]
                    remaining_sector = policy.max_sector_weight_pct - sector_used.get(industry, 0.0)
                    weight = model_weight_pct(
                        entry,
                        stop,
                        plan["fundamental_status"],
                        remaining_market,
                        remaining_sector,
                        policy,
                    )
                    plan["model_weight_pct"] = weight
                    remaining_market = max(0.0, remaining_market - weight)
                    sector_used[industry] = sector_used.get(industry, 0.0) + weight
                buckets[status].append(plan)
                all_plans.append(plan)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"code": str(row.get("code") or ""), "error": f"{type(exc).__name__}: {exc}"})
    return {
        "status": "ready" if all_plans else "empty",
        "policy_version": policy.version,
        "target_date": target_date.isoformat(),
        "valid_for": valid_for.isoformat(),
        "market_regime": regime,
        "executable": list(buckets["ready_next_session"]),
        **buckets,
        "all_plans": all_plans,
        "errors": errors,
    }
