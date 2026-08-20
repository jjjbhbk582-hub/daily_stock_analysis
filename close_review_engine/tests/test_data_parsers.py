from __future__ import annotations

from datetime import date

import pandas as pd

import ashare_review.fallbacks as fallback_module
from ashare_review.config import StockConfig
from ashare_review.data import StockBundle, fetch_tencent_quote
from ashare_review.fallbacks import (
    ResilientLiveDataSource,
    fetch_sina_intraday,
    fetch_tencent_intraday,
    fetch_tencent_market_indices,
    parse_sina_industry_payload,
    parse_sina_market_rows,
)


class FakeClient:
    def get_text(self, url, *, params=None, encoding=None):
        fields = [""] * 50
        fields[1] = "工业富联"
        fields[3] = "62.15"
        fields[4] = "61.20"
        fields[5] = "61.50"
        fields[6] = "123456"
        fields[30] = "20260820150000"
        fields[32] = "1.55"
        fields[33] = "62.80"
        fields[34] = "61.10"
        fields[35] = "62.15/123456/765432100.00"
        fields[38] = "2.36"
        fields[39] = "28.4"
        fields[44] = "3500.0"
        fields[45] = "4200.0"
        fields[46] = "4.2"
        return 'v_sh601138="' + "~".join(fields) + '";'


def test_tencent_quote_parser_keeps_close_timestamp_and_units() -> None:
    config = StockConfig("601138", "工业富联", "SH", "消费电子", ("AI算力",), 90)
    quote = fetch_tencent_quote(FakeClient(), config)
    assert quote.close == 62.15
    assert quote.data_date.isoformat() == "2026-08-20"
    assert quote.volume == 12_345_600
    assert quote.amount == 765_432_100
    assert quote.turnover_rate == 2.36


class FakeTencentMinuteClient:
    def get_json(self, url, *, params=None):
        symbol = str(params["param"]).split(",", maxsplit=1)[0]
        return {
            "data": {
                symbol: {
                    "m60": [
                        ["202608201000", "61.00", "61.80", "62.00", "60.90", "12000", "742000"],
                        ["202608201100", "61.80", "62.05", "62.20", "61.70", "15000", "930000"],
                        ["202608201400", "62.05", "62.15", "62.40", "61.95", "18000", "1.12e6"],
                    ]
                }
            }
        }


def test_tencent_intraday_parser_returns_60m_ohlcv() -> None:
    frame = fetch_tencent_intraday(FakeTencentMinuteClient(), "sh601138", limit=320)
    assert list(frame.columns[:7]) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert len(frame) == 3
    assert frame.iloc[-1]["date"].isoformat() == "2026-08-20T14:00:00"
    assert frame.iloc[-1]["close"] == 62.15
    assert frame.iloc[-1]["amount"] == 1_120_000


class FakeSinaMinuteClient:
    def get_text(self, url, *, params=None, encoding=None):
        return (
            'callback=([{"day":"2026-08-20 10:30:00","open":"61.00","high":"62.00",'
            '"low":"60.90","close":"61.80","volume":"12000","amount":"742000"},'
            '{"day":"2026-08-20 11:30:00","open":"61.80","high":"62.20",'
            '"low":"61.70","close":"62.05","volume":"15000","amount":"930000"}]);'
        )


def test_sina_intraday_parser_returns_60m_ohlcv() -> None:
    frame = fetch_sina_intraday(FakeSinaMinuteClient(), "sh601138", limit=1970)
    assert list(frame.columns[:7]) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert len(frame) == 2
    assert frame.iloc[-1]["date"].isoformat() == "2026-08-20T11:30:00"
    assert frame.iloc[-1]["close"] == 62.05


def _tencent_line(
    symbol: str,
    name: str,
    code: str,
    close: float,
    previous_close: float,
    amount: float,
) -> str:
    fields = [""] * 50
    fields[1] = name
    fields[2] = code
    fields[3] = str(close)
    fields[4] = str(previous_close)
    fields[5] = str(previous_close)
    fields[6] = "123456"
    fields[30] = "20260820150000"
    fields[31] = str(close - previous_close)
    fields[32] = str((close / previous_close - 1) * 100)
    fields[33] = str(close + 10)
    fields[34] = str(close - 10)
    fields[35] = f"{close}/123456/{amount}"
    fields[36] = "123456"
    fields[37] = str(amount / 10_000)
    return f'v_{symbol}="' + "~".join(fields) + '";'


class FakeTencentIndexClient:
    def get_text(self, url, *, params=None, encoding=None):
        return "\n".join(
            [
                _tencent_line("sh000001", "上证指数", "000001", 4100.0, 4090.0, 620_000_000_000),
                _tencent_line("sz399001", "深证成指", "399001", 13200.0, 13100.0, 480_000_000_000),
                _tencent_line("sz399006", "创业板指", "399006", 2850.0, 2820.0, 210_000_000_000),
                _tencent_line("sz399106", "深证综指", "399106", 2500.0, 2480.0, 530_000_000_000),
            ]
        )


def test_tencent_market_indices_and_two_market_amount() -> None:
    result = fetch_tencent_market_indices(FakeTencentIndexClient(), target_date=date(2026, 8, 20))
    assert [item["name"] for item in result["indices"]] == ["上证指数", "深证成指", "创业板指"]
    assert all(item["date"] == "2026-08-20" for item in result["indices"])
    assert result["indices"][0]["pct_change"] == round((4100 / 4090 - 1) * 100, 4)
    assert result["total_amount"] == 1_150_000_000_000


def test_sina_industry_payload_parser() -> None:
    payload = (
        'var S_Finance_bankuai_sinaindustry={"new_jrhy":"new_jrhy,半导体,100,20.1,0.5,2.30,'
        '123456,3456789000,600001,5.1,20.0,1.0,示例股","new_jrhy2":"new_jrhy2,通信设备,80,'
        '30.1,-0.2,-1.20,223456,2456789000,600002,3.1,30.0,0.9,示例股二"};'
    )
    rows = parse_sina_industry_payload(payload)
    assert rows[0]["industry"] == "半导体"
    assert rows[0]["pct_change"] == 2.3
    assert rows[0]["amount"] == 3_456_789_000
    assert rows[0]["count"] == 100
    assert rows[-1]["industry"] == "通信设备"


def test_sina_market_rows_normalize_numeric_fields() -> None:
    frame = parse_sina_market_rows(
        [
            {
                "symbol": "sh600000",
                "name": "浦发银行",
                "trade": "10.10",
                "changepercent": "1.20",
                "amount": "1000000",
                "turnoverratio": "0.50",
            },
            {
                "symbol": "sz000001",
                "name": "平安银行",
                "trade": "12.20",
                "changepercent": "-0.80",
                "amount": "2000000",
                "turnoverratio": "0.60",
            },
        ]
    )
    assert frame["amount"].sum() == 3_000_000
    assert int((frame["pct_change"] > 0).sum()) == 1
    assert int((frame["pct_change"] < 0).sum()) == 1


def test_load_stock_uses_sina_when_tencent_60m_is_unavailable(monkeypatch) -> None:
    config = StockConfig("600183", "生益科技", "SH", "元件", ("PCB",), 88)
    base_bundle = StockBundle(config=config)
    monkeypatch.setattr(
        fallback_module.LiveDataSource,
        "load_stock",
        lambda self, stock, target_date: base_bundle,
    )
    monkeypatch.setattr(
        fallback_module,
        "fetch_tencent_intraday",
        lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("unavailable")),
    )
    sina_frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-13 10:30:00", periods=30, freq="h"),
            "open": [10.0] * 30,
            "high": [10.4] * 30,
            "low": [9.8] * 30,
            "close": [10.2] * 30,
            "volume": [1000] * 30,
            "amount": [10_200] * 30,
        }
    )
    monkeypatch.setattr(fallback_module, "fetch_sina_intraday", lambda *args, **kwargs: sina_frame)

    source = ResilientLiveDataSource()
    source.client = object()
    bundle = source.load_stock(config, date(2026, 8, 20))
    assert len(bundle.intraday_60m) == 30
    assert any(item["source"] == "新浪60分钟" and item["ok"] for item in bundle.source_status)


def test_load_market_rejects_incomplete_eastmoney_spot_and_uses_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(
        fallback_module.LiveDataSource,
        "load_market",
        lambda self, stocks, target_date: {
            "data_date": target_date.isoformat(),
            "indices": [],
            "total_amount": 80e9,
            "breadth": {"up": 100, "down": 0, "flat": 0, "median_pct": 10.0},
            "industry_table": [
                {"industry": "错误样本", "pct_change": 20.0, "amount": 80e9, "count": 100}
            ],
            "source_status": [
                {"source": "东方财富全市场行情", "ok": True, "rows": 100}
            ],
        },
    )
    monkeypatch.setattr(
        fallback_module,
        "fetch_tencent_market_indices",
        lambda *args, **kwargs: {
            "indices": [
                {
                    "code": "000001",
                    "name": "上证指数",
                    "date": "2026-08-20",
                    "close": 4100.0,
                    "pct_change": 0.2,
                    "amount": 620e9,
                    "source": "腾讯行情",
                }
            ],
            "total_amount": 1.15e12,
        },
    )
    monkeypatch.setattr(
        fallback_module,
        "fetch_sina_market_spot",
        lambda *args, **kwargs: pd.DataFrame(
            {
                "code": ["600000", "000001", "000002"],
                "name": ["甲", "乙", "丙"],
                "close": [10.0, 11.0, 12.0],
                "pct_change": [1.0, -1.0, 0.0],
                "amount": [1e9, 2e9, 3e9],
                "turnover_rate": [1.0, 1.0, 1.0],
            }
        ),
    )
    monkeypatch.setattr(
        fallback_module,
        "fetch_sina_industries",
        lambda *args, **kwargs: [
            {"industry": "半导体", "pct_change": 2.0, "amount": 3e10, "count": 100}
        ],
    )

    source = ResilientLiveDataSource()
    source.client = object()
    result = source.load_market([], date(2026, 8, 20))
    assert result["indices"][0]["source"] == "腾讯行情"
    assert result["total_amount"] == 6e9
    assert result["breadth"] == {"up": 1, "down": 1, "flat": 1, "median_pct": 0.0}
    assert result["industry_table"][0]["industry"] == "半导体"
    assert any(item["source"] == "东方财富全市场完整性校验" and not item["ok"] for item in result["source_status"])
