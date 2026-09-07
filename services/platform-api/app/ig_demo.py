from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

import requests

from app.config import Settings


class IGDemoUnavailable(RuntimeError):
    """Safe public error for IG connection and response failures."""

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class IGAccount:
    account_id: str
    account_name: str
    currency: str
    balance: Decimal
    profit_loss: Decimal
    available: Decimal
    margin_used: Decimal

    @property
    def equity(self) -> Decimal:
        return self.balance + self.profit_loss

    @property
    def masked_account_id(self) -> str:
        suffix = self.account_id[-4:] if self.account_id else ""
        return f"••••{suffix}"


@dataclass(frozen=True)
class CurrencyRate:
    base_currency: str
    quote_currency: str
    rate: Decimal
    source: str
    observed_at_utc: datetime


@dataclass(frozen=True)
class BrokerMarketRule:
    epic: str
    market_status: str
    min_deal_size: Decimal
    size_increment: Decimal
    size_increment_source: str
    size_increment_authoritative: bool
    raw_rule_sha256: str
    min_stop_distance: Decimal
    stop_distance_unit: str
    lot_size: Decimal
    value_per_price_unit_zar: Decimal
    source_currency: str
    deal_currency: str
    expiry: str
    force_open_allowed: bool
    market_order_preference: str
    margin_factor_pct: Decimal | None
    current_bid: Decimal
    current_ask: Decimal
    observed_at_utc: datetime


class IGDemoClient:
    """Read-only IG demo client. This class intentionally has no order methods."""

    base_url = "https://demo-api.ig.com/gateway/deal"

    def __init__(self, settings: Settings) -> None:
        if settings.ig_environment != "demo" or settings.broker_environment != "demo":
            raise ValueError("IG demo client cannot use a live environment")
        if not settings.ig_configured:
            raise ValueError("IG demo configuration is incomplete")
        self.settings = settings
        self.session = requests.Session()
        self.account_id = ""
        self.cst = ""
        self.security_token = ""
        self.lightstreamer_endpoint = ""

    def __enter__(self) -> "IGDemoClient":
        self.authenticate()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def authenticate(self) -> None:
        try:
            response = self.session.post(
                f"{self.base_url}/session",
                headers={
                    "X-IG-API-KEY": self.settings.ig_api_key,
                    "Version": "2",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "identifier": self.settings.ig_username,
                    "password": self.settings.ig_password,
                    "encryptedPassword": False,
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise IGDemoUnavailable("IG demo is unreachable") from exc

        if response.status_code != 200:
            payload = self._json(response)
            error_code = str(payload.get("errorCode") or "unknown_error")
            raise IGDemoUnavailable(
                f"IG demo authentication failed ({response.status_code}, {error_code})",
                error_code=error_code,
            )

        cst = response.headers.get("CST")
        security_token = response.headers.get("X-SECURITY-TOKEN")
        payload = self._json(response)
        account_id = str(payload.get("currentAccountId") or "")
        if not cst or not security_token or not account_id:
            raise IGDemoUnavailable("IG demo authentication response was incomplete")
        if account_id != self.settings.ig_account_id:
            raise IGDemoUnavailable("IG demo returned a different account than IG_ACCOUNT_ID")

        self.account_id = account_id
        self.cst = cst
        self.security_token = security_token
        self.lightstreamer_endpoint = str(payload.get("lightstreamerEndpoint") or "")
        if not self.lightstreamer_endpoint:
            raise IGDemoUnavailable("IG demo authentication omitted the streaming endpoint")
        self.session.headers.update(
            {
                "X-IG-API-KEY": self.settings.ig_api_key,
                "CST": cst,
                "X-SECURITY-TOKEN": security_token,
                "Accept": "application/json",
            }
        )

    def account(self) -> IGAccount:
        payload = self._get("/accounts", version="1")
        accounts = payload.get("accounts") or []
        account = next((item for item in accounts if item.get("accountId") == self.account_id), None)
        if not account:
            raise IGDemoUnavailable("Configured IG demo account was not returned")
        balance = account.get("balance") or {}
        return IGAccount(
            account_id=self.account_id,
            account_name=str(account.get("accountName") or "IG demo account"),
            currency=str(account.get("currency") or "").upper(),
            balance=Decimal(str(balance.get("balance") or 0)),
            profit_loss=Decimal(str(balance.get("profitLoss") or 0)),
            available=Decimal(str(balance.get("available") or 0)),
            margin_used=Decimal(str(balance.get("deposit") or 0)),
        )

    def positions(self) -> list[dict[str, Any]]:
        payload = self._get("/positions", version="2")
        return list(payload.get("positions") or [])

    def working_orders(self) -> list[dict[str, Any]]:
        """Read IG working orders for reconciliation; this method cannot mutate them."""
        payload = self._get("/workingorders", version="2")
        return list(payload.get("workingOrders") or [])

    def transactions(self, *, from_date: str, to_date: str) -> list[dict[str, Any]]:
        """Read a bounded IG Demo transaction window for reconciliation evidence."""
        try:
            start = datetime.strptime(from_date, "%Y-%m-%d").date()
            end = datetime.strptime(to_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Transaction dates must use YYYY-MM-DD") from exc
        if start > end or (end-start).days > 31:
            raise ValueError("Transaction history window must be chronological and at most 31 days")
        payload = self._get_params(
            "/history/transactions", version="2",
            params={"type": "ALL", "from": from_date, "to": to_date,
                    "pageSize": 100, "pageNumber": 1},
        )
        return list(payload.get("transactions") or [])

    def historical_prices(
        self, epic: str, *, resolution: str = "MINUTE_15", count: int = 500
    ) -> list[dict[str, Any]]:
        """Read completed historical prices from IG demo; never places an order."""
        self._validate_cfd_epic(epic)
        if resolution not in {"MINUTE_5", "MINUTE_15"}:
            raise ValueError("Unsupported historical resolution")
        if count < 1 or count > 10000:
            raise ValueError("Historical count must be between 1 and 10000")
        # v2 exposes only account-local ``snapshotTime``. v3 also supplies
        # ``snapshotTimeUTC``, which is mandatory for canonical persistence.
        page_size = min(count, 1000)
        prices: list[dict[str, Any]] = []
        page_number = 1
        while len(prices) < count:
            payload = self._get_params(
                f"/prices/{epic}", version="3",
                params={"resolution": resolution, "pageSize": page_size,
                        "pageNumber": page_number},
            )
            page = [row for row in list(payload.get("prices") or [])
                    if row.get("snapshotTimeUTC")]
            prices.extend(page)
            total_pages = max(1, int(payload.get("metadata", {}).get(
                "pageData", {},
            ).get("totalPages") or 1))
            if page_number >= total_pages or not page:
                break
            page_number += 1
        return prices[:count]

    def historical_prices_page(
        self, epic: str, *, resolution: str = "MINUTE_5", page_size: int = 500,
        page_number: int = 1,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read one explicit IG v3 history page so callers can enforce a quota budget."""
        self._validate_cfd_epic(epic)
        if resolution != "MINUTE_5":
            raise ValueError("Canonical backfill must use MINUTE_5")
        if page_size < 1 or page_size > 1000 or page_number < 1:
            raise ValueError("Invalid historical page request")
        path = (
            f"/prices/{epic}?resolution={resolution}&pageSize={page_size}"
            f"&pageNumber={page_number}"
        )
        payload = self._get(path, version="3")
        page_data = payload.get("metadata", {}).get("pageData", {})
        total_pages = max(1, int(page_data.get("totalPages") or 1))
        return list(payload.get("prices") or []), total_pages

    def historical_prices_range(
        self, epic: str, *, start_utc: datetime, end_utc: datetime,
        resolution: str = "MINUTE_5", page_size: int = 64,
    ) -> list[dict[str, Any]]:
        """Read one exact bounded UTC gap window; never substitute the newest page."""
        self._validate_cfd_epic(epic)
        if resolution != "MINUTE_5" or page_size < 1 or page_size > 500:
            raise ValueError("Invalid bounded historical range request")
        start = start_utc.astimezone(timezone.utc)
        end = end_utc.astimezone(timezone.utc)
        if start > end or (end - start).total_seconds() > 7 * 24 * 3600:
            raise ValueError("Historical recovery window must be chronological and no longer than seven days")
        # IG interprets v3 ``from``/``to`` in the account's price timezone,
        # even though returned rows also include an unambiguous UTC timestamp.
        # Resolve the offset from a broker-supplied timestamp pair; never infer
        # it from the server or machine timezone.
        probe = self._get_params(
            f"/prices/{epic}", version="3",
            params={"resolution": resolution, "pageSize": 1, "pageNumber": 1},
        )
        probe_rows = list(probe.get("prices") or [])
        if not probe_rows:
            raise IGDemoUnavailable("IG demo did not expose price timezone evidence",
                                    error_code="PRICE_TIMEZONE_UNAVAILABLE")
        utc_text = str(probe_rows[0].get("snapshotTimeUTC") or "")
        local_text = str(probe_rows[0].get("snapshotTime") or "")
        try:
            utc_probe = datetime.fromisoformat(utc_text).replace(tzinfo=None)
            local_probe = datetime.strptime(local_text, "%Y/%m/%d %H:%M:%S")
        except ValueError as exc:
            raise IGDemoUnavailable("IG demo returned invalid price timezone evidence",
                                    error_code="PRICE_TIMEZONE_INVALID") from exc
        price_offset = local_probe - utc_probe
        if abs(price_offset.total_seconds()) > 14 * 3600 or price_offset.total_seconds() % 900:
            raise IGDemoUnavailable("IG demo returned implausible price timezone evidence",
                                    error_code="PRICE_TIMEZONE_INVALID")
        local_start = start.replace(tzinfo=None) + price_offset
        local_end = end.replace(tzinfo=None) + price_offset
        payload = self._get_params(
            f"/prices/{epic}", version="3",
            params={"resolution": resolution, "from": local_start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "to": local_end.strftime("%Y-%m-%dT%H:%M:%S"), "pageSize": page_size,
                    "pageNumber": 1},
        )
        prices = list(payload.get("prices") or [])
        return [row for row in prices if row.get("snapshotTimeUTC") and
                start.replace(tzinfo=None) <= datetime.fromisoformat(
                    str(row["snapshotTimeUTC"]),
                ).replace(tzinfo=None) <= end.replace(tzinfo=None)]

    def market_details(self, epic: str) -> dict[str, Any]:
        """Return broker dealing rules for one allow-listed demo CFD epic."""
        self._validate_cfd_epic(epic)
        return self._get(f"/markets/{epic}", version="3")

    def search_markets(self, search_term: str) -> list[dict[str, Any]]:
        """Return bounded read-only IG market search results for instrument discovery."""
        normalized = search_term.strip().upper().replace("/", "")
        if not normalized or len(normalized) > 40 or not normalized.isalnum():
            raise ValueError("Invalid IG market search term")
        payload = self._get(f"/markets?searchTerm={normalized}", version="1")
        return list(payload.get("markets") or [])[:50]

    def resolve_cash_cfd(self, search_term: str, *, expected_name: str) -> dict[str, Any]:
        """Resolve one exact non-expiring CFD and reject ambiguous or derivative matches."""
        matches = []
        for market in self.search_markets(search_term):
            if str(market.get("instrumentName") or "").strip().upper() != expected_name.upper():
                continue
            epic = str(market.get("epic") or "")
            if str(market.get("expiry") or "-") != "-":
                continue
            try:
                self._validate_cfd_epic(epic)
            except ValueError:
                continue
            matches.append(market)
        if len(matches) != 1:
            raise IGDemoUnavailable(
                f"IG demo market resolution was {'ambiguous' if matches else 'empty'} for {expected_name}"
            )
        return matches[0]

    @staticmethod
    def _validate_cfd_epic(epic: str) -> None:
        """Permit provisioned spot/FX and index CFDs while rejecting options/futures/shares."""
        if not epic.endswith(".IP") or not epic.startswith(("CS.D.", "IX.D.")):
            raise ValueError("Only provisioned FX and index CFD market epics are supported")

    def broker_market_rule(
        self, epic: str, *, quote_currency: str, quote_to_zar: Decimal
    ) -> BrokerMarketRule:
        return parse_broker_market_rule(
            self.market_details(epic),
            epic=epic,
            quote_currency=quote_currency,
            quote_to_zar=quote_to_zar,
        )

    def zar_rate(self, source_currency: str) -> CurrencyRate:
        base = source_currency.upper()
        observed_at = datetime.now(timezone.utc)
        if base == "ZAR":
            return CurrencyRate("ZAR", "ZAR", Decimal("1"), "identity", observed_at)
        try:
            rate = self._fx_mid(base, "ZAR")
            source = "ig_demo_mid"
        except IGDemoUnavailable:
            # Less commonly traded quote currencies may not have a direct ZAR
            # market. Cross only through broker-quoted USD legs; never guess.
            if base == "USD":
                raise
            rate = self._fx_mid(base, "USD") * self._fx_mid("USD", "ZAR")
            source = "ig_demo_cross_usd_mid"
        if rate <= 0:
            raise IGDemoUnavailable("IG demo returned an invalid ZAR conversion rate")
        return CurrencyRate(base, "ZAR", rate, source, observed_at)

    def _fx_mid(self, base: str, quote: str) -> Decimal:
        for search, inverted in ((f"{base}{quote}", False), (f"{quote}{base}", True)):
            payload = self._get(f"/markets?searchTerm={search}", version="1")
            markets = payload.get("markets") or []
            for market in markets:
                name = "".join(
                    character for character in str(market.get("instrumentName") or "").upper()
                    if character.isalpha()
                )
                direct_index = name.find(f"{base}{quote}")
                inverse_index = name.find(f"{quote}{base}")
                if direct_index < 0 and inverse_index < 0:
                    continue
                snapshot = market.get("snapshot") or market
                bid, offer = snapshot.get("bid"), snapshot.get("offer")
                if bid is None or offer is None:
                    continue
                mid = (Decimal(str(bid)) + Decimal(str(offer))) / Decimal("2")
                pair_is_inverse = inverse_index >= 0 and direct_index < 0
                if mid <= 0:
                    continue
                return Decimal("1") / mid if pair_is_inverse else mid
        raise IGDemoUnavailable(f"IG demo has no quoted {base}/{quote} conversion market")

    def close(self) -> None:
        # Close the local pool without immediately revoking the IG session.
        # Rapid DELETE/login churn can invalidate a newly issued client token
        # when API, bootstrap, and streaming workers start close together.
        self.session.close()
        self.account_id = ""
        self.cst = ""
        self.security_token = ""
        self.lightstreamer_endpoint = ""

    def _get(self, path: str, *, version: str) -> dict[str, Any]:
        if not self.account_id:
            raise IGDemoUnavailable("IG demo session is not authenticated")
        try:
            response = self.session.get(
                f"{self.base_url}{path}", headers={"Version": version}, timeout=20
            )
        except requests.RequestException as exc:
            raise IGDemoUnavailable("IG demo request failed") from exc
        if response.status_code != 200:
            payload = self._json(response)
            error_code = str(payload.get("errorCode") or "unknown_error")
            raise IGDemoUnavailable(
                f"IG demo request failed ({response.status_code}, {error_code})",
                error_code=error_code,
            )
        return self._json(response)

    def _get_params(
        self, path: str, *, version: str, params: dict[str, object],
    ) -> dict[str, Any]:
        if not self.account_id:
            raise IGDemoUnavailable("IG demo session is not authenticated")
        try:
            response = self.session.get(
                f"{self.base_url}{path}", headers={"Version": version}, params=params, timeout=20,
            )
        except requests.RequestException as exc:
            raise IGDemoUnavailable("IG demo request failed") from exc
        if response.status_code != 200:
            payload = self._json(response)
            error_code = str(payload.get("errorCode") or "unknown_error")
            raise IGDemoUnavailable(
                f"IG demo request failed ({response.status_code}, {error_code})",
                error_code=error_code,
            )
        return self._json(response)

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise IGDemoUnavailable("IG demo returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise IGDemoUnavailable("IG demo returned an unexpected response")
        return payload


def parse_broker_market_rule(
    payload: dict[str, Any], *, epic: str, quote_currency: str, quote_to_zar: Decimal,
    observed_at_utc: datetime | None = None,
) -> BrokerMarketRule:
    """Validate IG's market-detail response and derive conservative sizing inputs.

    Risk calculations use raw price distance, so the value multiplier is the
    instrument lot size converted from quote currency to ZAR. IG does not expose
    a separate deal-size increment; using its minimum deal size as the increment
    is deliberately conservative and never approves a sub-minimum size.
    """
    instrument = payload.get("instrument") or {}
    rules = payload.get("dealingRules") or {}
    snapshot = payload.get("snapshot") or {}
    returned_epic = str(instrument.get("epic") or "")
    if returned_epic and returned_epic != epic:
        raise IGDemoUnavailable("IG demo returned dealing rules for a different market")
    minimum = rules.get("minDealSize") or {}
    stop_rule = rules.get("minNormalStopOrLimitDistance") or {}
    try:
        min_deal_size = Decimal(str(minimum["value"]))
        stop_value = Decimal(str(stop_rule["value"]))
        lot_size = Decimal(str(instrument["lotSize"]))
        value_of_one_pip = Decimal(str(instrument["valueOfOnePip"]))
        scaling_factor = Decimal(str(snapshot["scalingFactor"]))
        rate = Decimal(str(quote_to_zar))
        current_bid = Decimal(str(snapshot["bid"]))
        current_ask = Decimal(str(snapshot["offer"]))
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise IGDemoUnavailable("IG demo market rules were incomplete") from exc
    if any(value <= 0 for value in (
        min_deal_size, stop_value, lot_size, value_of_one_pip, scaling_factor, rate, current_bid,
    )) or current_ask <= current_bid:
        raise IGDemoUnavailable("IG demo market rules contained non-positive values")
    unit = str(stop_rule.get("unit") or "").upper()
    if unit == "PERCENTAGE":
        bid, offer = snapshot.get("bid"), snapshot.get("offer")
        if bid is None or offer is None:
            raise IGDemoUnavailable("IG demo percentage stop rule omitted a market price")
        mid = (Decimal(str(bid)) + Decimal(str(offer))) / Decimal("2")
        min_stop_distance = mid * stop_value / Decimal("100")
    elif unit == "POINTS":
        # IG levels use decimal FX prices while its dealing rule is expressed in
        # broker points. scalingFactor is the documented multiplier between them.
        min_stop_distance = stop_value / scaling_factor
    else:
        raise IGDemoUnavailable("IG demo returned an unsupported stop-distance unit")
    margin_raw = instrument.get("marginFactor")
    try:
        margin_factor = Decimal(str(margin_raw)) if margin_raw is not None else None
    except (ValueError, ArithmeticError):
        margin_factor = None
    if margin_factor is not None and margin_factor <= 0:
        margin_factor = None
    return BrokerMarketRule(
        epic=epic,
        market_status=str(snapshot.get("marketStatus") or "UNKNOWN").upper(),
        min_deal_size=min_deal_size,
        size_increment=min_deal_size,
        size_increment_source="CONSERVATIVE_MINIMUM_FALLBACK",
        size_increment_authoritative=False,
        raw_rule_sha256=sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
        min_stop_distance=min_stop_distance,
        stop_distance_unit=unit,
        lot_size=lot_size,
        # valueOfOnePip is for one contract. One raw price unit contains
        # scalingFactor pips, then quote currency is converted to ZAR.
        value_per_price_unit_zar=value_of_one_pip * scaling_factor * rate,
        source_currency=quote_currency.upper(),
        deal_currency=_default_deal_currency(instrument),
        expiry=str(instrument.get("expiry") or "-").upper(),
        force_open_allowed=bool(instrument.get("forceOpenAllowed", False)),
        market_order_preference=str(rules.get("marketOrderPreference") or "NOT_AVAILABLE").upper(),
        margin_factor_pct=margin_factor,
        current_bid=current_bid,
        current_ask=current_ask,
        observed_at_utc=observed_at_utc or datetime.now(timezone.utc),
    )


def _default_deal_currency(instrument: dict[str, Any]) -> str:
    currencies = instrument.get("currencies") or []
    selected = next((item for item in currencies if item.get("isDefault")), currencies[0] if currencies else None)
    code = str((selected or {}).get("code") or "").upper()
    if len(code) != 3:
        raise IGDemoUnavailable("IG demo market rules omitted the default dealing currency")
    return code
