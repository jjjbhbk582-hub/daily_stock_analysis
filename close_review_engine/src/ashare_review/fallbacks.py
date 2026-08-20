from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from ashare_review.config import StockConfig
from ashare_review.data import HttpClient, LiveDataSource, StockBundle
from ashare_review.indicators import normalize_ohlcv

_TENCENT_INDEX_SYMBOLS = (
    ("sh000001", "000001", "上证指数"),
    ("sz399001", "399001", "深证成指"),
    ("sz399006", "399006", "创业板指"),
)
_TENCENT_TURNOVER_SYMBOLS = ("sh000001", "sz399106")
_SINA_MARKET_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/"
    "api/json_v2.php/Market_Center.getHQNodeData"
)
_SINA_INDUSTRY_URL = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
_SINA_MINUTE_URL = (
    "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
    "CN_MarketDataService.getKLineData"
)
_MIN_FULL_MARKET_ROWS = 3_000


def _number(value: Any, *, scale: float = 1.0) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        result = float(value) / scale
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _short_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {text[:240]}"


def _parse_datetime(value: Any) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in (
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return pd.Timestamp(datetime.strptime(text, pattern))
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _standard_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = normalize_ohlcv(frame)
    preferred = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "pct_change",
    ]
    return normalized[[column for column in preferred if column in normalized.columns]]


def _parse_tencent_quote_lines(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for match in re.finditer(r'v_([^=]+)="([^"]*)";?', text):
        result[match.group(1)] = match.group(2).split("~")
    return result


def _tencent_amount(fields: list[str]) -> float | None:
    if len(fields) > 35 and fields[35]:
        pieces = fields[35].split("/")
        if len(pieces) >= 3:
            precise = _number(pieces[2])
            if precise is not None:
                return precise
    if len(fields) > 37:
        fallback = _number(fields[37])
        if fallback is not None:
            return fallback * 10_000
    return None


def fetch_tencent_intraday(
    client: HttpClient,
    symbol: str,
    *,
    limit: int = 320,
) -> pd.DataFrame:
    payload = client.get_json(
        "https://web.ifzq.gtimg.cn/appstock/app/kline/mkline",
        params={"param": f"{symbol},m60,{limit}"},
    )
    data = payload.get("data")
    item = data.get(symbol) if isinstance(data, dict) else None
    rows = item.get("m60") if isinstance(item, dict) else None
    records: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, list) or len(row) < 6:
            continue
        timestamp = _parse_datetime(row[0])
        if timestamp is None:
            continue
        records.append(
            {
                "date": timestamp,
                "open": row[1],
                "high": row[3],
                "low": row[4],
                "close": row[2],
                "volume": row[5],
                "amount": row[6] if len(row) > 6 else None,
            }
        )
    return _standard_intraday(pd.DataFrame(records))


def fetch_sina_intraday(
    client: HttpClient,
    symbol: str,
    *,
    limit: int = 1_970,
) -> pd.DataFrame:
    text = client.get_text(
        _SINA_MINUTE_URL,
        params={
            "symbol": symbol,
            "scale": "60",
            "ma": "no",
            "datalen": str(limit),
        },
        encoding="utf-8",
    )
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("Sina minute payload missing JSON array")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("Sina minute payload is not a list")
    records: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        timestamp = _parse_datetime(item.get("day") or item.get("date"))
        if timestamp is None:
            continue
        records.append(
            {
                "date": timestamp,
                "open": item.get("open"),
                "high": item.get("high"),
                "low": item.get("low"),
                "close": item.get("close"),
                "volume": item.get("volume"),
                "amount": item.get("amount"),
            }
        )
    return _standard_intraday(pd.DataFrame(records))


def fetch_tencent_market_indices(
    client: HttpClient,
    *,
    target_date: date,
) -> dict[str, Any]:
    symbols = [item[0] for item in _TENCENT_INDEX_SYMBOLS]
    symbols.extend(symbol for symbol in _TENCENT_TURNOVER_SYMBOLS if symbol not in symbols)
    text = client.get_text(
        "https://qt.gtimg.cn/q",
        params={"q": ",".join(symbols)},
        encoding="gbk",
    )
    parsed = _parse_tencent_quote_lines(text)
    indices: list[dict[str, Any]] = []
    for symbol, code, fallback_name in _TENCENT_INDEX_SYMBOLS:
        fields = parsed.get(symbol)
        if not fields or len(fields) < 35:
            continue
        timestamp = _parse_datetime(fields[30] if len(fields) > 30 else "")
        if timestamp is None or timestamp.date() != target_date:
            continue
        close = _number(fields[3] if len(fields) > 3 else None)
        previous_close = _number(fields[4] if len(fields) > 4 else None)
        pct_change = _number(fields[32] if len(fields) > 32 else None)
        if pct_change is None and close is not None and previous_close not in (None, 0):
            pct_change = (close / previous_close - 1) * 100
        indices.append(
            {
                "code": code,
                "name": fields[1] if len(fields) > 1 and fields[1] else fallback_name,
                "date": target_date.isoformat(),
                "close": close,
                "pct_change": None if pct_change is None else round(pct_change, 4),
                "amount": _tencent_amount(fields),
                "source": "腾讯行情",
            }
        )

    turnover_amounts: list[float] = []
    for symbol in _TENCENT_TURNOVER_SYMBOLS:
        fields = parsed.get(symbol)
        if not fields:
            continue
        timestamp = _parse_datetime(fields[30] if len(fields) > 30 else "")
        if timestamp is None or timestamp.date() != target_date:
            continue
        amount = _tencent_amount(fields)
        if amount is not None:
            turnover_amounts.append(amount)
    total_amount = (
        sum(turnover_amounts)
        if len(turnover_amounts) == len(_TENCENT_TURNOVER_SYMBOLS)
        else None
    )
    return {"indices": indices, "total_amount": total_amount}


def parse_sina_industry_payload(text: str) -> list[dict[str, Any]]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for raw in payload.values():
        fields = str(raw).split(",")
        if len(fields) < 8:
            continue
        name = fields[1].strip()
        pct_change = _number(fields[5])
        if not name or pct_change is None:
            continue
        rows.append(
            {
                "industry": name,
                "pct_change": pct_change,
                "amount": _number(fields[7]),
                "count": int(_number(fields[2]) or 0),
                "source": "新浪行业行情",
            }
        )
    return sorted(rows, key=lambda row: float(row["pct_change"]), reverse=True)


def parse_sina_market_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or row.get("code") or "").strip()
        code = symbol[2:] if symbol.lower().startswith(("sh", "sz", "bj")) else symbol
        records.append(
            {
                "code": code,
                "name": str(row.get("name") or "").strip(),
                "close": row.get("trade", row.get("close")),
                "pct_change": row.get("changepercent", row.get("pct_change")),
                "amount": row.get("amount"),
                "turnover_rate": row.get("turnoverratio", row.get("turnover_rate")),
            }
        )
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    for column in ("close", "pct_change", "amount", "turnover_rate"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["code", "pct_change"])
        .drop_duplicates("code", keep="last")
        .reset_index(drop=True)
    )


def _get_sina_json_rows(
    client: HttpClient,
    *,
    page: int,
    page_size: int,
) -> list[dict[str, Any]]:
    text = client.get_text(
        _SINA_MARKET_URL,
        params={
            "page": page,
            "num": page_size,
            "sort": "symbol",
            "asc": 1,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page",
        },
        encoding="utf-8",
    ).strip()
    if not text:
        return []
    payload = json.loads(text)
    return payload if isinstance(payload, list) else []


def fetch_sina_market_spot(client: HttpClient) -> pd.DataFrame:
    first = _get_sina_json_rows(client, page=1, page_size=5_000)
    if not first:
        return pd.DataFrame()

    pages: list[list[dict[str, Any]]]
    if len(first) >= _MIN_FULL_MARKET_ROWS:
        pages = [first]
        page = 2
        while len(pages[-1]) >= 5_000 and page <= 4:
            rows = _get_sina_json_rows(client, page=page, page_size=5_000)
            if not rows:
                break
            pages.append(rows)
            page += 1
    else:
        pages = []
        page = 1
        while page <= 80:
            rows = _get_sina_json_rows(client, page=page, page_size=100)
            if not rows:
                break
            pages.append(rows)
            if len(rows) < 100:
                break
            page += 1
        if page > 80 and pages and len(pages[-1]) == 100:
            raise RuntimeError("新浪全市场行情分页未结束，拒绝将不完整样本冒充全市场")

    frame = parse_sina_market_rows([row for page_rows in pages for row in page_rows])
    if len(frame) < _MIN_FULL_MARKET_ROWS:
        raise RuntimeError(
            f"新浪全市场行情仅返回{len(frame)}只，不足以代表完整A股市场"
        )
    return frame


def fetch_sina_industries(client: HttpClient) -> list[dict[str, Any]]:
    text = client.get_text(
        _SINA_INDUSTRY_URL,
        params={"param": "industry"},
        encoding="gbk",
    )
    return parse_sina_industry_payload(text)


def _merge_indices(
    existing: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
    *,
    target_date: date,
) -> list[dict[str, Any]]:
    by_code = {
        str(item.get("code")): item
        for item in existing
        if item.get("date") == target_date.isoformat()
    }
    for item in fallback:
        code = str(item.get("code") or "")
        if code and item.get("date") == target_date.isoformat() and code not in by_code:
            by_code[code] = item
    order = [item[1] for item in _TENCENT_INDEX_SYMBOLS]
    return [by_code[code] for code in order if code in by_code]


def _breadth(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame["pct_change"].dropna()
    return {
        "up": int((valid > 0).sum()),
        "down": int((valid < 0).sum()),
        "flat": int((valid == 0).sum()),
        "median_pct": float(valid.median()) if not valid.empty else None,
    }


def _eastmoney_market_row_count(result: dict[str, Any]) -> int | None:
    counts: list[int] = []
    for item in result.get("source_status", []):
        if item.get("source") != "东方财富全市场行情":
            continue
        try:
            counts.append(int(item.get("rows") or 0))
        except (TypeError, ValueError):
            continue
    breadth = result.get("breadth") or {}
    try:
        breadth_count = sum(int(breadth.get(key) or 0) for key in ("up", "down", "flat"))
    except (TypeError, ValueError):
        breadth_count = 0
    if breadth_count:
        counts.append(breadth_count)
    return max(counts) if counts else None


def _invalidate_incomplete_eastmoney_market(result: dict[str, Any]) -> None:
    row_count = _eastmoney_market_row_count(result)
    if row_count is None or row_count >= _MIN_FULL_MARKET_ROWS:
        return
    result["total_amount"] = None
    result["breadth"] = {}
    result["industry_table"] = []
    result.setdefault("source_status", []).append(
        {
            "source": "东方财富全市场完整性校验",
            "ok": False,
            "rows": row_count,
            "error": (
                f"仅返回{row_count}只股票，低于完整性阈值"
                f"{_MIN_FULL_MARKET_ROWS}，未将局部样本冒充全市场"
            ),
        }
    )


class ResilientLiveDataSource(LiveDataSource):
    def load_stock(self, config: StockConfig, target_date: date) -> StockBundle:
        bundle = super().load_stock(config, target_date)
        if len(bundle.intraday_60m) >= 26:
            return bundle

        intraday_sources = (
            (
                "腾讯60分钟",
                lambda: fetch_tencent_intraday(self.client, config.symbol, limit=320),
            ),
            (
                "新浪60分钟",
                lambda: fetch_sina_intraday(self.client, config.symbol, limit=1_970),
            ),
        )
        for source_name, loader in intraday_sources:
            try:
                frame = loader()
                if not frame.empty:
                    frame = frame[frame["date"].dt.date <= target_date].reset_index(drop=True)
                usable = len(frame) >= 26
                if usable:
                    bundle.intraday_60m = frame
                bundle.source_status.append(
                    {
                        "source": source_name,
                        "ok": usable,
                        "date": None if frame.empty else str(frame["date"].max()),
                        "rows": len(frame),
                    }
                )
                if usable:
                    break
            except Exception as exc:  # noqa: BLE001
                bundle.source_status.append(
                    {"source": source_name, "ok": False, "error": _short_error(exc)}
                )
        return bundle

    def load_market(self, stocks: list[StockConfig], target_date: date) -> dict[str, Any]:
        result = super().load_market(stocks, target_date)
        _invalidate_incomplete_eastmoney_market(result)

        valid_indices = [
            item
            for item in result.get("indices", [])
            if item.get("date") == target_date.isoformat()
        ]
        result["indices"] = valid_indices
        if len(valid_indices) < 3 or result.get("total_amount") is None:
            try:
                fallback = fetch_tencent_market_indices(self.client, target_date=target_date)
                result["indices"] = _merge_indices(
                    result.get("indices", []),
                    fallback.get("indices", []),
                    target_date=target_date,
                )
                if result.get("total_amount") is None and fallback.get("total_amount") is not None:
                    result["total_amount"] = float(fallback["total_amount"])
                result["source_status"].append(
                    {
                        "source": "腾讯指数与两市成交额",
                        "ok": len(fallback.get("indices", [])) > 0,
                        "indices": len(fallback.get("indices", [])),
                        "total_amount": fallback.get("total_amount"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                result["source_status"].append(
                    {
                        "source": "腾讯指数与两市成交额",
                        "ok": False,
                        "error": _short_error(exc),
                    }
                )

        if not result.get("breadth") or result.get("total_amount") is None:
            try:
                spot = fetch_sina_market_spot(self.client)
                if not spot.empty:
                    if result.get("total_amount") is None:
                        result["total_amount"] = float(spot["amount"].fillna(0).sum())
                    result["breadth"] = _breadth(spot)
                result["source_status"].append(
                    {"source": "新浪全市场行情", "ok": not spot.empty, "rows": len(spot)}
                )
            except Exception as exc:  # noqa: BLE001
                result["source_status"].append(
                    {"source": "新浪全市场行情", "ok": False, "error": _short_error(exc)}
                )

        if not result.get("industry_table"):
            try:
                industries = fetch_sina_industries(self.client)
                if industries:
                    result["industry_table"] = industries
                result["source_status"].append(
                    {"source": "新浪行业行情", "ok": bool(industries), "rows": len(industries)}
                )
            except Exception as exc:  # noqa: BLE001
                result["source_status"].append(
                    {"source": "新浪行业行情", "ok": False, "error": _short_error(exc)}
                )
        return result
