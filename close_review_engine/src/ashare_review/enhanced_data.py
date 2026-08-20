from __future__ import annotations

from datetime import date, time
from typing import Any

import numpy as np
import pandas as pd

from ashare_review.config import StockConfig
from ashare_review.data import (
    HttpClient,
    LiveDataSource,
    StockBundle,
    _number,
    _short_error,
    fetch_tencent_quote,
)
from ashare_review.indicators import normalize_ohlcv

TENCENT_MINUTE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
SINA_MARKET_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)


def fetch_tencent_intraday_60m(
    client: HttpClient,
    symbol: str,
    *,
    target_date: date,
    limit: int = 320,
) -> pd.DataFrame:
    response = client.session.get(
        TENCENT_MINUTE_URL,
        params={"param": f"{symbol},m60,,{limit}"},
        headers={"Referer": "https://gu.qq.com/"},
        timeout=client.timeout,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    item = data.get(symbol) if isinstance(data, dict) else None
    rows = item.get("m60") if isinstance(item, dict) else None
    records: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        volume_lots = _number(row[5])
        open_price = _number(row[1])
        close_price = _number(row[2])
        high_price = _number(row[3])
        low_price = _number(row[4])
        if None in (volume_lots, open_price, close_price, high_price, low_price):
            continue
        volume = float(volume_lots) * 100
        typical_price = (
            float(open_price) + float(close_price) + float(high_price) + float(low_price)
        ) / 4
        turnover_rate = _number(row[7], scale=100) if len(row) > 7 else None
        records.append(
            {
                "date": row[0],
                "open": open_price,
                "close": close_price,
                "high": high_price,
                "low": low_price,
                "volume": volume,
                "amount": volume * typical_price,
                "turnover_rate": turnover_rate,
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame = normalize_ohlcv(frame)
    frame = frame[frame["date"].dt.date <= target_date].reset_index(drop=True)
    return frame


def fetch_sina_market_snapshot(client: HttpClient) -> pd.DataFrame:
    response = client.session.get(
        SINA_MARKET_URL,
        params={
            "page": 1,
            "num": 5000,
            "sort": "symbol",
            "asc": 1,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page",
        },
        headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
        timeout=client.timeout,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = frame.rename(
        columns={
            "trade": "close",
            "changepercent": "pct_change",
            "turnoverratio": "turnover_rate",
        }
    )
    for column in ("close", "pct_change", "amount", "turnover_rate"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _completed_intraday(frame: pd.DataFrame, target_date: date) -> bool:
    if frame.empty or len(frame) < 40:
        return False
    target_rows = frame[frame["date"].dt.date == target_date]
    if target_rows.empty:
        return False
    return target_rows["date"].max().time() >= time(15, 0)


def _fill_daily_quote_fields(bundle: StockBundle, target_date: date) -> None:
    quote = bundle.quote
    if quote is None or quote.data_date != target_date or bundle.daily.empty:
        return
    mask = bundle.daily["date"].dt.date == target_date
    if not mask.any():
        return
    index = bundle.daily.index[mask][-1]
    replacements = {
        "amount": quote.amount,
        "turnover_rate": quote.turnover_rate,
        "pct_change": quote.pct_change,
    }
    changed = False
    for column, value in replacements.items():
        if value is None:
            continue
        if column not in bundle.daily.columns:
            bundle.daily[column] = np.nan
        current = bundle.daily.at[index, column]
        if pd.isna(current):
            bundle.daily.at[index, column] = value
            changed = True
    if changed:
        bundle.source_status.append(
            {"source": "腾讯收盘字段补全", "ok": True, "date": target_date.isoformat()}
        )


class ResilientLiveDataSource(LiveDataSource):
    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle:
        bundle = super().load_stock(config, target_date)
        _fill_daily_quote_fields(bundle, target_date)
        if _completed_intraday(bundle.intraday_60m, target_date):
            return bundle
        try:
            fallback = fetch_tencent_intraday_60m(
                self.client,
                config.symbol,
                target_date=target_date,
            )
            complete = _completed_intraday(fallback, target_date)
            bundle.source_status.append(
                {
                    "source": "腾讯60分钟",
                    "ok": complete,
                    "rows": len(fallback),
                    "date": None if fallback.empty else str(fallback["date"].max()),
                }
            )
            if complete:
                bundle.intraday_60m = fallback
                bundle.core_sources.append("腾讯60分钟")
        except Exception as exc:  # noqa: BLE001
            bundle.source_status.append(
                {"source": "腾讯60分钟", "ok": False, "error": _short_error(exc)}
            )
        return bundle

    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]:
        result = super().load_market(stocks, target_date)
        target = target_date.isoformat()
        valid_indices = {
            str(item.get("code")): item
            for item in result.get("indices", [])
            if item.get("date") == target
        }
        index_configs = (
            StockConfig("000001", "上证指数", "SH", "指数", (), 50),
            StockConfig("399001", "深证成指", "SZ", "指数", (), 50),
            StockConfig("399006", "创业板指", "SZ", "指数", (), 50),
        )
        for config in index_configs:
            if config.code in valid_indices:
                continue
            try:
                quote = fetch_tencent_quote(self.client, config)
                if quote.data_date != target_date or quote.close is None:
                    raise ValueError(f"腾讯指数日期为{quote.data_date}，目标日期为{target_date}")
                valid_indices[config.code] = {
                    "code": config.code,
                    "name": config.name,
                    "date": target,
                    "close": quote.close,
                    "pct_change": quote.pct_change,
                    "amount": quote.amount,
                    "source": "腾讯指数行情",
                }
                result["source_status"].append(
                    {"source": f"腾讯{config.name}", "ok": True, "date": target}
                )
            except Exception as exc:  # noqa: BLE001
                result["source_status"].append(
                    {
                        "source": f"腾讯{config.name}",
                        "ok": False,
                        "error": _short_error(exc),
                    }
                )
        result["indices"] = [
            valid_indices[config.code]
            for config in index_configs
            if config.code in valid_indices
        ]

        need_spot = result.get("total_amount") is None or not result.get("breadth")
        if need_spot:
            try:
                spot = fetch_sina_market_snapshot(self.client)
                if len(spot) < 500:
                    raise ValueError(f"新浪全市场仅返回{len(spot)}行，拒绝冒充全市场")
                if result.get("total_amount") is None and "amount" in spot:
                    result["total_amount"] = float(spot["amount"].fillna(0).sum())
                if not result.get("breadth") and "pct_change" in spot:
                    pct = spot["pct_change"].dropna()
                    result["breadth"] = {
                        "up": int((pct > 0).sum()),
                        "down": int((pct < 0).sum()),
                        "flat": int((pct == 0).sum()),
                        "median_pct": float(pct.median()) if not pct.empty else None,
                    }
                result["source_status"].append(
                    {"source": "新浪全市场行情", "ok": True, "rows": len(spot)}
                )
            except Exception as exc:  # noqa: BLE001
                result["source_status"].append(
                    {"source": "新浪全市场行情", "ok": False, "error": _short_error(exc)}
                )

        if result.get("total_amount") is None:
            amounts = {
                item["code"]: _number(item.get("amount"))
                for item in result.get("indices", [])
            }
            if amounts.get("000001") is not None and amounts.get("399001") is not None:
                result["total_amount"] = float(amounts["000001"] + amounts["399001"])
                result["source_status"].append(
                    {"source": "腾讯沪深指数成交额合计", "ok": True, "date": target}
                )
        return result
