from __future__ import annotations

from ashare_review.config import StockConfig
from ashare_review.sector_link import calculate_sector_industry_score


def _config() -> StockConfig:
    return StockConfig(
        code="002463",
        name="沪电股份",
        exchange="SZ",
        industry="电子元件",
        themes=("PCB", "AI算力"),
        industry_logic=80,
    )


def test_fixed_stock_industry_score_uses_sector_six_part_breakdown() -> None:
    sectors = {
        "industry_ranking": [
            {
                "board_type": "industry",
                "board_name": "电子元件",
                "score": 90,
                "score_breakdown": {
                    "daily_strength": 20,
                    "trend": 20,
                    "amount": 20,
                    "breadth": 15,
                    "leadership": 15,
                },
            }
        ]
    }
    score, note, matched = calculate_sector_industry_score(_config(), sectors)
    assert score == 18.4
    assert "电子元件" in note
    assert "板块动态" in note
    assert matched["board_name"] == "电子元件"


def test_one_day_sector_spike_cannot_max_out_twenty_points() -> None:
    sectors = {
        "concept_ranking": [
            {
                "board_type": "concept",
                "board_name": "PCB概念",
                "score": 55,
                "score_breakdown": {
                    "daily_strength": 20,
                    "trend": 0,
                    "amount": 0,
                    "breadth": 0,
                    "leadership": 0,
                },
            }
        ]
    }
    score, _, _ = calculate_sector_industry_score(_config(), sectors)
    assert score == 10.4
    assert score < 15


def test_missing_sector_data_uses_neutral_dynamic_six_points() -> None:
    score, note, matched = calculate_sector_industry_score(_config(), {})
    assert score == 12.4
    assert "板块动态数据暂缺" in note
    assert matched is None
