from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

from ashare_review.analysis import analyze_stock
from ashare_review.comparison import _alerts, _compare, _market_summary
from ashare_review.config import StockConfig
from ashare_review.data import StockBundle
from ashare_review.fallbacks import ResilientLiveDataSource
from ashare_review.fixture import FixtureDataSource as FixtureDataSource


class ReviewDataSource(Protocol):
    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]: ...

    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle: ...


@dataclass(slots=True)
class RunResult:
    status: str
    message: str
    snapshot: dict[str, Any] | None


def run_review(
    stocks: list[StockConfig],
    source: ReviewDataSource,
    *,
    target_date: date,
    generated_at: datetime,
    previous_snapshot: dict[str, Any] | None = None,
    max_workers: int = 5,
) -> RunResult:
    market = source.load_market(stocks, target_date)
    bundles: dict[str, StockBundle] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(source.load_stock, stock, target_date): stock for stock in stocks}
        for future in as_completed(futures):
            stock = futures[future]
            try:
                bundles[stock.code] = future.result()
            except Exception as exc:  # noqa: BLE001
                bundles[stock.code] = StockBundle(
                    config=stock,
                    source_status=[{"source": "pipeline", "ok": False, "error": f"{type(exc).__name__}: {exc}"}],
                )
    rows = [analyze_stock(bundles[stock.code], market, target_date) for stock in stocks]
    rows.sort(key=lambda row: (bool(row.get("data_valid")), float(row.get("score", 0))), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    market = _market_summary(market, rows)
    comparison = _compare(previous_snapshot, rows)
    alerts = _alerts(rows, comparison)
    valid_count = sum(bool(row.get("data_valid")) for row in rows)
    if valid_count == 0:
        return RunResult(
            status="failure",
            message=f"{target_date.isoformat()}：多个独立行情源均未能确认当日完整日线，未生成伪排名。",
            snapshot=None,
        )
    status = "success" if valid_count == len(stocks) else "partial"
    snapshot = {
        "schema_version": 1,
        "status": status,
        "target_date": target_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "valid_count": valid_count,
        "universe_count": len(stocks),
        "market": market,
        "stocks": rows,
        "top5": [row["code"] for row in rows[:5]],
        "comparison": comparison,
        "alerts": alerts,
        "source_policy": {
            "daily": ["东方财富日线", "腾讯日线", "网易日线"],
            "close_cross_check": "腾讯15:00收盘快照",
            "intraday": ["东方财富60分钟", "腾讯60分钟"],
            "market": ["东方财富", "腾讯指数", "新浪全市场/行业"],
            "enrichment": ["东方财富财务", "东方财富公告", "东方财富资金流"],
        },
    }
    message = f"{target_date.isoformat()}：{valid_count}/{len(stocks)}只股票通过当日完整日线校验。"
    return RunResult(status=status, message=message, snapshot=_clean(snapshot))


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_live_source() -> ResilientLiveDataSource:
    return ResilientLiveDataSource()


def dump_json(value: Any) -> str:
    return json.dumps(_clean(value), ensure_ascii=False, indent=2)
