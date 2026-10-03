from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.market_calendar import is_regular_session


@dataclass(frozen=True)
class HistoricalGap:
    start_utc: datetime
    end_utc: datetime
    missing_minutes: int
    reason_code: str
    unexpected: bool


def expected_trading_minutes(start: datetime, end: datetime, *, calendar_code: str,
                             market_timezone: str, session_open: object,
                             session_close: object, holidays: set[object],
                             symbol: str | None = None) -> set[datetime]:
    point=(start if start.tzinfo else start.replace(tzinfo=timezone.utc)).replace(second=0,microsecond=0)
    boundary=end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    expected:set[datetime]=set()
    while point < boundary:
        regular = is_regular_session(point,calendar_code=calendar_code,market_timezone=market_timezone,
                                     session_open=session_open,session_close=session_close,holidays=holidays)
        # Spot Gold has an evidenced 22:00-23:00 Europe/London daily break.
        # Keep this research expectation aligned with the operational calendar;
        # do not generalize the exception to continuously quoted FX pairs.
        london = point.astimezone(ZoneInfo("Europe/London"))
        instrument_closed = (
            symbol == "XAUUSD" and calendar_code == "FX_24X5"
            and london.weekday() < 5 and 22 <= london.hour < 23
        )
        if regular and not instrument_closed:
            expected.add(point.replace(tzinfo=None))
        point += timedelta(minutes=1)
    return expected


def classify_missing_minutes(expected: set[datetime], observed: set[datetime], *, symbol: str) -> list[HistoricalGap]:
    missing=sorted(expected-observed)
    if not missing:
        return []
    spans:list[tuple[datetime,datetime,int]]=[]; start=previous=missing[0]
    for value in missing[1:]:
        if value-previous != timedelta(minutes=1):
            spans.append((start,previous+timedelta(minutes=1),int((previous-start).total_seconds()/60)+1))
            start=value
        previous=value
    spans.append((start,previous+timedelta(minutes=1),int((previous-start).total_seconds()/60)+1))
    return [HistoricalGap(start,end,count,
            "LOW_LIQUIDITY_NO_UPDATE" if symbol=="USDZAR" and count<=2 else "SOURCE_MISSING",True)
            for start,end,count in spans]


def ohlc_valid(opened: object, high: object, low: object, closed: object) -> bool:
    try:
        values=[Decimal(str(item)) for item in (opened,high,low,closed)]
    except Exception:
        return False
    return min(values)>0 and values[1]>=max(values[0],values[3]) and values[2]<=min(values[0],values[3])
