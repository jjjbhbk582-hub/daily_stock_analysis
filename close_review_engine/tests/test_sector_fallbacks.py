from __future__ import annotations

import json
from datetime import date

from ashare_review.sector_data import fetch_board_constituents, fetch_board_overview


class FakeResponse:
    def __init__(self, *, text: str = "", payload=None):
        self.text = text
        self._payload = payload
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSinaSession:
    def __init__(self) -> None:
        self.nodes: list[str] = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        params = params or {}
        if "newFLJK.php" in url:
            payload = {
                "a": "hangye_a,通信设备,80,20.0,0.6,3.2,1000000,90000000000,600001,9.8,50.0,4.5,容量龙头",
                "b": "hangye_b,半导体,180,30.0,0.4,1.5,2000000,150000000000,600002,6.2,60.0,3.5,弹性股",
            }
            return FakeResponse(
                text="var S_Finance_bankuai_sinaindustry = "
                + json.dumps(payload, ensure_ascii=False)
            )
        if "getHQNodeStockCount" in url:
            self.nodes.append(str(params.get("node") or ""))
            return FakeResponse(text="2", payload=2)
        if "getHQNodeData" in url:
            self.nodes.append(str(params.get("node") or ""))
            return FakeResponse(
                payload=[
                    {
                        "symbol": "sh600001",
                        "code": "600001",
                        "name": "容量龙头",
                        "trade": "88.00",
                        "changepercent": "3.20",
                        "open": "85.00",
                        "high": "89.00",
                        "low": "84.00",
                        "volume": "10000000",
                        "amount": "8000000000",
                        "turnoverratio": "5.0",
                        "mktcap": "100000000000",
                        "nmc": "80000000000",
                    },
                    {
                        "symbol": "sz000001",
                        "code": "000001",
                        "name": "深市候选",
                        "trade": "99.00",
                        "changepercent": "2.10",
                        "open": "97.00",
                        "high": "99.50",
                        "low": "96.50",
                        "volume": "5000000",
                        "amount": "1200000000",
                        "turnoverratio": "4.0",
                        "mktcap": "50000000000",
                        "nmc": "40000000000",
                    },
                ]
            )
        raise AssertionError(url)


class EastmoneyDownClient:
    timeout = 1

    def __init__(self):
        self.session = FakeSinaSession()

    def get_json(self, url, *, params=None):
        raise ConnectionError("Eastmoney unavailable")


def test_board_overview_falls_back_to_sina() -> None:
    rows = fetch_board_overview(
        EastmoneyDownClient(),
        "industry",
        date(2026, 8, 20),
    )
    assert len(rows) == 2
    assert rows[0]["board_code"] == "hangye_a"
    assert rows[0]["board_name"] == "通信设备"
    assert rows[0]["pct_change"] == 3.2
    assert rows[0]["amount"] == 90_000_000_000
    assert rows[0]["leader_name"] == "容量龙头"
    assert rows[0]["leader_pct_change"] == 9.8
    assert rows[0]["source"] == "新浪板块行情"
    assert rows[0]["data_date"] == "2026-08-20"


def test_board_constituents_fall_back_to_sina_label() -> None:
    client = EastmoneyDownClient()
    rows = fetch_board_constituents(client, "hangye_a")
    assert [row["code"] for row in rows] == ["600001", "000001"]
    assert rows[0]["close"] == 88.0
    assert rows[0]["amount"] == 8_000_000_000
    assert rows[0]["turnover_rate"] == 5.0
    assert rows[0]["source"] == "新浪板块成份"
    assert client.session.nodes == ["hangye_a", "hangye_a"]


def test_eastmoney_bk_constituents_map_to_sina_label_by_name() -> None:
    client = EastmoneyDownClient()
    rows = fetch_board_constituents(
        client,
        "BK9999",
        board_type="industry",
        board_name="通信设备",
        target_date=date(2026, 8, 20),
    )
    assert [row["code"] for row in rows] == ["600001", "000001"]
    assert client.session.nodes == ["hangye_a", "hangye_a"]
