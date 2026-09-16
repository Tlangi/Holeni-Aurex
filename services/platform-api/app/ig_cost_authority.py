"""Governed IG ZA cost evidence for short-horizon research outcomes."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


COST_AUTHORITY_VERSION = "IG_ZA_SPREAD_ONLY_NO_ROLLOVER_COHORT_V1"
LONDON = ZoneInfo("Europe/London")


def crosses_ig_funding_boundary(decision_at_utc: datetime,
                                max_holding_minutes: int) -> bool:
    """Whether the conservative full holding window crosses 22:00 London.

    A boundary at the entry instant is treated as a crossing. The caller must
    exclude the row instead of assuming a financing rate.
    """
    if (decision_at_utc.tzinfo is None or decision_at_utc.utcoffset() != timedelta(0)
            or max_holding_minutes < 1):
        raise ValueError("UTC decision and positive holding window required")
    start = decision_at_utc.astimezone(LONDON)
    end = (decision_at_utc + timedelta(minutes=max_holding_minutes)).astimezone(LONDON)
    day = start.date()
    while day <= end.date():
        boundary = datetime.combine(day, datetime.min.time(), LONDON).replace(hour=22)
        if start <= boundary < end:
            return True
        day += timedelta(days=1)
    return False


def research_cost_policy(*, slippage_bps_per_side: float) -> dict[str, object]:
    """Costs valid only after the no-rollover cohort gate has passed."""
    if slippage_bps_per_side < 0:
        raise ValueError("Slippage cannot be negative")
    return {"version": COST_AUTHORITY_VERSION,
            "slippage_bps_per_side": float(slippage_bps_per_side),
            "commission_bps_round_trip": 0.0,
            "financing_bps_per_day": 0.0,
            "financing_rollover_hour_utc": None}
