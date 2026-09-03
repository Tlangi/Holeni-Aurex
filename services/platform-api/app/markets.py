from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
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
            "SELECT 1 AS supported FROM app.markets WHERE symbol=%s AND enabled=1 AND research_enabled=1",
            (symbol,),
        )
        if not cursor.fetchone():
            raise ValueError("Unsupported market")
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
