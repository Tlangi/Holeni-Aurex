from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.historical_quality import classify_missing_minutes, expected_trading_minutes, ohlc_valid


VALIDATION_VERSION = "HISTORICAL_PARTITION_V3_CANONICAL"


def _naive_utc(value):
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)


def effective_validation_end(requested_end, *, now_utc: datetime | None = None):
    """Never classify minutes which have not completed yet as missing data."""
    end = _naive_utc(requested_end)
    now = _naive_utc(now_utc or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    return min(end, now) if end is not None else None


def effective_observed_end(end, observed, *, active_partition: bool):
    """Exclude a vendor-publication tail while retaining internal missing intervals."""
    if not active_partition or not observed:
        return end
    return min(end, max(observed) + timedelta(minutes=1))


def validation_failure_detail(result: dict[str, object]) -> str:
    """Return stable, actionable evidence instead of a generic worker failure."""
    gates = result.get("failed_gates") or ["UNKNOWN"]
    recent = result.get("recent_unexpected_gaps") or []
    interval = ""
    if recent:
        first = recent[0]
        interval = f"; first_recent_gap={first['start_utc']}..{first['end_utc']}"
    return (
        f"failed_gates={','.join(str(gate) for gate in gates)}; "
        f"coverage={float(result.get('coverage_percentage') or 0):.6%}; "
        f"invalid_ohlc={int(result.get('invalid_ohlc_count') or 0)}; "
        f"timestamp_errors={int(result.get('timestamp_error_count') or 0)}; "
        f"recent_gap_count={len(recent)}{interval}"
    )


def validate_partition(settings: Settings, import_batch_id: str) -> dict[str, object]:
    """Validate one vendor partition on a canonical timeline without changing provenance."""
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT b.import_batch_id,b.market_id,b.vendor,b.requested_start_utc,b.requested_end_utc,
                      b.row_count,b.accepted_count,b.rejected_count,b.price_completeness,
                      m.symbol,m.calendar_code,m.market_timezone,m.session_open_local,m.session_close_local,
                      sm.instrument_equivalence,sm.qualification_allowed,sm.review_status
               FROM app.historical_import_batches b
               JOIN app.markets m ON m.market_id=b.market_id
               LEFT JOIN app.instrument_source_mappings sm ON sm.market_id=b.market_id AND sm.vendor=b.vendor
               WHERE b.import_batch_id=%s""",
            (import_batch_id,),
        )
        batch = cursor.fetchone()
        if not batch:
            raise ValueError("historical import batch not found")
        start = _naive_utc(batch["requested_start_utc"])
        requested_end = _naive_utc(batch["requested_end_utc"])
        completed_minute = _naive_utc(datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        active_partition = requested_end is not None and requested_end > completed_minute
        end = effective_validation_end(requested_end)
        if start is None or end is None or end <= start:
            raise ValueError("historical import batch has an invalid requested period")

        cursor.execute(
            "SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s",
            (str(batch["calendar_code"]),),
        )
        holidays = {row["holiday_date"] for row in cursor.fetchall()}
        vendor_prefix = f"{str(batch['vendor']).upper()}%"
        cursor.execute(
            """SELECT timestamp_utc,bid_open,bid_high,bid_low,bid_close,
                      ask_open,ask_high,ask_low,ask_close,import_batch_id,source
               FROM app.market_candles_m1
               WHERE market_id=%s AND source LIKE %s
                 AND timestamp_utc>=%s AND timestamp_utc<%s
               ORDER BY timestamp_utc""",
            (str(batch["market_id"]), vendor_prefix, start, end),
        )
        candles = cursor.fetchall()
        if active_partition and candles:
            # Historical vendor publication can trail the live clock. Validate
            # through its latest completed candle, not through an unavailable
            # future/vendor-lagging tail. Missing intervals before that candle
            # remain visible and recent ones still block.
            end = effective_observed_end(
                end, [_naive_utc(row["timestamp_utc"]) for row in candles],
                active_partition=True,
            )
            candles = [row for row in candles if _naive_utc(row["timestamp_utc"]) < end]
        expected = expected_trading_minutes(
            start, end,
            calendar_code=str(batch["calendar_code"]),
            market_timezone=str(batch["market_timezone"]),
            session_open=batch["session_open_local"],
            session_close=batch["session_close_local"],
            holidays=holidays,
        )
        observed = {_naive_utc(row["timestamp_utc"]) for row in candles}
        gaps = classify_missing_minutes(expected, observed, symbol=str(batch["symbol"]))
        invalid = sum(
            not ohlc_valid(row["bid_open"], row["bid_high"], row["bid_low"], row["bid_close"])
            or (row["ask_open"] is not None and not ohlc_valid(row["ask_open"], row["ask_high"], row["ask_low"], row["ask_close"]))
            for row in candles
        )
        timestamp_errors = sum(stamp < start or stamp >= end for stamp in observed)
        expected_count = len(expected)
        observed_count = len(observed & expected)
        coverage = Decimal(observed_count) / Decimal(expected_count) if expected_count else Decimal(0)
        largest_gap = max((gap.missing_minutes for gap in gaps if gap.unexpected), default=0)
        rejected_ratio = Decimal(int(batch["rejected_count"] or 0)) / Decimal(max(1, int(batch["row_count"] or 0)))
        bid_ask_complete = bool(candles) and str(batch["price_completeness"]) == "BID_ASK_FULL" and all(
            row["ask_open"] is not None and row["ask_high"] is not None
            and row["ask_low"] is not None and row["ask_close"] is not None for row in candles
        )

        structural_pass = bool(candles) and invalid == 0 and timestamp_errors == 0 and rejected_ratio <= Decimal(str(settings.historical_maximum_rejected_tick_ratio))
        recent_cutoff = _naive_utc(datetime.now(timezone.utc) - timedelta(
            hours=settings.execution_gap_lookback_hours
        ))
        recent_gaps = [gap for gap in gaps if gap.unexpected and gap.end_utc >= recent_cutoff]
        calendar_pass = (
            coverage >= Decimal(str(settings.historical_minimum_coverage))
            and not recent_gaps
        )

        cursor.execute("DELETE FROM app.historical_partition_gaps WHERE import_batch_id=%s", (import_batch_id,))
        for gap in gaps:
            cursor.execute(
                """INSERT app.historical_partition_gaps(
                     historical_partition_gap_id,import_batch_id,gap_start_utc,gap_end_utc,
                     missing_minutes,reason_code,is_unexpected,evidence_detail)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), import_batch_id, gap.start_utc, gap.end_utc, gap.missing_minutes,
                 gap.reason_code, int(gap.unexpected), "Calendar-aware expected-minute comparison"),
            )

        comparison = _reconcile_partition(cursor, batch, import_batch_id, start, end, settings)
        cross_pass = comparison["primary"]["status"] == "PASS"
        mapping_pass = bool(batch["qualification_allowed"]) and str(batch["review_status"]) in {"APPROVED", "VERIFIED"}
        eligible = structural_pass and calendar_pass and cross_pass and mapping_pass
        if eligible:
            state = "PROMOTED"
        elif not structural_pass:
            state = "REJECTED"
        elif not calendar_pass:
            state = "QUARANTINED"
        elif not cross_pass:
            state = "CALENDAR_VALIDATED"
        else:
            state = "CROSS_SOURCE_VALIDATED"
        candle_quality = (
            "VALIDATED" if eligible else "ACCEPTABLE"
            if structural_pass and calendar_pass else "UNVERIFIED"
        )
        details = {
            "structural_pass": structural_pass, "calendar_pass": calendar_pass,
            "cross_source_pass": cross_pass, "mapping_pass": mapping_pass,
            "rejected_tick_ratio": float(rejected_ratio),
            "comparison_status": comparison["primary"]["status"],
            "comparisons": comparison["comparisons"],
            "canonical_vendor_timeline": True,
            "provenance_batch_count": len({str(row["import_batch_id"]) for row in candles}),
            "old_gap_warning_count": len(gaps) - len(recent_gaps),
            "recent_unexpected_gap_count": len(recent_gaps),
            "effective_validation_end_utc": end.isoformat(),
        }
        cursor.execute(
            """UPDATE app.historical_import_batches SET expected_trading_minutes=%s,
                 observed_trading_minutes=%s,coverage_percentage=%s,largest_unexpected_gap_minutes=%s,
                 unexpected_gap_count=%s,invalid_ohlc_count=%s,timestamp_error_count=%s,
                 price_anomaly_count=0,bid_ask_complete=%s,validation_state=%s,
                 validation_version=%s,validation_details_json=%s,validated_at_utc=SYSUTCDATETIME(),
                 promoted_at_utc=CASE WHEN %s=1 THEN SYSUTCDATETIME() ELSE NULL END,
                 status='COMPLETE',updated_at_utc=SYSUTCDATETIME() WHERE import_batch_id=%s""",
            (expected_count, observed_count, coverage, largest_gap, len(gaps), invalid,
             timestamp_errors, int(bid_ask_complete), state, VALIDATION_VERSION,
             json.dumps(details, sort_keys=True), int(eligible), import_batch_id),
        )
        cursor.execute(
            """UPDATE app.market_candles_m1 SET quality_state=%s,research_eligible=%s,
                 instrument_equivalence=%s
               WHERE market_id=%s AND source LIKE %s
                 AND timestamp_utc>=%s AND timestamp_utc<%s""",
            (candle_quality, int(eligible),
             str(batch["instrument_equivalence"] or "UNVERIFIED"),
             str(batch["market_id"]), vendor_prefix, start, end),
        )
        connection.commit()
    return {
        "status": "VALIDATED" if structural_pass and calendar_pass else "REJECTED",
        "validation_state": state, "research_eligible": eligible,
        "coverage_percentage": float(coverage), "unexpected_gap_count": len(gaps),
        "largest_unexpected_gap_minutes": largest_gap, "cross_source": comparison,
        "invalid_ohlc_count": invalid, "timestamp_error_count": timestamp_errors,
        "recent_unexpected_gaps": [
            {"start_utc": gap.start_utc.isoformat(), "end_utc": gap.end_utc.isoformat(),
             "missing_minutes": gap.missing_minutes} for gap in recent_gaps
        ],
        "failed_gates": [
            name for name, passed in (("STRUCTURAL", structural_pass),
                                      ("COMPLETENESS_OR_RECENT_GAPS", calendar_pass))
            if not passed
        ],
    }


def _reconcile_partition(cursor, batch, import_batch_id: str, start, end, settings: Settings) -> dict[str, object]:
    vendor = str(batch["vendor"]).upper()
    primary_prefix = "HISTDATA" if vendor == "DUKASCOPY" else "DUKASCOPY"
    cursor.execute(
        "DELETE FROM app.historical_partition_reconciliations "
        "WHERE import_batch_id=%s AND comparison_source='INDEPENDENT_M1'",
        (import_batch_id,),
    )
    cursor.execute(
        """SELECT DISTINCT b.source FROM app.market_candles_m1 b
           WHERE b.market_id=%s AND b.timestamp_utc>=%s AND b.timestamp_utc<%s
             AND b.source NOT LIKE %s""",
        (str(batch["market_id"]), start, end, f"{vendor}%"),
    )
    sources = sorted(str(row["source"]) for row in cursor.fetchall())
    # IG is an explicit governed evidence lane. Persist absence instead of allowing
    # another independent vendor to make an aggregate comparison appear complete.
    if not any(source.startswith("IG") for source in sources):
        sources.append("IG_M1")
    comparisons = [
        _reconcile_source(cursor, batch, import_batch_id, start, end, settings, source)
        for source in sources
    ]
    primary = next(
        (comparison for comparison in comparisons
         if str(comparison["comparison_source"]).startswith(primary_prefix)),
        {"comparison_source": primary_prefix, "status": "NO_OVERLAP",
         "comparable_candles": 0, "within_tolerance": 0, "match_percentage": None},
    )
    return {"primary": primary, "comparisons": comparisons}


def _reconcile_source(cursor, batch, import_batch_id: str, start, end,
                      settings: Settings, comparison_source: str) -> dict[str, object]:
    cursor.execute(
        """SELECT a.timestamp_utc,COALESCE(a.mid_open,a.bid_open) mid_open,
                  COALESCE(a.mid_high,a.bid_high) mid_high,COALESCE(a.mid_low,a.bid_low) mid_low,
                  COALESCE(a.mid_close,a.bid_close) mid_close,
                  COALESCE(b.mid_open,b.bid_open) AS other_open,
                  COALESCE(b.mid_high,b.bid_high) AS other_high,
                  COALESCE(b.mid_low,b.bid_low) AS other_low,
                  COALESCE(b.mid_close,b.bid_close) AS other_close
           FROM app.market_candles_m1 a
           JOIN app.market_candles_m1 b ON b.market_id=a.market_id AND b.timestamp_utc=a.timestamp_utc
             AND b.source=%s
           WHERE a.market_id=%s AND a.source LIKE %s
             AND a.timestamp_utc>=%s AND a.timestamp_utc<%s
             """,
        (comparison_source, str(batch["market_id"]), f"{str(batch['vendor']).upper()}%", start, end),
    )
    rows = cursor.fetchall()
    tolerance = Decimal(str(settings.historical_cross_source_tolerance_ratio))
    deltas: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    within = 0
    for row in rows:
        values = (row["mid_open"], row["mid_high"], row["mid_low"], row["mid_close"])
        others = (row["other_open"], row["other_high"], row["other_low"], row["other_close"])
        if any(value is None for value in values + others):
            continue
        delta = tuple(abs(Decimal(value) - Decimal(other)) for value, other in zip(values, others))
        deltas.append(delta)
        within += int(all(item <= max(abs(Decimal(other)) * tolerance, Decimal("0.00000001")) for item, other in zip(delta, others)))
    comparable = len(deltas)
    match = Decimal(within) / Decimal(comparable) if comparable else None
    if comparable < settings.historical_minimum_cross_source_candles:
        status = "NO_OVERLAP" if comparable == 0 else "INSUFFICIENT"
    else:
        status = "PASS" if match is not None and match >= Decimal(str(settings.historical_minimum_cross_source_match)) else "FAIL"
    averages = [sum((row[index] for row in deltas), Decimal(0)) / Decimal(comparable) if comparable else None for index in range(4)]
    cursor.execute(
        "DELETE FROM app.historical_partition_reconciliations WHERE import_batch_id=%s AND comparison_source=%s",
        (import_batch_id, comparison_source),
    )
    cursor.execute(
        """INSERT app.historical_partition_reconciliations(
             historical_partition_reconciliation_id,import_batch_id,market_id,comparison_source,
             partition_start_utc,partition_end_utc,comparison_start_utc,comparison_end_utc,
             comparable_candles,within_tolerance_candles,match_percentage,open_delta,high_delta,
             low_delta,close_delta,timestamp_aligned,coverage_overlap,status)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)""",
        (str(uuid4()), import_batch_id, str(batch["market_id"]), comparison_source, start, end,
         start if comparable else None, end if comparable else None, comparable, within, match,
         averages[0], averages[1], averages[2], averages[3],
         Decimal(comparable) / Decimal(max(1, int(batch["accepted_count"] or 0))), status),
    )
    return {"comparison_source": comparison_source, "status": status,
            "comparable_candles": comparable, "within_tolerance": within,
            "match_percentage": float(match) if match is not None else None}
