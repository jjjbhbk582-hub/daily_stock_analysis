from __future__ import annotations

from datetime import date, datetime, time, timedelta
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


def last_completed_trading_day(now: datetime | None = None) -> date:
    """Return the latest XSHG session whose closing guard has elapsed in Beijing time."""
    current = now or datetime.now(tz=SHANGHAI)
    current = current if current.tzinfo else current.replace(tzinfo=SHANGHAI)
    current = current.astimezone(SHANGHAI)
    candidate = current.date()
    if not (is_trading_day(candidate) and market_is_closed(current)):
        candidate -= timedelta(days=1)
    for _ in range(15):
        if is_trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
    raise RuntimeError("unable to resolve a completed A-share trading day within 15 days")
