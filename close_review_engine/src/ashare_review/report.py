from __future__ import annotations

from typing import Any, Iterable

from ashare_review.indicators import finite

ROLE_LABELS = {
    "capacity_leader": "资金容量龙头",
    "momentum_leader": "弹性龙头",
    "pullback_potential": "缩量回踩潜力",
    "breakout_potential": "放量突破潜力",
}


def _fmt_number(value: Any, digits: int = 2, missing: str = "—") -> str:
    numeric = finite(value)
    return missing if numeric is None else f"{numeric:.{digits}f}"


def _fmt_price(value: Any) -> str:
    return _fmt_number(value, 2)


def _fmt_pct(value: Any) -> str:
    numeric = finite(value)
    return "—" if numeric is None else f"{numeric:+.2f}%"


def _fmt_amount(value: Any) -> str:
    numeric = finite(value)
    if numeric is None:
        return "—"
    if abs(numeric) >= 1_000_000_000_000:
        return f"{numeric / 1_000_000_000_000:.2f}万亿元"
    if abs(numeric) >= 100_000_000:
        return f"{numeric / 100_000_000:.2f}亿元"
    if abs(numeric) >= 10_000:
        return f"{numeric / 10_000:.2f}万元"
    return f"{numeric:.0f}元"


def _fmt_range(low: Any, high: Any) -> str:
    low_value = finite(low)
    high_value = finite(high)
    if low_value is None or high_value is None:
        return "等待数据确认"
    left, right = sorted((low_value, high_value))
    return f"{left:.2f}—{right:.2f}元"


def _join_names(rows: Iterable[dict[str, Any]], limit: int = 10) -> str:
    names = [str(row.get("board_name") or row.get("name") or row.get("code") or "") for row in rows]
    names = [name for name in names if name]
    return "、".join(names[:limit]) if names else "无"


def _stock_name_map(snapshot: dict[str, Any]) -> dict[str, str]:
    mapping = {str(row.get("code")): str(row.get("name")) for row in snapshot.get("stocks", [])}
    for item in (snapshot.get("sectors") or {}).get("dynamic_candidates", []):
        if item.get("code"):
            mapping[str(item["code"])] = str(item.get("name") or item["code"])
    return mapping


def _render_market(snapshot: dict[str, Any]) -> list[str]:
    market = snapshot.get("market") or {}
    indices = market.get("indices") or []
    index_text = []
    for item in indices:
        index_text.append(
            f"{item.get('name')}收于{_fmt_number(item.get('close'))}，"
            f"{_fmt_pct(item.get('pct_change'))}（{item.get('date') or snapshot['target_date']}，"
            f"{item.get('source') or '来源暂缺'}）"
        )
    breadth = market.get("breadth") or {}
    lines = ["## 第一部分：市场环境", ""]
    lines.append("；".join(index_text) + "。" if index_text else "三大指数数据暂缺。")
    lines.append(
        f"两市成交额：**{_fmt_amount(market.get('total_amount'))}**；"
        f"上涨{breadth.get('up') if breadth.get('up') is not None else '—'}家、"
        f"下跌{breadth.get('down') if breadth.get('down') is not None else '—'}家、"
        f"平盘{breadth.get('flat') if breadth.get('flat') is not None else '—'}家，"
        f"市场中位涨跌幅{_fmt_pct(breadth.get('median_pct'))}。"
    )
    lines.append(
        f"强势行业：{_join_names([{'board_name': item} for item in market.get('strong_industries', [])])}；"
        f"弱势行业：{_join_names([{'board_name': item} for item in market.get('weak_industries', [])])}。"
    )
    lines.append(f"当前环境判断：**{market.get('posture') or '等待数据确认'}**。")
    lines.append("")
    return lines


def _render_sector_ranking(rows: list[dict[str, Any]], heading: str) -> list[str]:
    lines = [heading, ""]
    if not rows:
        lines.extend(["板块数据暂缺，未使用固定股票池样本冒充全市场板块。", ""])
        return lines
    lines.extend(
        [
            "| 排名 | 板块 | 今日涨幅 | 5日 | 20日 | 成交额 | 相对20日量能 | 上涨/下跌 | 涨停数 | 评分 | 置信度 |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row.get('rank', '—')} | {row.get('board_name', '—')} | {_fmt_pct(row.get('pct_change'))} | "
            f"{_fmt_pct(row.get('return_5d'))} | {_fmt_pct(row.get('return_20d'))} | "
            f"{_fmt_amount(row.get('amount'))} | {_fmt_number(row.get('amount_ratio_20'))}倍 | "
            f"{row.get('up_count', '—')}/{row.get('down_count', '—')} | {row.get('limit_up_count', 0)} | "
            f"{_fmt_number(row.get('score'), 1)} | {row.get('confidence', 'partial')} |"
        )
    lines.append("")
    return lines


def _render_concepts(sectors: dict[str, Any]) -> list[str]:
    lines = ["## 第三部分：重点概念板块", ""]
    concept_rows = sectors.get("concept_ranking") or []
    if concept_rows:
        lines.extend(
            [
                "### 概念板块综合排名（前30）",
                "",
                "| 排名 | 概念 | 今日涨幅 | 5日 | 20日 | 成交额 | 广度 | 评分 |",
                "|---:|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in concept_rows[:30]:
            lines.append(
                f"| {row.get('rank')} | {row.get('board_name')} | {_fmt_pct(row.get('pct_change'))} | "
                f"{_fmt_pct(row.get('return_5d'))} | {_fmt_pct(row.get('return_20d'))} | "
                f"{_fmt_amount(row.get('amount'))} | {_fmt_pct((finite(row.get('breadth_ratio')) or 0) * 100)} | "
                f"{_fmt_number(row.get('score'), 1)} |"
            )
    else:
        lines.append("概念板块全市场数据暂缺。")
    lines.extend(
        [
            "",
            "### 固定关注概念",
            "",
            "| 方向 | 对应板块 | 今日涨幅 | 5日 | 20日 | 评分 | 状态 |",
            "|---|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in sectors.get("focus_concepts", []):
        lines.append(
            f"| {row.get('focus_label')} | {row.get('board_name') or '数据暂缺'} | "
            f"{_fmt_pct(row.get('pct_change'))} | {_fmt_pct(row.get('return_5d'))} | "
            f"{_fmt_pct(row.get('return_20d'))} | {_fmt_number(row.get('score'), 1)} | "
            f"{row.get('status', 'data_unavailable')} |"
        )
    lines.append("")
    return lines


def _render_board_groups(sectors: dict[str, Any]) -> list[str]:
    lines = ["## 第四部分：强势、上升与退潮板块", ""]
    for title, key in (
        ("强势板块Top5", "top_boards"),
        ("排名提升最快Top2", "rising_boards"),
        ("退潮风险Top3", "weak_boards"),
    ):
        rows = sectors.get(key) or []
        lines.extend([f"### {title}", ""])
        if not rows:
            lines.append("无可验证结果。")
        else:
            lines.extend(
                [
                    "| 板块 | 类型 | 今日涨幅 | 5日 | 20日 | 评分 | 风险提示 |",
                    "|---|---|---:|---:|---:|---:|---|",
                ]
            )
            for row in rows:
                flags = "、".join(row.get("risk_flags") or []) or "无明显量价风险标记"
                lines.append(
                    f"| {row.get('board_name')} | {row.get('board_type')} | {_fmt_pct(row.get('pct_change'))} | "
                    f"{_fmt_pct(row.get('return_5d'))} | {_fmt_pct(row.get('return_20d'))} | "
                    f"{_fmt_number(row.get('score'), 1)} | {flags} |"
                )
        lines.append("")
    return lines


def _render_board_2plus2(sectors: dict[str, Any]) -> list[str]:
    lines = ["## 第五部分：重点板块2+2", ""]
    boards = sectors.get("detailed_boards") or []
    if not boards:
        lines.extend(["没有形成可验证的重点板块2+2，不强行补足。", ""])
        return lines
    for index, board in enumerate(boards, start=1):
        lines.extend(
            [
                f"### {index}. {board.get('board_name')}（{board.get('board_type')}）",
                "",
                f"板块今日{_fmt_pct(board.get('pct_change'))}，5日{_fmt_pct(board.get('return_5d'))}，"
                f"20日{_fmt_pct(board.get('return_20d'))}，成交额{_fmt_amount(board.get('amount'))}，"
                f"综合评分**{_fmt_number(board.get('score'), 1)}**；合格主板100元以下候选"
                f"{board.get('qualified_count', 0)}只。",
                "",
                "| 角色 | 股票 | 收盘价 | 涨跌幅 | 日线/60分钟 | 回踩区 | 突破触发 | 失效参考 | 入选理由 |",
                "|---|---|---:|---:|---|---|---:|---:|---|",
            ]
        )
        picks = board.get("picks") or {}
        for role in (
            "capacity_leader",
            "momentum_leader",
            "pullback_potential",
            "breakout_potential",
        ):
            pick = picks.get(role) or {}
            role_label = pick.get("role_label") or ROLE_LABELS[role]
            if not pick.get("code"):
                lines.append(
                    f"| {role_label} | 无合格标的 | — | — | — | — | — | — | "
                    f"{pick.get('reason') or '不强行补足'} |"
                )
                continue
            levels = pick.get("levels") or {}
            lines.append(
                f"| {role_label} | {pick.get('name')} {pick.get('code')} | {_fmt_price(pick.get('close'))} | "
                f"{_fmt_pct(pick.get('pct_change'))} | {pick.get('daily_trend')}/{pick.get('trend_60m')} | "
                f"{_fmt_range(levels.get('pullback_low'), levels.get('pullback_high'))} | "
                f"{_fmt_price(levels.get('breakout_trigger'))} | {_fmt_price(levels.get('invalidation'))} | "
                f"{pick.get('reason')} |"
            )
        lines.append("")
    return lines


def _render_fixed_ranking(snapshot: dict[str, Any]) -> list[str]:
    universe_count = int(snapshot.get("universe_count") or len(snapshot.get("stocks") or []))
    lines = [f"## 第六部分：{universe_count}只固定股票完整排名", ""]
    lines.extend(
        [
            "| 排名 | 代码 | 名称 | 收盘价 | 当日涨跌幅 | 综合评分 | 评级 | 日线趋势 | 60分钟趋势 | 主要结论 |",
            "|---:|---|---|---:|---:|---:|---|---|---|---|",
        ]
    )
    for row in snapshot.get("stocks", []):
        lines.append(
            f"| {row.get('rank')} | {row.get('code')} | {row.get('name')} | {_fmt_price(row.get('close'))} | "
            f"{_fmt_pct(row.get('pct_change'))} | {_fmt_number(row.get('score'), 1)} | {row.get('rating')} | "
            f"{row.get('daily_trend')} | {row.get('trend_60m')} | {row.get('conclusion')} |"
        )
    lines.extend(
        [
            "",
            "评分维度固定为：基本面和业绩30分、行业景气和产业逻辑20分、日线和周线趋势25分、"
            "60分钟与量价结构15分、事件催化和风险控制10分。板块层不会因单日上涨直接替代固定池评分。",
            "",
        ]
    )
    return lines


def _top5_detail(row: dict[str, Any], index: int) -> list[str]:
    metrics = row.get("metrics") or {}
    levels = row.get("levels") or {}
    sources = "、".join(row.get("source") or []) or "来源暂缺"
    patterns = "、".join(row.get("patterns") or []) or "无显著形态标签"
    breakdown = row.get("score_breakdown") or {}
    events = "；".join(str(item) for item in (row.get("events") or [])[:4]) or "暂无新增可验证事件"
    ready = levels.get("status") == "ready"
    if ready:
        pullback = _fmt_range(levels.get("pullback_low"), levels.get("pullback_high"))
        breakout = _fmt_price(levels.get("breakout_trigger")) + "元"
        no_chase = _fmt_price(levels.get("no_chase_above")) + "元以上"
        invalidation = _fmt_price(levels.get("invalidation")) + "元"
        targets = f"第一目标{_fmt_price(levels.get('target_1'))}元，第二目标{_fmt_price(levels.get('target_2'))}元"
        risk_reward = (
            f"到第一/第二目标约{_fmt_number(levels.get('risk_reward_1'))}/"
            f"{_fmt_number(levels.get('risk_reward_2'))}"
        )
    else:
        pullback = breakout = no_chase = invalidation = targets = risk_reward = "等待数据确认"
    lines = [
        f"### {index}. {row.get('name')}（{row.get('code')}）",
        "",
        f"- 当前收盘价：**{_fmt_price(row.get('close'))}元**，当日{_fmt_pct(row.get('pct_change'))}；"
        f"数据日期{row.get('data_date')}，来源：{sources}，核心数据置信度：{row.get('data_confidence')}。",
        f"- 当日K线和成交量：开{_fmt_price(metrics.get('open'))}、高{_fmt_price(metrics.get('high'))}、"
        f"低{_fmt_price(metrics.get('low'))}、收{_fmt_price(metrics.get('close'))}；"
        f"成交额{_fmt_amount(metrics.get('amount'))}，换手率{_fmt_pct(metrics.get('turnover_rate'))}，"
        f"相对20日均量{_fmt_number(metrics.get('rel_volume_20'))}倍。",
        f"- 结构：日线**{row.get('daily_trend')}**，周线**{row.get('weekly_trend')}**，"
        f"60分钟**{row.get('trend_60m')}**；形态信号：{patterns}。",
        f"- 指标：MA5/10/20/50={_fmt_price(metrics.get('ma_5'))}/{_fmt_price(metrics.get('ma_10'))}/"
        f"{_fmt_price(metrics.get('ma_20'))}/{_fmt_price(metrics.get('ma_50'))}；"
        f"RSI14={_fmt_number(metrics.get('rsi_14'))}；MACD DIF/DEA/柱="
        f"{_fmt_number(metrics.get('macd_dif'))}/{_fmt_number(metrics.get('macd_dea'))}/"
        f"{_fmt_number(metrics.get('macd_hist'))}；ADX={_fmt_number(metrics.get('adx_14'))}。",
        f"- 最理想回踩买入区间：**{pullback}**。",
        f"- 放量突破买入触发价：**{breakout}**，需要收盘或60分钟级别放量确认，而非盘中瞬间越过。",
        f"- 不建议追涨区域：**{no_chase}**。",
        f"- 技术结构失效价/止损参考：**{invalidation}**。",
        f"- 目标位：{targets}。",
        f"- 当前风险收益比：{risk_reward}。",
        f"- 入选原因：总分{_fmt_number(row.get('score'), 1)}（基本面{_fmt_number(breakdown.get('fundamental'), 1)}、"
        f"行业{_fmt_number(breakdown.get('industry'), 1)}、趋势{_fmt_number(breakdown.get('trend'), 1)}、"
        f"量价{_fmt_number(breakdown.get('structure'), 1)}、事件风险{_fmt_number(breakdown.get('events'), 1)}）。"
        f"{events}",
        f"- 次日结论：**{row.get('conclusion')}** 股票本身优秀、当前价格值得买、目前只适合观察三者不能等同。",
        "",
    ]
    return lines


def _render_fixed_top5(snapshot: dict[str, Any]) -> list[str]:
    lines = ["## 第七部分：固定池Top5重点分析", ""]
    for index, row in enumerate(snapshot.get("stocks", [])[:5], start=1):
        lines.extend(_top5_detail(row, index))
    return lines


def _render_dynamic_candidates(sectors: dict[str, Any]) -> list[str]:
    lines = ["## 第八部分：动态候选买点", ""]
    candidates = sectors.get("dynamic_candidates") or []
    if not candidates:
        lines.extend(["今日没有满足沪深主板、100元以下、非ST和流动性门槛的动态2+2候选。", ""])
        return lines
    lines.extend(
        [
            "动态候选只对当日和下一交易日有效，不自动加入固定股票池。相同股票在不同板块承担不同角色时会分别展示。",
            "",
            "| 板块 | 角色 | 股票 | 收盘 | 涨跌幅 | 日线/60分钟 | 回踩区 | 突破价 | 失效价 | 目标1/2 | 当前结论 |",
            "|---|---|---|---:|---:|---|---|---:|---:|---|---|",
        ]
    )
    for item in candidates:
        levels = item.get("levels") or {}
        conclusion = (
            "等待回踩确认"
            if item.get("role") == "pullback_potential"
            else "等待放量突破确认"
            if item.get("role") == "breakout_potential"
            else "板块观察锚，不等于立即买入"
        )
        lines.append(
            f"| {item.get('board_name')} | {item.get('role_label')} | {item.get('name')} {item.get('code')} | "
            f"{_fmt_price(item.get('close'))} | {_fmt_pct(item.get('pct_change'))} | "
            f"{item.get('daily_trend')}/{item.get('trend_60m')} | "
            f"{_fmt_range(levels.get('pullback_low'), levels.get('pullback_high'))} | "
            f"{_fmt_price(levels.get('breakout_trigger'))} | {_fmt_price(levels.get('invalidation'))} | "
            f"{_fmt_price(levels.get('target_1'))}/{_fmt_price(levels.get('target_2'))} | {conclusion} |"
        )
    lines.append("")
    return lines


def _format_stock_changes(comparison: dict[str, Any], names: dict[str, str]) -> list[str]:
    lines = []
    if comparison.get("baseline"):
        return ["固定股票池为首次有效基准，没有上一交易日可比数据。"]
    lines.append(
        "固定Top5：新进入"
        + ("、".join(names.get(code, code) for code in comparison.get("new_top5", [])) or "无")
        + "；跌出"
        + ("、".join(names.get(code, code) for code in comparison.get("dropped_top5", [])) or "无")
        + "。"
    )
    for label, key in (
        ("排名变化超过2位", "rank_moves"),
        ("评分变化达到3分", "score_moves"),
        ("日线评级变化", "rating_changes"),
        ("60分钟趋势变化", "trend_60m_changes"),
        ("关键价位变化超过1%", "level_changes"),
    ):
        items = comparison.get(key) or []
        lines.append(f"{label}：" + ("、".join(names.get(str(item.get('code')), str(item.get('code'))) for item in items) or "无") + "。")
    return lines


def _render_comparison(snapshot: dict[str, Any]) -> list[str]:
    lines = ["## 第九部分：与上一次排名对比", ""]
    sectors = snapshot.get("sectors") or {}
    sector_comparison = sectors.get("comparison") or {}
    if sector_comparison.get("baseline"):
        lines.append("板块层为首次有效基准，没有上一交易日可比数据。")
    else:
        lines.append(
            "板块Top5：新进入"
            + (_join_names(sector_comparison.get("new_top_boards") or []) or "无")
            + "；退出"
            + (_join_names(sector_comparison.get("dropped_top_boards") or []) or "无")
            + "。"
        )
        lines.append(
            "板块排名变化超过2位："
            + (_join_names(sector_comparison.get("rank_moves") or []) or "无")
            + "。"
        )
        lines.append(
            "板块评分变化达到5分："
            + (_join_names(sector_comparison.get("score_moves") or []) or "无")
            + "。"
        )
        lines.append(
            "2+2角色发生变化："
            + (_join_names(sector_comparison.get("role_changes") or []) or "无")
            + "。"
        )
    lines.append("")
    names = _stock_name_map(snapshot)
    lines.extend(_format_stock_changes(snapshot.get("comparison") or {}, names))
    lines.extend(["", "### 重要买点与事件变化", ""])
    alerts = snapshot.get("alerts") or []
    if alerts:
        lines.extend(f"- {item}" for item in alerts)
    else:
        lines.append("今日Top5名单及核心买点没有实质变化。")
    lines.append("")
    return lines


def _candidate_pool(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in (snapshot.get("sectors") or {}).get("dynamic_candidates", []):
        copy = dict(item)
        copy["pool"] = "dynamic"
        rows.append(copy)
    for item in snapshot.get("stocks", []):
        copy = dict(item)
        copy["pool"] = "fixed"
        copy.setdefault("board_name", item.get("industry"))
        rows.append(copy)
    return rows


def _best_pullback(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = []
    for row in rows:
        levels = row.get("levels") or {}
        close = finite(row.get("close"))
        low = finite(levels.get("pullback_low"))
        high = finite(levels.get("pullback_high"))
        if levels.get("status") != "ready" or None in (close, low, high):
            continue
        left, right = sorted((float(low), float(high)))
        distance = 0.0 if left <= close <= right else min(abs(close - left), abs(close - right)) / max(close, 0.01)
        trend_bonus = 0 if row.get("daily_trend") in {"强势空头", "空头"} else 0.03
        scored.append((trend_bonus - distance, row))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _best_breakout(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = []
    for row in rows:
        levels = row.get("levels") or {}
        close = finite(row.get("close"))
        trigger = finite(levels.get("breakout_trigger"))
        if levels.get("status") != "ready" or close in (None, 0) or trigger is None:
            continue
        distance = trigger / close - 1
        if -0.01 <= distance <= 0.10:
            scored.append((-abs(distance) + (finite(row.get("score"), 0.0) or 0) / 1000, row))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _most_extended(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = []
    for row in rows:
        close = finite(row.get("close"))
        no_chase = finite((row.get("levels") or {}).get("no_chase_above"))
        pct = finite(row.get("pct_change"), 0.0) or 0.0
        if close is None:
            continue
        extension = close / no_chase if no_chase not in (None, 0) else 0
        scored.append((extension + max(pct, 0) / 20, row))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _decision_text(label: str, row: dict[str, Any] | None) -> str:
    if not row:
        return f"{label}：暂无满足数据和结构条件的标的。"
    board = row.get("board_name") or row.get("industry") or "所属板块"
    return (
        f"{label}：**{board}—{row.get('name')}（{row.get('code')}）**。"
        "这是条件化观察结论，不代表当前价格必须买入。"
    )


def _trade_recommendations(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    eligible = []
    for row in snapshot.get("stocks", []):
        levels = row.get("levels") or {}
        required = (
            "pullback_low",
            "pullback_high",
            "breakout_trigger",
            "no_chase_above",
            "invalidation",
            "target_1",
            "target_2",
            "risk_reward_1",
        )
        if levels.get("status") != "ready" or any(finite(levels.get(key)) is None for key in required):
            continue
        if row.get("daily_trend") in {"强势空头", "空头"}:
            continue
        close = finite(row.get("close"))
        no_chase = finite(levels.get("no_chase_above"))
        risk_reward = finite(levels.get("risk_reward_1"), 0.0) or 0.0
        if close is None or no_chase is None or close >= no_chase or risk_reward < 1.5:
            continue
        eligible.append(row)
    return sorted(eligible, key=lambda row: (-(finite(row.get("score"), 0.0) or 0.0), int(row.get("rank") or 999)))[:2]


def _render_trade_plan(snapshot: dict[str, Any]) -> list[str]:
    decision = snapshot.get("trade_decision") or {}
    regime = decision.get("market_regime") or (snapshot.get("market") or {}).get("trade_regime") or {}
    lines = [
        "## 第十部分：推荐交易计划",
        "",
        "所有计划均为下一交易日的条件化方案，不自动下单；未触发、跳空越过追高线或开盘跌破止损即取消。",
        "模型仓位上限按每笔账户风险0.5%计算，不代表已经读取或校验用户真实持仓。",
        "",
        "### 1. 市场交易状态与模型总仓位上限",
        "",
        f"市场状态：**{regime.get('label', 'unavailable')}**，评分{_fmt_number(regime.get('score'), 1)}；"
        f"模型总仓位上限**{_fmt_number(regime.get('max_total_weight_pct'), 1)}%**。",
    ]
    for evidence in regime.get("evidence") or []:
        lines.append(f"- {evidence}")

    def append_plan_table(heading: str, plans: list[dict[str, Any]], empty: str) -> None:
        lines.extend(["", heading, ""])
        if not plans:
            lines.append(empty)
            return
        lines.extend(
            [
                "| 股票 | 类型 | 状态 | 技术/综合分 | 有效日 | 入场 | 止损 | 目标1/2 | 赔率1/2 | 禁止追高 | 模型仓位上限 |",
                "|---|---|---|---:|---|---|---:|---|---:|---:|---:|",
            ]
        )
        for plan in plans:
            entry = plan.get("entry") or {}
            status = {
                "ready_next_session": "下一交易日条件就绪",
                "waiting_trigger": "等待触发",
                "watch_only": "仅观察",
                "rejected": "回避",
            }.get(str(plan.get("decision_status")), str(plan.get("decision_status") or "未知"))
            recommendation = (
                "综合推荐" if plan.get("recommendation_type") == "comprehensive" else "技术交易"
            )
            lines.append(
                f"| {plan.get('name')} {plan.get('code')} | {recommendation}·{plan.get('setup')} | {status} | "
                f"{_fmt_number(plan.get('technical_trade_score'), 1)}/{_fmt_number(plan.get('composite_score'), 1)} | "
                f"{plan.get('valid_for', '—')} | {_fmt_range(entry.get('low'), entry.get('high'))} | "
                f"{_fmt_price(plan.get('stop'))} | {_fmt_price(plan.get('target_1'))}/"
                f"{_fmt_price(plan.get('target_2'))} | {_fmt_number(plan.get('risk_reward_1'))}/"
                f"{_fmt_number(plan.get('risk_reward_2'))} | {_fmt_price(plan.get('no_chase_above'))} | "
                f"{_fmt_number(plan.get('model_weight_pct'), 2)}% |"
            )

    append_plan_table(
        "### 2. 今日可执行",
        list(decision.get("executable") or []),
        "**今日无可执行交易。** 不为凑数而把相对排名靠前的股票写成买入建议。",
    )
    append_plan_table(
        "### 3. 等待触发",
        list(decision.get("waiting_trigger") or []),
        "没有等待触发的合格结构。",
    )

    technical_missing = [
        plan
        for plan in decision.get("all_plans") or []
        if plan.get("recommendation_type") == "technical_only"
        and plan.get("fundamental_status") in {"missing", "stale", "partial"}
        and plan.get("decision_status") != "rejected"
    ]
    lines.extend(["", "### 4. 技术交易但基本面缺失", ""])
    if not technical_missing:
        lines.append("没有基本面降级的技术候选。")
    else:
        seen: set[tuple[str, str]] = set()
        for plan in technical_missing:
            key = (str(plan.get("code")), str(plan.get("setup")))
            if key in seen:
                continue
            seen.add(key)
            status_label = {
                "missing": "基本面缺失",
                "stale": "基本面过期",
                "partial": "基本面不完整",
            }.get(str(plan.get("fundamental_status")), "基本面降级")
            missing = "、".join(plan.get("fundamental_missing_fields") or []) or "报告日期过期"
            lines.append(
                f"- **技术交易｜{status_label}**：{plan.get('name')}（{plan.get('code')}）{plan.get('setup')}；"
                f"缺失字段：{missing}；基本面状态仓位上限"
                f"{_fmt_number(plan.get('fundamental_position_cap_pct'), 2)}%，当前模型仓位上限"
                f"{_fmt_number(plan.get('model_weight_pct'), 2)}%，"
                "最长持有5个交易日，不得标为综合推荐。"
            )

    watch_and_rejected = [
        *(decision.get("watch_only") or []),
        *(decision.get("rejected") or []),
    ]
    lines.extend(["", "### 5. 观察与回避", ""])
    if not watch_and_rejected:
        lines.append("没有额外观察或回避项。")
    else:
        for plan in watch_and_rejected:
            reasons = "、".join(plan.get("rejection_reasons") or []) or "尚未达到执行门槛"
            lines.append(
                f"- {plan.get('name')}（{plan.get('code')}）{plan.get('setup')}："
                f"{plan.get('decision_status')}；未入选原因：{reasons}。"
            )

    all_plans = list(decision.get("all_plans") or [])
    append_plan_table(
        "### 6. 回踩计划明细",
        [plan for plan in all_plans if plan.get("setup") == "pullback"],
        "没有价位完整的回踩计划。",
    )
    append_plan_table(
        "### 7. 突破计划明细",
        [plan for plan in all_plans if plan.get("setup") == "breakout"],
        "没有价位完整的突破计划。",
    )
    lines.extend(
        [
            "",
            "突破第一目标必须严格高于突破入场；突破计划使用自己的止损、目标与赔率，不复用回踩计划。",
            "",
            "### 8. 推荐依据与缺失字段",
            "",
            "绝对门槛：行情有效且高置信度、技术交易评分不低于70、日线多头或强势多头、"
            "60分钟非空头、第一目标赔率不低于1.80、关键价位与ATR完整、未进入追高区且无硬风险。",
        ]
    )
    for plan in [*(decision.get("executable") or []), *(decision.get("waiting_trigger") or [])]:
        trigger = (plan.get("trigger") or {}).get("description") or "等待量价确认"
        reasons = "、".join(plan.get("reasons") or []) or "全部绝对门槛已核验"
        lines.append(
            f"- {plan.get('name')}（{plan.get('code')}）{plan.get('setup')}：触发方式为{trigger}；"
            f"分析依据：{reasons}。"
        )

    lines.extend(["", "### 9. 昨日计划验收", ""])
    previous = snapshot.get("previous_trade_review") or []
    if not previous:
        lines.append("没有可验收的上一交易日已保存计划。")
    else:
        for item in previous:
            outcome = item.get("outcome") or {}
            lines.append(
                f"- {item.get('name')}（{item.get('code')}）{item.get('setup')}："
                f"{item.get('lifecycle_status')}；入场{_fmt_price(item.get('entry_price'))}，"
                f"MFE/MAE {_fmt_pct(item.get('mfe_pct'))}/{_fmt_pct(item.get('mae_pct'))}，"
                f"持有{item.get('holding_sessions') or 0}个交易日，"
                f"结束原因{outcome.get('exit_reason') or '尚未结束'}。"
            )

    stats = snapshot.get("trade_statistics") or {}
    lines.extend(["", "### 10. 累计统计与样本置信度", ""])
    lines.append(
        f"已结束且非歧义样本{int(stats.get('sample_count') or 0)}笔；胜率{_fmt_number(stats.get('win_rate_pct'))}%，"
        f"平均盈利/亏损{_fmt_number(stats.get('average_win_pct'))}%/"
        f"{_fmt_number(stats.get('average_loss_pct'))}%，期望收益{_fmt_number(stats.get('expectancy_pct'))}%，"
        f"最大连续亏损{int(stats.get('max_consecutive_losses') or 0)}笔，"
        f"模拟权益最大回撤{_fmt_number(stats.get('max_drawdown_pct'))}%。"
    )
    if stats.get("confidence") != "sufficient":
        lines.append("**统计置信度不足**：真实保存并结束的非歧义样本少于30笔，不输出高置信度胜率结论。")
    lines.append("")
    return lines


def _render_final(snapshot: dict[str, Any]) -> list[str]:
    rows = _candidate_pool(snapshot)
    pullback = _best_pullback(rows)
    breakout = _best_breakout(rows)
    extended = _most_extended(rows)
    sectors = snapshot.get("sectors") or {}
    weak_board = (sectors.get("weak_boards") or [None])[0]
    lines = ["## 第十一部分：最终操作结论", ""]
    lines.append(_decision_text("最值得等待回踩的板块和股票", pullback))
    lines.append(_decision_text("最值得等待突破确认的板块和股票", breakout))
    if extended:
        lines.append(_decision_text("当前最不适合追涨的板块和股票", extended))
    elif weak_board:
        lines.append(f"当前最不适合追涨的板块和股票：**{weak_board.get('board_name')}板块**，个股等待结构修复。")
    else:
        lines.append("当前最不适合追涨的板块和股票：暂无可靠结论。")
    lines.extend(
        [
            "",
            "必须区分：**股票本身优秀**、**当前价格值得买**、**目前只适合观察**。"
            "本报告不承诺收益，不构成确定性买卖指令。",
            "",
            f"结构化明细：`data/processed/{snapshot['target_date']}/snapshot.json`；"
            f"固定池{snapshot.get('universe_count', len(snapshot.get('stocks') or []))}只排名CSV："
            f"`data/processed/{snapshot['target_date']}/ranking.csv`。",
            "",
        ]
    )
    return lines


def render_report(snapshot: dict[str, Any]) -> str:
    target_date = str(snapshot.get("target_date"))
    valid_count = int(snapshot.get("valid_count") or 0)
    universe_count = int(snapshot.get("universe_count") or 0)
    sectors = snapshot.get("sectors") or {}
    lines = [
        f"# {target_date} 沪深A股板块2+2与固定股票池收盘复盘",
        "",
        f"> 数据状态：固定池{valid_count}/{universe_count}只股票通过{target_date}完整日线校验；"
        f"行业板块{len(sectors.get('industry_ranking', []))}个、概念板块"
        f"{len(sectors.get('concept_ranking', []))}个；报告生成时间{snapshot.get('generated_at')}。",
        "> 固定池、动态板块候选和关键价位均只使用已完成日线；板块或扩展数据缺失时明确降级，"
        "不以前一交易日数据冒充，不用固定股票池样本冒充全市场概念板块。",
        "",
    ]
    lines.extend(_render_market(snapshot))
    lines.extend(_render_sector_ranking(sectors.get("industry_ranking") or [], "## 第二部分：行业板块完整排名"))
    lines.extend(_render_concepts(sectors))
    lines.extend(_render_board_groups(sectors))
    lines.extend(_render_board_2plus2(sectors))
    lines.extend(_render_fixed_ranking(snapshot))
    lines.extend(_render_fixed_top5(snapshot))
    lines.extend(_render_dynamic_candidates(sectors))
    lines.extend(_render_comparison(snapshot))
    lines.extend(_render_trade_plan(snapshot))
    lines.extend(_render_final(snapshot))
    return "\n".join(lines)
