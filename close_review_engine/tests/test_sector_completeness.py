from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ashare_review.sector_analysis import score_board
from ashare_review.sector_candidates import assign_roles
from ashare_review.sector_completeness import (
    aggregate_proxy_history,
    build_focus_proxy_rows,
    enrich_board_from_constituents,
)
from ashare_review.sector_config import load_sector_monitor


def _history(start: float, end: float, *, last_amount_ratio: float = 1.2) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-08-20", periods=30)
    close = np.linspace(start, end, len(dates))
    amount = np.full(len(dates), 1_000_000_000.0)
    amount[-1] *= last_amount_ratio
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": amount / close,
            "amount": amount,
            "pct_change": pd.Series(close).pct_change().to_numpy() * 100,
        }
    )


def test_constituent_enrichment_populates_real_breadth_and_limit_counts() -> None:
    board = {
        "board_code": "hangye_demo",
        "board_name": "示例行业",
        "board_type": "industry",
        "up_count": 0,
        "down_count": 0,
        "limit_up_count": 0,
        "amount": 10_000_000_000,
    }
    rows = [
        {"code": "600001", "name": "主板A", "pct_change": 10.01, "amount": 2e9},
        {"code": "300001", "name": "创业板A", "pct_change": 20.01, "amount": 1e9},
        {"code": "600002", "name": "ST示例", "pct_change": 5.01, "amount": 0.8e9},
        {"code": "600003", "name": "下跌股", "pct_change": -1.2, "amount": 1.1e9},
        {"code": "600004", "name": "平盘股", "pct_change": 0.0, "amount": 0.9e9},
    ]

    enriched = enrich_board_from_constituents(board, rows)

    assert enriched["up_count"] == 3
    assert enriched["down_count"] == 1
    assert enriched["flat_count"] == 1
    assert enriched["limit_up_count"] == 3
    assert enriched["constituent_count"] == 5
    assert enriched["breadth_source"] == "板块成份股收盘快照"
    assert enriched["leader_name"] == "创业板A"


def test_proxy_history_supplies_5d_20d_and_relative_amount() -> None:
    proxy = aggregate_proxy_history(
        {
            "600001": _history(10, 12, last_amount_ratio=1.4),
            "600002": _history(20, 23, last_amount_ratio=1.2),
            "000001": _history(30, 33, last_amount_ratio=1.1),
        },
        target_date=date(2026, 8, 20),
    )
    assert len(proxy) >= 21
    assert proxy.attrs["component_count"] == 3
    assert proxy.attrs["source"] == "腾讯成份股等权代理历史"

    scored = score_board(
        {
            "board_code": "proxy-demo",
            "board_name": "代理板块",
            "board_type": "concept",
            "pct_change": 1.5,
            "amount": 6e9,
            "up_count": 3,
            "down_count": 0,
            "limit_up_count": 0,
            "leader_pct_change": 3.0,
        },
        proxy,
        market_median=0.2,
    )
    assert scored["return_5d"] is not None
    assert scored["return_20d"] is not None
    assert scored["amount_ratio_20"] is not None


def test_missing_modern_focus_concept_uses_explicit_proxy_basket() -> None:
    current = [
        {
            "focus_label": "AI算力",
            "status": "data_unavailable",
            "board_type": "concept",
            "board_code": None,
            "board_name": None,
        }
    ]
    histories = {
        "000977": _history(70, 82),
        "603019": _history(80, 90),
        "000938": _history(30, 39),
    }
    rows = build_focus_proxy_rows(
        current,
        histories,
        target_date=date(2026, 8, 20),
        market_median=0.2,
        baskets={"AI算力": ("000977", "603019", "000938")},
    )
    row = rows[0]
    assert row["status"] == "proxy_ready"
    assert row["board_name"] == "AI算力主板100元以下代理篮子"
    assert row["return_5d"] is not None
    assert row["return_20d"] is not None
    assert row["proxy_count"] == 3
    assert row["confidence"] == "medium"
    assert "非官方概念指数" in row["risk_flags"]


def test_two_plus_two_uses_four_distinct_roles_when_setups_exist() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    rows = []
    for index, code in enumerate(("600001", "600002", "000001", "002001"), start=1):
        close = 10.0 + index
        rows.append(
            {
                "data_valid": True,
                "data_confidence": "high",
                "code": code,
                "name": f"候选{index}",
                "close": close,
                "pct_change": 0.5 + index * 0.2,
                "daily_trend": "震荡",
                "weekly_trend": "偏多震荡",
                "trend_60m": "震荡",
                "patterns": [],
                "metrics": {"rel_volume_20": 1.10},
                "levels": {
                    "status": "ready",
                    "pullback_low": close * 0.96,
                    "pullback_high": close * 0.99,
                    "breakout_trigger": close * 1.06,
                    "invalidation": close * 0.91,
                    "target_1": close * 1.12,
                    "target_2": close * 1.20,
                },
                "candidate_snapshot": {
                    "amount": (10 - index) * 1e9,
                    "float_market_cap": (10 - index) * 10e9,
                    "turnover_rate": 2.0 + index,
                },
            }
        )

    picks = assign_roles({"board_name": "测试板块"}, rows, config)
    codes = [picks[role]["code"] for role in (
        "capacity_leader",
        "momentum_leader",
        "pullback_potential",
        "breakout_potential",
    )]
    assert all(codes)
    assert len(set(codes)) == 4
