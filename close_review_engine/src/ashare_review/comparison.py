from __future__ import annotations

from typing import Any

import numpy as np

from ashare_review.indicators import finite


def _theme_states(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aliases = {
        "AI算力": {"AI算力", "服务器", "AI应用"},
        "CPO": {"CPO", "光模块"},
        "PCB": {"PCB", "覆铜板"},
        "半导体": {"半导体", "半导体设备", "先进封装", "国产替代"},
        "存储": {"存储", "MCU"},
        "稀土": {"稀土", "稀土永磁", "新材料"},
    }
    output: dict[str, Any] = {}
    for label, tags in aliases.items():
        matched = [
            row for row in rows if row.get("data_valid") and tags.intersection(set(row.get("themes", [])))
        ]
        pct_values = [float(row["pct_change"]) for row in matched if row.get("pct_change") is not None]
        scores = [float(row["score"]) for row in matched]
        output[label] = {
            "sample_count": len(matched),
            "median_pct_change": None if not pct_values else round(float(np.median(pct_values)), 2),
            "average_score": None if not scores else round(float(np.mean(scores)), 1),
            "source": "固定股票池样本代理",
        }
    return output


def _market_summary(market: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    industries = market.get("industry_table", [])
    strong = [str(item.get("industry")) for item in industries[:5]]
    weak = [str(item.get("industry")) for item in industries[-5:]][::-1] if industries else []
    indices = market.get("indices", [])
    index_pcts = [finite(item.get("pct_change"), 0.0) or 0.0 for item in indices]
    breadth = market.get("breadth", {})
    median_pct = finite(breadth.get("median_pct"), 0.0) or 0.0
    up = int(breadth.get("up") or 0)
    down = int(breadth.get("down") or 0)
    if index_pcts and np.mean(index_pcts) > 0.7 and median_pct > 0.2 and up > down:
        posture = "可关注放量突破，但仍优先选择强板块中的确认信号"
    elif index_pcts and np.mean(index_pcts) >= -0.3 and median_pct >= -0.3:
        posture = "更适合等待回踩，突破交易需要量能确认"
    else:
        posture = "市场风险偏好较弱，当前应控制仓位并减少追涨"
    market = dict(market)
    market["strong_industries"] = strong
    market["weak_industries"] = weak
    market["theme_states"] = _theme_states(rows)
    market["posture"] = posture
    return market


def _compare(previous: dict[str, Any] | None, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not previous or not previous.get("stocks"):
        return {"baseline": True, "new_top5": [row["code"] for row in rows[:5]], "material": True}
    old = {str(row["code"]): row for row in previous.get("stocks", [])}
    current = {str(row["code"]): row for row in rows}
    old_top = {code for code, row in old.items() if int(row.get("rank", 999)) <= 5}
    new_top = {code for code, row in current.items() if int(row.get("rank", 999)) <= 5}
    result: dict[str, Any] = {
        "baseline": False,
        "new_top5": sorted(new_top - old_top, key=lambda code: current[code]["rank"]),
        "dropped_top5": sorted(old_top - new_top, key=lambda code: old[code]["rank"]),
        "rank_moves": [],
        "score_moves": [],
        "rating_changes": [],
        "daily_trend_changes": [],
        "trend_60m_changes": [],
        "level_changes": [],
        "new_events": [],
    }
    for code in sorted(old.keys() & current.keys()):
        before = old[code]
        after = current[code]
        if abs(int(after.get("rank", 999)) - int(before.get("rank", 999))) > 2:
            result["rank_moves"].append(
                {"code": code, "before": before.get("rank"), "after": after.get("rank")}
            )
        if abs(float(after.get("score", 0)) - float(before.get("score", 0))) >= 3:
            result["score_moves"].append(
                {"code": code, "before": before.get("score"), "after": after.get("score")}
            )
        for field, key in (
            ("rating", "rating_changes"),
            ("daily_trend", "daily_trend_changes"),
            ("trend_60m", "trend_60m_changes"),
        ):
            if before.get(field) != after.get(field):
                result[key].append(
                    {"code": code, "before": before.get(field), "after": after.get(field)}
                )
        changed_levels: list[str] = []
        old_levels = before.get("levels") or {}
        new_levels = after.get("levels") or {}
        for field in (
            "pullback_low",
            "pullback_high",
            "breakout_trigger",
            "invalidation",
            "target_1",
            "target_2",
        ):
            old_value = finite(old_levels.get(field))
            new_value = finite(new_levels.get(field))
            if old_value is None or new_value is None:
                if old_value != new_value:
                    changed_levels.append(field)
            elif abs(new_value - old_value) / max(abs(old_value), 0.01) > 0.01:
                changed_levels.append(field)
        if changed_levels:
            result["level_changes"].append({"code": code, "fields": changed_levels})
        old_titles = {str(item.get("title")) for item in before.get("announcements", [])}
        new_items = [
            item for item in after.get("announcements", []) if str(item.get("title")) not in old_titles
        ]
        if new_items:
            result["new_events"].append({"code": code, "items": new_items[:5]})
    result["material"] = any(
        result[key]
        for key in (
            "new_top5",
            "dropped_top5",
            "rank_moves",
            "score_moves",
            "rating_changes",
            "daily_trend_changes",
            "trend_60m_changes",
            "level_changes",
            "new_events",
        )
    )
    return result


def _alerts(rows: list[dict[str, Any]], comparison: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    for row in rows[:5]:
        levels = row.get("levels") or {}
        close = finite(row.get("close"))
        if close is None:
            continue
        low = finite(levels.get("pullback_low"))
        high = finite(levels.get("pullback_high"))
        breakout = finite(levels.get("breakout_trigger"))
        invalidation = finite(levels.get("invalidation"))
        rel_volume = finite((row.get("metrics") or {}).get("rel_volume_20"), 0.0) or 0.0
        if low is not None and high is not None and low <= close <= high:
            alerts.append(f"{row['name']}已进入回踩观察区{low:.2f}—{high:.2f}")
        if breakout is not None and close >= breakout and rel_volume >= 1.3:
            alerts.append(f"{row['name']}已达到放量突破触发条件{breakout:.2f}")
        if invalidation is not None and close < invalidation:
            alerts.append(f"{row['name']}已跌破结构失效参考{invalidation:.2f}")
        if "假突破" in row.get("patterns", []):
            alerts.append(f"{row['name']}出现突破失败并跌回压力位下方")
        divergences = [flag for flag in row.get("patterns", []) if "背离" in flag]
        if divergences:
            alerts.append(f"{row['name']}出现{'、'.join(divergences)}")
    if comparison.get("new_top5") or comparison.get("dropped_top5"):
        alerts.append(
            "Top5发生变化：新进"
            + ("、".join(comparison.get("new_top5", [])) or "无")
            + "；调出"
            + ("、".join(comparison.get("dropped_top5", [])) or "无")
        )
    for item in comparison.get("new_events", []):
        for event in item.get("items", [])[:2]:
            alerts.append(f"{item['code']}新增公告：{event.get('title')}")
    return alerts
