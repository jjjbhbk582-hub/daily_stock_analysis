from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd

from ashare_review.analysis import analyze_stock
from ashare_review.sector_analysis import (
    compare_sector_rankings,
    rank_boards,
    score_board,
    select_detailed_boards,
)
from ashare_review.sector_candidates import (
    assign_roles,
    make_dynamic_stock_config,
    shortlist_constituents,
)
from ashare_review.sector_config import SectorMonitorConfig, load_sector_monitor
from ashare_review.sector_data import (
    fetch_board_constituents,
    fetch_board_history,
    fetch_board_overview,
    match_focus_concepts,
)


class BoardProvider(Protocol):
    def overview(self, board_type: str, target_date: date) -> list[dict[str, Any]]: ...

    def history(self, board_type: str, board_code: str, target_date: date) -> pd.DataFrame: ...

    def constituents(
        self, board_type: str, board_code: str, target_date: date
    ) -> list[dict[str, Any]]: ...


class LiveBoardProvider:
    def __init__(self, client: Any) -> None:
        self.client = client

    def overview(self, board_type: str, target_date: date) -> list[dict[str, Any]]:
        return fetch_board_overview(self.client, board_type, target_date)

    def history(self, board_type: str, board_code: str, target_date: date) -> pd.DataFrame:
        del board_type
        return fetch_board_history(self.client, board_code, target_date)

    def constituents(
        self, board_type: str, board_code: str, target_date: date
    ) -> list[dict[str, Any]]:
        del board_type, target_date
        return fetch_board_constituents(self.client, board_code)


_FIXTURE_INDUSTRIES = (
    ("BI01", "通信设备", 3.2),
    ("BI02", "电子元件", 2.7),
    ("BI03", "半导体", 2.2),
    ("BI04", "有色金属", 1.8),
    ("BI05", "医药制造", 1.5),
    ("BI06", "机器人", 1.2),
    ("BI07", "游戏", 0.4),
    ("BI08", "小金属", -0.5),
)
_FIXTURE_CONCEPTS = (
    ("BC01", "CPO概念", 3.8),
    ("BC02", "AI算力", 3.4),
    ("BC03", "PCB概念", 3.0),
    ("BC04", "液冷服务器", 2.8),
    ("BC05", "人形机器人", 2.4),
    ("BC06", "创新药", 2.0),
    ("BC07", "半导体设备", 1.7),
    ("BC08", "存储芯片", 1.4),
    ("BC09", "消费电子", 0.9),
    ("BC10", "军工", 0.4),
    ("BC11", "有色金属概念", 0.2),
    ("BC12", "稀土永磁", -0.6),
)
_FIXTURE_STOCKS = (
    ("000063", "中兴通讯", 36.0),
    ("000977", "浪潮信息", 81.0),
    ("002156", "通富微电", 71.0),
    ("002384", "东山精密", 42.0),
    ("002896", "中大力德", 84.0),
    ("000831", "中国稀土", 61.0),
    ("603019", "中科曙光", 90.0),
    ("600105", "永鼎股份", 42.0),
    ("603009", "北特科技", 49.0),
    ("601899", "紫金矿业", 35.0),
    ("600845", "宝信软件", 32.0),
    ("002230", "科大讯飞", 58.0),
    ("600588", "用友网络", 22.0),
    ("002050", "三花智控", 39.0),
    ("002074", "国轩高科", 34.0),
    ("600276", "恒瑞医药", 66.0),
    ("603259", "药明康德", 82.0),
    ("600570", "恒生电子", 41.0),
    ("000938", "紫光股份", 38.0),
    ("600460", "士兰微", 30.0),
    ("002185", "华天科技", 18.0),
    ("600745", "闻泰科技", 47.0),
    ("002130", "沃尔核材", 28.0),
    ("600435", "北方导航", 17.0),
)


class FixtureBoardProvider:
    def _definitions(self, board_type: str) -> tuple[tuple[str, str, float], ...]:
        return _FIXTURE_INDUSTRIES if board_type == "industry" else _FIXTURE_CONCEPTS

    def overview(self, board_type: str, target_date: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index, (code, name, pct) in enumerate(self._definitions(board_type)):
            total = 80 + index * 3
            up = int(total * max(0.25, min(0.88, 0.55 + pct / 12)))
            rows.append(
                {
                    "board_code": code,
                    "board_name": name,
                    "board_type": board_type,
                    "latest": 1000 + index * 25,
                    "pct_change": pct,
                    "amount": 35_000_000_000 + (len(self._definitions(board_type)) - index) * 5_000_000_000,
                    "turnover_rate": 2.2 + max(pct, 0) * 0.25,
                    "market_cap": 800_000_000_000 + index * 30_000_000_000,
                    "up_count": up,
                    "down_count": total - up,
                    "limit_up_count": max(0, int(round(max(pct, 0) / 1.1))),
                    "leader_name": _FIXTURE_STOCKS[index % len(_FIXTURE_STOCKS)][1],
                    "leader_pct_change": min(9.8, max(0.5, pct * 2.1)),
                    "data_date": target_date.isoformat(),
                    "source": "fixture板块行情",
                }
            )
        return rows

    def history(self, board_type: str, board_code: str, target_date: date) -> pd.DataFrame:
        definitions = self._definitions(board_type)
        index = next(
            (i for i, item in enumerate(definitions) if item[0] == board_code),
            0,
        )
        pct = definitions[index][2]
        dates = pd.bdate_range(end=target_date, periods=35)
        trend = 0.015 + pct / 80 - index * 0.001
        close = 100 * np.exp(np.linspace(0, trend, len(dates)))
        amount = np.full(len(dates), 8_000_000_000.0 + index * 300_000_000)
        amount[-1] *= max(0.75, min(2.0, 1 + pct / 10))
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": close * 0.995,
                "high": close * 1.012,
                "low": close * 0.988,
                "close": close,
                "volume": amount / close,
                "amount": amount,
            }
        )
        frame["pct_change"] = frame["close"].pct_change() * 100
        return frame

    def constituents(
        self, board_type: str, board_code: str, target_date: date
    ) -> list[dict[str, Any]]:
        del target_date
        definitions = self._definitions(board_type)
        index = next(
            (i for i, item in enumerate(definitions) if item[0] == board_code),
            0,
        )
        rows: list[dict[str, Any]] = []
        for offset in range(8):
            code, name, close = _FIXTURE_STOCKS[(index * 3 + offset) % len(_FIXTURE_STOCKS)]
            pct = 0.5 + (7 - offset) * 0.55 + max(0, definitions[index][2]) * 0.25
            amount = 500_000_000 + (8 - offset) * 650_000_000
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "close": close,
                    "pct_change": pct,
                    "volume": max(1_000_000, amount / close),
                    "amount": amount,
                    "turnover_rate": 2.0 + offset * 0.7,
                    "high": close * 1.025,
                    "low": close * 0.975,
                    "open": close * 0.99,
                    "previous_close": close / (1 + pct / 100),
                    "market_cap": 45_000_000_000 + (8 - offset) * 8_000_000_000,
                    "float_market_cap": 35_000_000_000 + (8 - offset) * 7_000_000_000,
                    "source": "fixture板块成份",
                }
            )
        return rows


def _provider_for(source: Any) -> BoardProvider | None:
    if hasattr(source, "client"):
        return LiveBoardProvider(source.client)
    if hasattr(source, "payload"):
        return FixtureBoardProvider()
    return None


def _preliminary_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("pct_change") or 0),
            float(row.get("amount") or 0),
        ),
        reverse=True,
    )


def _empty_sectors(config: SectorMonitorConfig, error: str) -> dict[str, Any]:
    return {
        "industry_ranking": [],
        "concept_ranking": [],
        "focus_concepts": [
            {
                "focus_label": item.label,
                "status": "data_unavailable",
                "board_type": "concept",
                "board_code": None,
                "board_name": None,
            }
            for item in config.focus_concepts
        ],
        "top_boards": [],
        "rising_boards": [],
        "weak_boards": [],
        "detailed_boards": [],
        "dynamic_candidates": [],
        "comparison": {"baseline": True, "material": False},
        "source_status": [{"source": "板块复盘", "ok": False, "error": error}],
    }


def build_sector_review(
    source: Any,
    market: dict[str, Any],
    *,
    target_date: date,
    previous_snapshot: dict[str, Any] | None,
    max_workers: int,
    config_path: str = "config/sector_monitor.yml",
) -> dict[str, Any]:
    config = load_sector_monitor(config_path)
    provider = _provider_for(source)
    if provider is None:
        return _empty_sectors(config, "当前数据源未提供板块接口")

    source_status: list[dict[str, Any]] = []
    overview: dict[str, list[dict[str, Any]]] = {"industry": [], "concept": []}
    for board_type in ("industry", "concept"):
        try:
            rows = provider.overview(board_type, target_date)
            overview[board_type] = rows
            source_status.append(
                {
                    "source": f"{board_type}板块列表",
                    "ok": bool(rows),
                    "rows": len(rows),
                    "date": target_date.isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            source_status.append(
                {
                    "source": f"{board_type}板块列表",
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    if not overview["industry"] and not overview["concept"]:
        result = _empty_sectors(config, "行业与概念板块列表均不可用")
        result["source_status"] = source_status
        return result

    focus_preliminary = match_focus_concepts(overview["concept"], config.focus_concepts)
    history_targets: dict[tuple[str, str], dict[str, Any]] = {}
    for board_type in ("industry", "concept"):
        for row in _preliminary_sort(overview[board_type])[: config.history_candidates_per_type]:
            history_targets[(board_type, str(row["board_code"]))] = row
    for row in focus_preliminary:
        if row.get("status") == "ready" and row.get("board_code"):
            history_targets[("concept", str(row["board_code"]))] = row

    histories: dict[tuple[str, str], pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as executor:
        futures = {
            executor.submit(provider.history, key[0], key[1], target_date): key
            for key in history_targets
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                frame = future.result()
                histories[key] = frame
                source_status.append(
                    {
                        "source": f"{key[0]}板块历史",
                        "board_code": key[1],
                        "ok": len(frame) >= 21,
                        "rows": len(frame),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                histories[key] = pd.DataFrame()
                source_status.append(
                    {
                        "source": f"{key[0]}板块历史",
                        "board_code": key[1],
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    market_median = float((market.get("breadth") or {}).get("median_pct") or 0.0)
    ranked_by_type: dict[str, list[dict[str, Any]]] = {}
    for board_type in ("industry", "concept"):
        scored = [
            score_board(
                row,
                histories.get((board_type, str(row["board_code"])), pd.DataFrame()),
                market_median=market_median,
            )
            for row in overview[board_type]
        ]
        ranked_by_type[board_type] = rank_boards(scored)

    combined = sorted(
        [*ranked_by_type["industry"], *ranked_by_type["concept"]],
        key=lambda row: (float(row.get("score") or 0), float(row.get("pct_change") or 0)),
        reverse=True,
    )
    for index, row in enumerate(combined, start=1):
        row["overall_rank"] = index
    previous_sectors = (previous_snapshot or {}).get("sectors") or None
    selection = select_detailed_boards(combined, previous_sectors, config)

    constituents_by_board: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 7))) as executor:
        futures = {
            executor.submit(
                provider.constituents,
                str(board.get("board_type")),
                str(board.get("board_code")),
                target_date,
            ): (str(board.get("board_type")), str(board.get("board_code")))
            for board in selection["detailed_boards"]
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                rows = future.result()
                constituents_by_board[key] = rows
                source_status.append(
                    {
                        "source": "板块成份",
                        "board_type": key[0],
                        "board_code": key[1],
                        "ok": bool(rows),
                        "rows": len(rows),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                constituents_by_board[key] = []
                source_status.append(
                    {
                        "source": "板块成份",
                        "board_type": key[0],
                        "board_code": key[1],
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    shortlists: dict[tuple[str, str], list[dict[str, Any]]] = {}
    dynamic_configs: dict[str, Any] = {}
    dynamic_snapshot: dict[str, dict[str, Any]] = {}
    for board in selection["detailed_boards"]:
        key = (str(board.get("board_type")), str(board.get("board_code")))
        shortlist = shortlist_constituents(constituents_by_board.get(key, []), config)
        shortlists[key] = shortlist
        for item in shortlist:
            code = str(item["code"])
            if code not in dynamic_configs and len(dynamic_configs) >= config.max_dynamic_stocks:
                continue
            dynamic_configs.setdefault(code, make_dynamic_stock_config(item, board))
            dynamic_snapshot.setdefault(code, item)

    analyzed_dynamic: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as executor:
        futures = {
            executor.submit(source.load_stock, stock_config, target_date): code
            for code, stock_config in dynamic_configs.items()
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                bundle = future.result()
                row = analyze_stock(bundle, market, target_date)
                row["candidate_snapshot"] = dynamic_snapshot[code]
                analyzed_dynamic[code] = row
            except Exception as exc:  # noqa: BLE001
                analyzed_dynamic[code] = {
                    "code": code,
                    "name": dynamic_configs[code].name,
                    "data_valid": False,
                    "close": dynamic_snapshot[code].get("close"),
                    "candidate_snapshot": dynamic_snapshot[code],
                    "error": f"{type(exc).__name__}: {exc}",
                }

    detailed_boards: list[dict[str, Any]] = []
    dynamic_candidates: list[dict[str, Any]] = []
    for board in selection["detailed_boards"]:
        key = (str(board.get("board_type")), str(board.get("board_code")))
        board_rows: list[dict[str, Any]] = []
        for item in shortlists.get(key, []):
            code = str(item["code"])
            analyzed = analyzed_dynamic.get(code)
            if not analyzed:
                continue
            copy = dict(analyzed)
            copy["candidate_snapshot"] = item
            board_rows.append(copy)
        board_copy = dict(board)
        board_copy["qualified_count"] = len(shortlists.get(key, []))
        board_copy["picks"] = assign_roles(board_copy, board_rows, config)
        detailed_boards.append(board_copy)
        for role, pick in board_copy["picks"].items():
            if not pick.get("code"):
                continue
            item = dict(pick)
            item.update(
                {
                    "board_type": board_copy.get("board_type"),
                    "board_code": board_copy.get("board_code"),
                    "board_name": board_copy.get("board_name"),
                    "board_score": board_copy.get("score"),
                    "role": role,
                }
            )
            dynamic_candidates.append(item)

    current: dict[str, Any] = {
        "industry_ranking": ranked_by_type["industry"],
        "concept_ranking": ranked_by_type["concept"],
        "focus_concepts": match_focus_concepts(
            ranked_by_type["concept"], config.focus_concepts
        ),
        "top_boards": selection["top_boards"],
        "rising_boards": selection["rising_boards"],
        "weak_boards": selection["weak_boards"],
        "detailed_boards": detailed_boards,
        "dynamic_candidates": dynamic_candidates,
        "source_status": source_status,
    }
    current["comparison"] = compare_sector_rankings(previous_sectors, current)
    return current
