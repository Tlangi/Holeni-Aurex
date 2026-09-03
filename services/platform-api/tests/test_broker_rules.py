from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.ig_demo import IGDemoClient, IGDemoUnavailable, parse_broker_market_rule


def payload(unit: str = "POINTS") -> dict[str, object]:
    return {
        "instrument": {
            "epic": "CS.D.EURUSD.CFD.IP", "lotSize": 10,
            "valueOfOnePip": "10.00",
            "marginFactor": "3.5",
            "expiry": "-", "forceOpenAllowed": True,
            "currencies": [{"code": "USD", "isDefault": True}],
        },
        "dealingRules": {
            "minDealSize": {"value": 0.5, "unit": "POINTS"},
            "minNormalStopOrLimitDistance": {"value": 2, "unit": unit},
            "marketOrderPreference": "AVAILABLE_DEFAULT_ON",
        },
        "snapshot": {
            "marketStatus": "TRADEABLE", "bid": 1.10, "offer": 1.1002,
            "scalingFactor": 10000,
        },
    }


def test_rule_uses_broker_minimum_and_quote_currency_conversion() -> None:
    rule = parse_broker_market_rule(
        payload(), epic="CS.D.EURUSD.CFD.IP", quote_currency="USD",
        quote_to_zar=Decimal("18.25"), observed_at_utc=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    assert rule.min_deal_size == Decimal("0.5")
    assert rule.size_increment == rule.min_deal_size
    assert rule.size_increment_source == "CONSERVATIVE_MINIMUM_FALLBACK"
    assert rule.size_increment_authoritative is False
    assert len(rule.raw_rule_sha256) == 64
    assert rule.min_stop_distance == Decimal("0.0002")
    assert rule.value_per_price_unit_zar == Decimal("1825000.00")
    assert rule.margin_factor_pct == Decimal("3.5")


def test_percentage_stop_is_converted_to_price_distance() -> None:
    data = payload("PERCENTAGE")
    data["dealingRules"]["minNormalStopOrLimitDistance"]["value"] = 1
    rule = parse_broker_market_rule(
        data, epic="CS.D.EURUSD.CFD.IP", quote_currency="USD", quote_to_zar=Decimal("18")
    )
    assert rule.min_stop_distance == Decimal("0.011001")


def test_incomplete_or_mismatched_rules_fail_closed() -> None:
    data = payload()
    data["instrument"]["epic"] = "CS.D.GBPUSD.CFD.IP"
    with pytest.raises(IGDemoUnavailable):
        parse_broker_market_rule(
            data, epic="CS.D.EURUSD.CFD.IP", quote_currency="USD", quote_to_zar=Decimal("18")
        )


def test_inverse_broker_quote_is_converted_without_guessing() -> None:
    client = object.__new__(IGDemoClient)
    client._get = lambda path, version: {
        "markets": [{"instrumentName": "USD/JPY", "bid": 149.9, "offer": 150.1}]
    }
    assert client._fx_mid("JPY", "USD") == Decimal("1") / Decimal("150.0")


def test_allow_list_accepts_index_cfd_and_rejects_other_products() -> None:
    IGDemoClient._validate_cfd_epic("IX.D.DAX.BMU.IP")
    IGDemoClient._validate_cfd_epic("CS.D.EURUSD.CFD.IP")
    with pytest.raises(ValueError):
        IGDemoClient._validate_cfd_epic("OP.D.DAX3.020000P.IP")


def test_transaction_history_uses_bounded_v2_query() -> None:
    client = object.__new__(IGDemoClient)
    observed = {}
    def fake_get(path: str, *, version: str, params: dict[str, object]):
        observed.update({"path": path, "version": version, "params": params})
        return {"transactions": []}
    client._get_params = fake_get
    assert client.transactions(from_date="2026-09-01", to_date="2026-09-01") == []
    assert observed == {
        "path": "/history/transactions", "version": "2",
        "params": {"type": "ALL", "from": "2026-09-01", "to": "2026-09-01",
                   "pageSize": 100, "pageNumber": 1},
    }


def test_transaction_history_rejects_unbounded_or_invalid_dates() -> None:
    client = object.__new__(IGDemoClient)
    with pytest.raises(ValueError):
        client.transactions(from_date="2026-09-02", to_date="2026-09-01")
    with pytest.raises(ValueError):
        client.transactions(from_date="not-a-date", to_date="2026-09-01")
