from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import ashare_review.enhanced_data as enhanced_data
from ashare_review.config import StockConfig
from ashare_review.data import LiveDataSource, Quote, StockBundle
from ashare_review.enhanced_data import (
    ResilientLiveDataSource,
    fetch_sina_industries,
    fetch_sina_intraday_60m,
    fetch_sina_market_snapshot,
    fetch_tencent_intraday_60m,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeResponse:
    def __init__(self, payload=None, *, text: str | None = None):
        self.payload = payload
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return FakeResponse(self.payload)


class FakeClient:
    timeout = 1

    def __init__(self, payload):
        self.session = FakeSession(payload)


def _config() -> StockConfig:
    return StockConfig("601138", "工业富联", "SH", "消费电子", ("AI算力",), 90)


def _complete_intraday(rows: int = 48) -> pd.DataFrame:
    dates = pd.date_range("2026-08-07 10:30:00", periods=rows, freq="2h30min")
    dates = pd.DatetimeIndex(list(dates[:-1]) + [pd.Timestamp("2026-08-20 15:00:00")])
    return pd.DataFrame(
        {
            "date": dates,
            "open": 61.0,
            "high": 63.0,
            "low": 60.0,
            "close": 62.0,
            "volume": 1_000_000.0,
            "amount": 62_000_000.0,
        }
    )


def test_tencent_intraday_parser_keeps_timestamp_and_share_units() -> None:
    payload = {
        "data": {
            "sh601138": {
                "m60": [
                    ["2026-08-20 14:00:00", "61.00", "61.80", "62.00", "60.90", "1200", {}, "15"],
                    ["2026-08-20 15:00:00", "61.80", "62.13", "62.30", "61.70", "800", {}, "12"],
                ]
            }
        }
    }
    frame = fetch_tencent_intraday_60m(
        FakeClient(payload),
        "sh601138",
        target_date=date(2026, 8, 20),
    )
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].strftime("%Y-%m-%d %H:%M:%S") == "2026-08-20 15:00:00"
    assert frame.iloc[-1]["volume"] == 80_000
    assert frame.iloc[-1]["turnover_rate"] == 0.12
    assert frame.iloc[-1]["amount"] > 4_000_000


def test_sina_intraday_parser_keeps_completed_60m_bar() -> None:
    payload = [
        {
            "day": "2026-08-20 14:00:00",
            "open": "61.00",
            "high": "62.00",
            "low": "60.90",
            "close": "61.80",
            "volume": "120000",
            "amount": "7420000",
        },
        {
            "day": "2026-08-20 15:00:00",
            "open": "61.80",
            "high": "62.30",
            "low": "61.70",
            "close": "62.13",
            "volume": "80000",
            "amount": "4960000",
        },
    ]
    text = "callback=(" + json.dumps(payload) + ");"
    client = FakeClient([])
    client.session = FakeSession([])
    client.session.get = lambda *args, **kwargs: FakeResponse(text=text)

    frame = fetch_sina_intraday_60m(
        client,
        "sh601138",
        target_date=date(2026, 8, 20),
    )
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].strftime("%Y-%m-%d %H:%M:%S") == "2026-08-20 15:00:00"
    assert frame.iloc[-1]["close"] == 62.13
    assert frame.iloc[-1]["amount"] == 4_960_000


def test_sina_snapshot_parser_normalizes_numeric_fields() -> None:
    payload = [
        {
            "symbol": "sh601138",
            "code": "601138",
            "trade": "62.13",
            "changepercent": "0.49",
            "amount": "123456789.00",
            "turnoverratio": "1.25",
        }
    ]
    frame = fetch_sina_market_snapshot(FakeClient(payload), minimum_rows=1)
    assert frame.iloc[0]["close"] == 62.13
    assert frame.iloc[0]["pct_change"] == 0.49
    assert frame.iloc[0]["amount"] == 123_456_789


def test_sina_snapshot_paginates_using_stock_count() -> None:
    rows = [
        {
            "symbol": f"sh{600000 + index:06d}",
            "code": f"{600000 + index:06d}",
            "name": f"样本{index}",
            "trade": "10.00",
            "changepercent": "0.10",
            "amount": "1000000",
            "turnoverratio": "1.00",
        }
        for index in range(160)
    ]

    class PagingSession:
        def get(self, url, *, params=None, **kwargs):
            if "getHQNodeStockCount" in url:
                return FakeResponse(text="160")
            page = int(params["page"])
            start = (page - 1) * 80
            return FakeResponse(rows[start : start + 80])

    client = FakeClient([])
    client.session = PagingSession()
    frame = fetch_sina_market_snapshot(client, minimum_rows=100)
    assert len(frame) == 160
    assert frame["code"].nunique() == 160


def test_sina_industry_parser_returns_rankable_rows() -> None:
    text = (
        'var S_Finance_bankuai_sinaindustry={"a":"a,半导体,100,20.1,0.5,2.30,'
        '123456,3456789000,600001,5.1,20.0,1.0,示例股","b":"b,通信设备,80,'
        '30.1,-0.2,-1.20,223456,2456789000,600002,3.1,30.0,0.9,示例股二"};'
    )
    client = FakeClient([])
    client.session.get = lambda *args, **kwargs: FakeResponse(text=text)
    rows = fetch_sina_industries(client)
    assert rows[0]["industry"] == "半导体"
    assert rows[0]["pct_change"] == 2.3
    assert rows[0]["amount"] == 3_456_789_000
    assert rows[-1]["industry"] == "通信设备"


def test_resilient_source_fills_quote_fields_and_intraday(monkeypatch) -> None:
    target = date(2026, 8, 20)
    config = _config()
    daily_dates = pd.bdate_range(end=target, periods=220)
    daily = pd.DataFrame(
        {
            "date": daily_dates,
            "open": 60.0,
            "high": 63.0,
            "low": 59.0,
            "close": 62.13,
            "volume": 10_000_000.0,
            "amount": np.nan,
            "turnover_rate": np.nan,
            "pct_change": np.nan,
        }
    )
    quote = Quote(
        code=config.code,
        name=config.name,
        timestamp=datetime(2026, 8, 20, 15, 0, tzinfo=SHANGHAI),
        open=61.5,
        high=62.8,
        low=61.1,
        close=62.13,
        previous_close=61.83,
        volume=12_345_600,
        amount=765_432_100,
        pct_change=0.49,
        turnover_rate=2.36,
        pe_ttm=28.4,
        pb=4.2,
        total_market_cap=420_000_000_000,
        float_market_cap=350_000_000_000,
        source="腾讯行情",
    )
    base_bundle = StockBundle(
        config=config,
        daily=daily,
        intraday_60m=pd.DataFrame(),
        quote=quote,
        valid_for_target=True,
        data_confidence="high",
        last_data_date=target,
    )
    fallback = _complete_intraday()

    monkeypatch.setattr(LiveDataSource, "load_stock", lambda self, config, target_date: base_bundle)
    monkeypatch.setattr(
        enhanced_data,
        "fetch_tencent_intraday_60m",
        lambda client, symbol, target_date: fallback,
    )
    source = ResilientLiveDataSource(timeout=1)
    bundle = source.load_stock(config, target)
    row = bundle.daily[bundle.daily["date"].dt.date == target].iloc[-1]
    assert row["amount"] == 765_432_100
    assert row["turnover_rate"] == 2.36
    assert row["pct_change"] == 0.49
    assert len(bundle.intraday_60m) == 48
    assert "腾讯60分钟" in bundle.core_sources


def test_resilient_source_uses_sina_when_tencent_60m_fails(monkeypatch) -> None:
    target = date(2026, 8, 20)
    config = _config()
    base_bundle = StockBundle(config=config, intraday_60m=pd.DataFrame())
    fallback = _complete_intraday()

    monkeypatch.setattr(LiveDataSource, "load_stock", lambda self, config, target_date: base_bundle)
    monkeypatch.setattr(
        enhanced_data,
        "fetch_tencent_intraday_60m",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("unavailable")),
    )
    monkeypatch.setattr(
        enhanced_data,
        "fetch_sina_intraday_60m",
        lambda client, symbol, target_date: fallback,
    )

    source = ResilientLiveDataSource(timeout=1)
    bundle = source.load_stock(config, target)
    assert len(bundle.intraday_60m) == 48
    assert "新浪60分钟" in bundle.core_sources
    assert any(item["source"] == "新浪60分钟" and item["ok"] for item in bundle.source_status)


def test_market_guard_rejects_100_row_sample_and_uses_full_fallbacks(monkeypatch) -> None:
    target = date(2026, 8, 20)
    base_result = {
        "data_date": target.isoformat(),
        "indices": [
            {
                "code": "000001",
                "name": "上证指数",
                "date": target.isoformat(),
                "close": 3900.0,
                "pct_change": 0.2,
                "amount": 1.0e12,
                "source": "东方财富日线",
            },
            {
                "code": "399001",
                "name": "深证成指",
                "date": target.isoformat(),
                "close": 13900.0,
                "pct_change": 0.5,
                "amount": 1.1e12,
                "source": "东方财富日线",
            },
            {
                "code": "399006",
                "name": "创业板指",
                "date": target.isoformat(),
                "close": 3490.0,
                "pct_change": 0.6,
                "amount": 5.0e11,
                "source": "东方财富日线",
            },
        ],
        "total_amount": 80_000_000_000.0,
        "breadth": {"up": 100, "down": 0, "flat": 0, "median_pct": 10.8},
        "industry_table": [
            {"industry": "局部样本", "pct_change": 20.0, "amount": 80e9, "count": 100}
        ],
        "source_status": [
            {"source": "东方财富全市场行情", "ok": True, "rows": 100}
        ],
    }
    spot = pd.DataFrame(
        {
            "code": [f"{index:06d}" for index in range(3_200)],
            "pct_change": ([1.0] * 1_700) + ([-1.0] * 1_400) + ([0.0] * 100),
            "amount": [1_000_000_000.0] * 3_200,
        }
    )

    monkeypatch.setattr(
        LiveDataSource,
        "load_market",
        lambda self, stocks, target_date: base_result,
    )
    monkeypatch.setattr(enhanced_data, "fetch_sina_market_snapshot", lambda client: spot)
    monkeypatch.setattr(
        enhanced_data,
        "fetch_sina_industries",
        lambda client: [
            {"industry": "半导体", "pct_change": 2.0, "amount": 3e10, "count": 100}
        ],
    )

    source = ResilientLiveDataSource(timeout=1)
    result = source.load_market([], target)
    assert result["total_amount"] == 3.2e12
    assert result["breadth"] == {"up": 1700, "down": 1400, "flat": 100, "median_pct": 1.0}
    assert result["industry_table"][0]["industry"] == "半导体"
    assert any(
        item["source"] == "东方财富全市场完整性校验" and not item["ok"]
        for item in result["source_status"]
    )
