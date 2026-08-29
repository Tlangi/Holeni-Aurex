from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


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
