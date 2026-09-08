from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from app.config import Settings
from app.database import open_database
from app.historical_market_data import parse_histdata_m1


PARSER_VERSION = "HISTDATA_GENERIC_ASCII_M1_V1"


def import_histdata_m1(settings: Settings, *, symbol: str, archive: Path,
                       requested_start: datetime, requested_end: datetime) -> dict[str, object]:
    """Import one official HistData Generic ASCII M1 archive as BID-only evidence."""
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested partition timestamps must be timezone-aware")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    symbol = symbol.upper()
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
        market = cursor.fetchone()
        if not market:
            raise ValueError("unknown market")
        cursor.execute("SELECT TOP(1) import_batch_id,status FROM app.historical_import_batches WHERE payload_sha256=%s", (checksum,))
        prior = cursor.fetchone()
        if prior and str(prior["status"]) in {"IMPORTED", "COMPLETE"}:
            return {"status": "ALREADY_IMPORTED", "import_batch_id": str(prior["import_batch_id"])}
        batch_id = str(prior["import_batch_id"]) if prior else str(uuid4())
        if not prior:
            cursor.execute(
                """INSERT app.historical_import_batches(import_batch_id,market_id,vendor,vendor_symbol,
                     source_format,price_completeness,requested_start_utc,requested_end_utc,downloaded_at_utc,
                     source_timezone,payload_sha256,parser_version,conversion_rules,status)
                   VALUES(%s,%s,'HISTDATA',%s,'GENERIC_ASCII_M1','BID_ONLY',%s,%s,SYSUTCDATETIME(),
                     'EST_FIXED_UTC_MINUS_5',%s,%s,'Documented fixed EST converted to UTC; BID OHLC only; ASK and spread remain NULL','VALIDATING')""",
                (batch_id, str(market["market_id"]), symbol, requested_start, requested_end, checksum, PARSER_VERSION),
            )
        connection.commit()

    rows_by_timestamp = {}
    rejected = 0
    duplicate_count = 0
    with ZipFile(archive) as package:
        csv_names = [name for name in package.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError("HistData archive must contain exactly one CSV")
        with package.open(csv_names[0]) as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                try:
                    row = parse_histdata_m1(raw.decode("ascii"))
                    if requested_start <= row.timestamp_utc < requested_end:
                        if row.timestamp_utc in rows_by_timestamp:
                            duplicate_count += 1
                        rows_by_timestamp[row.timestamp_utc] = row
                except (ValueError, UnicodeDecodeError):
                    rejected += 1
    rows = [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]
    with open_database(settings, query_timeout_seconds=120) as connection:
        cursor = connection.cursor()
        # A retry can rebuild only this immutable batch from the retained archive.
        cursor.execute("DELETE FROM app.market_candles_m1 WHERE import_batch_id=%s", (batch_id,))
        connection.commit()
        statement = """INSERT app.market_candles_m1(market_id,timestamp_utc,source,source_symbol,source_timezone,
                 bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
                 mid_open,mid_high,mid_low,mid_close,spread_open,spread_close,spread_min,spread_max,spread_mean,
                 tick_count,price_completeness,quality_state,instrument_equivalence,import_batch_id,
                 is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible)
               VALUES(%s,%s,'HISTDATA_M1_BID',%s,'EST_FIXED_UTC_MINUS_5',%s,%s,%s,%s,
                 NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,%s,'BID_ONLY','UNVERIFIED',
                 'EXACT_PAIR',%s,1,0,0,1,0)"""
        parameters = [(str(market["market_id"]), row.timestamp_utc, symbol, row.bid_open, row.bid_high,
                       row.bid_low, row.bid_close, row.tick_count, batch_id) for row in rows]
        # Keep each guarded insert chunk below the platform's deliberately short
        # operational SQL timeout. Commits make retries resumable and dedup-safe.
        chunk_size = 500
        for offset in range(0, len(parameters), chunk_size):
            cursor.executemany(statement, parameters[offset:offset + chunk_size], batch_size=chunk_size)
            connection.commit()
        cursor.execute(
            """UPDATE app.historical_import_batches SET actual_start_utc=%s,actual_end_utc=%s,row_count=%s,
                 accepted_count=%s,rejected_count=%s,duplicate_count=%s,status='IMPORTED',updated_at_utc=SYSUTCDATETIME()
               WHERE import_batch_id=%s""",
            (rows[0].timestamp_utc if rows else None, rows[-1].timestamp_utc if rows else None,
             len(rows) + rejected + duplicate_count, len(rows), rejected, duplicate_count, batch_id),
        )
        connection.commit()
    return {"status": "IMPORTED", "import_batch_id": batch_id,
            "accepted_m1": len(rows), "rejected_rows": rejected,
            "duplicate_rows": duplicate_count, "price_completeness": "BID_ONLY"}
