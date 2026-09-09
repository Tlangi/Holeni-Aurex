"""Bounded read-only comparison of IG PRICE and CHART event clocks."""
from __future__ import annotations

import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from lightstreamer.client import (  # noqa: E402
    ConsoleLoggerProvider,
    ConsoleLogLevel,
    LightstreamerClient,
    Subscription,
)
from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.ig_demo import IGDemoClient  # noqa: E402


class Listener:
    def __init__(self, output: dict[str, object], done: Event) -> None:
        self.output, self.done = output, done

    def onItemUpdate(self, update: object) -> None:
        item = str(update.getItemName())
        is_chart = item.startswith("CHART:")
        self.output[item] = {
            "received_at_utc": datetime.now(timezone.utc).isoformat(),
            "utm": update.getValue("UTM") if is_chart else None,
            "update_time": None if is_chart else update.getValue("UPDATE_TIME"),
            "bid": update.getValue("BID_CLOSE") if is_chart else update.getValue("BID"),
            "offer": update.getValue("OFR_CLOSE") if is_chart else update.getValue("OFFER"),
            "snapshot": update.isSnapshot(),
        }
        if any(str(key).startswith("MARKET:") for key in self.output) and sum(
            str(key).startswith("CHART:") for key in self.output
        ) >= 2:
            self.done.set()

    def onSubscriptionError(self, code: int, message: str) -> None:
        self.output["subscription_error"] = {"code": code, "message": message[:200]}
        self.done.set()

    def onListenStart(self) -> None: pass
    def onListenEnd(self) -> None: pass
    def onSubscription(self) -> None: pass
    def onUnsubscription(self) -> None: pass
    def onClearSnapshot(self, itemName: str, itemPos: int) -> None: pass
    def onEndOfSnapshot(self, itemName: str, itemPos: int) -> None: pass
    def onItemLostUpdates(self, itemName: str, itemPos: int, lostUpdates: int) -> None: pass
    def onRealMaxFrequency(self, frequency: str) -> None: pass
    def onCommandSecondLevelSubscriptionError(self, code: int, message: str, key: str) -> None: pass
    def onCommandSecondLevelItemLostUpdates(self, lostUpdates: int, key: str) -> None: pass


class ConnectionListener:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output

    def onStatusChange(self, status: str) -> None:
        self.output.setdefault("connection_history", []).append(
            {"status": status, "at_utc": datetime.now(timezone.utc).isoformat()}
        )

    def onServerError(self, code: int, message: str) -> None:
        self.output["server_error"] = {"code": code, "message": message[:200]}

    def onListenStart(self) -> None: pass
    def onListenEnd(self) -> None: pass
    def onPropertyChange(self, property: str) -> None: pass


if __name__ == "__main__":
    LightstreamerClient.setLoggerProvider(ConsoleLoggerProvider(ConsoleLogLevel.WARN))
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT ig_epic FROM app.markets WHERE symbol='USDJPY'")
        epic = str(cursor.fetchone()[0])
    done = Event()
    signal.signal(signal.SIGINT, lambda *_: done.set())
    output: dict[str, object] = {}
    with IGDemoClient(settings) as authenticated:
        client = LightstreamerClient(authenticated.lightstreamer_endpoint, "DEFAULT")
        client.connectionDetails.setUser(authenticated.account_id)
        client.connectionDetails.setPassword(f"CST-{authenticated.cst}|XST-{authenticated.security_token}")
        price = Subscription("MERGE", [f"MARKET:{epic}"], ["UPDATE_TIME", "BID", "OFFER", "MARKET_STATE"])
        chart = Subscription("MERGE", [f"CHART:{epic}:1MINUTE"],
                             ["UTM", "BID_CLOSE", "OFR_CLOSE", "CONS_END"])
        chart_m5 = Subscription("MERGE", [f"CHART:{epic}:5MINUTE"],
                                ["UTM", "BID_CLOSE", "OFR_CLOSE", "CONS_END"])
        listener = Listener(output, done)
        client.connectionOptions.setRetryDelay(1000)
        client.addListener(ConnectionListener(output))
        price.addListener(listener)
        chart.addListener(listener)
        chart_m5.addListener(listener)
        client.connect()
        client.subscribe(price)
        client.subscribe(chart)
        client.subscribe(chart_m5)
        done.wait(25)
        client.disconnect()
    print({"epic": epic, "events": output}, flush=True)
