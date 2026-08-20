from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ashare_review.config import StockConfig
from ashare_review.data import Quote, StockBundle


class FixtureDataSource:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    @classmethod
    def from_path(cls, path: str | Path) -> "FixtureDataSource":
        return cls(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]:
        market = dict(self.payload.get("market") or {})
        market.setdefault("data_date", target_date.isoformat())
        market.setdefault(
            "indices",
            [
                {"code": "000001", "name": "上证指数", "date": target_date.isoformat(), "close": 4100, "pct_change": 0.4, "source": "fixture"},
                {"code": "399001", "name": "深证成指", "date": target_date.isoformat(), "close": 13200, "pct_change": 0.7, "source": "fixture"},
                {"code": "399006", "name": "创业板指", "date": target_date.isoformat(), "close": 2850, "pct_change": 0.9, "source": "fixture"},
            ],
        )
        market.setdefault("total_amount", 1_650_000_000_000)
        market.setdefault("breadth", {"up": 3200, "down": 1800, "flat": 120, "median_pct": 0.32})
        market.setdefault(
            "industry_table",
            [
                {"industry": "通信设备", "pct_change": 2.3, "amount": 90_000_000_000, "count": 80},
                {"industry": "电子元件", "pct_change": 1.8, "amount": 160_000_000_000, "count": 240},
                {"industry": "半导体", "pct_change": 1.2, "amount": 140_000_000_000, "count": 180},
                {"industry": "游戏", "pct_change": 0.5, "amount": 35_000_000_000, "count": 35},
                {"industry": "小金属", "pct_change": -0.4, "amount": 28_000_000_000, "count": 45},
            ],
        )
        market.setdefault("source_status", [{"source": "fixture", "ok": True}])
        return market

    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle:
        settings = (self.payload.get("stocks") or {}).get(config.code, {})
        bias = float(settings.get("bias", 0.8))
        base_price = float(settings.get("base_price", 40.0))
        dates = pd.bdate_range(end=target_date, periods=330)
        index = np.arange(len(dates), dtype=float)
        trend = np.exp((bias - 0.65) * index / 620)
        wave = 1 + 0.035 * np.sin(index / 8.0 + int(config.code[-2:]) / 9)
        close = base_price * trend * wave
        open_price = close * (1 + 0.005 * np.sin(index / 5.0))
        high = np.maximum(open_price, close) * 1.018
        low = np.minimum(open_price, close) * 0.982
        volume = 8_000_000 * (1 + 0.25 * np.sin(index / 11.0) + bias * 0.2)
        volume[-1] *= 1.1 + max(0, bias - 0.8)
        amount = volume * close
        daily = pd.DataFrame(
            {
                "date": dates,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
                "turnover_rate": 1.5 + bias,
            }
        )
        daily["pct_change"] = daily["close"].pct_change() * 100

        intraday_rows: list[dict[str, Any]] = []
        for day, day_close in zip(dates[-80:], close[-80:], strict=True):
            for hour, factor in ((10, 0.992), (11, 0.997), (14, 1.002), (15, 1.0)):
                timestamp = day.replace(hour=hour, minute=0)
                intraday_rows.append(
                    {
                        "date": timestamp,
                        "open": day_close * (factor - 0.003),
                        "high": day_close * (factor + 0.006),
                        "low": day_close * (factor - 0.007),
                        "close": day_close * factor,
                        "volume": volume[-1] / 4,
                        "amount": amount[-1] / 4,
                    }
                )
        intraday = pd.DataFrame(intraday_rows)
        latest = daily.iloc[-1]
        quote = Quote(
            code=config.code,
            name=config.name,
            timestamp=datetime.combine(target_date, datetime.min.time()).replace(hour=15, tzinfo=None).astimezone(),
            open=float(latest["open"]),
            high=float(latest["high"]),
            low=float(latest["low"]),
            close=float(latest["close"]),
            previous_close=float(daily.iloc[-2]["close"]),
            volume=float(latest["volume"]),
            amount=float(latest["amount"]),
            pct_change=float(latest["pct_change"]),
            turnover_rate=float(latest["turnover_rate"]),
            pe_ttm=25 + bias * 10,
            pb=3 + bias,
            total_market_cap=80_000_000_000,
            float_market_cap=70_000_000_000,
            source="fixture",
        )
        financials = {
            "report_date": target_date.replace(day=1).isoformat(),
            "revenue_yoy": float(settings.get("revenue_growth", 8 + bias * 12)),
            "net_profit_yoy": float(settings.get("profit_growth", 10 + bias * 18)),
            "roe": float(settings.get("roe", 9 + bias * 7)),
            "eps": 1.2,
            "source": "fixture",
        }
        announcements = [
            {"date": target_date.isoformat(), "title": "经营情况正常，无重大监管风险", "source": "fixture"}
        ]
        fund_flow = {
            "date": target_date.isoformat(),
            "main_net_ratio": (bias - 0.7) * 12,
            "source": "fixture",
        }
        return StockBundle(
            config=config,
            daily=daily,
            intraday_60m=intraday,
            quote=quote,
            financials=financials,
            announcements=announcements,
            fund_flow=fund_flow,
            core_sources=["fixture日线", "fixture收盘"],
            source_status=[{"source": "fixture", "ok": True}],
            valid_for_target=True,
            data_confidence="high",
            last_data_date=target_date,
        )
