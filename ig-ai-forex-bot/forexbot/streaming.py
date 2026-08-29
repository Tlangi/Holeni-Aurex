from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time

import pandas as pd
from lightstreamer.client import LightstreamerClient, Subscription

from .candle_store import CandleStore

log = logging.getLogger("forexbot.streaming")

CHART_FIELDS = [
    "UTM", "BID_OPEN", "BID_HIGH", "BID_LOW", "BID_CLOSE",
    "OFR_OPEN", "OFR_HIGH", "OFR_LOW", "OFR_CLOSE", "LTV", "CONS_END",
]
ACCOUNT_FIELDS = ["FUNDS", "EQUITY", "MARGIN", "AVAILABLE_TO_DEAL", "PNL"]
TRADE_FIELDS = ["CONFIRMS", "OPU", "WOU"]


def _number(update, field: str) -> float | None:
    value = update.getValue(field)
    if value in (None, ""):
        return None
    return float(value)


@dataclass
class StreamHealth:
    status: str
    last_update_age: float | None
    symbols_seen: int


class _ConnectionListener:
    def __init__(self, owner: "IGStreamingFeed"):
        self.owner = owner

    def onStatusChange(self, status):
        self.owner.status = status
        log.info("IG stream status=%s", status)

    def onServerError(self, code, message):
        log.error("IG stream server error code=%s message=%s", code, message)


class _PriceListener:
    def __init__(self, owner: "IGStreamingFeed"):
        self.owner = owner

    def onItemUpdate(self, update):
        self.owner.on_price(update)

    def onSubscriptionError(self, code, message):
        log.error("IG price subscription error code=%s message=%s", code, message)

    def onSubscription(self):
        log.info("IG price stream subscribed")

    def onUnsubscription(self):
        log.warning("IG price stream unsubscribed")


class _EventListener:
    def __init__(self, owner: "IGStreamingFeed", event_type: str):
        self.owner, self.event_type = owner, event_type

    def onItemUpdate(self, update):
        self.owner.last_event[self.event_type] = time.time()
        log.info("IG %s event received", self.event_type)

    def onSubscriptionError(self, code, message):
        log.error("IG %s subscription error code=%s message=%s", self.event_type, code, message)


class IGStreamingFeed:
    """IG Lightstreamer feed that persists completed M5 and aggregated M15 candles."""

    def __init__(self, gateway, store: CandleStore | None = None, prices_only: bool = False,
                 max_frequency: str | None = None):
        if not gateway.lightstreamer_endpoint or not gateway.account_id:
            raise RuntimeError("Authenticate with IG before starting the stream")
        self.gateway = gateway
        self.store = store or gateway.candles
        self.prices_only = prices_only
        self.max_frequency = max_frequency
        self.status = "DISCONNECTED"
        self.last_price: dict[str, float] = {}
        self.last_event: dict[str, float] = {}
        self._lock = threading.Lock()
        self._epic_to_symbol = {
            gateway.settings.data["instruments"][symbol]["epic"]: symbol
            for symbol in gateway.settings.data["symbols"]
        }
        self.client = LightstreamerClient(gateway.lightstreamer_endpoint, "DEFAULT")
        self.client.connectionDetails.setUser(gateway.account_id)
        self.client.connectionDetails.setPassword(f"CST-{gateway.cst}|XST-{gateway.xst}")
        self.client.addListener(_ConnectionListener(self))
        self.subscriptions: list[Subscription] = []

    def start(self) -> None:
        price = Subscription(
            "MERGE", [f"CHART:{epic}:5MINUTE" for epic in self._epic_to_symbol], CHART_FIELDS
        )
        price.setRequestedSnapshot("yes")
        if self.max_frequency:
            price.setRequestedMaxFrequency(self.max_frequency)
        price.addListener(_PriceListener(self))
        self.client.connect()
        subscriptions = [price]
        if not self.prices_only:
            account = Subscription("MERGE", [f"ACCOUNT:{self.gateway.account_id}"], ACCOUNT_FIELDS)
            account.addListener(_EventListener(self, "account"))
            trades = Subscription("DISTINCT", [f"TRADE:{self.gateway.account_id}"], TRADE_FIELDS)
            trades.setRequestedSnapshot("yes")
            trades.addListener(_EventListener(self, "trade"))
            subscriptions.extend([account, trades])
        for subscription in subscriptions:
            self.client.subscribe(subscription)
            self.subscriptions.append(subscription)

    def stop(self) -> None:
        self.client.disconnect()

    def on_price(self, update) -> None:
        try:
            item = update.getItemName()
            epic = item.removeprefix("CHART:").removesuffix(":5MINUTE")
            symbol = self._epic_to_symbol.get(epic)
            if not symbol:
                return
            with self._lock:
                self.last_price[symbol] = time.time()
            if update.getValue("CONS_END") != "1":
                return
            timestamp_ms = _number(update, "UTM")
            bid = [_number(update, f"BID_{name}") for name in ("OPEN", "HIGH", "LOW", "CLOSE")]
            offer = [_number(update, f"OFR_{name}") for name in ("OPEN", "HIGH", "LOW", "CLOSE")]
            if timestamp_ms is None or any(value is None for value in bid + offer):
                log.warning("ignored incomplete completed-candle update for %s", symbol)
                return
            stamp = pd.Timestamp(datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)).floor("5min")
            mids = [(left + right) / 2 for left, right in zip(bid, offer)]
            frame = pd.DataFrame([{
                "time": stamp, "open": mids[0], "high": mids[1], "low": mids[2], "close": mids[3],
                "tick_volume": _number(update, "LTV") or 0,
            }])
            self.store.put(symbol, "M5", frame)
            self._aggregate_m15(symbol, stamp)
        except Exception:
            log.exception("failed to process IG stream price update")

    def _aggregate_m15(self, symbol: str, stamp: pd.Timestamp) -> None:
        recent = self.store.get(symbol, "M5", 3)
        if len(recent) != 3:
            return
        bucket = stamp.floor("15min")
        selected = recent[recent.time.dt.floor("15min") == bucket].drop_duplicates("time")
        if len(selected) != 3:
            return
        selected = selected.sort_values("time")
        expected = [bucket + pd.Timedelta(minutes=offset) for offset in (0, 5, 10)]
        if list(selected.time) != expected:
            return
        aggregate = pd.DataFrame([{
            "time": bucket,
            "open": selected.iloc[0].open,
            "high": selected.high.max(),
            "low": selected.low.min(),
            "close": selected.iloc[-1].close,
            "tick_volume": selected.tick_volume.sum(),
        }])
        self.store.put(symbol, "M15", aggregate)
        log.info("cached completed M15 candle symbol=%s time=%s", symbol, bucket.isoformat())

    def health(self, stale_after: float = 90.0) -> StreamHealth:
        with self._lock:
            ages = [time.time() - value for value in self.last_price.values()]
        age = max(ages) if ages else None
        return StreamHealth(self.status, age, len(ages))

    def is_healthy(self, stale_after: float = 90.0) -> bool:
        health = self.health(stale_after)
        return health.status.startswith("CONNECTED") and health.symbols_seen == len(self._epic_to_symbol) \
            and health.last_update_age is not None and health.last_update_age <= stale_after

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_healthy():
                return True
            time.sleep(0.25)
        return False
