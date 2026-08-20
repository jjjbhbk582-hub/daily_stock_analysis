from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as clock_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ashare_review.config import StockConfig
from ashare_review.indicators import normalize_ohlcv

SHANGHAI = ZoneInfo("Asia/Shanghai")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(slots=True)
class Quote:
    code: str
    name: str
    timestamp: datetime | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    previous_close: float | None
    volume: float | None
    amount: float | None
    pct_change: float | None
    turnover_rate: float | None
    pe_ttm: float | None
    pb: float | None
    total_market_cap: float | None
    float_market_cap: float | None
    source: str

    @property
    def data_date(self) -> date | None:
        return None if self.timestamp is None else self.timestamp.astimezone(SHANGHAI).date()


@dataclass(slots=True)
class StockBundle:
    config: StockConfig
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)
    intraday_60m: pd.DataFrame = field(default_factory=pd.DataFrame)
    quote: Quote | None = None
    financials: dict[str, Any] = field(default_factory=dict)
    announcements: list[dict[str, Any]] = field(default_factory=list)
    fund_flow: dict[str, Any] = field(default_factory=dict)
    core_sources: list[str] = field(default_factory=list)
    source_status: list[dict[str, Any]] = field(default_factory=list)
    valid_for_target: bool = False
    data_confidence: str = "low"
    last_data_date: date | None = None


class HttpClient:
    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            backoff_factor=0.45,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16))
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://quote.eastmoney.com/",
            }
        )

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected JSON payload from {url}")
        return payload

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        encoding: str | None = None,
    ) -> str:
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        result = float(value) / scale
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _eastmoney_rows(payload: dict[str, Any]) -> list[list[str]]:
    data = payload.get("data")
    rows = data.get("klines") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [str(row).split(",") for row in rows]


def _parse_kline_rows(rows: list[list[str]], *, intraday: bool = False) -> pd.DataFrame:
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 7:
            continue
        parsed.append(
            {
                "date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume": row[5],
                "amount": row[6],
                "amplitude": row[7] if len(row) > 7 else None,
                "pct_change": row[8] if len(row) > 8 else None,
                "change": row[9] if len(row) > 9 else None,
                "turnover_rate": row[10] if len(row) > 10 else None,
            }
        )
    frame = pd.DataFrame(parsed)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in frame.columns.difference(["date"]):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "close", "high", "low", "volume"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if not intraday:
        frame["date"] = frame["date"].dt.normalize()
    return frame


def fetch_eastmoney_kline(
    client: HttpClient,
    secid: str,
    *,
    period: int,
    limit: int,
    target_date: date,
) -> pd.DataFrame:
    payload = client.get_json(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": secid,
            "klt": period,
            "fqt": 1,
            "lmt": limit,
            "beg": 0,
            "end": target_date.strftime("%Y%m%d"),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        },
    )
    return _parse_kline_rows(_eastmoney_rows(payload), intraday=period < 100)


def fetch_tencent_daily(
    client: HttpClient, symbol: str, *, target_date: date, limit: int = 360
) -> pd.DataFrame:
    start = (target_date - timedelta(days=700)).isoformat()
    payload = client.get_json(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{symbol},day,{start},{target_date.isoformat()},{limit},qfq"},
    )
    data = payload.get("data")
    item = data.get(symbol) if isinstance(data, dict) else None
    rows = (item.get("qfqday") or item.get("day")) if isinstance(item, dict) else []
    parsed: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        parsed.append(
            {
                "date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume": _number(row[5], scale=0.01),
                "amount": row[6] if len(row) > 6 else np.nan,
            }
        )
    frame = pd.DataFrame(parsed)
    if frame.empty:
        return frame
    return normalize_ohlcv(frame)


def fetch_netease_daily(
    client: HttpClient, config: StockConfig, *, target_date: date
) -> pd.DataFrame:
    prefix = "0" if config.exchange == "SH" else "1"
    text = client.get_text(
        "https://quotes.money.163.com/service/chddata.html",
        params={
            "code": f"{prefix}{config.code}",
            "start": (target_date - timedelta(days=700)).strftime("%Y%m%d"),
            "end": target_date.strftime("%Y%m%d"),
            "fields": "TCLOSE;HIGH;LOW;TOPEN;LCLOSE;CHG;PCHG;TURNOVER;VOTURNOVER;VATURNOVER",
        },
        encoding="gbk",
    )
    reader = csv.DictReader(io.StringIO(text))
    records: list[dict[str, Any]] = []
    for row in reader:
        records.append(
            {
                "date": row.get("日期"),
                "open": row.get("开盘价"),
                "high": row.get("最高价"),
                "low": row.get("最低价"),
                "close": row.get("收盘价"),
                "volume": row.get("成交量"),
                "amount": row.get("成交金额"),
                "pct_change": row.get("涨跌幅"),
                "turnover_rate": row.get("换手率"),
            }
        )
    frame = pd.DataFrame(records)
    return normalize_ohlcv(frame) if not frame.empty else frame


def fetch_tencent_quote(client: HttpClient, config: StockConfig) -> Quote:
    text = client.get_text(
        "https://qt.gtimg.cn/q",
        params={"q": config.symbol},
        encoding="gbk",
    )
    match = re.search(r'="(.*)";?', text.strip())
    if not match:
        raise ValueError("Tencent quote payload missing quoted fields")
    fields = match.group(1).split("~")
    if len(fields) < 39:
        raise ValueError("Tencent quote payload has too few fields")
    timestamp: datetime | None = None
    raw_time = fields[30] if len(fields) > 30 else ""
    if raw_time:
        try:
            timestamp = datetime.strptime(raw_time, "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
        except ValueError:
            timestamp = None
    amount = None
    if len(fields) > 35 and fields[35]:
        pieces = fields[35].split("/")
        amount = _number(pieces[2]) if len(pieces) >= 3 else None
    if amount is None and len(fields) > 37:
        raw_amount = _number(fields[37])
        amount = None if raw_amount is None else raw_amount * 10_000
    volume_lots = _number(fields[6])
    total_market_cap = _number(fields[45]) if len(fields) > 45 else None
    float_market_cap = _number(fields[44]) if len(fields) > 44 else None
    return Quote(
        code=config.code,
        name=fields[1] or config.name,
        timestamp=timestamp,
        open=_number(fields[5]),
        high=_number(fields[33]),
        low=_number(fields[34]),
        close=_number(fields[3]),
        previous_close=_number(fields[4]),
        volume=None if volume_lots is None else volume_lots * 100,
        amount=amount,
        pct_change=_number(fields[32]),
        turnover_rate=_number(fields[38]),
        pe_ttm=_number(fields[39]) if len(fields) > 39 else None,
        pb=_number(fields[46]) if len(fields) > 46 else None,
        total_market_cap=None if total_market_cap is None else total_market_cap * 100_000_000,
        float_market_cap=None if float_market_cap is None else float_market_cap * 100_000_000,
        source="腾讯行情",
    )


def fetch_financials(client: HttpClient, config: StockConfig) -> dict[str, Any]:
    payload = client.get_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params={
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{config.code}")',
            "pageNumber": 1,
            "pageSize": 4,
            "sortColumns": "REPORT_DATE",
            "sortTypes": -1,
            "source": "WEB",
            "client": "WEB",
        },
    )
    result = payload.get("result")
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows:
        return {}
    row = rows[0]

    def first(*keys: str) -> Any:
        for key in keys:
            if row.get(key) not in (None, "", "-"):
                return row.get(key)
        return None

    return {
        "report_date": first("REPORT_DATE", "REPORTDATE"),
        "notice_date": first("NOTICE_DATE", "UPDATE_DATE"),
        "revenue": _number(first("TOTAL_OPERATE_INCOME", "OPERATE_INCOME")),
        "revenue_yoy": _number(first("TOTAL_OPERATE_INCOME_YOY", "YSTZ")),
        "net_profit": _number(first("PARENT_NETPROFIT", "NETPROFIT")),
        "net_profit_yoy": _number(first("PARENT_NETPROFIT_YOY", "SJLTZ")),
        "roe": _number(first("WEIGHTAVG_ROE", "ROE_WEIGHT", "ROE")),
        "eps": _number(first("BASIC_EPS", "EPSJB")),
        "gross_margin": _number(first("XSMLL", "GROSS_PROFIT_MARGIN")),
        "source": "东方财富数据中心",
    }


def fetch_announcements(
    client: HttpClient, config: StockConfig, *, target_date: date
) -> list[dict[str, Any]]:
    payload = client.get_json(
        "https://np-anotice-stock.eastmoney.com/api/security/ann",
        params={
            "sr": -1,
            "page_size": 12,
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": config.code,
        },
    )
    data = payload.get("data")
    rows = data.get("list") if isinstance(data, dict) else None
    output: list[dict[str, Any]] = []
    cutoff = target_date - timedelta(days=45)
    for item in rows or []:
        raw_date = item.get("notice_date") or item.get("display_time")
        try:
            event_date = pd.to_datetime(raw_date).date()
        except (TypeError, ValueError):
            continue
        if event_date < cutoff or event_date > target_date:
            continue
        output.append(
            {
                "date": event_date.isoformat(),
                "title": str(item.get("title") or "").strip(),
                "art_code": item.get("art_code"),
                "source": "东方财富公告",
            }
        )
    return output


def fetch_fund_flow(client: HttpClient, config: StockConfig, *, target_date: date) -> dict[str, Any]:
    payload = client.get_json(
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
        params={
            "secid": config.secid,
            "lmt": 20,
            "klt": 101,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
        },
    )
    data = payload.get("data")
    rows = data.get("klines") if isinstance(data, dict) else None
    if not rows:
        return {}
    fields = str(rows[-1]).split(",")
    if len(fields) < 7:
        return {}
    try:
        flow_date = pd.to_datetime(fields[0]).date()
    except (TypeError, ValueError):
        return {}
    if flow_date > target_date:
        return {}
    return {
        "date": flow_date.isoformat(),
        "main_net_inflow": _number(fields[1]),
        "small_net_inflow": _number(fields[2]),
        "medium_net_inflow": _number(fields[3]),
        "large_net_inflow": _number(fields[4]),
        "super_large_net_inflow": _number(fields[5]),
        "main_net_ratio": _number(fields[6]),
        "source": "东方财富资金流",
    }


def fetch_market_spot(client: HttpClient) -> pd.DataFrame:
    payload = client.get_json(
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        params={
            "pn": 1,
            "pz": 6000,
            "po": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f6,f8,f10,f20,f21,f100",
        },
    )
    data = payload.get("data")
    rows = data.get("diff") if isinstance(data, dict) else None
    frame = pd.DataFrame(rows or [])
    if frame.empty:
        return frame
    frame = frame.rename(
        columns={
            "f12": "code",
            "f14": "name",
            "f2": "close",
            "f3": "pct_change",
            "f6": "amount",
            "f8": "turnover_rate",
            "f10": "volume_ratio",
            "f20": "market_cap",
            "f21": "float_market_cap",
            "f100": "industry",
        }
    )
    for column in (
        "close",
        "pct_change",
        "amount",
        "turnover_rate",
        "volume_ratio",
        "market_cap",
        "float_market_cap",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _append_completed_bar(
    daily: pd.DataFrame, intraday: pd.DataFrame, quote: Quote, target_date: date
) -> pd.DataFrame:
    if intraday.empty or quote.data_date != target_date:
        return daily
    day_rows = intraday[intraday["date"].dt.date == target_date]
    if day_rows.empty:
        return daily
    last_time = day_rows["date"].max().time()
    if last_time < clock_time(15, 0):
        return daily
    close = float(day_rows.iloc[-1]["close"])
    if quote.close is None or abs(close - quote.close) / max(abs(quote.close), 0.01) > 0.003:
        return daily
    bar = {
        "date": pd.Timestamp(target_date),
        "open": float(day_rows.iloc[0]["open"]),
        "high": float(day_rows["high"].max()),
        "low": float(day_rows["low"].min()),
        "close": quote.close,
        "volume": quote.volume if quote.volume is not None else float(day_rows["volume"].sum()),
        "amount": quote.amount if quote.amount is not None else float(day_rows["amount"].sum()),
        "pct_change": quote.pct_change,
        "turnover_rate": quote.turnover_rate,
    }
    combined = pd.concat([daily, pd.DataFrame([bar])], ignore_index=True)
    return normalize_ohlcv(combined)


class LiveDataSource:
    def __init__(self, *, timeout: float = 12.0) -> None:
        self.client = HttpClient(timeout=timeout)

    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle:
        bundle = StockBundle(config=config)
        quote: Quote | None = None
        intraday = pd.DataFrame()
        try:
            quote = fetch_tencent_quote(self.client, config)
            bundle.source_status.append({"source": "腾讯行情", "ok": True, "date": str(quote.data_date)})
        except Exception as exc:
            bundle.source_status.append({"source": "腾讯行情", "ok": False, "error": _short_error(exc)})
        bundle.quote = quote

        try:
            intraday = fetch_eastmoney_kline(
                self.client, config.secid, period=60, limit=240, target_date=target_date
            )
            bundle.source_status.append(
                {
                    "source": "东方财富60分钟",
                    "ok": not intraday.empty,
                    "date": None if intraday.empty else str(intraday["date"].max()),
                }
            )
        except Exception as exc:
            bundle.source_status.append({"source": "东方财富60分钟", "ok": False, "error": _short_error(exc)})
        bundle.intraday_60m = intraday

        candidates: list[tuple[str, pd.DataFrame]] = []
        source_calls = (
            (
                "东方财富日线",
                lambda: fetch_eastmoney_kline(
                    self.client, config.secid, period=101, limit=360, target_date=target_date
                ),
            ),
            ("腾讯日线", lambda: fetch_tencent_daily(self.client, config.symbol, target_date=target_date)),
            ("网易日线", lambda: fetch_netease_daily(self.client, config, target_date=target_date)),
        )
        for source_name, loader in source_calls:
            try:
                frame = loader()
                if not frame.empty:
                    frame = normalize_ohlcv(frame)
                    candidates.append((source_name, frame))
                bundle.source_status.append(
                    {
                        "source": source_name,
                        "ok": not frame.empty,
                        "date": None if frame.empty else frame["date"].max().date().isoformat(),
                        "rows": len(frame),
                    }
                )
            except Exception as exc:
                bundle.source_status.append({"source": source_name, "ok": False, "error": _short_error(exc)})
            if candidates and candidates[-1][1]["date"].max().date() == target_date and len(candidates[-1][1]) >= 220:
                if len(candidates) >= 2:
                    break

        chosen_name = ""
        chosen = pd.DataFrame()
        for name, frame in candidates:
            if len(frame) >= 220 and frame["date"].max().date() == target_date:
                chosen_name, chosen = name, frame
                break
        if chosen.empty and candidates:
            chosen_name, chosen = max(candidates, key=lambda pair: len(pair[1]))
            if quote is not None:
                chosen = _append_completed_bar(chosen, intraday, quote, target_date)
                if not chosen.empty and chosen["date"].max().date() == target_date:
                    chosen_name += "+腾讯收盘+60分钟合成"

        bundle.daily = chosen
        bundle.last_data_date = None if chosen.empty else chosen["date"].max().date()
        bundle.valid_for_target = bool(
            not chosen.empty and len(chosen) >= 220 and bundle.last_data_date == target_date
        )
        if bundle.valid_for_target:
            bundle.core_sources.append(chosen_name)
            target_closes = [
                float(frame.loc[frame["date"].dt.date == target_date, "close"].iloc[-1])
                for _, frame in candidates
                if not frame.empty and (frame["date"].dt.date == target_date).any()
            ]
            if quote is not None and quote.data_date == target_date and quote.close is not None:
                target_closes.append(float(quote.close))
                bundle.core_sources.append(quote.source)
            disagreement = False
            if len(target_closes) >= 2:
                disagreement = (max(target_closes) - min(target_closes)) / max(abs(np.mean(target_closes)), 0.01) > 0.003
            bundle.data_confidence = "medium" if disagreement or len(target_closes) < 2 else "high"
            if disagreement:
                bundle.source_status.append(
                    {"source": "交叉校验", "ok": False, "error": "收盘价跨源差异超过0.3%"}
                )
        else:
            bundle.data_confidence = "low"

        for label, loader, setter in (
            ("东方财富财务", lambda: fetch_financials(self.client, config), "financials"),
            (
                "东方财富公告",
                lambda: fetch_announcements(self.client, config, target_date=target_date),
                "announcements",
            ),
            (
                "东方财富资金流",
                lambda: fetch_fund_flow(self.client, config, target_date=target_date),
                "fund_flow",
            ),
        ):
            try:
                value = loader()
                setattr(bundle, setter, value)
                bundle.source_status.append({"source": label, "ok": bool(value)})
            except Exception as exc:
                bundle.source_status.append({"source": label, "ok": False, "error": _short_error(exc)})
        return bundle

    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]:
        result: dict[str, Any] = {
            "data_date": target_date.isoformat(),
            "indices": [],
            "total_amount": None,
            "breadth": {},
            "industry_table": [],
            "source_status": [],
        }
        index_items = (
            ("000001", "上证指数", "1.000001"),
            ("399001", "深证成指", "0.399001"),
            ("399006", "创业板指", "0.399006"),
        )
        for code, name, secid in index_items:
            try:
                frame = fetch_eastmoney_kline(
                    self.client, secid, period=101, limit=5, target_date=target_date
                )
                row = frame.iloc[-1]
                result["indices"].append(
                    {
                        "code": code,
                        "name": name,
                        "date": row["date"].date().isoformat(),
                        "close": float(row["close"]),
                        "pct_change": float(row["pct_change"]),
                        "amount": _number(row.get("amount")),
                        "source": "东方财富日线",
                    }
                )
            except Exception as exc:
                result["source_status"].append(
                    {"source": f"{name}行情", "ok": False, "error": _short_error(exc)}
                )
        try:
            spot = fetch_market_spot(self.client)
            if not spot.empty:
                result["total_amount"] = float(spot["amount"].fillna(0).sum())
                valid_pct = spot["pct_change"].dropna()
                result["breadth"] = {
                    "up": int((valid_pct > 0).sum()),
                    "down": int((valid_pct < 0).sum()),
                    "flat": int((valid_pct == 0).sum()),
                    "median_pct": float(valid_pct.median()) if not valid_pct.empty else None,
                }
                industry = (
                    spot.dropna(subset=["industry", "pct_change"])
                    .groupby("industry", as_index=False)
                    .agg(pct_change=("pct_change", "median"), amount=("amount", "sum"), count=("code", "count"))
                    .sort_values("pct_change", ascending=False)
                )
                result["industry_table"] = industry.to_dict("records")
                result["source_status"].append(
                    {"source": "东方财富全市场行情", "ok": True, "rows": len(spot)}
                )
        except Exception as exc:
            result["source_status"].append(
                {"source": "东方财富全市场行情", "ok": False, "error": _short_error(exc)}
            )
        return result


def _short_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:240]}"
