from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ashare_review.config import StockConfig
from ashare_review.data import LiveDataSource, Quote, StockBundle
from ashare_review.enhanced_data import (
    ResilientLiveDataSource,
    fetch_sina_market_snapshot,
    fetch_tencent_intraday_60m,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

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
    frame = fetch_sina_market_snapshot(FakeClient(payload))
    assert frame.iloc[0]["close"] == 62.13
    assert frame.iloc[0]["pct_change"] == 0.49
    assert frame.iloc[0]["amount"] == 123_456_789


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
    intraday_dates = pd.date_range("2026-08-07 10:30:00", periods=48, freq="2h30min")
    intraday_dates = intraday_dates.map(
        lambda value: value.replace(hour=15, minute=0)
        if value.date() == target
        else value
    )
    intraday_dates = pd.DatetimeIndex(list(intraday_dates[:-1]) + [pd.Timestamp("2026-08-20 15:00:00")])
    fallback = pd.DataFrame(
        {
            "date": intraday_dates,
            "open": 61.0,
            "high": 63.0,
            "low": 60.0,
            "close": 62.0,
            "volume": 1_000_000.0,
            "amount": 62_000_000.0,
        }
    )

    monkeypatch.setattr(LiveDataSource, "load_stock", lambda self, config, target_date: base_bundle)
    monkeypatch.setattr(
        "ashare_review.enhanced_data.fetch_tencent_intraday_60m",
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
