from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_review.indicators import add_indicators, to_weekly


def make_frame(rows: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=rows)
    index = np.arange(rows, dtype=float)
    close = 50 + index * 0.08 + np.sin(index / 7)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": 1_000_000 + index * 1_000,
            "amount": close * (1_000_000 + index * 1_000),
            "turnover_rate": 2.0,
        }
    )


def test_all_required_indicators_are_calculated() -> None:
    result = add_indicators(make_frame())
    latest = result.iloc[-1]
    for column in (
        "ma_5",
        "ma_10",
        "ma_20",
        "ma_50",
        "ma_100",
        "ma_200",
        "ema_5",
        "ema_10",
        "ema_20",
        "ema_50",
        "rsi_14",
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "kdj_k",
        "kdj_d",
        "kdj_j",
        "stoch_rsi_k",
        "stoch_rsi_d",
        "adx_14",
        "obv",
        "high_20",
        "low_20",
        "rel_volume_20",
    ):
        assert column in result.columns
        assert pd.notna(latest[column]), column


def test_weekly_aggregation_preserves_ohlcv_contract() -> None:
    weekly = to_weekly(make_frame())
    assert len(weekly) > 40
    assert {"date", "open", "high", "low", "close", "volume", "amount"}.issubset(weekly.columns)
