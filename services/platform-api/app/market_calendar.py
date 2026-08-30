from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo


FX_WEEK_OPEN_UTC = time(21, 0)
FX_WEEK_CLOSE_UTC = time(21, 0)


@dataclass(frozen=True)
class MarketSessionState:
    status: str
    reason: str
    should_receive_data: bool
    session_open_utc: datetime | None = None
    grace_until_utc: datetime | None = None


def operational_session_state(
    now_utc: datetime, *, calendar_code: str, market_timezone: str,
    session_open: time | None, session_close: time | None,
    holidays: Mapping[date, time | None] | None = None,
    reopen_grace: timedelta = timedelta(minutes=20),
) -> MarketSessionState:
    """Describe whether an operational feed should currently produce candles.

    This is intentionally separate from ``is_regular_session``. FX Sunday data
    may be monitored operationally while remaining a new model-continuity anchor.
    """
    now = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    if calendar_code == "FX_24X5":
        weekday, clock = now.weekday(), now.time().replace(tzinfo=None)
        if weekday == 5 or (weekday == 4 and clock >= FX_WEEK_CLOSE_UTC) or (
            weekday == 6 and clock < FX_WEEK_OPEN_UTC
        ):
            return MarketSessionState("CLOSED", "FX_WEEKEND", False)
        if weekday == 6:
            opened = datetime.combine(now.date(), FX_WEEK_OPEN_UTC, tzinfo=timezone.utc)
            grace_until = opened + reopen_grace
            if now < grace_until:
                return MarketSessionState("OPEN_GRACE", "FX_WEEKLY_REOPEN_GRACE", False,
                                          opened, grace_until)
            return MarketSessionState("OPEN", "FX_WEEKLY_SESSION", True, opened, grace_until)
        opened = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        return MarketSessionState("OPEN", "FX_WEEKLY_SESSION", True, opened, opened)

    local_zone = ZoneInfo(market_timezone)
    local = now.astimezone(local_zone)
    holiday_schedule = holidays or {}
    if local.weekday() >= 5:
        return MarketSessionState("CLOSED", "WEEKEND", False)
    if local.date() in holiday_schedule and holiday_schedule[local.date()] is None:
        return MarketSessionState("CLOSED", "MARKET_HOLIDAY", False)
    if session_open is None or session_close is None:
        return MarketSessionState("CLOSED", "SESSION_SCHEDULE_MISSING", False)
    effective_close = holiday_schedule.get(local.date()) or session_close
    local_open = datetime.combine(local.date(), session_open, tzinfo=local_zone)
    local_close = datetime.combine(local.date(), effective_close, tzinfo=local_zone)
    if local < local_open:
        return MarketSessionState("CLOSED", "BEFORE_REGULAR_SESSION", False)
    if local >= local_close:
        return MarketSessionState("CLOSED", "AFTER_REGULAR_SESSION", False)
    opened = local_open.astimezone(timezone.utc)
    grace_until = opened + reopen_grace
    if now < grace_until:
        return MarketSessionState("OPEN_GRACE", "REGULAR_SESSION_REOPEN_GRACE", False,
                                  opened, grace_until)
    return MarketSessionState("OPEN", "REGULAR_SESSION", True, opened, grace_until)


def market_data_stale(
    latest_completed_utc: datetime | None, *, now_utc: datetime,
    session: MarketSessionState, freshness: timedelta,
) -> bool:
    if not session.should_receive_data:
        return False
    if latest_completed_utc is None:
        return True
    latest = latest_completed_utc
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return latest < now_utc.astimezone(timezone.utc) - freshness


def is_regular_session(
    opened_utc: datetime, *, calendar_code: str, market_timezone: str,
    session_open: time | None, session_close: time | None,
    holidays: set[date] | None = None,
) -> bool:
    """Return whether a candle belongs to the configured model-evidence session.

    Broker marketStatus remains the execution authority. This calendar controls
    data-quality expectations and model evidence only.
    """
    opened = opened_utc if opened_utc.tzinfo else opened_utc.replace(tzinfo=timezone.utc)
    local = opened.astimezone(ZoneInfo(market_timezone))
    if calendar_code == "FX_24X5":
        # IG's retained candles close at 21:00 UTC on Friday. Sunday is excluded
        # from gap expectations because individual CFD feeds reopen at slightly
        # different times; the first observed Sunday candle becomes the new
        # continuity anchor.
        if opened.weekday() >= 5 or (opened.weekday() == 4 and opened.time() >= time(21)):
            return False
        return True
    if local.weekday() >= 5 or local.date() in (holidays or set()):
        return False
    if session_open is None or session_close is None:
        return False
    local_time = local.timetz().replace(tzinfo=None)
    return session_open <= local_time < session_close
