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


def test_cnooc_prefers_oil_and_gas_extraction_industry_over_petroleum_theme() -> None:
    config = StockConfig(
        code="600938",
        name="中国海油",
        exchange="SH",
        industry="石油行业",
        themes=("石油", "高股息", "能源"),
        industry_logic=77,
    )
    sectors = {
        "industry_ranking": [
            {
                "board_type": "industry",
                "board_name": "石油和天然气开采",
                "score": 75,
                "confidence": "high",
                "data_date": "2026-08-24",
                "score_breakdown": {},
            },
            {
                "board_type": "industry",
                "board_name": "石油加工",
                "score": 99,
                "confidence": "high",
                "data_date": "2026-08-24",
                "score_breakdown": {},
            },
        ],
        "concept_ranking": [
            {
                "board_type": "concept",
                "board_name": "石油概念",
                "score": 100,
                "confidence": "high",
                "data_date": "2026-08-24",
                "score_breakdown": {},
            }
        ],
    }

    _, _, matched = calculate_sector_industry_score(config, sectors, target_date="2026-08-24")

    assert matched["board_name"] == "石油和天然气开采"
    assert matched["match_kind"] == "industry_exact_or_alias"
    assert matched["eligible_for_trade_gate"] is True


def test_partial_concept_cannot_satisfy_trade_gate() -> None:
    sectors = {
        "concept_ranking": [
            {
                "board_type": "concept",
                "board_name": "PCB概念",
                "score": 95,
                "confidence": "partial",
                "data_date": "2026-08-24",
                "score_breakdown": {},
            }
        ]
    }

    _, _, matched = calculate_sector_industry_score(_config(), sectors, target_date="2026-08-24")

    assert matched["match_kind"] == "concept_exact_or_alias"
    assert matched["eligible_for_trade_gate"] is False
