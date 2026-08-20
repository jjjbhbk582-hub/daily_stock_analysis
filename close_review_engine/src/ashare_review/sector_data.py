from __future__ import annotations

import json
from math import ceil
from typing import Any

import pandas as pd

from ashare_review.config import StockConfig
from ashare_review.data import HttpClient, _number, _short_error
from ashare_review.enhanced_data import (
    SINA_INDUSTRY_URL,
    SINA_MARKET_COUNT_URL,
    SINA_MARKET_URL,
    ResilientLiveDataSource,
)

SINA_SECTOR_PAGE_SIZE = 80


def _sector_param(kind: str) -> str:
    if kind == "industry":
        return "industry"
    if kind == "concept":
        return "class"
    raise ValueError(f"unsupported sector kind: {kind}")


def fetch_sina_sector_boards(
    client: HttpClient,
    *,
    kind: str,
) -> list[dict[str, Any]]:
    response = client.session.get(
        SINA_INDUSTRY_URL,
        params={"param": _sector_param(kind)},
        headers={"Referer": "https://money.finance.sina.com.cn/"},
        timeout=client.timeout,
    )
    response.raise_for_status()
    response.encoding = "gbk"
    text = response.text
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
        if len(fields) < 13:
            continue
        label = fields[0].strip()
        name = fields[1].strip()
        if not label or not name:
            continue
        rows.append(
            {
                "label": label,
                "sector_name": name,
                "industry": name,
                "count": int(_number(fields[2]) or 0),
                "average_price": _number(fields[3]),
                "change": _number(fields[4]),
                "pct_change": _number(fields[5]),
                "volume": _number(fields[6]),
                "amount": _number(fields[7]),
                "leader_code": fields[8].strip(),
                "leader_pct_change": _number(fields[9]),
                "leader_price": _number(fields[10]),
                "leader_change": _number(fields[11]),
                "leader_name": fields[12].strip(),
                "source": "新浪板块行情",
            }
        )
    return sorted(
        rows,
        key=lambda row: float(row.get("pct_change") or 0),
        reverse=True,
    )


def _sector_count(client: HttpClient, label: str) -> int:
    response = client.session.get(
        SINA_MARKET_COUNT_URL,
        params={"node": label},
        headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
        timeout=client.timeout,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = response.text
    return int(str(payload).strip().strip('"'))


def fetch_sina_sector_constituents(
    client: HttpClient,
    label: str,
) -> pd.DataFrame:
    total = _sector_count(client, label)
    records: list[dict[str, Any]] = []
    for page in range(1, ceil(total / SINA_SECTOR_PAGE_SIZE) + 1):
        response = client.session.get(
            SINA_MARKET_URL,
            params={
                "page": page,
                "num": SINA_SECTOR_PAGE_SIZE,
                "sort": "symbol",
                "asc": 1,
                "node": label,
                "symbol": "",
                "_s_r_a": "page",
            },
            headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
            timeout=client.timeout,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            break
        records.extend(row for row in rows if isinstance(row, dict))

    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    frame = frame.rename(
        columns={
            "trade": "close",
            "changepercent": "pct_change",
            "turnoverratio": "turnover_rate",
            "mktcap": "market_cap",
            "nmc": "float_market_cap",
        }
    )
    if "code" not in frame.columns and "symbol" in frame.columns:
        frame["code"] = frame["symbol"].astype(str).str.replace(
            r"^(?:sh|sz|bj)",
            "",
            regex=True,
        )
    if "code" in frame.columns:
        frame["code"] = frame["code"].astype(str).str.extract(r"(\d{6})", expand=False)
    if "name" not in frame.columns:
        frame["name"] = ""
    for column in (
        "close",
        "pct_change",
        "open",
        "high",
        "low",
        "volume",
        "amount",
        "turnover_rate",
        "market_cap",
        "float_market_cap",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    required = ["code", "name", "close", "pct_change", "amount"]
    for column in required:
        if column not in frame.columns:
            frame[column] = pd.NA
    return (
        frame.dropna(subset=["code", "close"])
        .drop_duplicates("code", keep="last")
        .reset_index(drop=True)
    )


def stock_config_from_candidate(row: dict[str, Any], sector_name: str) -> StockConfig:
    code = str(row.get("code") or "").zfill(6)
    exchange = "SH" if code.startswith(("600", "601", "603", "605")) else "SZ"
    return StockConfig(
        code=code,
        name=str(row.get("name") or code),
        exchange=exchange,
        industry=sector_name,
        themes=(sector_name,),
        industry_logic=50.0,
    )


class SectorAwareLiveDataSource(ResilientLiveDataSource):
    def load_market(self, stocks: list[StockConfig], target_date) -> dict[str, Any]:
        result = super().load_market(stocks, target_date)
        for kind, key in (("industry", "sector_industries_raw"), ("concept", "sector_concepts_raw")):
            try:
                rows = fetch_sina_sector_boards(self.client, kind=kind)
                result[key] = rows
                result.setdefault("source_status", []).append(
                    {
                        "source": "新浪行业板块" if kind == "industry" else "新浪概念板块",
                        "ok": bool(rows),
                        "rows": len(rows),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                result[key] = []
                result.setdefault("source_status", []).append(
                    {
                        "source": "新浪行业板块" if kind == "industry" else "新浪概念板块",
                        "ok": False,
                        "error": _short_error(exc),
                    }
                )
        return result

    def load_sector_constituents(
        self,
        sectors: list[dict[str, Any]],
    ) -> dict[str, pd.DataFrame]:
        output: dict[str, pd.DataFrame] = {}
        for sector in sectors:
            sector_id = str(sector.get("sector_id") or "")
            label = str(sector.get("label") or "")
            if not sector_id or not label:
                continue
            try:
                output[sector_id] = fetch_sina_sector_constituents(self.client, label)
            except Exception:  # noqa: BLE001
                output[sector_id] = pd.DataFrame()
        return output
