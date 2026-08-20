from __future__ import annotations

import numpy as np
import pandas as pd

MA_PERIODS = (5, 10, 20, 50, 100, 200)
EMA_PERIODS = (5, 10, 20, 50)


def _wilder(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def normalize_ohlcv(source: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")
    frame = source.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_change"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if "amount" not in frame:
        frame["amount"] = np.nan
    if "turnover_rate" not in frame:
        frame["turnover_rate"] = np.nan
    if "pct_change" not in frame:
        frame["pct_change"] = frame["close"].pct_change() * 100
    return frame


def add_indicators(source: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_ohlcv(source)
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"].fillna(0.0)

    for period in MA_PERIODS:
        frame[f"ma_{period}"] = close.rolling(period, min_periods=period).mean()
    for period in EMA_PERIODS:
        frame[f"ema_{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, 14)
    avg_loss = _wilder(loss, 14)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(avg_loss.ne(0), 100.0)
    rsi = rsi.where(avg_gain.ne(0), 0.0)
    frame["rsi_14"] = rsi.clip(0, 100)

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    frame["macd_dif"] = ema12 - ema26
    frame["macd_dea"] = frame["macd_dif"].ewm(span=9, adjust=False, min_periods=9).mean()
    frame["macd_hist"] = 2 * (frame["macd_dif"] - frame["macd_dea"])

    low9 = low.rolling(9, min_periods=9).min()
    high9 = high.rolling(9, min_periods=9).max()
    rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100).clip(0, 100)
    frame["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    frame["kdj_d"] = frame["kdj_k"].ewm(alpha=1 / 3, adjust=False, min_periods=1).mean()
    frame["kdj_j"] = 3 * frame["kdj_k"] - 2 * frame["kdj_d"]

    rsi_min = frame["rsi_14"].rolling(14, min_periods=14).min()
    rsi_max = frame["rsi_14"].rolling(14, min_periods=14).max()
    stoch = (frame["rsi_14"] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    frame["stoch_rsi"] = stoch.clip(0, 1)
    frame["stoch_rsi_k"] = frame["stoch_rsi"].rolling(3, min_periods=1).mean() * 100
    frame["stoch_rsi_d"] = frame["stoch_rsi_k"].rolling(3, min_periods=1).mean()

    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    frame["atr_14"] = _wilder(true_range, 14)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=frame.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=frame.index)
    atr = frame["atr_14"].replace(0, np.nan)
    frame["plus_di_14"] = 100 * _wilder(plus_dm, 14) / atr
    frame["minus_di_14"] = 100 * _wilder(minus_dm, 14) / atr
    di_sum = (frame["plus_di_14"] + frame["minus_di_14"]).replace(0, np.nan)
    dx = 100 * (frame["plus_di_14"] - frame["minus_di_14"]).abs() / di_sum
    frame["adx_14"] = _wilder(dx, 14)

    direction = np.sign(close.diff()).fillna(0.0)
    frame["obv"] = (direction * volume).cumsum()
    frame["obv_ema_20"] = frame["obv"].ewm(span=20, adjust=False, min_periods=20).mean()

    frame["high_20"] = high.rolling(20, min_periods=20).max()
    frame["low_20"] = low.rolling(20, min_periods=20).min()
    frame["prior_high_20"] = high.shift(1).rolling(20, min_periods=20).max()
    frame["prior_low_20"] = low.shift(1).rolling(20, min_periods=20).min()
    avg_volume = volume.shift(1).rolling(20, min_periods=20).mean()
    frame["avg_volume_20"] = avg_volume
    frame["rel_volume_20"] = volume / avg_volume.replace(0, np.nan)
    return frame


def to_weekly(source: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_ohlcv(source).set_index("date")
    aggregations = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "amount": "sum",
        "turnover_rate": "sum",
    }
    weekly = frame.resample("W-FRI", label="right", closed="right").agg(aggregations)
    weekly = weekly.dropna(subset=["open", "high", "low", "close"]).reset_index()
    weekly["pct_change"] = weekly["close"].pct_change() * 100
    return weekly


def finite(value: object, default: float | None = None) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if np.isfinite(numeric) else default
