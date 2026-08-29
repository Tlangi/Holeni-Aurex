from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock

from lightstreamer.client import LightstreamerClient, Subscription

from app.config import Settings
from app.database import open_database
from app.ig_demo import IGDemoClient
from app.market_calendar import is_regular_session

logger = logging.getLogger("aurex.market_stream")
FIELDS = [
    "UTM", "BID_OPEN", "BID_HIGH", "BID_LOW", "BID_CLOSE",
    "OFR_OPEN", "OFR_HIGH", "OFR_LOW", "OFR_CLOSE", "LTV", "CONS_END",
]


def _number(update: object, field: str) -> Decimal | None:
    value = update.getValue(field)
    return None if value in (None, "") else Decimal(str(value))


class _ConnectionListener:
    def __init__(self, feed: "IGMarketStream") -> None:
        self.feed = feed

    def onStatusChange(self, status: str) -> None:
        self.feed.status = status
        logger.info(
            "IG Lightstreamer status changed",
            extra={"worker": "market_stream", "operation": "ig.stream.connection", "result": status},
        )
        self.feed._component("CURRENT" if status.startswith("CONNECTED") else "DEGRADED",
                             f"IG Lightstreamer {status}")

    def onServerError(self, code: int, message: str) -> None:
        logger.error("IG streaming server error", extra={"operation": "ig.stream", "result": str(code)})


class _PriceListener:
    def __init__(self, feed: "IGMarketStream") -> None:
        self.feed = feed

    def onItemUpdate(self, update: object) -> None:
        self.feed.on_price(update)

    def onSubscriptionError(self, code: int, message: str) -> None:
        logger.error("IG price subscription failed", extra={"operation": "ig.stream.subscribe", "result": str(code)})


class IGMarketStream:
    """IG Lightstreamer subscription that persists completed M5/M15 candles."""

    def __init__(self, settings: Settings, authenticated: IGDemoClient) -> None:
        if not authenticated.lightstreamer_endpoint or not authenticated.account_id:
            raise ValueError("IG client must be authenticated before streaming")
        self.settings = settings
        self.authenticated = authenticated
        self.status = "DISCONNECTED"
        self._lock = Lock()
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT market_id,symbol,ig_epic,calendar_code,market_timezone,
                          session_open_local,session_close_local
                   FROM app.markets WHERE enabled=1"""
            )
            self.markets = {
                str(row[2]): {
                    "market_id": str(row[0]), "symbol": str(row[1]),
                    "calendar_code": str(row[3]), "timezone": str(row[4]),
                    "open": row[5], "close": row[6],
                }
                for row in cursor.fetchall()
            }
            cursor.execute("SELECT calendar_code,holiday_date FROM app.market_holidays")
            holidays: dict[str, set[object]] = {}
            for calendar_code, holiday_date in cursor.fetchall():
                holidays.setdefault(str(calendar_code), set()).add(holiday_date)
            for market in self.markets.values():
                market["holidays"] = holidays.get(str(market["calendar_code"]), set())
        self.client = LightstreamerClient(authenticated.lightstreamer_endpoint, "DEFAULT")
        self.client.connectionDetails.setUser(authenticated.account_id)
        self.client.connectionDetails.setPassword(
            f"CST-{authenticated.cst}|XST-{authenticated.security_token}"
        )
        self.client.addListener(_ConnectionListener(self))
        self.subscription: Subscription | None = None

    def start(self) -> None:
        subscription = Subscription(
            "MERGE", [f"CHART:{epic}:5MINUTE" for epic in self.markets], FIELDS
        )
        subscription.setRequestedSnapshot("yes")
        subscription.addListener(_PriceListener(self))
        self.client.connect()
        self.client.subscribe(subscription)
        self.subscription = subscription
        logger.info(
            "IG market subscriptions requested",
            extra={
                "worker": "market_stream",
                "operation": "ig.stream.subscribe",
                "result": f"{len(self.markets)}_MARKETS",
            },
        )

    def stop(self) -> None:
        self.client.disconnect()

    def on_price(self, update: object) -> None:
        if update.getValue("CONS_END") != "1":
            return
        item = str(update.getItemName())
        epic = item.removeprefix("CHART:").removesuffix(":5MINUTE")
        market = self.markets.get(epic)
        if not market:
            return
        timestamp_ms = _number(update, "UTM")
        bid = [_number(update, f"BID_{field}") for field in ("OPEN", "HIGH", "LOW", "CLOSE")]
        offer = [_number(update, f"OFR_{field}") for field in ("OPEN", "HIGH", "LOW", "CLOSE")]
        if timestamp_ms is None or any(value is None for value in bid + offer):
            return
        values = [(left + right) / 2 for left, right in zip(bid, offer)]
        opened = datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc)
        opened = opened.replace(minute=opened.minute - opened.minute % 5, second=0, microsecond=0)
        ticks = int(_number(update, "LTV") or 0)
        with self._lock:
            self._persist(market, opened, values, bid, offer, ticks)
        logger.info(
            "completed M5 candle persisted",
            extra={
                "worker": "market_stream",
                "operation": "ig.stream.candle",
                "result": market["symbol"],
            },
        )

    def _persist(
        self, market: dict[str, object], opened: datetime, values: list[Decimal],
        bid: list[Decimal], ask: list[Decimal], ticks: int,
    ) -> None:
        market_id = str(market["market_id"])
        regular = is_regular_session(
            opened, calendar_code=str(market["calendar_code"]),
            market_timezone=str(market["timezone"]), session_open=market["open"],
            session_close=market["close"], holidays=market["holidays"],
        )
        with open_database(self.settings) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """IF NOT EXISTS(SELECT 1 FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc=%s)
                       INSERT app.candles(market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],
                         bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                         spread_open,spread_close,is_regular_session,tick_count,source,completed)
                       VALUES(%s,'M5',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'IG_LIGHTSTREAMER',1)""",
                    (market_id, opened, market_id, opened, opened + timedelta(minutes=5),
                     *values, *bid, *ask, ask[0] - bid[0], ask[3] - bid[3], regular, ticks),
                )
                bucket = opened.replace(minute=opened.minute - opened.minute % 15)
                cursor.execute(
                    """SELECT COUNT(*),MIN([low]),MAX([high]),SUM(tick_count),
                              (SELECT TOP 1 [open] FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc),
                              (SELECT TOP 1 [close] FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc DESC)
                       FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s""",
                    (market_id, bucket, bucket + timedelta(minutes=15), market_id, bucket,
                     bucket + timedelta(minutes=15), market_id, bucket, bucket + timedelta(minutes=15)),
                )
                count, low, high, volume, first_open, last_close = cursor.fetchone()
                if int(count) == 3:
                    cursor.execute(
                        """IF NOT EXISTS(SELECT 1 FROM app.candles WHERE market_id=%s AND timeframe='M15' AND open_time_utc=%s)
                           INSERT app.candles(market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],
                             bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                             spread_open,spread_close,is_regular_session,tick_count,source,completed)
                           SELECT %s,'M15',%s,%s,%s,%s,%s,%s,
                             (SELECT TOP 1 bid_open FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc),
                             MAX(bid_high),MIN(bid_low),(SELECT TOP 1 bid_close FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc DESC),
                             (SELECT TOP 1 ask_open FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc),
                             MAX(ask_high),MIN(ask_low),(SELECT TOP 1 ask_close FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc DESC),
                             (SELECT TOP 1 spread_open FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc),
                             (SELECT TOP 1 spread_close FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s ORDER BY open_time_utc DESC),
                             MIN(CAST(is_regular_session AS int)),%s,'IG_LIGHTSTREAMER',1
                           FROM app.candles WHERE market_id=%s AND timeframe='M5' AND open_time_utc>=%s AND open_time_utc<%s""",
                        (market_id, bucket, market_id, bucket, bucket + timedelta(minutes=15),
                         first_open, high, low, last_close,
                         market_id,bucket,bucket+timedelta(minutes=15), market_id,bucket,bucket+timedelta(minutes=15),
                         market_id,bucket,bucket+timedelta(minutes=15), market_id,bucket,bucket+timedelta(minutes=15),
                         market_id,bucket,bucket+timedelta(minutes=15), market_id,bucket,bucket+timedelta(minutes=15),
                         volume, market_id,bucket,bucket+timedelta(minutes=15)),
                    )
                connection.commit()
                self._component("CURRENT", "IG Lightstreamer completed candles are current")
            except Exception:
                connection.rollback()
                logger.exception("Failed to persist IG streaming candle")

    def _component(self, status: str, detail: str) -> None:
        try:
            with open_database(self.settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE app.platform_components SET status=%s,status_detail=%s,
                       checked_at_utc=SYSUTCDATETIME() WHERE component_code='market_feed'""",
                    (status, detail[:300]),
                )
                connection.commit()
        except Exception:
            logger.exception("Could not update market stream status")
