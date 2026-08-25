from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ashare_review.config import StockConfig
from ashare_review.data import Quote, StockBundle
from ashare_review.fundamental_quality import assess_fundamentals, technical_trade_score
from ashare_review.indicators import add_indicators, finite, to_weekly

TREND_POINTS = {
    "强势多头": 1.0,
    "多头": 0.78,
    "偏多震荡": 0.62,
    "震荡": 0.5,
    "偏空震荡": 0.34,
    "空头": 0.18,
    "强势空头": 0.0,
    "数据不足": 0.25,
}

POSITIVE_EVENT_WORDS = (
    "业绩预增",
    "增长",
    "中标",
    "回购",
    "增持",
    "重大合同",
    "战略合作",
    "产能",
    "扩产",
    "分红",
    "股权激励",
)
NEGATIVE_EVENT_WORDS = (
    "立案",
    "调查",
    "处罚",
    "减持",
    "业绩预减",
    "亏损",
    "风险提示",
    "问询函",
    "终止",
    "诉讼",
    "冻结",
)


def _trend(frame: pd.DataFrame) -> str:
    if frame.empty or len(frame) < 26:
        return "数据不足"
    data = add_indicators(frame)
    latest = data.iloc[-1]
    close = finite(latest.get("close"))
    ema10 = finite(latest.get("ema_10"))
    ema20 = finite(latest.get("ema_20"))
    ma20 = finite(latest.get("ma_20"))
    ma50 = finite(latest.get("ma_50"))
    dif = finite(latest.get("macd_dif"), 0.0)
    dea = finite(latest.get("macd_dea"), 0.0)
    adx = finite(latest.get("adx_14"), 0.0)
    plus_di = finite(latest.get("plus_di_14"), 0.0)
    minus_di = finite(latest.get("minus_di_14"), 0.0)
    if None in (close, ema10, ema20, ma20):
        return "数据不足"
    slope = 0.0
    if len(data) >= 6 and finite(data.iloc[-6].get("ema_20")):
        slope = ema20 / float(data.iloc[-6]["ema_20"]) - 1
    above_50 = ma50 is not None and close > ma50
    below_50 = ma50 is not None and close < ma50
    if close > ema10 > ema20 > ma20 and above_50 and slope > 0.01 and dif >= dea and adx >= 20 and plus_di >= minus_di:
        return "强势多头"
    if close > ema20 and ema10 >= ema20 and slope >= 0 and (ma50 is None or close >= ma50):
        return "多头"
    if close >= ma20 and ema10 >= ema20:
        return "偏多震荡"
    if close < ema10 < ema20 < ma20 and below_50 and slope < -0.01 and dif < dea and adx >= 20 and minus_di > plus_di:
        return "强势空头"
    if close < ema20 and ema10 <= ema20 and slope <= 0 and (ma50 is None or close <= ma50):
        return "空头"
    if close < ma20:
        return "偏空震荡"
    return "震荡"


def _patterns(data: pd.DataFrame) -> list[str]:
    if len(data) < 30:
        return []
    latest = data.iloc[-1]
    previous = data.iloc[-2]
    flags: list[str] = []
    close = float(latest["close"])
    high = float(latest["high"])
    low = float(latest["low"])
    prior_high = finite(latest.get("prior_high_20"))
    prior_low = finite(latest.get("prior_low_20"))
    rel_volume = finite(latest.get("rel_volume_20"), 0.0) or 0.0
    ema10 = finite(latest.get("ema_10"))
    ema20 = finite(latest.get("ema_20"))
    if prior_high is not None and close > prior_high and rel_volume >= 1.35:
        flags.append("放量突破")
    if (
        ema10 is not None
        and ema20 is not None
        and min(ema10, ema20) * 0.985 <= close <= max(ema10, ema20) * 1.02
        and rel_volume <= 0.9
        and close >= float(previous["close"]) * 0.98
    ):
        flags.append("缩量回踩")
    if prior_high is not None and high > prior_high and close < prior_high and rel_volume >= 1.15:
        flags.append("假突破")
    if prior_low is not None and low < prior_low and close > prior_low:
        flags.append("跌破后反抽")

    recent = data.iloc[-11:-1]
    latest_rsi = finite(latest.get("rsi_14"))
    latest_macd = finite(latest.get("macd_hist"))
    if latest_rsi is not None and not recent.empty:
        prior_rsi_max = finite(recent["rsi_14"].max())
        prior_rsi_min = finite(recent["rsi_14"].min())
        if close >= float(recent["close"].max()) and prior_rsi_max is not None and latest_rsi < prior_rsi_max - 5:
            flags.append("RSI顶背离")
        if close <= float(recent["close"].min()) and prior_rsi_min is not None and latest_rsi > prior_rsi_min + 5:
            flags.append("RSI底背离")
    if latest_macd is not None and not recent.empty:
        if close >= float(recent["close"].max()) and latest_macd < float(recent["macd_hist"].max()) * 0.75:
            flags.append("MACD顶背离")
        if close <= float(recent["close"].min()) and latest_macd > float(recent["macd_hist"].min()) * 0.75:
            flags.append("MACD底背离")
    return list(dict.fromkeys(flags))


def _round_price(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else round(max(0.01, value), 2)


def _levels(data: pd.DataFrame, *, allowed: bool) -> dict[str, Any]:
    if not allowed or len(data) < 60:
        return {"status": "等待数据确认", "reason": "核心行情未达到精确价位计算门槛。"}
    latest = data.iloc[-1]
    close = float(latest["close"])
    atr = finite(latest.get("atr_14"))
    if atr is None or atr <= 0:
        return {"status": "数据不足", "reason": "ATR无法可靠计算。"}
    supports = [
        finite(latest.get("ema_10")),
        finite(latest.get("ema_20")),
        finite(latest.get("ma_20")),
    ]
    prior_high = finite(latest.get("prior_high_20"))
    if prior_high is not None and prior_high <= close * 1.015:
        supports.append(prior_high)
    supports = [value for value in supports if value is not None and 0 < value <= close * 1.04]
    if not supports:
        return {"status": "数据不足", "reason": "没有形成可验证的支撑共振区。"}
    anchor = float(np.median(supports))
    half_width = max(atr * 0.35, anchor * 0.004)
    pullback_low = anchor - half_width
    pullback_high = min(close * 1.01, anchor + half_width)
    entry = (pullback_low + pullback_high) / 2
    recent_low = float(data.iloc[-11:-1]["low"].min())
    ma50 = finite(latest.get("ma_50"))
    candidates = [recent_low - atr * 0.2]
    if ma50 is not None:
        candidates.append(ma50 - atr * 0.45)
    below = [value for value in candidates if value < pullback_low]
    invalidation = max(below) if below else pullback_low - atr
    invalidation = min(invalidation, pullback_low - atr * 0.3)
    risk = max(entry - invalidation, atr * 0.5)
    breakout = (prior_high if prior_high is not None else float(data.iloc[-21:-1]["high"].max())) * 1.003
    prior_60_high = float(data.iloc[-61:-1]["high"].max())
    target_1 = max(entry + risk * 1.5, breakout)
    target_2 = max(entry + risk * 2.5, prior_60_high, target_1 + atr * 0.5)
    no_chase = max(breakout + atr * 0.8, close * 1.04)
    return {
        "status": "ready",
        "pullback_low": _round_price(pullback_low),
        "pullback_high": _round_price(pullback_high),
        "breakout_trigger": _round_price(breakout),
        "no_chase_above": _round_price(no_chase),
        "invalidation": _round_price(invalidation),
        "target_1": _round_price(target_1),
        "target_2": _round_price(target_2),
        "risk_reward_1": round((target_1 - entry) / risk, 2),
        "risk_reward_2": round((target_2 - entry) / risk, 2),
        "reason": "EMA10/EMA20/MA20、近20日突破位、近期低点与ATR共同计算。",
    }


def _fundamental_score(financials: dict[str, Any], quote: Quote | None) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not financials:
        notes.append("最新财务接口暂缺，基本面按中性基准计分并降低置信度")
        score = 15.0
        if quote and quote.pe_ttm and 0 < quote.pe_ttm < 80:
            score += 1.0
        return min(score, 18.0), notes

    revenue_yoy = finite(financials.get("revenue_yoy"))
    profit_yoy = finite(financials.get("net_profit_yoy"))
    roe = finite(financials.get("roe"))
    eps = finite(financials.get("eps"))
    score = 0.0
    if revenue_yoy is None:
        score += 3.5
    elif revenue_yoy >= 30:
        score += 8
    elif revenue_yoy >= 15:
        score += 7
    elif revenue_yoy >= 5:
        score += 6
    elif revenue_yoy >= 0:
        score += 4.5
    elif revenue_yoy >= -10:
        score += 2.5
    if profit_yoy is None:
        score += 4.0
    elif profit_yoy >= 50:
        score += 10
    elif profit_yoy >= 25:
        score += 9
    elif profit_yoy >= 10:
        score += 7
    elif profit_yoy >= 0:
        score += 5
    elif profit_yoy >= -10:
        score += 3
    if roe is None:
        score += 3
    elif roe >= 20:
        score += 7
    elif roe >= 15:
        score += 6
    elif roe >= 10:
        score += 5
    elif roe >= 5:
        score += 3
    else:
        score += 1
    if eps is not None and eps > 0:
        score += 2
    if revenue_yoy is not None and profit_yoy is not None and revenue_yoy > 0 and profit_yoy > 0:
        score += 2
    if quote and quote.pe_ttm and 0 < quote.pe_ttm < 100:
        score += 1
    notes.append(
        f"财报日{str(financials.get('report_date') or '未知')[:10]}，营收同比{_fmt_pct(revenue_yoy)}，归母净利同比{_fmt_pct(profit_yoy)}，ROE{_fmt_pct(roe)}"
    )
    return min(30.0, score), notes


def _industry_score(config: StockConfig, market: dict[str, Any]) -> tuple[float, str]:
    base = max(0.0, min(100.0, config.industry_logic)) / 100 * 13.0
    industry_pct = None
    for item in market.get("industry_table", []):
        if str(item.get("industry")) == config.industry:
            industry_pct = finite(item.get("pct_change"))
            break
    if industry_pct is None:
        current = 3.5
        note = "板块实时强弱暂缺"
    else:
        current = max(0.0, min(7.0, 3.5 + industry_pct * 0.8))
        note = f"{config.industry}板块中位涨跌幅{industry_pct:+.2f}%"
    return min(20.0, base + current), note


def _trend_score(daily_trend: str, weekly_trend: str, data: pd.DataFrame) -> float:
    latest = data.iloc[-1]
    score = TREND_POINTS.get(daily_trend, 0.25) * 13
    score += TREND_POINTS.get(weekly_trend, 0.25) * 8
    adx = finite(latest.get("adx_14"), 0.0) or 0.0
    plus_di = finite(latest.get("plus_di_14"), 0.0) or 0.0
    minus_di = finite(latest.get("minus_di_14"), 0.0) or 0.0
    if adx >= 25 and plus_di > minus_di:
        score += 3
    elif adx >= 25 and minus_di > plus_di:
        score += 0.5
    else:
        score += 1.8
    rsi = finite(latest.get("rsi_14"))
    if rsi is not None and 48 <= rsi <= 72:
        score += 1
    return min(25.0, score)


def _structure_score(trend_60m: str, data: pd.DataFrame, patterns: list[str]) -> float:
    latest = data.iloc[-1]
    score = TREND_POINTS.get(trend_60m, 0.25) * 7
    rel_volume = finite(latest.get("rel_volume_20"), 1.0) or 1.0
    if 1.1 <= rel_volume <= 2.2:
        score += 3.5
    elif 0.7 <= rel_volume < 1.1:
        score += 2.5
    elif rel_volume > 2.2:
        score += 2.0
    else:
        score += 1.2
    if "放量突破" in patterns:
        score += 3
    if "缩量回踩" in patterns:
        score += 2.5
    if "假突破" in patterns:
        score -= 2
    if "跌破后反抽" in patterns:
        score += 0.5
    if any("顶背离" in flag for flag in patterns):
        score -= 1.5
    if any("底背离" in flag for flag in patterns):
        score += 1
    return max(0.0, min(15.0, score))


def _event_score(bundle: StockBundle) -> tuple[float, list[str]]:
    score = 5.0
    notes: list[str] = []
    for item in bundle.announcements[:8]:
        title = str(item.get("title") or "")
        if any(word in title for word in POSITIVE_EVENT_WORDS):
            score += 0.8
            notes.append(f"{item.get('date')} {title}")
        if any(word in title for word in NEGATIVE_EVENT_WORDS):
            score -= 1.5
            notes.append(f"风险：{item.get('date')} {title}")
    flow = bundle.fund_flow
    ratio = finite(flow.get("main_net_ratio")) if flow else None
    if ratio is not None:
        if ratio >= 5:
            score += 1.5
        elif ratio <= -5:
            score -= 1.5
        notes.append(f"主力净流入占比{ratio:+.2f}%（{flow.get('date')}）")
    if bundle.data_confidence == "low":
        score -= 2
    elif bundle.data_confidence == "medium":
        score -= 0.5
    return max(0.0, min(10.0, score)), notes[:6]


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


def analyze_stock(bundle: StockBundle, market: dict[str, Any], target_date: date) -> dict[str, Any]:
    config = bundle.config
    fundamental_quality = assess_fundamentals(
        bundle.financials,
        target_date,
        announcements=bundle.announcements,
    )
    if bundle.daily.empty or not bundle.valid_for_target:
        quote = bundle.quote
        return {
            "code": config.code,
            "name": config.name,
            "industry": config.industry,
            "themes": list(config.themes),
            "data_date": None if bundle.last_data_date is None else bundle.last_data_date.isoformat(),
            "source": bundle.core_sources,
            "data_confidence": bundle.data_confidence,
            "data_valid": False,
            "close": None if quote is None else quote.close,
            "pct_change": None if quote is None else quote.pct_change,
            "score": 0.0,
            "rating": "D",
            "daily_trend": "数据不足",
            "weekly_trend": "数据不足",
            "trend_60m": "数据不足",
            "conclusion": "当日完整日线未通过校验，只适合观察，不输出伪精确买点。",
            "patterns": [],
            "levels": {"status": "等待数据确认", "reason": "当日完整日线未通过校验。"},
            "financials": bundle.financials,
            "announcements": bundle.announcements,
            "fund_flow": bundle.fund_flow,
            "score_breakdown": {
                "fundamental": 0,
                "industry": 0,
                "trend": 0,
                "structure": 0,
                "events": 0,
            },
            "technical_trade_score": 0.0,
            **fundamental_quality,
            "source_status": bundle.source_status,
            "metrics": {},
            "events": [],
        }

    daily = add_indicators(bundle.daily)
    weekly = add_indicators(to_weekly(bundle.daily))
    intraday = add_indicators(bundle.intraday_60m) if len(bundle.intraday_60m) >= 26 else pd.DataFrame()
    daily_trend = _trend(daily)
    weekly_trend = _trend(weekly)
    trend_60m = _trend(intraday)
    patterns = _patterns(daily)
    levels = _levels(daily, allowed=bundle.data_confidence in {"high", "medium"})
    fundamental, fundamental_notes = _fundamental_score(bundle.financials, bundle.quote)
    industry, industry_note = _industry_score(config, market)
    trend = _trend_score(daily_trend, weekly_trend, daily)
    structure = _structure_score(trend_60m, daily, patterns)
    events_score, event_notes = _event_score(bundle)
    score = round(fundamental + industry + trend + structure + events_score, 1)
    if bundle.data_confidence == "medium":
        score = min(score, 89.0)
    latest = daily.iloc[-1]
    close = float(latest["close"])
    pullback_low = levels.get("pullback_low")
    pullback_high = levels.get("pullback_high")
    breakout = levels.get("breakout_trigger")
    rel_volume = finite(latest.get("rel_volume_20"), 0.0) or 0.0
    if pullback_low is not None and pullback_high is not None and pullback_low <= close <= pullback_high:
        action = "已进入条件化回踩观察区，仍需次日量价确认"
    elif breakout is not None and close >= breakout and rel_volume >= 1.3:
        action = "已达到放量突破条件，但不适合无条件追涨"
    elif daily_trend in {"强势多头", "多头"}:
        action = "股票结构较强，目前优先等待回踩或突破确认"
    else:
        action = "目前只适合观察，等待结构改善"
    conclusion = f"{daily_trend}/{weekly_trend}，60分钟{trend_60m}；{action}。"

    metric_keys = (
        "open",
        "high",
        "low",
        "close",
        "pct_change",
        "volume",
        "amount",
        "turnover_rate",
        "rel_volume_20",
        "ma_5",
        "ma_10",
        "ma_20",
        "ma_50",
        "ma_100",
        "ma_200",
        "ema_5",
        "ema_10",
        "ema_20",
        "ema_50",
        "rsi_14",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "kdj_k",
        "kdj_d",
        "kdj_j",
        "stoch_rsi_k",
        "stoch_rsi_d",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "obv",
        "high_20",
        "low_20",
        "atr_14",
    )
    metrics = {key: finite(latest.get(key)) for key in metric_keys}
    source_names = list(dict.fromkeys(bundle.core_sources + [
        str(bundle.financials.get("source") or ""),
        str(bundle.fund_flow.get("source") or ""),
    ]))
    source_names = [name for name in source_names if name]
    score_breakdown = {
        "fundamental": round(fundamental, 1),
        "industry": round(industry, 1),
        "trend": round(trend, 1),
        "structure": round(structure, 1),
        "events": round(events_score, 1),
    }
    return {
        "code": config.code,
        "name": config.name,
        "industry": config.industry,
        "themes": list(config.themes),
        "data_date": target_date.isoformat(),
        "source": source_names,
        "data_confidence": bundle.data_confidence,
        "data_valid": True,
        "close": close,
        "pct_change": float(latest["pct_change"]),
        "score": score,
        "rating": _rating(score),
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "trend_60m": trend_60m,
        "conclusion": conclusion,
        "patterns": patterns,
        "levels": levels,
        "financials": bundle.financials,
        "announcements": bundle.announcements,
        "fund_flow": bundle.fund_flow,
        "score_breakdown": score_breakdown,
        "technical_trade_score": technical_trade_score(score_breakdown),
        **fundamental_quality,
        "source_status": bundle.source_status,
        "metrics": metrics,
        "events": fundamental_notes + [industry_note] + event_notes,
    }


def _fmt_pct(value: float | None) -> str:
    return "暂缺" if value is None else f"{value:+.2f}%"
