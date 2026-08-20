from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ashare_review.sector_config import load_sector_monitor
from ashare_review.sector_data import (
    match_focus_concepts,
    normalize_board_constituents,
    normalize_board_overview,
)


def test_board_overview_normalizes_eastmoney_fields() -> None:
    rows = normalize_board_overview(
        [
            {
                "f12": "BK0001",
                "f14": "通信设备",
                "f2": 1234.5,
                "f3": 2.1,
                "f6": 90_000_000_000,
                "f8": 3.2,
                "f20": 2_000_000_000_000,
                "f104": 70,
                "f105": 20,
                "f128": "龙头A",
                "f136": 9.9,
            }
        ],
        board_type="industry",
        target_date=date(2026, 8, 20),
    )
    assert rows[0]["board_code"] == "BK0001"
    assert rows[0]["board_type"] == "industry"
    assert rows[0]["board_name"] == "通信设备"
    assert rows[0]["up_count"] == 70
    assert rows[0]["down_count"] == 20
    assert rows[0]["data_date"] == "2026-08-20"


def test_board_overview_uses_exchange_timestamp_instead_of_requested_date() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    source_time = datetime(2026, 8, 19, 15, 0, tzinfo=shanghai)
    rows = normalize_board_overview(
        [{"f12": "BK0001", "f14": "通信设备", "f3": 1.0, "f124": source_time.timestamp()}],
        board_type="industry",
        target_date=date(2026, 8, 20),
    )
    assert rows[0]["data_date"] == "2026-08-19"


def test_constituents_are_normalized_for_candidate_filtering() -> None:
    rows = normalize_board_constituents(
        [
            {
                "f12": "002156",
                "f14": "通富微电",
                "f2": 70.67,
                "f3": 3.2,
                "f5": 120_000_000,
                "f6": 7_300_000_000,
                "f8": 6.8,
                "f15": 72.0,
                "f16": 68.0,
                "f17": 69.1,
                "f18": 68.5,
                "f20": 110_000_000_000,
                "f21": 100_000_000_000,
            }
        ]
    )
    row = rows[0]
    assert row["code"] == "002156"
    assert row["close"] == 70.67
    assert row["amount"] == 7_300_000_000
    assert row["float_market_cap"] == 100_000_000_000


def test_focus_concepts_match_aliases_without_duplicates() -> None:
    config = load_sector_monitor("config/sector_monitor.yml")
    boards = [
        {"board_code": "BK1", "board_name": "CPO概念", "board_type": "concept"},
        {"board_code": "BK2", "board_name": "共封装光学", "board_type": "concept"},
        {"board_code": "BK3", "board_name": "液冷服务器", "board_type": "concept"},
    ]
    matched = match_focus_concepts(boards, config.focus_concepts)
    labels = [item["focus_label"] for item in matched]
    assert labels.count("CPO") == 1
    assert "液冷服务器" in labels
