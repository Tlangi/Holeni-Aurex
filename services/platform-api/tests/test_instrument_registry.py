from __future__ import annotations

import pytest

from app.ig_demo import IGDemoClient, IGDemoUnavailable
from app.instrument_registry import (
    INSTRUMENTS, SUPPORTED_SYMBOLS, TIER_2_SYMBOLS, TIER_3_SYMBOLS, normalized_symbol,
)


def test_registry_defines_all_markets_once_with_explicit_tiers() -> None:
    assert len(INSTRUMENTS) == len(SUPPORTED_SYMBOLS) == 9
    assert TIER_2_SYMBOLS == {"GBPJPY", "EURJPY", "XAUUSD"}
    assert TIER_3_SYMBOLS == {"AUDJPY", "USDZAR"}
    assert INSTRUMENTS["XAUUSD"].asset_class == "METAL"
    assert INSTRUMENTS["USDZAR"].research_only is True
    assert all(INSTRUMENTS[symbol].research_only for symbol in TIER_3_SYMBOLS)


def test_symbol_normalization_accepts_slashes_but_rejects_unknown_markets() -> None:
    assert normalized_symbol("gbp/jpy") == "GBPJPY"
    with pytest.raises(ValueError, match="Unsupported market"):
        normalized_symbol("BTCUSD")


def test_ig_resolution_selects_only_exact_non_expiring_cfd(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(IGDemoClient)
    monkeypatch.setattr(client, "search_markets", lambda _: [
        {"epic": "CS.D.GBPJPY.CFD.IP", "instrumentName": "GBP/JPY", "expiry": "-"},
        {"epic": "CS.D.GBPJPY.MINI.IP", "instrumentName": "GBP/JPY Mini", "expiry": "-"},
        {"epic": "DO.D.GBPYEN.1.IP", "instrumentName": "GBP/JPY", "expiry": "01-SEP-26"},
    ])
    assert client.resolve_cash_cfd("GBPJPY", expected_name="GBP/JPY")["epic"] == "CS.D.GBPJPY.CFD.IP"


def test_ig_resolution_fails_closed_when_exact_market_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(IGDemoClient)
    monkeypatch.setattr(client, "search_markets", lambda _: [
        {"epic": "CS.D.ONE.CFD.IP", "instrumentName": "Spot Gold ($1)", "expiry": "-"},
        {"epic": "CS.D.TWO.CFD.IP", "instrumentName": "Spot Gold ($1)", "expiry": "-"},
    ])
    with pytest.raises(IGDemoUnavailable, match="ambiguous"):
        client.resolve_cash_cfd("GOLD", expected_name="Spot Gold ($1)")
