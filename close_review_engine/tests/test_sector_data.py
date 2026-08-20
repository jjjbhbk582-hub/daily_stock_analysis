from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ashare_review.sector_config import load_sector_monitor
from ashare_review.sector_data import (
    fetch_board_constituents,
    fetch_board_history,
    fetch_board_overview,
    match_focus_concepts,
    normalize_board_constituents,
    normalize_board_overview,
)


class FakeBoardClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url, *, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if "push2his" in url:
            return {
                "data": {
                    "klines": [
                        "2026-08-19,100,101,102,99,1000,100000,3,1,1,2",
                        "2026-08-20,101,103,104,100,1200,130000,4,1.98,2,2.5",
                    ]
                }
            }
        if str(params.get("fs", "")).startswith("b:"):
            return {
                "data": {
                    "total": 2,
                    "diff": [
                        {"f12": "002156", "f14": "通富微电", "f2": 70, "f5": 1, "f6": 500_000_000},
                        {"f12": "600105", "f14": "永鼎股份", "f2": 42, "f5": 1, "f6": 600_000_000},
                    ],
                }
            }
        page = int(params.get("pn", 1))
        timestamp = datetime(2026, 8, 20, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        if page == 1:
            rows = [
                {"f12": f"BK{i:04d}", "f14": f"概念{i}", "f3": 1.0, "f124": timestamp}
                for i in range(100)
            ]
        elif page == 2:
            rows = [
                {"f12": f"BK{i:04d}", "f14": f"概念{i}", "f3": 0.5, "f124": timestamp}
                for i in range(100, 120)
            ]
        else:
            rows = []
        return {"data": {"total": 120, "diff": rows}}


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


def test_board_overview_uses_100_row_pagination_until_total() -> None:
    client = FakeBoardClient()
    rows = fetch_board_overview(client, "concept", date(2026, 8, 20))
    assert len(rows) == 120
    board_calls = [params for url, params in client.calls if "clist/get" in url]
    assert board_calls[0]["pz"] == 100
    assert {int(item["pn"]) for item in board_calls} == {1, 2}


def test_board_history_prefers_91_host_and_parses_completed_rows() -> None:
    client = FakeBoardClient()
    frame = fetch_board_history(client, "BK0001", date(2026, 8, 20))
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].date() == date(2026, 8, 20)
    assert frame.iloc[-1]["close"] == 103
    assert client.calls[0][0].startswith("https://91.push2his.eastmoney.com/")


def test_board_constituents_use_service_safe_100_row_pages() -> None:
    client = FakeBoardClient()
    rows = fetch_board_constituents(client, "BK0001")
    assert len(rows) == 2
    assert client.calls[0][1]["pz"] == 100
    assert client.calls[0][1]["fid"] == "f12"


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
