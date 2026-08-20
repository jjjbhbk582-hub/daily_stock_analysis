from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime
from difflib import SequenceMatcher
from math import ceil
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ashare_review.data import HttpClient
from ashare_review.indicators import finite, normalize_ohlcv
from ashare_review.sector_config import FocusConcept

SHANGHAI = ZoneInfo("Asia/Shanghai")
BOARD_LIST_HOSTS = (
    "https://79.push2.eastmoney.com/api/qt/clist/get",
    "https://17.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
BOARD_HISTORY_HOSTS = (
    "https://91.push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
)
BOARD_CONSTITUENT_HOSTS = (
    "https://29.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
SINA_BOARD_LIST_URL = "https://money.finance.sina.com.cn/q/view/newFLJK.php"
SINA_NODE_DATA_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_NODE_COUNT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)
SINA_PAGE_SIZE = 80

_BOARD_ALIASES: dict[str, tuple[str, ...]] = {
    "医药生物": ("医药制造业", "生物制品", "医药"),
    "医疗服务": ("医疗服务", "卫生"),
    "生物制品": ("生物制品", "医药制造业"),
    "贵金属": ("贵金属", "有色金属矿采选业"),
    "通信设备": ("通信设备", "计算机通信和其他电子设备制造业"),
    "电子元件": ("电子元件", "元件", "计算机通信和其他电子设备制造业"),
    "半导体": ("半导体", "芯片", "计算机通信和其他电子设备制造业"),
    "有色金属": ("有色金属", "有色金属冶炼和压延加工业"),
    "小金属": ("小金属", "有色金属"),
}


def _as_int(value: Any) -> int:
    numeric = finite(value, 0.0) or 0.0
    return int(numeric)


def _board_data_date(item: dict[str, Any], target_date: date) -> date:
    explicit = item.get("data_date")
    if explicit:
        parsed = pd.to_datetime(explicit, errors="coerce")
        if not pd.isna(parsed):
            return parsed.date()
    raw_timestamp = finite(item.get("f124"))
    if raw_timestamp is None or raw_timestamp <= 0:
        return target_date
    if raw_timestamp > 10_000_000_000:
        raw_timestamp /= 1000
    try:
        return datetime.fromtimestamp(raw_timestamp, tz=SHANGHAI).date()
    except (OverflowError, OSError, ValueError):
        return target_date


def normalize_board_overview(
    rows: Iterable[dict[str, Any]],
    board_type: str,
    target_date: date,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in rows:
        code = str(item.get("board_code") or item.get("f12") or "").strip()
        name = str(item.get("board_name") or item.get("f14") or "").strip()
        if not code or not name:
            continue
        source_date = _board_data_date(item, target_date)
        output.append(
            {
                "board_code": code,
                "board_name": name,
                "board_type": board_type,
                "latest": finite(item.get("latest", item.get("f2"))),
                "pct_change": finite(item.get("pct_change", item.get("f3"))),
                "amount": finite(item.get("amount", item.get("f6"))),
                "turnover_rate": finite(item.get("turnover_rate", item.get("f8"))),
                "market_cap": finite(item.get("market_cap", item.get("f20"))),
                "up_count": _as_int(item.get("up_count", item.get("f104"))),
                "down_count": _as_int(item.get("down_count", item.get("f105"))),
                "limit_up_count": _as_int(item.get("limit_up_count", 0)),
                "leader_name": str(item.get("leader_name") or item.get("f128") or "").strip(),
                "leader_pct_change": finite(
                    item.get("leader_pct_change", item.get("f136"))
                ),
                "data_date": source_date.isoformat(),
                "source": str(item.get("source") or "东方财富板块行情"),
            }
        )
    return output


def normalize_board_constituents(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in rows:
        code = str(item.get("code") or item.get("f12") or "").strip().zfill(6)
        name = str(item.get("name") or item.get("f14") or "").strip()
        if not code or not name:
            continue
        output.append(
            {
                "code": code,
                "name": name,
                "close": finite(item.get("close", item.get("f2"))),
                "pct_change": finite(item.get("pct_change", item.get("f3"))),
                "volume": finite(item.get("volume", item.get("f5"))),
                "amount": finite(item.get("amount", item.get("f6"))),
                "turnover_rate": finite(item.get("turnover_rate", item.get("f8"))),
                "high": finite(item.get("high", item.get("f15"))),
                "low": finite(item.get("low", item.get("f16"))),
                "open": finite(item.get("open", item.get("f17"))),
                "previous_close": finite(item.get("previous_close", item.get("f18"))),
                "market_cap": finite(item.get("market_cap", item.get("f20"))),
                "float_market_cap": finite(
                    item.get("float_market_cap", item.get("f21"))
                ),
                "source": str(item.get("source") or "东方财富板块成份"),
            }
        )
    return output


def _fetch_paginated(
    client: HttpClient,
    hosts: tuple[str, ...],
    params: dict[str, Any],
    *,
    max_pages: int,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    page_size = int(params["pz"])
    for host in hosts:
        collected: list[dict[str, Any]] = []
        try:
            for page in range(1, max_pages + 1):
                page_params = dict(params)
                page_params["pn"] = page
                payload = client.get_json(host, params=page_params)
                data = payload.get("data")
                rows = data.get("diff") if isinstance(data, dict) else None
                if not isinstance(rows, list) or not rows:
                    break
                collected.extend(item for item in rows if isinstance(item, dict))
                total = _as_int(data.get("total")) if isinstance(data, dict) else 0
                if total > 0 and len(collected) >= total:
                    break
                if total <= 0 and len(rows) < page_size:
                    break
            if collected:
                return collected
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _sina_board_parameter(board_type: str) -> str:
    if board_type == "industry":
        return "industry"
    if board_type == "concept":
        return "class"
    raise ValueError(f"unsupported board type: {board_type}")


def _fetch_sina_board_overview(
    client: HttpClient,
    board_type: str,
    target_date: date,
) -> list[dict[str, Any]]:
    response = client.session.get(
        SINA_BOARD_LIST_URL,
        params={"param": _sina_board_parameter(board_type)},
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
                "board_code": label,
                "board_name": name,
                "board_type": board_type,
                "latest": finite(fields[3]),
                "pct_change": finite(fields[5]),
                "amount": finite(fields[7]),
                "turnover_rate": None,
                "market_cap": None,
                "up_count": 0,
                "down_count": 0,
                "limit_up_count": 0,
                "leader_name": fields[12].strip(),
                "leader_pct_change": finite(fields[9]),
                "data_date": target_date.isoformat(),
                "source": "新浪板块行情",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("pct_change") or -999),
            float(row.get("amount") or 0),
        ),
        reverse=True,
    )


def fetch_board_overview(
    client: HttpClient,
    board_type: str,
    target_date: date,
) -> list[dict[str, Any]]:
    if board_type not in {"industry", "concept"}:
        raise ValueError(f"unsupported board type: {board_type}")
    board_filter = "m:90 t:2 f:!50" if board_type == "industry" else "m:90 t:3 f:!50"
    eastmoney_error: Exception | None = None
    try:
        rows = _fetch_paginated(
            client,
            BOARD_LIST_HOSTS,
            {
                "pz": 100,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f12",
                "fs": board_filter,
                "fields": "f2,f3,f6,f8,f12,f14,f20,f104,f105,f124,f128,f136",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            },
            max_pages=8,
        )
        normalized = normalize_board_overview(rows, board_type, target_date)
        completed = [
            row for row in normalized if row.get("data_date") == target_date.isoformat()
        ]
        if completed:
            return completed
    except Exception as exc:  # noqa: BLE001
        eastmoney_error = exc

    try:
        fallback = _fetch_sina_board_overview(client, board_type, target_date)
        if fallback:
            return fallback
    except Exception as exc:  # noqa: BLE001
        if eastmoney_error is not None:
            raise RuntimeError(
                f"东方财富板块列表失败：{eastmoney_error}; 新浪板块列表失败：{exc}"
            ) from exc
        raise
    if eastmoney_error is not None:
        raise eastmoney_error
    return []


def _parse_board_history_rows(rows: Iterable[Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for raw in rows:
        fields = str(raw).split(",")
        if len(fields) < 7:
            continue
        records.append(
            {
                "date": fields[0],
                "open": fields[1],
                "close": fields[2],
                "high": fields[3],
                "low": fields[4],
                "volume": fields[5],
                "amount": fields[6],
                "amplitude": fields[7] if len(fields) > 7 else None,
                "pct_change": fields[8] if len(fields) > 8 else None,
                "change": fields[9] if len(fields) > 9 else None,
                "turnover_rate": fields[10] if len(fields) > 10 else None,
            }
        )
    frame = pd.DataFrame(records)
    return normalize_ohlcv(frame) if not frame.empty else frame


def fetch_board_history(
    client: HttpClient,
    board_code: str,
    target_date: date,
    *,
    limit: int = 45,
) -> pd.DataFrame:
    if not str(board_code).upper().startswith("BK"):
        return pd.DataFrame()
    last_error: Exception | None = None
    for host in BOARD_HISTORY_HOSTS:
        try:
            payload = client.get_json(
                host,
                params={
                    "secid": f"90.{board_code}",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "klt": 101,
                    "fqt": 0,
                    "beg": 0,
                    "end": target_date.strftime("%Y%m%d"),
                    "smplmt": 10000,
                    "lmt": limit,
                },
            )
            data = payload.get("data")
            rows = data.get("klines") if isinstance(data, dict) else None
            frame = _parse_board_history_rows(rows or [])
            if not frame.empty:
                return frame[frame["date"].dt.date <= target_date].reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.DataFrame()


def _sina_node_count(client: HttpClient, board_code: str) -> int:
    response = client.session.get(
        SINA_NODE_COUNT_URL,
        params={"node": board_code},
        headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
        timeout=client.timeout,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = response.text
    text = str(payload).strip().strip('"')
    return int(text) if text.isdigit() else 0


def _fetch_sina_board_constituents(
    client: HttpClient,
    board_code: str,
) -> list[dict[str, Any]]:
    total = _sina_node_count(client, board_code)
    if total <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for page in range(1, ceil(total / SINA_PAGE_SIZE) + 1):
        response = client.session.get(
            SINA_NODE_DATA_URL,
            params={
                "page": page,
                "num": SINA_PAGE_SIZE,
                "sort": "symbol",
                "asc": 1,
                "node": board_code,
                "symbol": "",
                "_s_r_a": "page",
            },
            headers={"Referer": "https://vip.stock.finance.sina.com.cn/"},
            timeout=client.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "code": item.get("code") or item.get("symbol"),
                    "name": item.get("name"),
                    "close": item.get("trade", item.get("close")),
                    "pct_change": item.get("changepercent", item.get("pct_change")),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "turnover_rate": item.get("turnoverratio", item.get("turnover_rate")),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "open": item.get("open"),
                    "previous_close": item.get("settlement", item.get("previous_close")),
                    "market_cap": item.get("mktcap", item.get("market_cap")),
                    "float_market_cap": item.get("nmc", item.get("float_market_cap")),
                    "source": "新浪板块成份",
                }
            )
    for item in rows:
        raw_code = str(item.get("code") or "").strip()
        if raw_code.lower().startswith(("sh", "sz", "bj")):
            item["code"] = raw_code[2:]
    return normalize_board_constituents(rows)


def _normalise_board_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"(?:概念|行业|板块|指数|Ⅱ|II)$", "", text)
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff]+", "", text)


def _board_name_candidates(board_name: str) -> tuple[str, ...]:
    values = [board_name, *_BOARD_ALIASES.get(board_name, ())]
    return tuple(dict.fromkeys(_normalise_board_name(value) for value in values if value))


def _sina_name_score(requested_name: str, candidate_name: str) -> float:
    requested = _board_name_candidates(requested_name)
    candidate = _normalise_board_name(candidate_name)
    if not requested or not candidate:
        return 0.0
    best = 0.0
    for term in requested:
        if candidate == term:
            score = 120.0
        elif len(term) >= 2 and term in candidate:
            score = 92.0 + min(len(term), 12)
        elif len(candidate) >= 2 and candidate in term:
            score = 82.0 + min(len(candidate), 12)
        else:
            score = SequenceMatcher(None, term, candidate).ratio() * 75.0
        best = max(best, score)
    return best


def _resolve_sina_board_label(
    client: HttpClient,
    *,
    board_type: str,
    board_name: str,
    target_date: date,
) -> str | None:
    search_types = (board_type, "concept" if board_type == "industry" else "industry")
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for index, current_type in enumerate(search_types):
        try:
            rows = _fetch_sina_board_overview(client, current_type, target_date)
        except Exception:  # noqa: BLE001
            continue
        for row in rows:
            score = _sina_name_score(board_name, str(row.get("board_name") or ""))
            if score >= 45:
                candidates.append((score, -index, row))
    if not candidates:
        return None
    _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
    return str(selected.get("board_code") or "") or None


def fetch_board_constituents(
    client: HttpClient,
    board_code: str,
    *,
    board_type: str | None = None,
    board_name: str | None = None,
    target_date: date | None = None,
) -> list[dict[str, Any]]:
    eastmoney_error: Exception | None = None
    if str(board_code).upper().startswith("BK"):
        try:
            rows = _fetch_paginated(
                client,
                BOARD_CONSTITUENT_HOSTS,
                {
                    "pz": 100,
                    "po": 1,
                    "np": 1,
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f12",
                    "fs": f"b:{board_code} f:!50",
                    "fields": "f2,f3,f5,f6,f8,f12,f14,f15,f16,f17,f18,f20,f21",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                },
                max_pages=12,
            )
            normalized = normalize_board_constituents(rows)
            if normalized:
                return normalized
        except Exception as exc:  # noqa: BLE001
            eastmoney_error = exc

    fallback_code = str(board_code)
    if (
        fallback_code.upper().startswith("BK")
        and board_type in {"industry", "concept"}
        and board_name
        and target_date is not None
    ):
        mapped = _resolve_sina_board_label(
            client,
            board_type=str(board_type),
            board_name=str(board_name),
            target_date=target_date,
        )
        if mapped:
            fallback_code = mapped

    try:
        fallback = _fetch_sina_board_constituents(client, fallback_code)
        if fallback:
            return fallback
    except Exception as exc:  # noqa: BLE001
        if eastmoney_error is not None:
            raise RuntimeError(
                f"东方财富板块成份失败：{eastmoney_error}; 新浪板块成份失败：{exc}"
            ) from exc
        raise
    if eastmoney_error is not None:
        raise eastmoney_error
    return []


def _focus_match_score(board_name: str, focus: FocusConcept) -> int:
    if board_name == focus.label:
        return 100
    score = 0
    for alias in focus.aliases:
        if board_name == alias:
            score = max(score, 90)
        elif alias and alias in board_name:
            score = max(score, 70 + min(len(alias), 10))
        elif board_name and board_name in alias:
            score = max(score, 50 + min(len(board_name), 10))
    return score


def match_focus_concepts(
    boards: Iterable[dict[str, Any]],
    focus_concepts: Iterable[FocusConcept],
) -> list[dict[str, Any]]:
    concept_rows = [row for row in boards if row.get("board_type") == "concept"]
    matched: list[dict[str, Any]] = []
    used_codes: set[str] = set()
    for focus in focus_concepts:
        candidates = []
        for row in concept_rows:
            code = str(row.get("board_code") or "")
            score = _focus_match_score(str(row.get("board_name") or ""), focus)
            if score > 0 and code not in used_codes:
                candidates.append(
                    (
                        score,
                        finite(row.get("pct_change"), -999.0) or -999.0,
                        row,
                    )
                )
        if not candidates:
            matched.append(
                {
                    "focus_label": focus.label,
                    "status": "data_unavailable",
                    "board_type": "concept",
                    "board_code": None,
                    "board_name": None,
                }
            )
            continue
        _, _, selected = max(candidates, key=lambda item: (item[0], item[1]))
        selected_copy = dict(selected)
        selected_copy["focus_label"] = focus.label
        selected_copy["status"] = "ready"
        matched.append(selected_copy)
        used_codes.add(str(selected.get("board_code") or ""))
    return matched
