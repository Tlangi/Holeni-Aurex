from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR


@dataclass(frozen=True)
class PositionSizingInput:
    account_equity: Decimal
    risk_percentage: Decimal
    entry_price: Decimal
    stop_price: Decimal
    broker_minimum_size: Decimal
    broker_size_increment: Decimal
    value_per_point_account_currency: Decimal
    margin_factor_pct: Decimal
    available_margin: Decimal


@dataclass(frozen=True)
class PositionSizingResult:
    approved: bool
    maximum_loss_amount: Decimal
    raw_size: Decimal
    broker_rounded_size: Decimal
    estimated_stop_loss: Decimal
    estimated_margin: Decimal
    effective_risk_percentage: Decimal
    rejection_reason: str | None


def calculate_position_size(item: PositionSizingInput) -> PositionSizingResult:
    """Canonical, account-currency sizing. It never rounds risk upward."""
    values = (
        item.account_equity, item.risk_percentage, item.entry_price,
        item.broker_minimum_size, item.broker_size_increment,
        item.value_per_point_account_currency,
    )
    if any(value <= 0 for value in values):
        return _rejected(item, "INVALID_SIZING_INPUT")
    stop_distance = abs(item.entry_price - item.stop_price)
    if stop_distance <= 0:
        return _rejected(item, "INVALID_STOP_DISTANCE")
    maximum_loss = item.account_equity * item.risk_percentage / Decimal("100")
    risk_per_size = stop_distance * item.value_per_point_account_currency
    raw_size = maximum_loss / risk_per_size
    steps = (raw_size / item.broker_size_increment).to_integral_value(rounding=ROUND_FLOOR)
    size = steps * item.broker_size_increment
    if size < item.broker_minimum_size:
        return _result(item, maximum_loss, raw_size, size, "BROKER_MINIMUM_EXCEEDS_RISK")
    stop_loss = size * risk_per_size
    if stop_loss > maximum_loss:
        return _result(item, maximum_loss, raw_size, size, "ROUNDED_SIZE_EXCEEDS_RISK")
    if item.margin_factor_pct <= 0 or item.available_margin < 0:
        return _result(item, maximum_loss, raw_size, size, "MARGIN_EVIDENCE_MISSING")
    margin = (
        item.entry_price * size * item.value_per_point_account_currency
        * item.margin_factor_pct / Decimal("100")
    )
    if margin > item.available_margin:
        return _result(item, maximum_loss, raw_size, size, "INSUFFICIENT_AVAILABLE_MARGIN")
    effective = stop_loss / item.account_equity * Decimal("100")
    return PositionSizingResult(True, maximum_loss, raw_size, size, stop_loss, margin, effective, None)


def _rejected(item: PositionSizingInput, reason: str) -> PositionSizingResult:
    maximum = max(Decimal("0"), item.account_equity * item.risk_percentage / Decimal("100"))
    return PositionSizingResult(False, maximum, Decimal("0"), Decimal("0"), Decimal("0"),
                                Decimal("0"), Decimal("0"), reason)


def _result(item: PositionSizingInput, maximum: Decimal, raw: Decimal, size: Decimal,
            reason: str) -> PositionSizingResult:
    distance = abs(item.entry_price - item.stop_price)
    loss = max(Decimal("0"), size * distance * item.value_per_point_account_currency)
    margin = max(Decimal("0"), item.entry_price * size * item.value_per_point_account_currency
                 * max(item.margin_factor_pct, Decimal("0")) / Decimal("100"))
    effective = loss / item.account_equity * Decimal("100") if item.account_equity > 0 else Decimal("0")
    return PositionSizingResult(False, maximum, raw, size, loss, margin, effective, reason)
