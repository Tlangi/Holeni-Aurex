"""Additive quality policy for the current M5 decision window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class RecentM5WindowResult:
    required_rows: int
    observed_rows: int
    start_utc: datetime | None
    end_utc: datetime | None
    valid_ohlc: bool
    no_duplicates: bool
    no_unresolved_gaps: bool
    explicit_lineage: bool
    passed: bool
    reasons: tuple[str, ...]
    gap_ranges: tuple[tuple[datetime, datetime, int], ...] = ()

    @property
    def completeness_percentage(self) -> float:
        missing = sum(item[2] for item in self.gap_ranges)
        expected = self.observed_rows + missing
        return round(self.observed_rows / expected * 100, 3) if expected else 0.0


def assess_recent_m5_window(
    rows: Sequence[Mapping[str, object]], *, required_rows: int = 2000,
    max_gap_minutes: int = 5,
    is_expected_timestamp: Callable[[datetime], bool] | None = None,
) -> RecentM5WindowResult:
    """Assess only the newest completed M5 rows; never mutates historical data."""
    ordered = sorted(rows, key=lambda row: _as_utc(row.get("open_time_utc")))
    required = max(1, int(required_rows))
    selected = ordered[-required:]
    timestamps = [_as_utc(row.get("open_time_utc")) for row in selected]
    duplicate_free = len(timestamps) == len(set(timestamps))
    valid_ohlc = all(_valid_ohlc(row) for row in selected)
    lineage = all(str(row.get("source") or "").strip() for row in selected)
    gap_items = []
    for left, right in zip(timestamps, timestamps[1:]):
        if (right - left) <= timedelta(minutes=max_gap_minutes):
            continue
        missing = 0
        probe = left + timedelta(minutes=max_gap_minutes)
        while probe < right:
            if is_expected_timestamp is None or is_expected_timestamp(probe):
                missing += 1
            probe += timedelta(minutes=max_gap_minutes)
        if missing:
            gap_items.append((left, right, missing))
    gap_ranges = tuple(gap_items)
    gaps = bool(gap_ranges)
    reasons: list[str] = []
    if len(selected) < required:
        reasons.append("INSUFFICIENT_RECENT_M5_ROWS")
    if not valid_ohlc:
        reasons.append("INVALID_RECENT_M5_OHLC")
    if not duplicate_free:
        reasons.append("DUPLICATE_RECENT_M5_TIMESTAMP")
    if gaps:
        reasons.append("RECENT_M5_GAP")
    if not lineage:
        reasons.append("RECENT_M5_LINEAGE_MISSING")
    return RecentM5WindowResult(
        required, len(selected), timestamps[0] if timestamps else None,
        timestamps[-1] if timestamps else None, valid_ohlc, duplicate_free,
        not gaps, lineage, not reasons, tuple(reasons), gap_ranges,
    )


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Recent M5 rows require UTC timestamps")
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _valid_ohlc(row: Mapping[str, object]) -> bool:
    try:
        opened = Decimal(str(row["open"]))
        high = Decimal(str(row["high"]))
        low = Decimal(str(row["low"]))
        closed = Decimal(str(row["close"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return False
    return min(opened, high, low, closed) > 0 and high >= max(opened, closed, low) and low <= min(opened, closed, high)
