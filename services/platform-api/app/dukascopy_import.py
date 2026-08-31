from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.market_calendar import is_regular_session


INSTRUMENTS = {
    "eurusd": "EURUSD",
    "gbpusd": "GBPUSD",
    "usdjpy": "USDJPY",
    "deuidxeur": "GERMANY40",
}
FILE_PATTERN = re.compile(
    r"^(?P<instrument>eurusd|gbpusd|usdjpy|deuidxeur)-m5-(?P<side>bid)-.+\.csv$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candle:
    opened: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    regular: bool


def identify_file(path: Path) -> tuple[str, str]:
    match = FILE_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Unsupported Dukascopy filename: {path.name}")
    return INSTRUMENTS[match.group("instrument").lower()], match.group("side").upper()


def import_directory(
    settings: Settings, directory: Path, *, batch_size: int = 2000, dry_run: bool = False,
) -> dict[str, object]:
    if not directory.is_dir():
        raise ValueError(f"Dukascopy download directory does not exist: {directory}")
    files = sorted(path for path in directory.glob("*.csv") if FILE_PATTERN.match(path.name))
    if not files:
        raise ValueError("No supported Dukascopy M5 bid CSV files were found")
    return {path.name: import_file(settings, path, batch_size=batch_size, dry_run=dry_run) for path in files}


def import_file(
    settings: Settings, path: Path, *, batch_size: int = 2000, dry_run: bool = False,
) -> dict[str, object]:
    if batch_size < 100 or batch_size > 10000:
        raise ValueError("Batch size must be between 100 and 10,000")
    symbol, side = identify_file(path)
    if side != "BID":
        raise ValueError("Only bid-side Dukascopy history is accepted")
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT market_id,calendar_code,market_timezone,session_open_local,session_close_local
               FROM app.markets WHERE symbol=%s AND enabled=1""", (symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError(f"Market is not enabled: {symbol}")
        cursor.execute("SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s",
                       (str(market["calendar_code"]),))
        holidays = {row["holiday_date"] for row in cursor.fetchall()}
        digest = file_sha256(path)
        cursor.execute(
            """SELECT historical_import_run_id,status,imported_at_utc
               FROM app.historical_import_runs WHERE file_sha256=%s""", (digest,),
        )
        prior_import = cursor.fetchone()
        if prior_import and not dry_run:
            return {
                "symbol": symbol, "status": "ALREADY_IMPORTED", "file_sha256": digest,
                "imported_at_utc": prior_import["imported_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
            }

    stats: dict[str, object] = {
        "symbol": symbol, "side": side, "source": "DUKASCOPY_BID",
        "file_sha256": digest,
        "rows_read": 0, "accepted_m5": 0, "accepted_m15": 0,
        "invalid_rows": 0, "duplicate_timestamps": 0, "future_or_partial": 0,
        "flat_candles": 0, "regular_session_m5": 0, "regular_session_flat": 0,
        "invalid_reasons": {}, "first_utc": None, "last_utc": None,
        "quarantined_rows": 0,
    }
    quarantine_rows: list[tuple[int, dict[str, str], str, str]] = []
    m5_batch: list[Candle] = []
    m15_batch: list[Candle] = []
    bucket_rows: list[Candle] = []
    bucket_time: datetime | None = None
    previous: datetime | None = None
    complete_before = datetime.now(timezone.utc) - timedelta(minutes=5)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp", "open", "high", "low", "close"]:
            raise ValueError(f"Unexpected Dukascopy CSV columns: {reader.fieldnames}")
        for row_number, raw in enumerate(reader, start=2):
            stats["rows_read"] = int(stats["rows_read"]) + 1
            try:
                candle = parse_candle(raw, market, holidays)
            except (InvalidOperation, KeyError, TypeError, ValueError, OSError) as exc:
                stats["invalid_rows"] = int(stats["invalid_rows"]) + 1
                reasons = stats["invalid_reasons"]
                assert isinstance(reasons, dict)
                reason = str(exc)[:120] or type(exc).__name__
                reasons[reason] = int(reasons.get(reason, 0)) + 1
                if len(quarantine_rows) < 1000:
                    quarantine_rows.append((row_number, raw, _rejection_code(reason), reason))
                continue
            if candle.opened > complete_before:
                stats["future_or_partial"] = int(stats["future_or_partial"]) + 1
                if len(quarantine_rows) < 1000:
                    quarantine_rows.append((row_number, raw, "FUTURE_OR_PARTIAL", "Candle is not complete"))
                continue
            if previous is not None and candle.opened <= previous:
                if candle.opened == previous:
                    stats["duplicate_timestamps"] = int(stats["duplicate_timestamps"]) + 1
                    if len(quarantine_rows) < 1000:
                        quarantine_rows.append((row_number, raw, "DUPLICATE_TIMESTAMP",
                                                "Duplicate timestamp within source file"))
                    continue
                raise ValueError("Dukascopy rows are not in chronological order")
            previous = candle.opened
            stats["first_utc"] = stats["first_utc"] or candle.opened.isoformat()
            stats["last_utc"] = candle.opened.isoformat()
            stats["flat_candles"] = int(stats["flat_candles"]) + int(
                candle.open == candle.high == candle.low == candle.close
            )
            stats["regular_session_m5"] = int(stats["regular_session_m5"]) + int(candle.regular)
            stats["regular_session_flat"] = int(stats["regular_session_flat"]) + int(
                candle.regular and candle.open == candle.high == candle.low == candle.close
            )
            m5_batch.append(candle)
            stats["accepted_m5"] = int(stats["accepted_m5"]) + 1

            current_bucket = candle.opened.replace(minute=candle.opened.minute // 15 * 15)
            if bucket_time is not None and current_bucket != bucket_time:
                aggregated = aggregate_bucket(bucket_time, bucket_rows)
                if aggregated:
                    m15_batch.append(aggregated)
                    stats["accepted_m15"] = int(stats["accepted_m15"]) + 1
                bucket_rows = []
            bucket_time = current_bucket
            bucket_rows.append(candle)
            if len(m5_batch) >= batch_size:
                if not dry_run:
                    persist_batch(settings, str(market["market_id"]), m5_batch, "M5")
                    persist_batch(settings, str(market["market_id"]), m15_batch, "M15")
                m5_batch, m15_batch = [], []

    if bucket_time is not None:
        aggregated = aggregate_bucket(bucket_time, bucket_rows)
        if aggregated:
            m15_batch.append(aggregated)
            stats["accepted_m15"] = int(stats["accepted_m15"]) + 1
    if not dry_run:
        persist_batch(settings, str(market["market_id"]), m5_batch, "M5")
        persist_batch(settings, str(market["market_id"]), m15_batch, "M15")
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            first = datetime.fromisoformat(str(stats["first_utc"]))
            last = datetime.fromisoformat(str(stats["last_utc"]))
            cursor.execute(
                """SELECT timeframe,COUNT(*) source_rows,MIN(open_time_utc) first_utc,MAX(open_time_utc) last_utc
                   FROM app.candles WHERE market_id=%s AND source IN ('DUKASCOPY_BID_M5','DUKASCOPY_BID_M15')
                     AND open_time_utc>=%s AND open_time_utc<=%s
                   GROUP BY timeframe ORDER BY timeframe""", (str(market["market_id"]), first, last),
            )
            persisted = [
                {"timeframe": row["timeframe"], "rows": int(row["source_rows"]),
                 "first_utc": row["first_utc"].replace(tzinfo=timezone.utc).isoformat(),
                 "last_utc": row["last_utc"].replace(tzinfo=timezone.utc).isoformat()}
                for row in cursor.fetchall()
            ]
            stats["persisted"] = persisted
            counts = {str(item["timeframe"]): int(item["rows"]) for item in persisted}
            cursor.execute(
                """INSERT app.historical_import_runs
                   (historical_import_run_id,provider,market_id,file_name,file_sha256,price_side,
                    source_timeframe,source_start_utc,source_end_utc,rows_read,accepted_m5,
                    accepted_m15,invalid_rows,persisted_m5,persisted_m15,status)
                   VALUES(%s,'DUKASCOPY',%s,%s,%s,%s,'M5',%s,%s,%s,%s,%s,%s,%s,%s,'COMPLETED')""",
                (str(uuid4()), str(market["market_id"]), path.name, digest, side, first, last,
                 stats["rows_read"], stats["accepted_m5"], stats["accepted_m15"],
                 stats["invalid_rows"], counts.get("M5", 0), counts.get("M15", 0)),
            )
            _persist_quarantine(
                cursor, market_id=str(market["market_id"]), source_reference=path.name,
                source_sha256=digest, rows=quarantine_rows,
            )
            stats["quarantined_rows"] = len(quarantine_rows)
            connection.commit()
    stats["dry_run"] = dry_run
    return stats


def _rejection_code(reason: str) -> str:
    normalized = reason.lower()
    if "ohlc" in normalized:
        return "INVALID_OHLC"
    if "positive" in normalized or "finite" in normalized:
        return "NON_POSITIVE_OR_NON_FINITE"
    if "aligned" in normalized or "timestamp" in normalized:
        return "INVALID_TIMESTAMP"
    return "PARSE_ERROR"


def _persist_quarantine(
    cursor: object, *, market_id: str, source_reference: str, source_sha256: str,
    rows: list[tuple[int, dict[str, str], str, str]],
) -> None:
    if not rows:
        return
    cursor.executemany(
        """INSERT app.market_data_quarantine
             (market_data_quarantine_id,market_id,provider,source_reference,source_sha256,
              source_row_number,rejection_code,rejection_detail,raw_payload_json,status)
           VALUES(%s,%s,'DUKASCOPY',%s,%s,%s,%s,%s,%s,'QUARANTINED')""",
        [(str(uuid4()), market_id, source_reference, source_sha256, row_number,
          code, detail, json.dumps(raw, sort_keys=True))
         for row_number, raw, code, detail in rows],
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_candle(
    raw: dict[str, str], market: dict[str, object], holidays: set[object],
) -> Candle:
    timestamp_ms = int(raw["timestamp"])
    if timestamp_ms < 0 or timestamp_ms % 300000:
        raise ValueError("Timestamp is not aligned to an M5 UTC bucket")
    opened = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    values = [Decimal(raw[name]) for name in ("open", "high", "low", "close")]
    if any(not value.is_finite() or value <= 0 for value in values):
        raise ValueError("Prices must be finite and positive")
    if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
        raise ValueError("Invalid OHLC envelope")
    regular = is_regular_session(
        opened, calendar_code=str(market["calendar_code"]),
        market_timezone=str(market["market_timezone"]),
        session_open=market["session_open_local"], session_close=market["session_close_local"],
        holidays=holidays,
    )
    return Candle(opened, values[0], values[1], values[2], values[3], regular)


def aggregate_bucket(bucket: datetime, rows: list[Candle]) -> Candle | None:
    expected = [bucket + timedelta(minutes=offset) for offset in (0, 5, 10)]
    if len(rows) != 3 or [item.opened for item in rows] != expected:
        return None
    return Candle(
        bucket, rows[0].open, max(item.high for item in rows), min(item.low for item in rows),
        rows[-1].close, all(item.regular for item in rows),
    )


def persist_batch(settings: Settings, market_id: str, candles: list[Candle], timeframe: str) -> None:
    if not candles:
        return
    minutes = 5 if timeframe == "M5" else 15
    source = f"DUKASCOPY_BID_{timeframe}"
    rows = [
        (item.opened.replace(tzinfo=None),
         (item.opened + timedelta(minutes=minutes)).replace(tzinfo=None),
         item.open, item.high, item.low, item.close, int(item.regular))
        for item in candles
    ]
    with open_database(settings) as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(
                """CREATE TABLE #dukascopy_stage
                   (open_time_utc datetime2(3) NOT NULL PRIMARY KEY,
                    close_time_utc datetime2(3) NOT NULL,
                    [open] decimal(19,8) NOT NULL,high decimal(19,8) NOT NULL,
                    low decimal(19,8) NOT NULL,[close] decimal(19,8) NOT NULL,
                    is_regular_session bit NOT NULL)"""
            )
            connection.bulk_copy(
                "#dukascopy_stage", rows,
                column_ids=[1, 2, 3, 4, 5, 6, 7],
                batch_size=min(len(rows), 5000), tablock=True,
            )
            cursor.execute(
                """INSERT app.candles
                     (market_id,timeframe,open_time_utc,close_time_utc,[open],high,low,[close],
                      bid_open,bid_high,bid_low,bid_close,is_regular_session,tick_count,
                      source,completed,quality_status)
                   SELECT %s,%s,s.open_time_utc,s.close_time_utc,s.[open],s.high,s.low,s.[close],
                          s.[open],s.high,s.low,s.[close],s.is_regular_session,0,%s,1,'PASS'
                   FROM #dukascopy_stage s
                   WHERE NOT EXISTS
                     (SELECT 1 FROM app.candles c WHERE c.market_id=%s AND c.timeframe=%s
                        AND c.open_time_utc=s.open_time_utc)""",
                (market_id, timeframe, source, market_id, timeframe),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
