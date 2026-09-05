from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import Settings
from app.database import open_database
from app.market_calendar import is_regular_session

TIMEFRAME_MINUTES = {"M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def _quality_bucket(value: datetime, timeframe: str) -> datetime:
    if timeframe == "D1":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = TIMEFRAME_MINUTES[timeframe]
    minute_of_day = value.hour * 60 + value.minute
    bucket_minute = minute_of_day - minute_of_day % minutes
    return value.replace(hour=bucket_minute // 60, minute=bucket_minute % 60, second=0, microsecond=0)


def calculate_history_quality(
    rows: list[dict[str, object]], *, timeframe: str, requested_start: datetime | None,
    requested_end: datetime, market: dict[str, object], holidays: set[object], period: str,
) -> dict[str, object]:
    """Measure observed gaps without manufacturing candles or overstating calendar authority."""
    interval = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    observed = sorted(row["open_time_utc"].replace(tzinfo=timezone.utc) for row in rows)
    actual_start, actual_end = (observed[0], observed[-1]) if observed else (None, None)
    authoritative = (
        (str(market["asset_class"]) == "FX" and str(market["calendar_code"]) == "FX_24X5")
        or str(market["calendar_code"]) == "XETRA_REGULAR"
    ) and period != "ALL"
    expected: list[datetime] = []
    if authoritative and requested_start:
        point = requested_start.replace(second=0, microsecond=0)
        expected_buckets: set[datetime] = set()
        while point <= requested_end:
            if is_regular_session(
                point, calendar_code=str(market["calendar_code"]),
                market_timezone=str(market["market_timezone"]),
                session_open=market["session_open_local"], session_close=market["session_close_local"],
                holidays=holidays,
            ):
                candidate = _quality_bucket(point, timeframe)
                if candidate + interval <= requested_end:
                    expected_buckets.add(candidate)
            point += timedelta(minutes=5)
        expected = sorted(expected_buckets)
    expected_set, observed_set = set(expected), set(observed)
    missing = sorted(expected_set - observed_set) if authoritative else []
    internal_missing = [item for item in missing if actual_start and actual_end and actual_start < item < actual_end]
    not_retained = [item for item in missing if actual_start and item < actual_start]
    delayed = [item for item in missing if actual_end and item > actual_end]
    gaps: list[dict[str, object]] = []
    for left, right in zip(observed, observed[1:]):
        cursor = left + interval
        missing_between: list[datetime] = []
        while cursor < right:
            if not authoritative or cursor in expected_set:
                missing_between.append(cursor)
            cursor += interval
        if missing_between:
            gaps.append({
                "after_utc": left.isoformat(), "before_utc": right.isoformat(),
                "missing_candles": len(missing_between),
                "duration_seconds": int((right - left - interval).total_seconds()),
                "classification": "MISSING_CANDLE" if authoritative else "CALENDAR_UNCERTAINTY",
            })
    expected_count = len(expected) if authoritative else None
    completeness = round(100 * len(expected_set & observed_set) / expected_count, 2) if expected_count else None
    status = "UNVERIFIED" if not authoritative else "INCOMPLETE" if internal_missing or not_retained else "DELAYED" if delayed else "FRESH"
    return {
        "requested_start_utc": _quality_iso(requested_start), "requested_end_utc": _quality_iso(requested_end),
        "actual_start_utc": _quality_iso(actual_start), "actual_end_utc": _quality_iso(actual_end),
        "returned_candle_count": len(rows), "expected_candle_count": expected_count,
        "completeness_percentage": completeness, "gap_count": len(gaps),
        "missing_candle_count": len(internal_missing) if authoritative else None,
        "period_not_retained_count": len(not_retained) if authoritative else None,
        "delayed_candle_count": len(delayed) if authoritative else None,
        "largest_unexplained_gap_seconds": max((item["duration_seconds"] for item in gaps), default=0),
        "is_complete": (not missing) if authoritative else None, "quality_status": status,
        "calculation_method": "SESSION_CALENDAR_EXPECTED_BUCKETS_V1" if authoritative else "OBSERVED_INTERNAL_GAPS_ONLY_V1",
        "calendar_source": str(market["calendar_code"]),
        "limitation": None if authoritative else "Completeness unverified because an authoritative calendar is unavailable or retention start is unknown.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "gaps": gaps[:100],
    }


def _quality_iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def read_market_inventory(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            "SELECT 1 AS has_account FROM app.trading_accounts WHERE tenant_id=%s",
            (tenant_id,),
        )
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute(
            """SELECT symbol,display_name,asset_class,ig_epic,base_currency,
                      quote_currency,price_digits,calendar_code,market_timezone,
                      market_tier,research_enabled,training_enabled,signal_enabled,
                      demo_trading_enabled,live_trading_enabled,reporting_currency,
                      pip_size,tick_size,max_spread_bps,slippage_assumption_bps,
                      default_timeframe,confirmation_timeframe,risk_profile,
                      execution_promotion_required,broker_instrument_type,
                      broker_resolved_at_utc
               FROM app.markets WHERE enabled=1 ORDER BY market_tier,symbol"""
        )
        markets = cursor.fetchall()
    return {
        "markets": [
            {
                "symbol": str(item["symbol"]),
                "display_name": str(item["display_name"]),
                "asset_class": str(item["asset_class"]),
                "ig_epic": str(item["ig_epic"]),
                "base_currency": str(item["base_currency"]),
                "quote_currency": str(item["quote_currency"]),
                "price_digits": int(item["price_digits"]),
                "calendar_code": str(item["calendar_code"]),
                "market_timezone": str(item["market_timezone"]),
                "tier": int(item["market_tier"]),
                "research_enabled": bool(item["research_enabled"]),
                "training_enabled": bool(item["training_enabled"]),
                "signal_enabled": bool(item["signal_enabled"]),
                "demo_trading_enabled": bool(item["demo_trading_enabled"]),
                "live_trading_enabled": bool(item["live_trading_enabled"]),
                "reporting_currency": str(item["reporting_currency"]),
                "pip_size": str(item["pip_size"]) if item["pip_size"] is not None else None,
                "tick_size": str(item["tick_size"]) if item["tick_size"] is not None else None,
                "max_spread_bps": str(item["max_spread_bps"]) if item["max_spread_bps"] is not None else None,
                "slippage_assumption_bps": str(item["slippage_assumption_bps"])
                if item["slippage_assumption_bps"] is not None else None,
                "default_timeframe": str(item["default_timeframe"]),
                "confirmation_timeframe": str(item["confirmation_timeframe"]),
                "risk_profile": str(item["risk_profile"]),
                "execution_promotion_required": bool(item["execution_promotion_required"]),
                "broker_instrument_type": str(item["broker_instrument_type"] or "UNKNOWN"),
                "broker_resolved_at_utc": item["broker_resolved_at_utc"].replace(
                    tzinfo=timezone.utc,
                ).isoformat() if item["broker_resolved_at_utc"] else None,
                "eligibility": "RESEARCH_ONLY" if int(item["market_tier"]) == 3
                else "VALIDATING" if not bool(item["demo_trading_enabled"])
                else "DEMO_GATED",
            }
            for item in markets
        ],
        "timeframes": ["M5", "M15", "M30", "H1", "H4", "D1"],
        "periods": ["TODAY", "7D", "ALL"],
        "execution_enabled": False,
    }


def read_candles(
    settings: Settings, tenant_id: str, *, symbol: str, timeframe: str, limit: int,
    period: str = "7D",
) -> dict[str, object]:
    symbol = symbol.upper()
    timeframe = timeframe.upper()
    period = period.upper()
    if timeframe not in {"M5", "M15", "M30", "H1", "H4", "D1"}:
        raise ValueError("Unsupported timeframe")
    if period not in {"TODAY", "7D", "ALL"}:
        raise ValueError("Unsupported candle period")
    # The endpoint remains bounded, but ALL/7D views need enough observations to
    # pan through accumulated history instead of compressing only the latest 200.
    limit = max(10, min(limit, 2000))
    local_zone = ZoneInfo("Africa/Johannesburg")
    local_today = datetime.now(local_zone).date()
    period_start = local_today if period == "TODAY" else local_today - timedelta(days=6)
    start_utc = datetime.combine(period_start, time.min, tzinfo=local_zone).astimezone(timezone.utc)
    end_utc = min(datetime.combine(local_today, time.max, tzinfo=local_zone).astimezone(timezone.utc),
                  datetime.now(timezone.utc))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            "SELECT 1 AS has_account FROM app.trading_accounts WHERE tenant_id=%s",
            (tenant_id,),
        )
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute(
            """SELECT market_id,asset_class,calendar_code,market_timezone,session_open_local,session_close_local
               FROM app.markets WHERE symbol=%s AND enabled=1 AND research_enabled=1""",
            (symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError("Unsupported market")
        cursor.execute("SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s", (market["calendar_code"],))
        holidays = {row["holiday_date"] for row in cursor.fetchall()}
        source_timeframe = timeframe if timeframe in {"M5", "M15"} else "M15"
        multiplier = {"M30": 2, "H1": 4, "H4": 16, "D1": 96}.get(timeframe, 1)
        source_limit = min(10000, limit * multiplier + multiplier)
        cursor.execute(
            """SELECT TOP (%s) symbol,timeframe,open_time_utc,open_time_sast,
                      [open],high,low,[close],bid_close,ask_close,spread_close,
                      is_regular_session,tick_count,source
               FROM app.v_market_candles AS v
               WHERE symbol=%s AND timeframe=%s AND completed=1
                 AND EXISTS (SELECT 1 FROM app.candles AS quality
                             WHERE quality.candle_id=v.candle_id AND quality.quality_status='PASS')
                 AND (%s='ALL' OR (open_time_utc >= %s AND open_time_utc <= %s))
               ORDER BY open_time_utc DESC""",
            (source_limit, symbol, source_timeframe, period, start_utc, end_utc),
        )
        rows = list(reversed(cursor.fetchall()))
    if timeframe not in {"M5", "M15"}:
        rows = _aggregate_rows(rows, timeframe)[-limit:]
    else:
        rows = rows[-limit:]
    quality = calculate_history_quality(
        rows, timeframe=timeframe, requested_start=None if period == "ALL" else start_utc,
        requested_end=end_utc, market=market, holidays=holidays, period=period,
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": "Africa/Johannesburg",
        "session_date": local_today.isoformat(),
        "period": period,
        "quality": quality,
        "candles": [
            {
                "open_time_utc": row["open_time_utc"].replace(tzinfo=timezone.utc).isoformat(),
                "open_time_sast": row["open_time_sast"].isoformat(),
                "open": str(row["open"]),
                "high": str(row["high"]),
                "low": str(row["low"]),
                "close": str(row["close"]),
                "bid_close": str(row["bid_close"]) if row["bid_close"] is not None else None,
                "ask_close": str(row["ask_close"]) if row["ask_close"] is not None else None,
                "spread_close": str(row["spread_close"]) if row["spread_close"] is not None else None,
                "is_regular_session": bool(row["is_regular_session"]),
                "tick_count": int(row["tick_count"]),
                "source": str(row["source"]),
            }
            for row in rows
        ],
    }


def _aggregate_rows(rows: list[dict[str, object]], timeframe: str) -> list[dict[str, object]]:
    def bucket(value: datetime) -> datetime:
        opened = value.replace(tzinfo=timezone.utc)
        if timeframe == "M30":
            return opened.replace(minute=(opened.minute // 30) * 30, second=0, microsecond=0)
        if timeframe == "H1":
            return opened.replace(minute=0, second=0, microsecond=0)
        if timeframe == "H4":
            return opened.replace(hour=(opened.hour // 4) * 4, minute=0, second=0, microsecond=0)
        return opened.replace(hour=0, minute=0, second=0, microsecond=0)

    grouped: dict[datetime, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(bucket(row["open_time_utc"]), []).append(row)
    sast = ZoneInfo("Africa/Johannesburg")
    results: list[dict[str, object]] = []
    for opened, candles in sorted(grouped.items()):
        first, last = candles[0], candles[-1]
        results.append({
            "symbol": first["symbol"], "timeframe": timeframe,
            "open_time_utc": opened.replace(tzinfo=None),
            "open_time_sast": opened.astimezone(sast).replace(tzinfo=None),
            "open": first["open"], "high": max(Decimal(str(item["high"])) for item in candles),
            "low": min(Decimal(str(item["low"])) for item in candles), "close": last["close"],
            "bid_close": last["bid_close"], "ask_close": last["ask_close"],
            "spread_close": last["spread_close"],
            "is_regular_session": all(bool(item["is_regular_session"]) for item in candles),
            "tick_count": sum(int(item["tick_count"] or 0) for item in candles),
            "source": f"AGGREGATED_{timeframe}",
        })
    return results
