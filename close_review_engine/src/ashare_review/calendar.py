from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
CLOSE_GUARD = time(15, 3)


def is_trading_day(day: date) -> bool:
    try:
        import exchange_calendars as xcals

        return bool(xcals.get_calendar("XSHG").is_session(day.isoformat()))
    except Exception:  # pragma: no cover - only a last-resort runtime fallback
        return day.weekday() < 5


def market_is_closed(now: datetime) -> bool:
    current = now if now.tzinfo else now.replace(tzinfo=SHANGHAI)
    current = current.astimezone(SHANGHAI)
    return current.time().replace(tzinfo=None) >= CLOSE_GUARD
