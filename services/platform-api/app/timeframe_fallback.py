from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable, Mapping

from app.config import Settings
from app.database import open_database


M1_MISSING_M5_FALLBACK_AVAILABLE = "M1_MISSING_M5_FALLBACK_AVAILABLE"
DERIVED_FROM_M1 = "DERIVED_FROM_M1"


@dataclass(frozen=True)
class DerivedCandle:
    timestamp_utc: datetime
    bid_open: Decimal | None
    bid_high: Decimal | None
    bid_low: Decimal | None
    bid_close: Decimal | None
    ask_open: Decimal | None
    ask_high: Decimal | None
    ask_low: Decimal | None
    ask_close: Decimal | None
    source: str = DERIVED_FROM_M1
    quality_state: str = "VALIDATED"


def mark_m1_gap_fallback(missing_minutes: Iterable[datetime],
                         m5_timestamps: Iterable[datetime]) -> dict[datetime, str]:
    """Describe M5 coverage without creating even one synthetic M1 observation."""
    buckets = set(m5_timestamps)
    result: dict[datetime, str] = {}
    for stamp in missing_minutes:
        bucket = stamp.replace(minute=stamp.minute - stamp.minute % 5, second=0, microsecond=0)
        if bucket in buckets:
            result[stamp] = M1_MISSING_M5_FALLBACK_AVAILABLE
    return result


def derive_m5_from_complete_m1(rows: Iterable[Mapping[str, object]]) -> DerivedCandle | None:
    """Aggregate exactly five consecutive genuine M1 rows; incomplete input stays missing."""
    values = sorted(rows, key=lambda row: row["timestamp_utc"])
    if len(values) != 5:
        return None
    start = values[0]["timestamp_utc"]
    bucket = start.replace(minute=start.minute - start.minute % 5, second=0, microsecond=0)
    if any(row.get("is_derived") or row["timestamp_utc"] != bucket + timedelta(minutes=index)
           for index, row in enumerate(values)):
        return None

    def aggregate(prefix: str) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
        fields = tuple(tuple(row.get(f"{prefix}_{part}") for part in ("open", "high", "low", "close"))
                       for row in values)
        if any(any(value is None for value in row) for row in fields):
            return None, None, None, None
        return (Decimal(fields[0][0]), max(Decimal(row[1]) for row in fields),
                min(Decimal(row[2]) for row in fields), Decimal(fields[-1][3]))

    bid = aggregate("bid")
    ask = aggregate("ask")
    if bid[0] is None and ask[0] is None:
        return None
    return DerivedCandle(bucket, *bid, *ask)


def feature_availability(*, requires_genuine_m1: bool, m1_available: bool,
                         m5_available: bool) -> str:
    if m1_available:
        return "AVAILABLE_GENUINE_M1"
    if requires_genuine_m1:
        return "MISSING"
    if m5_available:
        return M1_MISSING_M5_FALLBACK_AVAILABLE
    return "MISSING"


def persist_batch_cross_timeframe_recovery(settings: Settings, import_batch_id: str) -> dict[str, int]:
    """Persist safe M1/M5 support for one batch without manufacturing M1 rows."""
    with open_database(settings, query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT b.market_id,b.requested_start_utc,b.requested_end_utc
               FROM app.historical_import_batches b WHERE b.import_batch_id=%s""",
            (import_batch_id,),
        )
        batch = cursor.fetchone()
        if not batch:
            raise ValueError("historical import batch not found")
        cursor.execute(
            """SELECT timestamp_utc,bid_open,bid_high,bid_low,bid_close,
                      ask_open,ask_high,ask_low,ask_close,is_derived
               FROM app.market_candles_m1
               WHERE import_batch_id=%s AND research_eligible=1 ORDER BY timestamp_utc""",
            (import_batch_id,),
        )
        buckets: dict[datetime, list[dict[str, object]]] = {}
        for row in cursor.fetchall():
            stamp = row["timestamp_utc"]
            bucket = stamp.replace(minute=stamp.minute - stamp.minute % 5, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(row)

        derived_count = 0
        for bucket, rows in buckets.items():
            derived = derive_m5_from_complete_m1(rows)
            if derived is None:
                continue
            cursor.execute(
                """IF NOT EXISTS(SELECT 1 FROM app.v_canonical_market_candles_m5
                                  WHERE market_id=%s AND timestamp_utc=%s)
                   INSERT app.market_candles_m5(market_id,timestamp_utc,source,source_symbol,source_timezone,
                    bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                    mid_open,mid_high,mid_low,mid_close,tick_count,price_completeness,quality_state,
                    instrument_equivalence,import_batch_id,is_historical_backfill,is_live,is_derived,
                    point_in_time_verified,research_eligible)
                   SELECT %s,%s,'DERIVED_FROM_M1',m.ig_epic,'UTC',%s,%s,%s,%s,%s,%s,%s,%s,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL THEN (%s+%s)/2 END,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL THEN (%s+%s)/2 END,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL THEN (%s+%s)/2 END,
                    CASE WHEN %s IS NOT NULL AND %s IS NOT NULL THEN (%s+%s)/2 END,
                    5,CASE WHEN %s IS NULL THEN 'BID_ONLY' ELSE 'BID_ASK_FULL' END,
                    'VALIDATED','EXACT_PAIR',%s,1,0,1,1,1 FROM app.markets m WHERE m.market_id=%s;
                   SELECT @@ROWCOUNT inserted""",
                (str(batch["market_id"]), bucket, str(batch["market_id"]), bucket,
                 derived.bid_open, derived.bid_high, derived.bid_low, derived.bid_close,
                 derived.ask_open, derived.ask_high, derived.ask_low, derived.ask_close,
                 derived.bid_open, derived.ask_open, derived.bid_open, derived.ask_open,
                 derived.bid_high, derived.ask_high, derived.bid_high, derived.ask_high,
                 derived.bid_low, derived.ask_low, derived.bid_low, derived.ask_low,
                 derived.bid_close, derived.ask_close, derived.bid_close, derived.ask_close,
                 derived.ask_open, import_batch_id, str(batch["market_id"])),
            )
            derived_count += int(cursor.fetchone()["inserted"] or 0)

        cursor.execute(
            """SELECT timestamp_utc,source FROM app.v_canonical_market_candles_m5
               WHERE market_id=%s AND timestamp_utc>=%s AND timestamp_utc<%s""",
            (str(batch["market_id"]), batch["requested_start_utc"], batch["requested_end_utc"]),
        )
        baselines = cursor.fetchall()
        fallback_count = 0
        for baseline in baselines:
            bucket = baseline["timestamp_utc"]
            observed = {row["timestamp_utc"] for row in buckets.get(bucket, [])}
            missing = [bucket + timedelta(minutes=index) for index in range(5)
                       if bucket + timedelta(minutes=index) not in observed]
            for stamp in mark_m1_gap_fallback(missing, [bucket]):
                cursor.execute(
                    """IF NOT EXISTS(SELECT 1 FROM app.market_timeframe_fallbacks
                                      WHERE market_id=%s AND missing_timeframe='M1'
                                        AND interval_start_utc=%s AND fallback_source=%s)
                       INSERT app.market_timeframe_fallbacks(market_id,missing_timeframe,interval_start_utc,
                        interval_end_utc,fallback_timeframe,fallback_source,fallback_timestamp_utc,
                        quality_state,genuine_m1_required,evidence_detail)
                       VALUES(%s,'M1',%s,DATEADD(minute,1,%s),'M5',%s,%s,
                        'M1_MISSING_M5_FALLBACK_AVAILABLE',1,
                        'M1 remains missing; M5 may support M5-compatible features only')""",
                    (str(batch["market_id"]), stamp, str(baseline["source"]),
                     str(batch["market_id"]), stamp, stamp, str(baseline["source"]), bucket),
                )
                fallback_count += int(cursor.rowcount or 0)
        connection.commit()
    return {"m5_derived_from_m1": derived_count, "m1_gaps_with_m5_fallback": fallback_count,
            "m1_rows_fabricated": 0}
