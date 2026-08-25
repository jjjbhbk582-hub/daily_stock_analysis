from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

import numpy as np
import pandas as pd

from ashare_review.analysis import analyze_stock
from ashare_review.calendar import next_trading_day
from ashare_review.comparison import _alerts, _compare, _market_summary
from ashare_review.completed_daily_source import CompletedDailyLiveDataSource
from ashare_review.config import StockConfig
from ashare_review.data import StockBundle
from ashare_review.fixture import FixtureDataSource as FixtureDataSource
from ashare_review.sector_link import apply_sector_scores_to_fixed_rows
from ashare_review.sector_runtime import build_sector_review
from ashare_review.trade_plans import build_trade_decision
from ashare_review.trade_tracking import calculate_trade_statistics, evaluate_plan


class ReviewDataSource(Protocol):
    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]: ...

    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle: ...


@dataclass(slots=True)
class RunResult:
    status: str
    message: str
    snapshot: dict[str, Any] | None
    active_plans: list[dict[str, Any]] = field(default_factory=list)
    new_outcomes: list[dict[str, Any]] = field(default_factory=list)


def run_review(
    stocks: list[StockConfig],
    source: ReviewDataSource,
    *,
    target_date: date,
    generated_at: datetime,
    previous_snapshot: dict[str, Any] | None = None,
    active_plans: list[dict[str, Any]] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
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
                    source_status=[
                        {
                            "source": "pipeline",
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                )

    rows = [analyze_stock(bundles[stock.code], market, target_date) for stock in stocks]
    valid_count = sum(bool(row.get("data_valid")) for row in rows)
    if valid_count == 0:
        return RunResult(
            status="failure",
            message=(
                f"{target_date.isoformat()}：多个独立行情源均未能确认当日完整日线，"
                "未生成伪排名。"
            ),
            snapshot=None,
        )

    preliminary_market = _market_summary(market, rows)
    sectors = build_sector_review(
        source,
        preliminary_market,
        target_date=target_date,
        previous_snapshot=previous_snapshot,
        max_workers=max_workers,
    )

    rows = apply_sector_scores_to_fixed_rows(rows, stocks, sectors)
    rows.sort(
        key=lambda row: (bool(row.get("data_valid")), float(row.get("score", 0))),
        reverse=True,
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    market = _market_summary(market, rows)
    try:
        trade_decision = build_trade_decision(
            rows,
            market,
            target_date,
            next_trading_day(target_date),
        )
        market["trade_regime"] = trade_decision["market_regime"]
    except Exception as exc:  # noqa: BLE001 - decision layer must not break the base review
        trade_decision = {
            "status": "unavailable",
            "target_date": target_date.isoformat(),
            "valid_for": next_trading_day(target_date).isoformat(),
            "executable": [],
            "ready_next_session": [],
            "waiting_trigger": [],
            "watch_only": [],
            "rejected": [],
            "all_plans": [],
            "errors": [{"error": f"{type(exc).__name__}: {exc}"}],
        }
    rows_by_code = {str(row.get("code") or ""): row for row in rows}
    surviving_plans: list[dict[str, Any]] = []
    previous_trade_review: list[dict[str, Any]] = []
    new_outcomes: list[dict[str, Any]] = []
    for active_plan in active_plans or []:
        row = rows_by_code.get(str(active_plan.get("code") or ""))
        if not row or not row.get("data_valid"):
            surviving_plans.append(active_plan)
            previous_trade_review.append(
                {
                    "plan_id": active_plan.get("plan_id"),
                    "code": active_plan.get("code"),
                    "name": active_plan.get("name"),
                    "lifecycle_status": active_plan.get("lifecycle_status", "pending"),
                    "review_status": "行情不可用，计划未推进",
                }
            )
            continue
        metrics = row.get("metrics") or {}
        daily_bar = {
            "date": target_date.isoformat(),
            "open": metrics.get("open"),
            "high": metrics.get("high"),
            "low": metrics.get("low"),
            "close": metrics.get("close"),
            "volume_ratio": metrics.get("rel_volume_20"),
            "tradable": True,
            "limit_locked": False,
        }
        updated, outcome = evaluate_plan(active_plan, daily_bar)
        previous_trade_review.append(
            {
                "plan_id": updated.get("plan_id"),
                "code": updated.get("code"),
                "name": updated.get("name"),
                "setup": updated.get("setup"),
                "lifecycle_status": updated.get("lifecycle_status"),
                "entry_price": updated.get("entry_price"),
                "mfe_pct": updated.get("mfe_pct"),
                "mae_pct": updated.get("mae_pct"),
                "holding_sessions": updated.get("holding_sessions"),
                "outcome": outcome,
            }
        )
        if outcome is None:
            surviving_plans.append(updated)
        else:
            new_outcomes.append(outcome)
    generated_plans = [
        *trade_decision.get("ready_next_session", []),
        *trade_decision.get("waiting_trigger", []),
    ]
    active_by_id = {
        str(plan.get("plan_id") or ""): plan
        for plan in [*surviving_plans, *generated_plans]
        if plan.get("plan_id")
    }
    updated_active_plans = list(active_by_id.values())
    trade_statistics = calculate_trade_statistics([*(outcomes or []), *new_outcomes])
    comparison = _compare(previous_snapshot, rows)
    alerts = _alerts(rows, comparison)
    status = "success" if valid_count == len(stocks) else "partial"
    snapshot = {
        "schema_version": 2,
        "status": status,
        "target_date": target_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "valid_count": valid_count,
        "universe_count": len(stocks),
        "market": market,
        "sectors": sectors,
        "stocks": rows,
        "top5": [row["code"] for row in rows[:5]],
        "comparison": comparison,
        "alerts": alerts,
        "trade_decision": trade_decision,
        "previous_trade_review": previous_trade_review,
        "trade_statistics": trade_statistics,
        "source_policy": {
            "daily": ["东方财富日线", "腾讯日线", "网易日线", "完成日线合成"],
            "close_cross_check": "腾讯15:00收盘快照",
            "intraday": ["东方财富60分钟", "腾讯60分钟", "新浪60分钟"],
            "market": ["东方财富全市场行情", "腾讯指数行情", "新浪全市场行情"],
            "sectors": [
                "东方财富行业/概念板块",
                "新浪行业/概念板块",
                "东方财富/新浪板块成份",
                "东方财富板块历史K线（可用时）",
            ],
            "enrichment": ["东方财富财务", "东方财富公告", "东方财富资金流"],
        },
    }
    message = (
        f"{target_date.isoformat()}：{valid_count}/{len(stocks)}只股票通过当日完整日线校验；"
        f"板块排名{len(sectors.get('industry_ranking', []))}+"
        f"{len(sectors.get('concept_ranking', []))}。"
    )
    return RunResult(
        status=status,
        message=message,
        snapshot=_clean(snapshot),
        active_plans=_clean(updated_active_plans),
        new_outcomes=_clean(new_outcomes),
    )


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


def build_live_source() -> CompletedDailyLiveDataSource:
    return CompletedDailyLiveDataSource()


def dump_json(value: Any) -> str:
    return json.dumps(_clean(value), ensure_ascii=False, indent=2)
