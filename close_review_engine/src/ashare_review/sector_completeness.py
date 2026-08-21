from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from ashare_review.data import HttpClient, fetch_tencent_daily
from ashare_review.indicators import finite
from ashare_review.sector_analysis import score_board

# These baskets are not presented as official concept indices. They are a
# transparent fallback for modern themes that are absent from Sina's older
# concept taxonomy. Every member is rechecked against the completed target-day
# close, and members above RMB 100 are excluded from the proxy calculation.
FOCUS_PROXY_BASKETS: dict[str, tuple[str, ...]] = {
    "AI算力": ("000977", "603019", "000938", "000063", "600845", "002230"),
    "CPO": ("000063", "600105", "002130", "600487", "600498"),
    "PCB": ("002384", "002436", "002938", "603228", "603920", "002463"),
    "半导体": ("002156", "600584", "600460", "002185", "600745", "603005"),
    "存储芯片": ("000021", "600460", "002156", "002185", "603986"),
    "稀土": ("600111", "000831", "600392", "600259", "000970"),
    "液冷服务器": ("000977", "603019", "000938", "600845", "002837"),
}


def _symbol_for_code(code: str) -> str | None:
    normalized = str(code).strip().zfill(6)
    if normalized.startswith("6"):
        return f"sh{normalized}"
    if normalized.startswith(("0", "3")):
        return f"sz{normalized}"
    return None


def _limit_threshold(code: str, name: str) -> float:
    normalized = str(code).strip().zfill(6)
    upper_name = str(name).upper()
    if "ST" in upper_name:
        return 4.8
    if normalized.startswith(("300", "301", "688")):
        return 19.5
    if normalized.startswith(("4", "8")):
        return 29.5
    return 9.5


def enrich_board_from_constituents(
    board: Mapping[str, Any],
    constituents: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in constituents]
    valid = [row for row in rows if finite(row.get("pct_change")) is not None]
    result = dict(board)
    if not valid:
        result.setdefault("breadth_source", "板块成份股数据暂缺")
        result.setdefault("breadth_confidence", "low")
        return result

    up = sum((finite(row.get("pct_change"), 0.0) or 0.0) > 0 for row in valid)
    down = sum((finite(row.get("pct_change"), 0.0) or 0.0) < 0 for row in valid)
    flat = len(valid) - up - down
    limit_up = sum(
        (finite(row.get("pct_change"), 0.0) or 0.0)
        >= _limit_threshold(str(row.get("code") or ""), str(row.get("name") or ""))
        for row in valid
    )
    leader = max(
        valid,
        key=lambda row: finite(row.get("pct_change"), -999.0) or -999.0,
    )
    constituent_amount = sum(finite(row.get("amount"), 0.0) or 0.0 for row in valid)

    result.update(
        {
            "up_count": int(up),
            "down_count": int(down),
            "flat_count": int(flat),
            "limit_up_count": int(limit_up),
            "constituent_count": len(valid),
            "constituent_amount": float(constituent_amount),
            "leader_name": str(leader.get("name") or result.get("leader_name") or ""),
            "leader_pct_change": finite(leader.get("pct_change")),
            "breadth_source": "板块成份股收盘快照",
            "breadth_confidence": "high" if len(valid) >= 8 else "partial",
        }
    )
    if finite(result.get("amount")) in (None, 0) and constituent_amount > 0:
        result["amount"] = float(constituent_amount)
    return result


def _prepare_history(frame: pd.DataFrame, target_date: date) -> pd.DataFrame:
    if frame.empty or "date" not in frame or "close" not in frame:
        return pd.DataFrame()
    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce")
    prepared = prepared.dropna(subset=["date", "close"])
    prepared = prepared[prepared["date"].dt.date <= target_date]
    prepared = prepared.sort_values("date").drop_duplicates("date", keep="last").tail(45)
    if len(prepared) < 21:
        return pd.DataFrame()
    prepared["close"] = pd.to_numeric(prepared["close"], errors="coerce")
    prepared = prepared.dropna(subset=["close"])
    if len(prepared) < 21 or float(prepared.iloc[0]["close"]) <= 0:
        return pd.DataFrame()
    if "amount" not in prepared:
        prepared["amount"] = np.nan
    prepared["amount"] = pd.to_numeric(prepared["amount"], errors="coerce")
    if "volume" in prepared:
        volume = pd.to_numeric(prepared["volume"], errors="coerce")
        prepared["amount"] = prepared["amount"].fillna(prepared["close"] * volume)
    prepared["amount"] = prepared["amount"].fillna(0.0)
    return prepared.reset_index(drop=True)


def aggregate_proxy_history(
    histories: Mapping[str, pd.DataFrame],
    *,
    target_date: date,
) -> pd.DataFrame:
    close_columns: list[pd.Series] = []
    amount_columns: list[pd.Series] = []
    used_codes: list[str] = []
    for code, raw in histories.items():
        frame = _prepare_history(raw, target_date)
        if frame.empty:
            continue
        indexed = frame.set_index("date")
        base = float(indexed.iloc[0]["close"])
        close_columns.append((indexed["close"] / base * 100).rename(str(code)))
        amount_columns.append(indexed["amount"].rename(str(code)))
        used_codes.append(str(code))
    if not close_columns:
        return pd.DataFrame()

    close_matrix = pd.concat(close_columns, axis=1).sort_index()
    amount_matrix = pd.concat(amount_columns, axis=1).reindex(close_matrix.index)
    minimum_components = 1 if len(used_codes) == 1 else 2
    valid_count = close_matrix.notna().sum(axis=1)
    output = pd.DataFrame(
        {
            "date": close_matrix.index,
            "close": close_matrix.mean(axis=1, skipna=True),
            "amount": amount_matrix.sum(axis=1, min_count=1),
        }
    )
    output = output[valid_count >= minimum_components].dropna(subset=["close"])
    output = output.reset_index(drop=True)
    output.attrs["source"] = "腾讯成份股等权代理历史"
    output.attrs["component_count"] = len(used_codes)
    output.attrs["component_codes"] = used_codes
    return output


def fetch_tencent_histories(
    client: HttpClient,
    codes: Iterable[str],
    *,
    target_date: date,
    max_workers: int = 6,
    max_price: float | None = None,
) -> dict[str, pd.DataFrame]:
    unique = tuple(dict.fromkeys(str(code).strip().zfill(6) for code in codes))

    def load(code: str) -> tuple[str, pd.DataFrame]:
        symbol = _symbol_for_code(code)
        if symbol is None:
            return code, pd.DataFrame()
        frame = fetch_tencent_daily(client, symbol, target_date=target_date, limit=60)
        prepared = _prepare_history(frame, target_date)
        if prepared.empty:
            return code, prepared
        if prepared.iloc[-1]["date"].date() != target_date:
            return code, pd.DataFrame()
        if max_price is not None and float(prepared.iloc[-1]["close"]) > max_price:
            return code, pd.DataFrame()
        if "pct_change" not in prepared:
            prepared["pct_change"] = prepared["close"].pct_change() * 100
        return code, prepared

    output: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as executor:
        futures = {executor.submit(load, code): code for code in unique}
        for future in as_completed(futures):
            code = futures[future]
            try:
                loaded_code, frame = future.result()
                if not frame.empty:
                    output[loaded_code] = frame
            except Exception:  # noqa: BLE001
                output[code] = pd.DataFrame()
    return output


def _last_pct(frame: pd.DataFrame) -> float | None:
    prepared = frame.sort_values("date").reset_index(drop=True)
    if prepared.empty:
        return None
    value = finite(prepared.iloc[-1].get("pct_change"))
    if value is not None:
        return value
    if len(prepared) < 2:
        return None
    previous = finite(prepared.iloc[-2].get("close"))
    current = finite(prepared.iloc[-1].get("close"))
    if previous in (None, 0) or current is None:
        return None
    return (current / previous - 1) * 100


def build_focus_proxy_rows(
    current_rows: Iterable[Mapping[str, Any]],
    histories_by_code: Mapping[str, pd.DataFrame],
    *,
    target_date: date,
    market_median: float,
    baskets: Mapping[str, tuple[str, ...]] = FOCUS_PROXY_BASKETS,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in current_rows:
        row = dict(raw)
        label = str(row.get("focus_label") or "")
        if row.get("status") == "ready" or label not in baskets:
            output.append(row)
            continue
        selected: dict[str, pd.DataFrame] = {}
        current_pcts: dict[str, float] = {}
        current_amount = 0.0
        for code in baskets[label]:
            frame = _prepare_history(histories_by_code.get(code, pd.DataFrame()), target_date)
            if frame.empty or frame.iloc[-1]["date"].date() != target_date:
                continue
            close = finite(frame.iloc[-1].get("close"))
            if close is None or not 0 < close <= 100:
                continue
            pct = _last_pct(frame)
            if pct is None:
                continue
            selected[code] = frame
            current_pcts[code] = pct
            current_amount += finite(frame.iloc[-1].get("amount"), 0.0) or 0.0
        if len(selected) < 2:
            output.append(row)
            continue

        proxy_history = aggregate_proxy_history(selected, target_date=target_date)
        up = sum(value > 0 for value in current_pcts.values())
        down = sum(value < 0 for value in current_pcts.values())
        flat = len(current_pcts) - up - down
        leader_code = max(current_pcts, key=current_pcts.get)
        board = {
            "board_code": f"PROXY-{label}",
            "board_name": f"{label}主板100元以下代理篮子",
            "board_type": "focus_proxy",
            "pct_change": float(np.mean(list(current_pcts.values()))),
            "amount": float(current_amount),
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "limit_up_count": sum(value >= 9.5 for value in current_pcts.values()),
            "leader_name": leader_code,
            "leader_pct_change": current_pcts[leader_code],
            "data_date": target_date.isoformat(),
            "source": "配置主题篮子+腾讯已完成日线",
        }
        scored = score_board(board, proxy_history, market_median=market_median)
        flags = list(scored.get("risk_flags") or [])
        flags.append("主板100元以下代理篮子，非官方概念指数")
        scored.update(
            {
                "focus_label": label,
                "status": "proxy_ready",
                "confidence": "medium",
                "risk_flags": flags,
                "proxy_count": len(selected),
                "proxy_codes": list(selected),
                "history_source": proxy_history.attrs.get("source"),
            }
        )
        output.append(scored)
    return output
