from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ashare_review.config import StockConfig
from ashare_review.indicators import finite

_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "电子元件": ("电子元件", "元件", "计算机通信和其他电子设备制造"),
    "通信设备": ("通信设备", "通信", "电信广播电视和卫星传输服务"),
    "半导体": ("半导体", "芯片"),
    "消费电子": ("消费电子", "电子设备制造"),
    "游戏": ("游戏", "互联网和相关服务"),
    "小金属": ("小金属", "有色金属"),
    "PCB": ("PCB", "印制电路板", "覆铜板"),
    "CPO": ("CPO", "共封装光学", "光模块", "光通信"),
    "AI算力": ("AI算力", "算力", "服务器", "数据中心"),
    "存储芯片": ("存储芯片", "存储", "存储器"),
    "稀土永磁": ("稀土永磁", "稀土"),
}


def _normalise(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"(?:概念|行业|板块|指数|Ⅱ|II)$", "", text)
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def _terms(config: StockConfig) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for kind, raw in [("industry", config.industry), *(("theme", item) for item in config.themes)]:
        values = _ALIAS_MAP.get(str(raw), (str(raw),))
        for value in values:
            normalised = _normalise(value)
            if normalised and (kind, normalised) not in output:
                output.append((kind, normalised))
    return output


def _match_quality(config: StockConfig, row: dict[str, Any]) -> int:
    board_name = _normalise(row.get("board_name"))
    if not board_name:
        return 0
    board_type = str(row.get("board_type") or "")
    best = 0
    for term_kind, term in _terms(config):
        if board_name == term:
            score = 100
        elif len(term) >= 2 and term in board_name:
            score = 80 + min(len(term), 10)
        elif len(board_name) >= 2 and board_name in term:
            score = 68 + min(len(board_name), 10)
        else:
            continue
        if term_kind == "industry" and board_type == "industry":
            score += 5
        if term_kind == "theme" and board_type == "concept":
            score += 3
        best = max(best, score)
    return best


def _sector_rows(sectors: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not sectors:
        return []
    rows: list[dict[str, Any]] = []
    for key in ("industry_ranking", "concept_ranking"):
        rows.extend(dict(row) for row in sectors.get(key, []) if isinstance(row, dict))
    return rows


def _component(value: Any, maximum: float, weight: float, neutral: float) -> float:
    numeric = finite(value)
    if numeric is None:
        return neutral
    return max(0.0, min(weight, numeric / maximum * weight))


def calculate_sector_industry_score(
    config: StockConfig,
    sectors: dict[str, Any] | None,
) -> tuple[float, str, dict[str, Any] | None]:
    """Return the agreed 8+4+4+2+2 industry score for a fixed-pool stock."""
    long_term = max(0.0, min(100.0, config.industry_logic)) / 100 * 8.0
    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for row in _sector_rows(sectors):
        quality = _match_quality(config, row)
        if quality <= 0:
            continue
        candidates.append((quality, finite(row.get("score"), 0.0) or 0.0, row))
    if not candidates:
        score = round(long_term + 6.0, 1)
        return score, "板块动态数据暂缺，动态12分按中性6分计入", None

    _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
    breakdown = selected.get("score_breakdown") or {}
    current = _component(breakdown.get("daily_strength"), 20, 4, 2)
    persistence = _component(breakdown.get("trend"), 20, 4, 2)
    liquidity = _component(breakdown.get("amount"), 20, 2, 1)
    breadth = _component(breakdown.get("breadth"), 15, 1, 0.5)
    leadership = _component(breakdown.get("leadership"), 15, 1, 0.5)
    dynamic = current + persistence + liquidity + breadth + leadership
    total = round(min(20.0, long_term + dynamic), 1)
    note = (
        f"板块动态匹配{selected.get('board_name')}：长期逻辑{long_term:.1f}/8，"
        f"当日{current:.1f}/4，5/20日趋势{persistence:.1f}/4，"
        f"量能{liquidity:.1f}/2，广度与龙头{breadth + leadership:.1f}/2"
    )
    matched = {
        "board_type": selected.get("board_type"),
        "board_code": selected.get("board_code"),
        "board_name": selected.get("board_name"),
        "board_score": selected.get("score"),
        "board_rank": selected.get("rank"),
        "dynamic_score": round(dynamic, 1),
    }
    return total, note, matched


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


def apply_sector_scores_to_fixed_rows(
    rows: Iterable[dict[str, Any]],
    stocks: Iterable[StockConfig],
    sectors: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    configs = {stock.code: stock for stock in stocks}
    output: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        config = configs.get(str(row.get("code") or ""))
        if config is None or not row.get("data_valid"):
            output.append(row)
            continue
        new_industry, note, matched = calculate_sector_industry_score(config, sectors)
        breakdown = dict(row.get("score_breakdown") or {})
        old_industry = finite(breakdown.get("industry"), 0.0) or 0.0
        breakdown["industry"] = new_industry
        row["score_breakdown"] = breakdown
        new_score = round((finite(row.get("score"), 0.0) or 0.0) - old_industry + new_industry, 1)
        if row.get("data_confidence") == "medium":
            new_score = min(new_score, 89.0)
        row["score"] = new_score
        row["rating"] = _rating(new_score)
        events = [
            str(item)
            for item in row.get("events", [])
            if "板块实时强弱暂缺" not in str(item) and "板块中位涨跌幅" not in str(item)
        ]
        events.append(note)
        row["events"] = events
        row["sector_link"] = matched or {"status": "unverified", "dynamic_score": 6.0}
        output.append(row)
    return output
