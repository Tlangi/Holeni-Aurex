"""Research-only, source-separated IG M1 continuity and executable quote checks."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Callable

from app.historical_quality import ohlc_valid


def assess_m1_rows(
    rows: list[dict], *, view: str, expected_session: Callable[[datetime], bool],
    now_utc: datetime,
) -> dict[str, object]:
    """Report one authority view; never let research candles satisfy IG execution."""
    if view not in {"RAW_IG", "HYBRID_RESEARCH", "CURRENT_IG_EXECUTION"}:
        raise ValueError("Unknown data-authority view")
    eligible = [row for row in rows if (
        view == "HYBRID_RESEARCH" or
        (str(row["source"]).startswith("IG_LIGHTSTREAMER") if view == "CURRENT_IG_EXECUTION"
         else str(row["source"]).startswith("IG_")))]
    eligible = [row for row in eligible if expected_session(
        row["open_time_utc"].replace(tzinfo=timezone.utc))]
    stamps = Counter(row["open_time_utc"] for row in eligible)
    duplicates = sum(count - 1 for count in stamps.values())
    # Prefer PASS/completed then the freshest row, while preserving raw duplicate evidence.
    chosen = {}
    for row in sorted(eligible, key=lambda r: (bool(r["completed"]),
                        r["quality_status"] == "PASS", r["ingested_at_utc"] or datetime.min)):
        chosen[row["open_time_utc"]] = row
    canonical = sorted(chosen.values(), key=lambda r: r["open_time_utc"])[-2000:]
    if not canonical:
        return {"view": view, "observed": 0, "status": "BLOCKED",
                "reason": "NO_SESSION_M1_ROWS", "duplicates_in_source_rows": duplicates}
    start, end = canonical[0]["open_time_utc"], canonical[-1]["open_time_utc"]
    present = {row["open_time_utc"] for row in canonical}
    missing = []
    at = start
    while at <= end:
        if at not in present and expected_session(at.replace(tzinfo=timezone.utc)):
            missing.append(at)
        at += timedelta(minutes=1)
    invalid_ohlc = missing_bid_ask = crossed = nonpositive_spread = incomplete = quality_failed = 0
    spreads = []
    for row in canonical:
        incomplete += not bool(row["completed"])
        quality_failed += row["quality_status"] != "PASS"
        quotes = [row.get(f"{side}_{part}") for side in ("bid", "ask")
                  for part in ("open", "high", "low", "close")]
        if any(value is None for value in quotes):
            missing_bid_ask += 1
            continue
        if not all(ohlc_valid(*(row[f"{side}_{part}"] for part in
                                 ("open", "high", "low", "close")))
                   for side in ("bid", "ask")):
            invalid_ohlc += 1
        if any(row[f"bid_{part}"] > row[f"ask_{part}"] for part in ("open", "close")):
            crossed += 1
        spread = float(row["ask_close"] - row["bid_close"])
        if spread <= 0:
            nonpositive_spread += 1
        else:
            spreads.append(spread)
    benchmark = median(spreads) if spreads else None
    extreme = sum(value > 10 * benchmark for value in spreads) if benchmark else 0
    last = end.replace(tzinfo=timezone.utc)
    stale = expected_session(now_utc) and last < now_utc - timedelta(minutes=3)
    blocked = any((missing, duplicates, invalid_ohlc, missing_bid_ask, crossed,
                   nonpositive_spread, incomplete, quality_failed, stale))
    return {"view": view, "authority": "RESEARCH_DIAGNOSTIC_ONLY",
            "observed": len(canonical), "first_utc": start.isoformat(),
            "last_utc": end.isoformat(), "missing_expected_session_m1": len(missing),
            "first_missing_utc": missing[0].isoformat() if missing else None,
            "duplicates_in_source_rows": duplicates,
            "missing_bid_ask": missing_bid_ask, "invalid_bid_ask_ohlc": invalid_ohlc,
            "crossed_open_or_close": crossed, "zero_or_negative_close_spread": nonpositive_spread,
            "extreme_close_spread_gt_10x_median": extreme,
            "incomplete": incomplete, "quality_failed": quality_failed,
            "stale_in_session": bool(stale),
            "status": "BLOCKED" if blocked else "PASS"}
