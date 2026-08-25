from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

import pandas as pd

from ashare_review.indicators import finite

CORE_FIELDS = ("revenue_yoy", "net_profit_yoy", "roe")
HARD_RISK_WORDS = ("退市", "暂停上市", "财务造假", "监管立案", "立案调查")


def _parse_report_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _is_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def assess_fundamentals(
    financials: Mapping[str, Any] | None,
    target_date: date,
    *,
    announcements: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    payload = dict(financials or {})
    report_date = _parse_report_date(payload.get("report_date"))
    missing = [field for field in CORE_FIELDS if not _is_finite(payload.get(field))]
    if report_date is None:
        missing.insert(0, "report_date")

    has_any_core = any(_is_finite(payload.get(field)) for field in CORE_FIELDS)
    age_days = None if report_date is None else (target_date - report_date).days
    if not payload or (not has_any_core and report_date is None):
        status = "missing"
    elif report_date is not None and age_days is not None and age_days > 200:
        status = "stale"
    elif missing:
        status = "partial"
    else:
        status = "verified"

    risk_flags: list[str] = []
    for announcement in announcements:
        title = str(announcement.get("title") or "")
        for word in HARD_RISK_WORDS:
            if word in title and word not in risk_flags:
                risk_flags.append(word)

    return {
        "fundamental_status": status,
        "fundamental_missing_fields": missing,
        "fundamental_report_date": None if report_date is None else report_date.isoformat(),
        "fundamental_age_days": age_days,
        "fundamental_risk_flags": risk_flags,
    }


def technical_trade_score(breakdown: Mapping[str, Any]) -> float:
    raw = sum(
        finite(breakdown.get(key), 0.0) or 0.0
        for key in ("industry", "trend", "structure", "events")
    )
    return round(max(0.0, min(100.0, raw / 70.0 * 100.0)), 1)
