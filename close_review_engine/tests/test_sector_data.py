from __future__ import annotations

import json

from ashare_review.sector_data import (
    fetch_sina_sector_boards,
    fetch_sina_sector_constituents,
)


class FakeResponse:
    def __init__(self, *, text: str = "", payload=None):
        self.text = text
        self._payload = payload
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def get(self, url, *, params=None, headers=None, timeout=None):
        params = params or {}
        if "newFLJK.php" in url:
            payload = {
                "a": "hangye_a,通信设备,80,20.0,0.6,3.2,1000000,90000000000,600001,9.8,50.0,4.5,容量龙头",
                "b": "hangye_b,半导体,180,30.0,0.4,1.5,2000000,150000000000,600002,6.2,60.0,3.5,弹性股",
            }
            return FakeResponse(text=f"var S_Finance_bankuai_sinaindustry = {json.dumps(payload, ensure_ascii=False)}")
        if "getHQNodeStockCount" in url:
            return FakeResponse(text="2", payload=2)
        if "getHQNodeData" in url:
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


class FakeClient:
    timeout = 1

    def __init__(self):
        self.session = FakeSession()


def test_sector_board_parser_keeps_label_name_liquidity_and_leader() -> None:
    rows = fetch_sina_sector_boards(FakeClient(), kind="industry")
    assert len(rows) == 2
    assert rows[0]["label"] == "hangye_a"
    assert rows[0]["sector_name"] == "通信设备"
    assert rows[0]["pct_change"] == 3.2
    assert rows[0]["amount"] == 90_000_000_000
    assert rows[0]["leader_code"] == "600001"
    assert rows[0]["leader_pct_change"] == 9.8


def test_sector_constituent_parser_normalizes_main_fields() -> None:
    frame = fetch_sina_sector_constituents(FakeClient(), "hangye_a")
    assert frame["code"].tolist() == ["600001", "000001"]
    assert frame.iloc[0]["close"] == 88.0
    assert frame.iloc[0]["pct_change"] == 3.2
    assert frame.iloc[0]["amount"] == 8_000_000_000
    assert frame.iloc[0]["turnover_rate"] == 5.0
    assert frame.iloc[0]["market_cap"] == 100_000_000_000
