from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

import ashare_review.enhanced_data as enhanced_data
from ashare_review.completed_daily_source import CompletedDailyLiveDataSource
from ashare_review.config import StockConfig
from ashare_review.data import LiveDataSource, Quote, StockBundle

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _config() -> StockConfig:
    return StockConfig("601138", "工业富联", "SH", "消费电子", ("AI算力",), 90)


def _previous_day_history(target: date) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(target) - pd.Timedelta(days=1), periods=220)
    return pd.DataFrame(
        {
            "date": dates,
            "open": 60.0,
            "high": 62.0,
            "low": 59.5,
            "close": 61.5,
            "volume": 10_000_000.0,
            "amount": 620_000_000.0,
            "pct_change": 0.3,
            "turnover_rate": 1.5,
        }
    )


def _completed_intraday(target: date, *, close: float = 62.13) -> pd.DataFrame:
    prior = list(pd.date_range("2026-08-10 10:00:00", periods=40, freq="6h"))
    current = [
        pd.Timestamp(f"{target.isoformat()} 10:30:00"),
        pd.Timestamp(f"{target.isoformat()} 11:30:00"),
        pd.Timestamp(f"{target.isoformat()} 14:00:00"),
        pd.Timestamp(f"{target.isoformat()} 15:00:00"),
    ]
    dates = pd.DatetimeIndex(prior + current)
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": 61.5,
            "high": 62.4,
            "low": 61.1,
            "close": 62.0,
            "volume": 1_000_000.0,
            "amount": 62_000_000.0,
        }
    )
    frame.loc[frame.index[-1], "close"] = close
    return frame


def _quote(config: StockConfig, target: date, *, close: float = 62.13) -> Quote:
    return Quote(
        code=config.code,
        name=config.name,
        timestamp=datetime(target.year, target.month, target.day, 15, 0, tzinfo=SHANGHAI),
        open=61.5,
        high=62.4,
        low=61.1,
        close=close,
        previous_close=61.5,
        volume=12_345_600,
        amount=765_432_100,
        pct_change=1.02,
        turnover_rate=2.36,
        pe_ttm=28.4,
        pb=4.2,
        total_market_cap=420_000_000_000,
        float_market_cap=350_000_000_000,
        source="腾讯行情",
    )


def _base_bundle(config: StockConfig, target: date) -> StockBundle:
    return StockBundle(
        config=config,
        daily=_previous_day_history(target),
        intraday_60m=pd.DataFrame(),
        quote=_quote(config, target),
        valid_for_target=False,
        data_confidence="low",
        last_data_date=date(2026, 8, 20),
    )


def test_completed_fallback_intraday_synthesizes_current_daily_bar(monkeypatch) -> None:
    target = date(2026, 8, 21)
    config = _config()
    base_bundle = _base_bundle(config, target)
    intraday = _completed_intraday(target)

    monkeypatch.setattr(
        LiveDataSource,
        "load_stock",
        lambda self, config, target_date: base_bundle,
    )
    monkeypatch.setattr(
        enhanced_data,
        "fetch_tencent_intraday_60m",
        lambda client, symbol, target_date: intraday,
    )

    bundle = CompletedDailyLiveDataSource(timeout=1).load_stock(config, target)

    assert bundle.valid_for_target is True
    assert bundle.last_data_date == target
    assert len(bundle.daily) == 221
    target_row = bundle.daily[bundle.daily["date"].dt.date == target].iloc[-1]
    assert target_row["close"] == 62.13
    assert target_row["volume"] == 12_345_600
    assert target_row["amount"] == 765_432_100
    assert bundle.data_confidence == "medium"
    assert any(
        status.get("source") == "完成日线合成" and status.get("ok")
        for status in bundle.source_status
    )


def test_completed_daily_synthesis_rejects_close_disagreement(monkeypatch) -> None:
    target = date(2026, 8, 21)
    config = _config()
    base_bundle = _base_bundle(config, target)
    intraday = _completed_intraday(target, close=60.00)

    monkeypatch.setattr(
        LiveDataSource,
        "load_stock",
        lambda self, config, target_date: base_bundle,
    )
    monkeypatch.setattr(
        enhanced_data,
        "fetch_tencent_intraday_60m",
        lambda client, symbol, target_date: intraday,
    )

    bundle = CompletedDailyLiveDataSource(timeout=1).load_stock(config, target)

    assert bundle.valid_for_target is False
    assert bundle.last_data_date == date(2026, 8, 20)
    assert not (bundle.daily["date"].dt.date == target).any()
    assert any(
        status.get("source") == "完成日线合成" and not status.get("ok")
        for status in bundle.source_status
    )
