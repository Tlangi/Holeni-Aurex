from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import time
import uuid

import pandas as pd
import requests

from .core import Settings
from .candle_store import CandleStore
from .errors import HistoricalQuotaExceeded, IGAPIError, IGConnectionError, MarketDataUnavailable


RESOLUTIONS = {"M1": "MINUTE", "M5": "MINUTE_5", "M15": "MINUTE_15",
               "M30": "MINUTE_30", "H1": "HOUR", "H4": "HOUR_4"}
INTERVAL_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}


class IGGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.base_url = ("https://demo-api.ig.com/gateway/deal" if settings.ig_environment == "demo"
                         else "https://api.ig.com/gateway/deal")
        self.account_id = ""
        self.lightstreamer_endpoint = ""
        self.cst = ""
        self.xst = ""
        self.candles = CandleStore(symbols=settings.data.get("symbols", ()))
        self._history_quota_exhausted = False

    def connect(self) -> None:
        if not self.settings.ig_api_key or not self.settings.ig_username or not self.settings.ig_password:
            raise ValueError("IG_API_KEY, IG_USERNAME and IG_PASSWORD are required")
        try:
            response = self.session.post(f"{self.base_url}/session", headers={
                "X-IG-API-KEY": self.settings.ig_api_key, "Version": "2",
                "Content-Type": "application/json", "Accept": "application/json",
            }, json={"identifier": self.settings.ig_username, "password": self.settings.ig_password,
                     "encryptedPassword": False}, timeout=30)
        except requests.RequestException as exc:
            raise IGConnectionError(
                "Could not connect to the IG demo API. Check the internet connection, firewall/proxy access "
                "to demo-api.ig.com, and try again. No subscription or order was created."
            ) from exc
        self._raise(response, "IG login")
        cst, xst = response.headers.get("CST"), response.headers.get("X-SECURITY-TOKEN")
        if not cst or not xst:
            raise RuntimeError("IG login did not return security tokens")
        payload = response.json()
        self.account_id = payload.get("currentAccountId", "")
        self.lightstreamer_endpoint = payload.get("lightstreamerEndpoint", "")
        self.cst, self.xst = cst, xst
        if not self.lightstreamer_endpoint:
            raise RuntimeError("IG login did not return a Lightstreamer endpoint")
        if self.settings.ig_account_id and self.account_id != self.settings.ig_account_id:
            raise PermissionError("IG preferred account does not match IG_ACCOUNT_ID")
        self.session.headers.update({"X-IG-API-KEY": self.settings.ig_api_key,
                                     "CST": cst, "X-SECURITY-TOKEN": xst,
                                     "Accept": "application/json"})

    def close(self) -> None:
        self.session.close()

    def assert_execution_allowed(self) -> None:
        if self.settings.ig_environment == "demo":
            return
        if not (self.settings.allow_live and self.settings.unlock_phrase == "I_ACCEPT_LIVE_TRADING_RISK"):
            raise PermissionError("IG live endpoint blocked by the double live-trading lock")

    def assert_execution_ready(self) -> None:
        self.assert_execution_allowed()
        if not self.account_id:
            raise RuntimeError("IG session is not authenticated")

    def account(self):
        response = self._get("/accounts", version="1")
        accounts = response.get("accounts", [])
        account = next((a for a in accounts if a.get("accountId") == self.account_id), None)
        if not account:
            raise RuntimeError("Authenticated IG account was not returned by /accounts")
        balance = account.get("balance") or {}
        cash = float(balance.get("balance") or 0)
        profit = float(balance.get("profitLoss") or 0)
        return SimpleNamespace(login=self.account_id, server="IG-DEMO" if self.settings.ig_environment == "demo" else "IG-LIVE",
                               trade_mode=self.settings.ig_environment, balance=cash, equity=cash + profit,
                               profit=profit, margin=float(balance.get("deposit") or 0),
                               margin_free=float(balance.get("available") or 0))

    def bars(self, symbol: str, count: int) -> pd.DataFrame:
        instrument = self._instrument(symbol)
        timeframe = self.settings.data["timeframe"]
        cached = self.candles.get(symbol, timeframe, count)
        now = time.time()
        refresh_key = f"last_refresh:{symbol}:{timeframe}"
        last_request = float(self.candles.get_meta(refresh_key) or 0)
        refresh_due = now - last_request >= INTERVAL_SECONDS[timeframe]
        if len(cached) >= count and not refresh_due:
            return cached
        if not refresh_due:
            wait_seconds = max(1, int(INTERVAL_SECONDS[timeframe] - (now - last_request)))
            raise MarketDataUnavailable(
                f"{symbol}: local cache has {len(cached)}/{count} required candles and the next IG "
                f"history refresh is throttled for {wait_seconds}s. No signal or order was generated."
            )
        if self._history_quota_exhausted:
            raise MarketDataUnavailable(
                f"{symbol}: IG weekly historical allowance is exhausted and the local cache has "
                f"{len(cached)}/{count} required candles. No signal or order was generated."
            )
        request_count = count if len(cached) < count else 2
        resolution = RESOLUTIONS[timeframe]
        # Persist before the request so restarts cannot hammer a failing endpoint.
        self.candles.set_meta(refresh_key, now)
        try:
            payload = self._get(f"/prices/{instrument['epic']}/{resolution}/{request_count}", version="2")
        except HistoricalQuotaExceeded:
            self._history_quota_exhausted = True
            if len(cached) >= count:
                return cached
            raise MarketDataUnavailable(
                f"{symbol}: IG weekly historical allowance is exhausted and the local cache has "
                f"{len(cached)}/{count} required candles. No signal or order was generated."
            ) from None
        rows = []
        for price in payload.get("prices", []):
            if price.get("complete") is False:
                continue
            def mid(field):
                item = price.get(field) or {}
                bid, ask = item.get("bid"), item.get("ask")
                if bid is not None and ask is not None:
                    return (float(bid) + float(ask)) / 2
                value = item.get("lastTraded")
                return float(value) if value is not None else None
            values = [mid("openPrice"), mid("highPrice"), mid("lowPrice"), mid("closePrice")]
            if any(value is None for value in values):
                continue
            stamp = price.get("snapshotTimeUTC") or price.get("snapshotTime")
            rows.append({"time": pd.to_datetime(stamp, utc=True), "open": values[0], "high": values[1],
                         "low": values[2], "close": values[3],
                         "tick_volume": float(price.get("lastTradedVolume") or 0)})
        if not rows:
            if len(cached) >= count:
                return cached
            raise RuntimeError(f"IG returned no complete prices for {symbol}")
        fresh = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        self.candles.put(symbol, timeframe, fresh)
        combined = self.candles.get(symbol, timeframe, count)
        if len(combined) < count:
            raise RuntimeError(f"Only {len(combined)} cached candles are available for {symbol}; {count} required")
        return combined

    def cached_bars(self, symbol: str, count: int) -> pd.DataFrame:
        """Read model input without consuming IG's historical REST allowance."""
        timeframe = self.settings.data["timeframe"]
        cached = self.candles.get(symbol, timeframe, count)
        if len(cached) < count:
            raise MarketDataUnavailable(
                f"{symbol}: streaming cache is warming ({len(cached)}/{count} completed {timeframe} candles). "
                "No signal or order was generated."
            )
        return cached

    def open_positions(self, symbol: str | None = None):
        payload = self._get("/positions", version="2")
        epic = self._instrument(symbol)["epic"] if symbol else None
        positions = [item for item in payload.get("positions", [])
                     if epic is None or (item.get("market") or {}).get("epic") == epic]
        return tuple(positions)

    def validate_instrument(self, symbol: str) -> None:
        configured = self._instrument(symbol)
        market = self._get(f"/markets/{configured['epic']}", version="3")
        instrument, rules = market.get("instrument") or {}, market.get("dealingRules") or {}
        if instrument.get("epic") and instrument["epic"] != configured["epic"]:
            raise RuntimeError(f"IG epic mismatch for {symbol}")
        available = {item.get("code") for item in instrument.get("currencies", [])}
        if available and configured["currency_code"] not in available:
            raise ValueError(f"Configured currency is unavailable for {symbol}; choices={sorted(available)}")
        minimum = float((rules.get("minDealSize") or {}).get("value") or 0)
        if float(configured["deal_size"]) < minimum:
            raise ValueError(f"Configured deal size for {symbol} is below IG minimum {minimum}")

    def market_order(self, symbol: str, side: str, atr: float):
        self.assert_execution_ready()
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"Invalid side: {side}")
        instrument = self._instrument(symbol)
        market = self._get(f"/markets/{instrument['epic']}", version="3")
        snapshot, rules = market.get("snapshot") or {}, market.get("dealingRules") or {}
        if snapshot.get("marketStatus") != "TRADEABLE":
            raise RuntimeError(f"IG market is not tradeable for {symbol}")
        bid, offer = float(snapshot["bid"]), float(snapshot["offer"])
        spread = offer - bid
        if spread > float(instrument["max_spread"]):
            raise RuntimeError(f"Spread blocked for {symbol}: {spread}")
        size = float(instrument["deal_size"])
        minimum = float((rules.get("minDealSize") or {}).get("value") or 0)
        if size < minimum:
            raise ValueError(f"Configured IG deal size {size} is below broker minimum {minimum}; trade blocked")
        price = offer if side == "BUY" else bid
        stop_distance = max(float(atr) * self.settings.data["risk"]["atr_stop_multiplier"],
                            float(instrument["minimum_stop_distance"]))
        reward = self.settings.data["risk"]["reward_to_risk"]
        digits = int(instrument["price_digits"])
        stop_level = round(price - stop_distance if side == "BUY" else price + stop_distance, digits)
        limit_level = round(price + stop_distance * reward if side == "BUY" else price - stop_distance * reward, digits)
        reference = f"fxbot-{uuid.uuid4().hex[:20]}"
        response = self.session.post(f"{self.base_url}/positions/otc", headers={"Version": "2", "Content-Type": "application/json"},
            json={"currencyCode": instrument["currency_code"], "dealReference": reference,
                  "direction": side, "epic": instrument["epic"], "expiry": instrument.get("expiry", "DFB"),
                  "forceOpen": True, "guaranteedStop": False, "orderType": "MARKET", "size": size,
                  "stopLevel": stop_level, "limitLevel": limit_level, "timeInForce": "FILL_OR_KILL",
                  "trailingStop": False}, timeout=30)
        self._raise(response, f"IG {side} order")
        deal_reference = response.json().get("dealReference")
        if not deal_reference:
            raise RuntimeError("IG order response omitted dealReference")
        confirmation = self._confirmation(deal_reference)
        if confirmation.get("dealStatus") != "ACCEPTED" or confirmation.get("status") == "REJECTED":
            raise RuntimeError(f"IG order rejected: {confirmation.get('reason')}")
        request = SimpleNamespace(volume=size, sl=stop_level, tp=limit_level)
        return SimpleNamespace(request=request, price=float(confirmation.get("level") or price),
                               order=confirmation.get("dealId") or deal_reference,
                               comment=confirmation.get("reason") or "SUCCESS")

    def _confirmation(self, reference: str) -> dict:
        for _ in range(10):
            response = self.session.get(f"{self.base_url}/confirms/{reference}", headers={"Version": "1"}, timeout=15)
            if response.status_code == 200:
                return response.json()
            if response.status_code != 404:
                self._raise(response, "IG deal confirmation")
            time.sleep(1)
        raise RuntimeError("Timed out waiting for IG deal confirmation")

    def _instrument(self, symbol: str) -> dict:
        try:
            return self.settings.data["instruments"][symbol]
        except KeyError as exc:
            raise ValueError(f"No IG instrument mapping for {symbol}") from exc

    def _get(self, path: str, version: str) -> dict:
        response = self.session.get(f"{self.base_url}{path}", headers={"Version": version}, timeout=30)
        self._raise(response, f"IG GET {path}")
        return response.json()

    @staticmethod
    def _raise(response, operation: str) -> None:
        if response.ok:
            return
        try:
            detail = response.json().get("errorCode") or response.json()
        except ValueError:
            detail = response.text[:300]
        error_code = str(detail)
        if error_code == "error.public-api.exceeded-account-historical-data-allowance":
            raise HistoricalQuotaExceeded(operation, response.status_code, error_code)
        raise IGAPIError(operation, response.status_code, error_code)
