from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Stage3CanaryInput:
    selected_market: str
    attempt_market: str
    requested_size: Decimal
    broker_minimum_size: Decimal
    stop_present: bool
    target_present: bool
    open_position_count: int
    prior_submission_count: int
    unresolved_submission: bool
    averaging_or_grid: bool = False


def stage3_canary_rejection(item: Stage3CanaryInput) -> str | None:
    """Dormant policy for the eventual first IG Demo lifecycle proof."""
    if item.attempt_market != item.selected_market:
        return "CANARY_SINGLE_MARKET_ONLY"
    if item.requested_size != item.broker_minimum_size:
        return "CANARY_BROKER_MINIMUM_SIZE_ONLY"
    if not item.stop_present or not item.target_present:
        return "CANARY_PROTECTION_REQUIRED"
    if item.open_position_count != 0:
        return "CANARY_ONE_POSITION_ONLY"
    if item.prior_submission_count != 0 or item.unresolved_submission:
        return "CANARY_NO_RETRY_AFTER_AMBIGUITY"
    if item.averaging_or_grid:
        return "CANARY_AVERAGING_FORBIDDEN"
    return None
