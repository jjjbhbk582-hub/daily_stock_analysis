from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd

from ashare_review.sector_analysis import (
    compare_sector_rankings,
    rank_boards,
    score_board,
    select_detailed_boards,
)


def _history(*, trend: float, amount_ratio: float) -> pd.DataFrame:
    dates = pd.bdate_range(end=date(2026, 8, 20), periods=30)
    close = 100 * np.exp(np.linspace(0, trend, 30))
    amount = np.full(30, 1_000_000_000.0)
    amount[-1] *= amount_ratio
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": amount / close,
            "amount": amount,
            "pct_change": pd.Series(close).pct_change().fillna(0).to_numpy() * 100,
        }
    )


def _board(code: str, name: str, **overrides):
    row = {
        "board_code": code,
        "board_name": name,
        "board_type": "industry",
        "pct_change": 2.0,
        "amount": 80_000_000_000,
        "turnover_rate": 3.0,
        "up_count": 80,
        "down_count": 20,
        "leader_name": "龙头",
        "leader_pct_change": 7.0,
        "limit_up_count": 4,
        "source": "fixture",
        "data_date": "2026-08-20",
    }
    row.update(overrides)
    return row


def test_healthy_broad_advance_scores_above_one_stock_spike() -> None:
    healthy = score_board(
        _board("BK1", "健康上涨", pct_change=2.5, up_count=82, down_count=18),
        _history(trend=0.12, amount_ratio=1.4),
        market_median=0.3,
    )
    spike = score_board(
        _board(
            "BK2",
            "单股脉冲",
            pct_change=6.0,
            up_count=18,
            down_count=62,
            leader_pct_change=10.0,
            limit_up_count=1,
        ),
        _history(trend=-0.04, amount_ratio=2.8),
        market_median=0.3,
    )
    assert 0 <= healthy["score"] <= 100
    assert healthy["score"] > spike["score"]
    assert "score_breakdown" in healthy


def test_rank_and_selection_use_top5_plus_two_material_risers() -> None:
    boards = []
    for index in range(10):
        boards.append(
            score_board(
                _board(f"BK{index}", f"板块{index}", pct_change=3.0 - index * 0.2),
                _history(trend=0.1 - index * 0.005, amount_ratio=1.2),
                market_median=0.0,
            )
        )
    ranked = rank_boards(boards)
    previous = {
        "industry_ranking": [
            {"board_code": row["board_code"], "board_type": "industry", "rank": 10 - i}
            for i, row in enumerate(ranked)
        ],
        "concept_ranking": [],
    }
    selection = select_detailed_boards(
        ranked,
        previous,
        SimpleNamespace(max_detailed_boards=7),
    )
    assert len(selection["top_boards"]) == 5
    assert len(selection["detailed_boards"]) <= 7
    assert len({row["board_code"] for row in selection["detailed_boards"]}) == len(
        selection["detailed_boards"]
    )


def test_sector_comparison_detects_rank_score_and_top_changes() -> None:
    previous = {
        "industry_ranking": [
            {"board_code": "BK1", "board_type": "industry", "board_name": "A", "rank": 1, "score": 80},
            {"board_code": "BK2", "board_type": "industry", "board_name": "B", "rank": 6, "score": 60},
        ],
        "concept_ranking": [],
        "top_boards": [{"board_code": "BK1", "board_type": "industry"}],
        "detailed_boards": [],
    }
    current = {
        "industry_ranking": [
            {"board_code": "BK2", "board_type": "industry", "board_name": "B", "rank": 1, "score": 72},
            {"board_code": "BK1", "board_type": "industry", "board_name": "A", "rank": 5, "score": 73},
        ],
        "concept_ranking": [],
        "top_boards": [{"board_code": "BK2", "board_type": "industry"}],
        "detailed_boards": [],
    }
    result = compare_sector_rankings(previous, current)
    assert result["new_top_boards"]
    assert result["rank_moves"]
    assert result["score_moves"]
    assert result["material"]
