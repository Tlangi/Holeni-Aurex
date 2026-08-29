from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.database import open_database
from app.ig_demo import IGDemoClient, IGDemoUnavailable


def _timestamp(value: object) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _midpoint(price: dict[str, Any]) -> Decimal:
    bid, ask = price.get("bid"), price.get("ask")
    if bid is not None and ask is not None:
        return (Decimal(str(bid)) + Decimal(str(ask))) / Decimal("2")
    traded = price.get("lastTraded")
    if traded is None:
        raise ValueError("Historical candle has no usable price")
    return Decimal(str(traded))


def persist_historical_prices(
    settings: Settings, client: IGDemoClient, *, symbol: str, count: int
) -> int:
    timeframe, resolution, minutes = "M15", "MINUTE_15", 15
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,ig_epic FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
        market = cursor.fetchone()
        if not market:
            raise ValueError(f"Unknown or disabled market: {symbol}")

        prices = client.historical_prices(str(market["ig_epic"]), resolution=resolution, count=count)
        inserted = 0
        try:
            for candle in prices:
                # The final bucket can still be forming. IG explicitly marks completed buckets.
                if str(candle.get("marketStatus") or "").upper() not in {"", "TRADEABLE", "CLOSED"}:
                    continue
                opened = _timestamp(candle.get("snapshotTimeUTC") or candle.get("snapshotTime"))
                values = [_midpoint(candle[name]) for name in ("openPrice", "highPrice", "lowPrice", "closePrice")]
                if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
                    continue
                tick_count = int(candle.get("lastTradedVolume") or 0)
                cursor.execute(
                    """IF NOT EXISTS(SELECT 1 FROM app.candles WHERE market_id=%s AND timeframe=%s AND open_time_utc=%s)
                       BEGIN
                         INSERT app.candles(market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],tick_count,source,completed)
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'IG_DEMO_HISTORICAL',1)
                       END""",
                    (
                        str(market["market_id"]), timeframe, opened,
                        str(market["market_id"]), timeframe, opened, opened + timedelta(minutes=minutes),
                        *values, tick_count,
                    ),
                )
                inserted += max(cursor.rowcount, 0)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return inserted


def bootstrap_markets(settings: Settings, *, count: int) -> dict[str, object]:
    results: dict[str, int] = {}
    with IGDemoClient(settings) as client:
        for symbol in ("EURUSD", "GBPUSD", "USDJPY"):
            try:
                results[symbol] = persist_historical_prices(
                    settings, client, symbol=symbol, count=count
                )
            except IGDemoUnavailable as exc:
                if exc.error_code == "error.public-api.exceeded-account-historical-data-allowance":
                    return {
                        "status": "historical_quota_exhausted",
                        "requested_per_market": count,
                        "inserted_before_limit": results,
                        "next_step": "run_market_stream",
                    }
                raise
    return results


def seed_market_history(
    settings: Settings, client: IGDemoClient
) -> dict[str, object]:
    """One-time bounded warm-up; streaming remains the normal data source."""
    outcomes: dict[str, object] = {}
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT s.market_id,m.symbol,s.target_m15_candles,s.retry_after_utc,
                      (SELECT COUNT(*) FROM app.candles c WHERE c.market_id=s.market_id
                       AND c.timeframe='M15' AND c.completed=1) AS available
               FROM app.market_seed_state s JOIN app.markets m ON m.market_id=s.market_id
               WHERE m.enabled=1 ORDER BY m.symbol"""
        )
        states = cursor.fetchall()

    now = datetime.now(timezone.utc)
    for state in states:
        symbol = str(state["symbol"])
        available, target = int(state["available"]), int(state["target_m15_candles"])
        retry_after = state["retry_after_utc"]
        if available >= target:
            outcomes[symbol] = {"status": "ready", "available": available}
            _record_seed(settings, str(state["market_id"]), "READY", None, None)
            continue
        if retry_after and retry_after.replace(tzinfo=timezone.utc) > now:
            outcomes[symbol] = {"status": "deferred", "available": available,
                                "retry_after_utc": retry_after.isoformat()}
            continue
        requested = min(target - available, 64)
        try:
            inserted = persist_historical_prices(
                settings, client, symbol=symbol, count=requested
            )
            outcomes[symbol] = {"status": "seeded", "requested": requested, "inserted": inserted}
            _record_seed(settings, str(state["market_id"]), "SEEDED", None, None)
        except IGDemoUnavailable as exc:
            if exc.error_code == "error.public-api.exceeded-account-historical-data-allowance":
                next_week = now + timedelta(days=7)
                _defer_all_seeds(settings, exc.error_code, next_week)
                outcomes[symbol] = {"status": "quota_deferred", "retry_after_utc": next_week.isoformat()}
                break
            _record_seed(settings, str(state["market_id"]), "FAILED", exc.error_code,
                         now + timedelta(hours=6))
            outcomes[symbol] = {"status": "failed", "error_code": exc.error_code}
    return outcomes


def _record_seed(settings: Settings, market_id: str, result: str,
                 error_code: str | None, retry_after: datetime | None) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.market_seed_state SET last_attempt_at_utc=SYSUTCDATETIME(),
               last_result=%s,last_error_code=%s,retry_after_utc=%s,
               updated_at_utc=SYSUTCDATETIME() WHERE market_id=%s""",
            (result, error_code, retry_after, market_id),
        )
        connection.commit()


def _defer_all_seeds(settings: Settings, error_code: str, retry_after: datetime) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.market_seed_state SET last_attempt_at_utc=SYSUTCDATETIME(),
               last_result='QUOTA_DEFERRED',last_error_code=%s,retry_after_utc=%s,
               updated_at_utc=SYSUTCDATETIME()""",
            (error_code, retry_after),
        )
        connection.commit()
