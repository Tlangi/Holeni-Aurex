from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from app.config import Settings
from app.database import open_database


PREFERRED_BASELINES = (
    "IG_DEMO_HISTORICAL",
    "IG_LIGHTSTREAMER_M5",
    "IG_LIGHTSTREAMER",
    "DUKASCOPY_BID_M5",
    "DUKASCOPY_M1_DERIVED",
)


def instrument_tolerance(*, reference_price: Decimal, tick_size: Decimal | None,
                         spread: Decimal | None, atr: Decimal | None,
                         relative_ratio: Decimal) -> Decimal:
    """Use the largest documented market-scale tolerance, never exact equality."""
    candidates = [abs(reference_price) * relative_ratio, Decimal("0.00000001")]
    if tick_size is not None:
        candidates.append(abs(tick_size) * Decimal(2))
    if spread is not None:
        candidates.append(abs(spread) * Decimal("1.5"))
    if atr is not None:
        candidates.append(abs(atr) * Decimal("0.02"))
    return max(candidates)


def quality_class(*, comparable: int, within: int, minimum_match: Decimal) -> str:
    if comparable == 0:
        return "NO_BASELINE"
    ratio = Decimal(within) / Decimal(comparable)
    if ratio >= minimum_match:
        return "MATCH_STRONG"
    if ratio >= Decimal("0.99"):
        return "MATCH_ACCEPTABLE"
    return "MISMATCH_REVIEW"


def reconcile_batch_to_accepted_m5(settings: Settings, import_batch_id: str) -> dict[str, object]:
    """Compare one immutable M1 batch with retained accepted M5 evidence.

    This function persists evidence only. It never creates or replaces candles.
    """
    with open_database(settings, query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT b.market_id,b.requested_start_utc,b.requested_end_utc,m.tick_size,
                      MIN(c.source) m1_source,MIN(c.instrument_equivalence) instrument_equivalence
               FROM app.historical_import_batches b
               JOIN app.market_candles_m1 c ON c.import_batch_id=b.import_batch_id
               JOIN app.markets m ON m.market_id=b.market_id
               WHERE b.import_batch_id=%s
               GROUP BY b.market_id,b.requested_start_utc,b.requested_end_utc,m.tick_size""",
            (import_batch_id,),
        )
        batch = cursor.fetchone()
        if not batch:
            raise ValueError("historical M1 batch has no candles")
        start, end = batch["requested_start_utc"], batch["requested_end_utc"]
        cursor.execute(
            """SELECT DISTINCT source FROM app.market_candles_m5
               WHERE market_id=%s AND timestamp_utc>=%s AND timestamp_utc<%s
                 AND quality_state IN ('GOOD','VALIDATED','ACCEPTABLE')""",
            (str(batch["market_id"]), start, end),
        )
        available = {str(row["source"]) for row in cursor.fetchall()}
        baselines = [source for source in PREFERRED_BASELINES if source in available]
        results = [
            _reconcile_source(cursor, batch, import_batch_id, start, end, source, settings)
            for source in baselines
        ]
        if not results:
            results = [_reconcile_source(
                cursor, batch, import_batch_id, start, end, "ACCEPTED_M5_NONE", settings,
            )]
        connection.commit()
    primary = results[0]
    return {"primary": primary, "baselines": results}


def _reconcile_source(cursor, batch, import_batch_id: str, start, end,
                      m5_source: str, settings: Settings) -> dict[str, object]:
    cursor.execute(
        """SELECT timestamp_utc,COALESCE(bid_open,mid_open) [open],
                  COALESCE(bid_high,mid_high) high,COALESCE(bid_low,mid_low) low,
                  COALESCE(bid_close,mid_close) [close]
           FROM app.market_candles_m1 WHERE import_batch_id=%s ORDER BY timestamp_utc""",
        (import_batch_id,),
    )
    buckets: dict[object, list[dict[str, object]]] = {}
    for row in cursor.fetchall():
        stamp = row["timestamp_utc"]
        bucket = stamp.replace(minute=stamp.minute - stamp.minute % 5, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)
    cursor.execute(
        """SELECT timestamp_utc,COALESCE(bid_open,mid_open) [open],
                  COALESCE(bid_high,mid_high) high,COALESCE(bid_low,mid_low) low,
                  COALESCE(bid_close,mid_close) [close]
           FROM app.market_candles_m5
           WHERE market_id=%s AND source=%s AND timestamp_utc>=%s AND timestamp_utc<%s""",
        (str(batch["market_id"]), m5_source, start, end),
    )
    baseline = {row["timestamp_utc"]: row for row in cursor.fetchall()}
    m1_source = str(batch["m1_source"])
    cursor.execute(
        """DELETE FROM app.m1_m5_reconciliation WHERE market_id=%s AND m1_source=%s
             AND m5_source=%s AND bucket_utc>=%s AND bucket_utc<%s""",
        (str(batch["market_id"]), m1_source, m5_source, start, end),
    )
    relative_tolerance = Decimal(str(settings.historical_cross_source_tolerance_ratio))
    counts = {"MATCH_STRONG": 0, "MATCH_ACCEPTABLE": 0, "MISMATCH_REVIEW": 0,
              "INCOMPLETE_OVERLAP": 0, "NO_BASELINE": 0}
    parameters = []
    for bucket, rows in sorted(buckets.items()):
        complete = len(rows) == 5 and all(
            rows[index]["timestamp_utc"] == bucket + timedelta(minutes=index)
            for index in range(5)
        )
        other = baseline.get(bucket)
        if not complete:
            status, deltas, within = "INCOMPLETE_OVERLAP", (None,) * 4, False
        elif other is None:
            status, deltas, within = "NO_BASELINE", (None,) * 4, False
        else:
            derived = (rows[0]["open"], max(row["high"] for row in rows),
                       min(row["low"] for row in rows), rows[-1]["close"])
            expected = (other["open"], other["high"], other["low"], other["close"])
            deltas = tuple(abs(Decimal(left) - Decimal(right)) for left, right in zip(derived, expected))
            within = all(delta <= instrument_tolerance(
                reference_price=Decimal(value),
                tick_size=Decimal(str(batch["tick_size"])) if batch.get("tick_size") is not None else None,
                spread=None, atr=None, relative_ratio=relative_tolerance,
            ) for delta, value in zip(deltas, expected))
            status = "MATCH_STRONG" if within else "MISMATCH_REVIEW"
        counts[status] += 1
        parameters.append((str(uuid4()), str(batch["market_id"]), m1_source, m5_source,
                           bucket, len(rows), int(complete), *deltas, 1, int(within),
                           str(batch["instrument_equivalence"]), status))
    if parameters:
        cursor.executemany(
            """INSERT app.m1_m5_reconciliation(reconciliation_id,market_id,m1_source,m5_source,
                 bucket_utc,m1_count,m1_complete,open_delta,high_delta,low_delta,close_delta,
                 timestamp_aligned,within_tolerance,instrument_equivalence,status)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            parameters,
            batch_size=500,
        )
    comparable = counts["MATCH_STRONG"] + counts["MATCH_ACCEPTABLE"] + counts["MISMATCH_REVIEW"]
    within_count = counts["MATCH_STRONG"] + counts["MATCH_ACCEPTABLE"]
    overall = quality_class(comparable=comparable, within=within_count,
                            minimum_match=Decimal(str(settings.historical_m1_m5_minimum_match)))
    return {"m5_source": m5_source, "buckets": len(parameters), "status": overall,
            "comparable_complete_buckets": comparable,
            "within_tolerance_percentage": (within_count / comparable if comparable else None), **counts}
