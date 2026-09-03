from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InstrumentDefinition:
    symbol: str
    display_name: str
    ig_epic: str
    asset_class: str
    tier: int
    base_currency: str
    quote_currency: str
    price_digits: int
    pip_size: str
    tick_size: str
    risk_profile: str
    research_only: bool = False


INSTRUMENTS: dict[str, InstrumentDefinition] = {
    "EURUSD": InstrumentDefinition("EURUSD", "EUR/USD", "CS.D.EURUSD.CFD.IP", "FX", 1,
                                   "EUR", "USD", 5, "0.0001", "0.00001", "FX_MAJOR"),
    "GBPUSD": InstrumentDefinition("GBPUSD", "GBP/USD", "CS.D.GBPUSD.CFD.IP", "FX", 1,
                                   "GBP", "USD", 5, "0.0001", "0.00001", "FX_MAJOR"),
    "USDJPY": InstrumentDefinition("USDJPY", "USD/JPY", "CS.D.USDJPY.CFD.IP", "FX", 1,
                                   "USD", "JPY", 3, "0.01", "0.001", "FX_JPY"),
    "GERMANY40": InstrumentDefinition("GERMANY40", "Germany 40 Cash (E1)",
                                      "IX.D.DAX.BMU.IP", "INDEX", 1, "EUR", "EUR", 1,
                                      "1", "0.1", "INDEX_CASH"),
    "GBPJPY": InstrumentDefinition("GBPJPY", "GBP/JPY", "CS.D.GBPJPY.CFD.IP", "FX", 2,
                                   "GBP", "JPY", 3, "0.01", "0.001", "FX_CROSS_JPY"),
    "EURJPY": InstrumentDefinition("EURJPY", "EUR/JPY", "CS.D.EURJPY.CFD.IP", "FX", 2,
                                   "EUR", "JPY", 3, "0.01", "0.001", "FX_CROSS_JPY"),
    "XAUUSD": InstrumentDefinition("XAUUSD", "Spot Gold ($1)", "CS.D.CFDGOLD.BMU.IP", "METAL", 2,
                                   "XAU", "USD", 2, "0.01", "0.01", "SPOT_GOLD"),
    "AUDJPY": InstrumentDefinition("AUDJPY", "AUD/JPY", "CS.D.AUDJPY.CFD.IP", "FX", 3,
                                   "AUD", "JPY", 3, "0.01", "0.001", "FX_CROSS_JPY", True),
    "USDZAR": InstrumentDefinition("USDZAR", "USD/ZAR", "CS.D.USDZAR.CFD.IP", "FX", 3,
                                   "USD", "ZAR", 5, "0.0001", "0.00001", "FX_EMERGING", True),
}

SUPPORTED_SYMBOLS = frozenset(INSTRUMENTS)
TIER_1_SYMBOLS = frozenset(key for key, item in INSTRUMENTS.items() if item.tier == 1)
TIER_2_SYMBOLS = frozenset(key for key, item in INSTRUMENTS.items() if item.tier == 2)
TIER_3_SYMBOLS = frozenset(key for key, item in INSTRUMENTS.items() if item.tier == 3)


def normalized_symbol(value: str) -> str:
    symbol = value.strip().upper().replace("/", "")
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError("Unsupported market")
    return symbol

