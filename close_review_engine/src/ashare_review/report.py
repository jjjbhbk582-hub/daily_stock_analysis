from __future__ import annotations

from typing import Any


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂缺"
    if abs(number) >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.2f}万亿元"
    if abs(number) >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿元"
    if abs(number) >= 10_000:
        return f"{number / 10_000:.2f}万元"
    return f"{number:.0f}元"


def _price(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _name_map(snapshot: dict[str, Any]) -> dict[str, str]:
    return {str(row["code"]): str(row["name"]) for row in snapshot.get("stocks", [])}


def _format_codes(codes: list[str], names: dict[str, str]) -> str:
    return "、".join(f"{names.get(code, code)}({code})" for code in codes) or "无"


def _format_changes(items: list[dict[str, Any]], names: dict[str, str]) -> str:
    if not items:
        return "无"
    return "；".join(
        f"{names.get(str(item['code']), item['code'])}：{item.get('before')}→{item.get('after')}"
        for item in items
    )


def _top5_action(row: dict[str, Any]) -> str:
    levels = row.get("levels") or {}
    close = row.get("close")
    try:
        close_value = float(close)
    except (TypeError, ValueError):
        return "只适合观察"
    low = levels.get("pullback_low")
    high = levels.get("pullback_high")
    trigger = levels.get("breakout_trigger")
    rel_volume = (row.get("metrics") or {}).get("rel_volume_20")
    try:
        if low is not None and high is not None and float(low) <= close_value <= float(high):
            return "已进入回踩观察区，但仍需次日止跌和量价确认，不等于立即买入"
        if trigger is not None and rel_volume is not None and close_value >= float(trigger) and float(rel_volume) >= 1.3:
            return "已满足放量突破条件，可观察次日能否守住触发价，不宜无条件追高"
    except (TypeError, ValueError):
        pass
    return "不建议次日直接追价，只等待回踩区或突破触发条件"


def _choose_final(snapshot: dict[str, Any]) -> tuple[str, str, str]:
    candidates = [row for row in snapshot.get("stocks", []) if (row.get("levels") or {}).get("status") == "ready"]
    if not candidates:
        return "暂无", "暂无", "全部等待数据确认"
    pullback = max(
        candidates,
        key=lambda row: (
            row.get("daily_trend") in {"强势多头", "多头"},
            float((row.get("levels") or {}).get("risk_reward_2") or 0),
            float(row.get("score") or 0),
        ),
    )
    breakout = max(
        candidates,
        key=lambda row: (
            "放量突破" in row.get("patterns", []),
            float(row.get("score") or 0),
        ),
    )
    no_chase = max(
        candidates,
        key=lambda row: (
            float(row.get("close") or 0) / max(float((row.get("levels") or {}).get("no_chase_above") or 1), 0.01),
            float((row.get("metrics") or {}).get("rsi_14") or 0),
        ),
    )
    return (
        f"{pullback['name']}({pullback['code']})",
        f"{breakout['name']}({breakout['code']})",
        f"{no_chase['name']}({no_chase['code']})",
    )


def render_report(snapshot: dict[str, Any]) -> str:
    target_date = snapshot["target_date"]
    market = snapshot.get("market") or {}
    rows = snapshot.get("stocks") or []
    comparison = snapshot.get("comparison") or {}
    names = _name_map(snapshot)
    lines: list[str] = [
        f"# {target_date} 17只沪深A股收盘复盘",
        "",
        f"> 数据状态：{snapshot.get('valid_count', 0)}/{snapshot.get('universe_count', 17)}只股票通过{target_date}完整日线校验；报告生成时间{snapshot.get('generated_at')}。",
        "> 价格与技术指标均以已经完成的日线和60分钟K线计算；扩展数据缺失只降低相关评分置信度，不以前一交易日冒充当日数据。",
        "",
        "## 第一部分：市场环境",
        "",
    ]

    indices = market.get("indices") or []
    if indices:
        lines.append(
            "；".join(
                f"{item.get('name')}收于{_price(item.get('close'))}，{_pct(item.get('pct_change'))}（{item.get('date')}，{item.get('source')}）"
                for item in indices
            ) + "。"
        )
    else:
        lines.append("三大指数当日收盘数据暂未完整验证。")
    breadth = market.get("breadth") or {}
    lines.extend(
        [
            f"全市场成交额：{_money(market.get('total_amount'))}；上涨{breadth.get('up', '—')}家、下跌{breadth.get('down', '—')}家，中位涨跌幅{_pct(breadth.get('median_pct'))}。",
            f"强势行业：{'、'.join(market.get('strong_industries') or []) or '暂缺'}；弱势行业：{'、'.join(market.get('weak_industries') or []) or '暂缺'}。",
            "",
            "相关方向资金/强弱状态（以固定股票池作为主题代理，不冒充全市场概念板块）：",
            "",
            "| 方向 | 样本数 | 样本中位涨跌幅 | 样本平均评分 | 来源 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for theme, item in (market.get("theme_states") or {}).items():
        lines.append(
            f"| {theme} | {item.get('sample_count', 0)} | {_pct(item.get('median_pct_change'))} | {_price(item.get('average_score'))} | {item.get('source')} |"
        )
    lines.extend(["", f"当前环境判断：**{market.get('posture', '等待数据确认')}**。", ""])

    lines.extend(
        [
            "## 第二部分：17只股票完整排名",
            "",
            "| 排名 | 代码 | 名称 | 收盘价 | 当日涨跌幅 | 综合评分 | 评级 | 日线趋势 | 60分钟趋势 | 主要结论 |",
            "|---:|---|---|---:|---:|---:|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {rank} | {code} | {name} | {close} | {pct} | {score:.1f} | {rating} | {daily} | {m60} | {conclusion} |".format(
                rank=row.get("rank"),
                code=row.get("code"),
                name=row.get("name"),
                close=_price(row.get("close")),
                pct=_pct(row.get("pct_change")),
                score=float(row.get("score") or 0),
                rating=row.get("rating"),
                daily=row.get("daily_trend"),
                m60=row.get("trend_60m"),
                conclusion=str(row.get("conclusion") or "").replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "评分维度固定为：基本面和业绩30分、行业景气和产业逻辑20分、日线和周线趋势25分、60分钟与量价结构15分、事件催化和风险控制10分。",
            "",
            "## 第三部分：Top5重点分析",
            "",
        ]
    )

    for row in rows[:5]:
        metrics = row.get("metrics") or {}
        levels = row.get("levels") or {}
        score_parts = row.get("score_breakdown") or {}
        source = "、".join(row.get("source") or []) or "核心数据源暂缺"
        lines.extend(
            [
                f"### {row.get('rank')}. {row.get('name')}（{row.get('code')}）",
                "",
                f"- 当前收盘价：**{_price(row.get('close'))}元**，当日{_pct(row.get('pct_change'))}；数据日期{row.get('data_date')}，来源：{source}，核心数据置信度：{row.get('data_confidence')}。",
                f"- 当日K线和成交量：开{_price(metrics.get('open'))}、高{_price(metrics.get('high'))}、低{_price(metrics.get('low'))}、收{_price(metrics.get('close'))}；成交额{_money(metrics.get('amount'))}，换手率{_pct(metrics.get('turnover_rate'))}，相对20日均量{_price(metrics.get('rel_volume_20'))}倍。",
                f"- 结构：日线**{row.get('daily_trend')}**，周线**{row.get('weekly_trend')}**，60分钟**{row.get('trend_60m')}**；形态信号：{'、'.join(row.get('patterns') or []) or '无明确突破/背离信号'}。",
                f"- 指标：MA5/10/20/50={_price(metrics.get('ma_5'))}/{_price(metrics.get('ma_10'))}/{_price(metrics.get('ma_20'))}/{_price(metrics.get('ma_50'))}；RSI14={_price(metrics.get('rsi_14'))}；MACD DIF/DEA/柱={_price(metrics.get('macd_dif'))}/{_price(metrics.get('macd_dea'))}/{_price(metrics.get('macd_hist'))}；ADX={_price(metrics.get('adx_14'))}。",
                f"- 最理想回踩买入区间：**{_price(levels.get('pullback_low'))}—{_price(levels.get('pullback_high'))}元**。",
                f"- 放量突破买入触发价：**{_price(levels.get('breakout_trigger'))}元**，需要收盘或60分钟级别放量确认，而非盘中瞬间越过。",
                f"- 不建议追涨区域：**{_price(levels.get('no_chase_above'))}元以上**。",
                f"- 技术结构失效价/止损参考：**{_price(levels.get('invalidation'))}元**。",
                f"- 目标位：第一目标**{_price(levels.get('target_1'))}元**，第二目标**{_price(levels.get('target_2'))}元**。",
                f"- 当前风险收益比：到第一/第二目标约**{_price(levels.get('risk_reward_1'))}/{_price(levels.get('risk_reward_2'))}**。",
                f"- 入选原因：总分{row.get('score')}（基本面{score_parts.get('fundamental')}、行业{score_parts.get('industry')}、趋势{score_parts.get('trend')}、量价{score_parts.get('structure')}、事件风险{score_parts.get('events')}）。{'；'.join(row.get('events') or [])}",
                f"- 次日结论：**{_top5_action(row)}**。股票本身优秀、当前价格值得买、目前只适合观察三者不能等同。",
                "",
            ]
        )

    lines.extend(["## 第四部分：和上一次排名对比", ""])
    if comparison.get("baseline"):
        lines.append("首次建立有效基准，暂无上一交易日排名可比较。")
    else:
        lines.extend(
            [
                f"1. 新进入Top5：{_format_codes(comparison.get('new_top5', []), names)}。",
                f"2. 跌出Top5：{_format_codes(comparison.get('dropped_top5', []), names)}。",
                f"3. 排名升降超过2位：{_format_changes(comparison.get('rank_moves', []), names)}。",
                f"4. 综合评分变化达到3分：{_format_changes(comparison.get('score_moves', []), names)}。",
                f"5. 日线评级变化：{_format_changes(comparison.get('rating_changes', []), names)}。",
                f"6. 60分钟趋势变化：{_format_changes(comparison.get('trend_60m_changes', []), names)}。",
                "7. 关键价位变化超过1%："
                + (
                    "；".join(
                        f"{names.get(str(item['code']), item['code'])}：{','.join(item.get('fields', []))}"
                        for item in comparison.get("level_changes", [])
                    )
                    or "无"
                )
                + "。",
                "8. 新财报、公告、监管或行业催化："
                + (
                    "；".join(
                        f"{names.get(str(item['code']), item['code'])}："
                        + "、".join(str(event.get("title")) for event in item.get("items", []))
                        for item in comparison.get("new_events", [])
                    )
                    or "无"
                )
                + "。",
            ]
        )
    lines.extend(["", "## 第五部分：买点变化提醒", ""])
    alerts = snapshot.get("alerts") or []
    if alerts:
        lines.extend(f"- {alert}" for alert in alerts)
    elif not comparison.get("material"):
        lines.append("**今日Top5名单及核心买点没有实质变化。**")
    else:
        lines.append("本日没有触发进入回踩区、放量突破、失效价或明显背离等高优先级提醒。")

    pullback, breakout, no_chase = _choose_final(snapshot)
    lines.extend(
        [
            "",
            "## 最终操作结论",
            "",
            f"1. 最值得等待回踩的股票：**{pullback}**。仅在回踩区获得止跌确认后再评估，不是确定性买入指令。",
            f"2. 最值得等待突破确认的股票：**{breakout}**。只有放量并守住触发价，才说明突破有效性提高。",
            f"3. 当前最不适合追涨的股票：**{no_chase}**。股票本身可能优秀，但当前价格和风险收益比未必适合追价。",
            "",
            "> 本报告不承诺收益，不构成确定性买卖指令。所有价格均为条件化技术参考，应结合仓位、交易制度和个人风险承受能力。",
            "",
            "### 数据来源说明",
            "",
            "- 日线降级链：东方财富公开K线 → 腾讯复权日线 → 网易历史行情。",
            "- 当日收盘交叉核验：腾讯15:00收盘快照；60分钟：东方财富60分钟K线。",
            "- 财报、公告与资金：东方财富数据中心/公告/资金流接口；缺失字段在JSON中保留来源状态，不用旧数据冒充。",
            f"- 结构化明细：`data/processed/{target_date}/snapshot.json`；17只排名CSV：`data/processed/{target_date}/ranking.csv`。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
