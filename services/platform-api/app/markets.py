from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import Settings
from app.database import open_database


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
                      quote_currency,price_digits,calendar_code,market_timezone
               FROM app.markets WHERE enabled=1 ORDER BY
                 CASE symbol WHEN 'EURUSD' THEN 1 WHEN 'GBPUSD' THEN 2
                             WHEN 'USDJPY' THEN 3 WHEN 'GERMANY40' THEN 4 ELSE 99 END,
                 symbol"""
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
            }
            for item in markets
        ],
        "timeframes": ["M5", "M15"],
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
    if symbol not in {"EURUSD", "GBPUSD", "USDJPY", "GERMANY40"}:
        raise ValueError("Unsupported market")
    if timeframe not in {"M5", "M15"}:
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
    end_utc = datetime.combine(local_today, time.max, tzinfo=local_zone).astimezone(timezone.utc)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            "SELECT 1 AS has_account FROM app.trading_accounts WHERE tenant_id=%s",
            (tenant_id,),
        )
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute(
            """SELECT TOP (%s) symbol,timeframe,open_time_utc,open_time_sast,
                      [open],high,low,[close],bid_close,ask_close,spread_close,
                      is_regular_session,tick_count,source
               FROM app.v_market_candles
               WHERE symbol=%s AND timeframe=%s AND completed=1
                 AND (%s='ALL' OR (open_time_utc >= %s AND open_time_utc <= %s))
               ORDER BY open_time_utc DESC""",
            (limit, symbol, timeframe, period, start_utc, end_utc),
        )
        rows = list(reversed(cursor.fetchall()))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": "Africa/Johannesburg",
        "session_date": local_today.isoformat(),
        "period": period,
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
