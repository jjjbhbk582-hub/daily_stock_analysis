from __future__ import annotations

from ashare_review.sector_config import is_eligible_main_board, load_sector_monitor


def _row(**overrides):
    row = {
        "code": "600000",
        "name": "浦发银行",
        "close": 12.0,
        "amount": 500_000_000,
        "volume": 1_000_000,
        "high": 12.3,
        "low": 11.8,
        "pct_change": 1.2,
    }
    row.update(overrides)
    return row


def test_config_contains_required_focus_concepts() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    labels = {item.label for item in config.focus_concepts}
    assert {
        "AI算力",
        "CPO",
        "PCB",
        "半导体",
        "存储芯片",
        "稀土",
        "人形机器人",
        "创新药",
        "液冷服务器",
        "消费电子",
        "军工",
        "有色金属",
    }.issubset(labels)
    assert config.max_price == 100.0
    assert config.min_amount == 300_000_000
    assert config.industry_history_candidates >= 80
    assert config.concept_history_candidates >= 30
    assert config.industry_history_candidates > config.concept_history_candidates


def test_candidate_filter_enforces_main_board_price_and_risk_rules() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    assert is_eligible_main_board(_row(), config)
    assert is_eligible_main_board(_row(code="002156", name="通富微电"), config)
    assert not is_eligible_main_board(_row(code="300308", name="中际旭创"), config)
    assert not is_eligible_main_board(_row(code="688012", name="中微公司"), config)
    assert not is_eligible_main_board(_row(close=100.01), config)
    assert not is_eligible_main_board(_row(name="ST示例"), config)
    assert not is_eligible_main_board(_row(name="退市示例"), config)
    assert not is_eligible_main_board(_row(amount=299_999_999), config)


def test_candidate_filter_rejects_one_price_limit_and_suspension() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    assert not is_eligible_main_board(
        _row(high=10.0, low=10.0, close=10.0, pct_change=10.0), config
    )
    assert not is_eligible_main_board(_row(volume=0), config)
