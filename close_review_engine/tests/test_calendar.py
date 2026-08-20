from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import ashare_review.calendar as calendar_module
from ashare_review.calendar import last_completed_trading_day

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_completed_session_uses_today_after_close(monkeypatch) -> None:
    monkeypatch.setattr(calendar_module, "is_trading_day", lambda day: day.weekday() < 5)
    now = datetime(2026, 8, 21, 15, 30, tzinfo=SHANGHAI)
    assert last_completed_trading_day(now) == date(2026, 8, 21)


def test_completed_session_uses_previous_session_before_close(monkeypatch) -> None:
    monkeypatch.setattr(calendar_module, "is_trading_day", lambda day: day.weekday() < 5)
    now = datetime(2026, 8, 21, 14, 30, tzinfo=SHANGHAI)
    assert last_completed_trading_day(now) == date(2026, 8, 20)


def test_completed_session_skips_weekend(monkeypatch) -> None:
    monkeypatch.setattr(calendar_module, "is_trading_day", lambda day: day.weekday() < 5)
    now = datetime(2026, 8, 23, 10, 0, tzinfo=SHANGHAI)
    assert last_completed_trading_day(now) == date(2026, 8, 21)
