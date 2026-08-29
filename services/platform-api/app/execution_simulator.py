from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SimulatedExit:
    closed: bool
    price: Decimal
    reason: str | None


@dataclass(frozen=True)
class TransactionCostEvidence:
    spread_cost_zar: Decimal
    explicit_cost_zar: Decimal
    spread_cost_in_price: bool


def resolve_candle_exit(
    direction: str, *, stop: Decimal, target: Decimal, opened: Decimal,
    high: Decimal, low: Decimal, close: Decimal, holding_candles: int,
    max_holding_candles: int,
) -> SimulatedExit:
    """Conservative OHLC fill resolver shared by replay and shadow execution."""
    if direction == "BUY":
        if opened <= stop:
            return SimulatedExit(True, opened, "STOP_GAP")
        if opened >= target:
            return SimulatedExit(True, target, "TAKE_PROFIT")
        stop_hit, target_hit = low <= stop, high >= target
    elif direction == "SELL":
        if opened >= stop:
            return SimulatedExit(True, opened, "STOP_GAP")
        if opened <= target:
            return SimulatedExit(True, target, "TAKE_PROFIT")
        stop_hit, target_hit = high >= stop, low <= target
    else:
        raise ValueError("Invalid simulated direction")
    if stop_hit:
        return SimulatedExit(True, stop, "STOP_LOSS")
    if target_hit:
        return SimulatedExit(True, target, "TAKE_PROFIT")
    if holding_candles >= max_holding_candles:
        return SimulatedExit(True, close, "MAX_HOLDING_TIME")
    return SimulatedExit(False, close, None)


def entry_price(direction: str, *, midpoint: Decimal, bid: Decimal | None, ask: Decimal | None) -> Decimal:
    if direction == "BUY":
        return ask if ask is not None else midpoint
    if direction == "SELL":
        return bid if bid is not None else midpoint
    raise ValueError("Invalid simulated direction")


def spread_cost(
    *, bid: Decimal | None, ask: Decimal | None, size: Decimal,
    value_per_price_point_zar: Decimal,
) -> Decimal:
    if bid is None or ask is None or ask < bid:
        return Decimal("0")
    return (ask - bid) * size * value_per_price_point_zar


def transaction_cost_evidence(
    *, midpoint: Decimal, bid: Decimal | None, ask: Decimal | None, size: Decimal,
    value_per_price_point_zar: Decimal, fallback_round_trip_cost_bps: Decimal,
) -> TransactionCostEvidence:
    """Capture spread evidence without charging executable bid/ask fills twice."""
    observed = spread_cost(
        bid=bid, ask=ask, size=size, value_per_price_point_zar=value_per_price_point_zar,
    )
    if bid is not None and ask is not None and ask >= bid:
        return TransactionCostEvidence(observed, Decimal("0"), True)
    fallback = midpoint * size * value_per_price_point_zar * fallback_round_trip_cost_bps / Decimal("10000")
    return TransactionCostEvidence(fallback, fallback, False)
