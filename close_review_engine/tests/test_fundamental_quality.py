from __future__ import annotations

from datetime import date

from ashare_review.fundamental_quality import assess_fundamentals, technical_trade_score

TARGET = date(2026, 8, 24)


def test_missing_fundamentals_remain_visible_as_technical_only() -> None:
    result = assess_fundamentals({}, TARGET)

    assert result == {
        "fundamental_status": "missing",
        "fundamental_missing_fields": [
            "report_date",
            "revenue_yoy",
            "net_profit_yoy",
            "roe",
        ],
        "fundamental_report_date": None,
        "fundamental_age_days": None,
        "fundamental_risk_flags": [],
    }


def test_report_older_than_200_days_is_stale() -> None:
    result = assess_fundamentals(
        {
            "report_date": "2026-01-31",
            "revenue_yoy": 5,
            "net_profit_yoy": 6,
            "roe": 8,
        },
        TARGET,
    )

    assert result["fundamental_status"] == "stale"
    assert result["fundamental_age_days"] == 205
    assert result["fundamental_missing_fields"] == []


def test_partial_and_verified_require_all_core_fields() -> None:
    partial = assess_fundamentals(
        {"report_date": "2026-06-30", "revenue_yoy": 5, "net_profit_yoy": None},
        TARGET,
    )
    verified = assess_fundamentals(
        {
            "report_date": "2026-06-30",
            "revenue_yoy": 5,
            "net_profit_yoy": 6,
            "roe": 8,
        },
        TARGET,
    )

    assert partial["fundamental_status"] == "partial"
    assert partial["fundamental_missing_fields"] == ["net_profit_yoy", "roe"]
    assert verified["fundamental_status"] == "verified"
    assert verified["fundamental_age_days"] == 55


def test_hard_risk_words_are_exposed_without_hiding_other_quality_fields() -> None:
    result = assess_fundamentals(
        {
            "report_date": "2026-06-30",
            "revenue_yoy": 5,
            "net_profit_yoy": 6,
            "roe": 8,
        },
        TARGET,
        announcements=[{"title": "关于收到监管立案告知书的公告"}],
    )

    assert result["fundamental_status"] == "verified"
    assert result["fundamental_risk_flags"] == ["监管立案"]


def test_technical_trade_score_excludes_fundamental_placeholder() -> None:
    breakdown = {
        "fundamental": 16,
        "industry": 14,
        "trend": 20,
        "structure": 10,
        "events": 7,
    }

    assert technical_trade_score(breakdown) == 72.9
