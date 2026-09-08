from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.historical_market_data import NormalizedM1, PriceCompleteness, Tick, aggregate_ticks_to_m1

PARSER_VERSION = "DUKASCOPY_TICK_CSV_V1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _flush_bucket(rows: list[Tick]) -> NormalizedM1 | None:
    return aggregate_ticks_to_m1(rows)[0] if rows else None


def import_dukascopy_ticks(settings: Settings, *, symbol: str, path: Path,
                           vendor_symbol: str, requested_start: datetime,
                           requested_end: datetime) -> dict[str, object]:
    """Stream one bounded partition and retain only its current minute in memory."""
    if requested_start.tzinfo is None or requested_end.tzinfo is None:
        raise ValueError("requested partition timestamps must be timezone-aware")
    symbol = symbol.upper()
    checksum = _sha256(path)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1 AND research_enabled=1", (symbol,))
        market = cursor.fetchone()
        if not market: raise ValueError("unknown research market")
        cursor.execute("SELECT TOP(1) import_batch_id,status FROM app.historical_import_batches WHERE payload_sha256=%s", (checksum,))
        prior = cursor.fetchone()
        if prior and str(prior["status"]) in {"IMPORTED","COMPLETE"}:
            return {"status":"ALREADY_IMPORTED","import_batch_id":str(prior["import_batch_id"]),"checksum":checksum}
        batch_id = str(prior["import_batch_id"]) if prior else str(uuid4())
        if not prior:
            cursor.execute("""INSERT app.historical_import_batches(import_batch_id,market_id,vendor,vendor_symbol,
            source_format,price_completeness,requested_start_utc,requested_end_utc,downloaded_at_utc,
            source_timezone,payload_sha256,parser_version,conversion_rules,status)
            VALUES(%s,%s,'DUKASCOPY',%s,'TICK_CSV','BID_ASK_FULL',%s,%s,SYSUTCDATETIME(),'UTC',%s,%s,
            'Unix milliseconds UTC; bidPrice and askPrice aggregated independently by UTC minute','VALIDATING')""",
             (batch_id,str(market["market_id"]),vendor_symbol,requested_start,requested_end,checksum,PARSER_VERSION))
        connection.commit()
    candles: list[NormalizedM1] = []; tick_rows: list[Tick] = []; current: datetime | None = None
    rows_read = rejected = 0
    with path.open("r",encoding="utf-8-sig",newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["timestamp","askPrice","bidPrice"]:
            raise ValueError("unexpected Dukascopy tick columns")
        for raw in reader:
            rows_read += 1
            try:
                stamp = datetime.fromtimestamp(int(raw["timestamp"])/1000,tz=timezone.utc)
                tick = Tick(stamp,Decimal(raw["bidPrice"]),Decimal(raw["askPrice"]))
                if tick.ask < tick.bid or tick.bid <= 0: raise ValueError("invalid bid/ask")
            except (ValueError,KeyError):
                rejected += 1; continue
            bucket = stamp.replace(second=0,microsecond=0)
            if current is not None and bucket != current:
                candle = _flush_bucket(tick_rows)
                if candle: candles.append(candle)
                tick_rows=[]
            current=bucket; tick_rows.append(tick)
        candle=_flush_bucket(tick_rows)
        if candle: candles.append(candle)
    accepted=[row for row in candles if requested_start <= row.timestamp_utc < requested_end]
    with open_database(settings) as connection:
        cursor=connection.cursor()
        cursor.executemany("""INSERT app.market_candles_m1(market_id,timestamp_utc,source,source_symbol,source_timezone,
          bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,
          mid_open,mid_high,mid_low,mid_close,spread_open,spread_close,spread_min,spread_max,spread_mean,
          tick_count,price_completeness,quality_state,instrument_equivalence,import_batch_id,
          is_historical_backfill,is_live,is_derived,point_in_time_verified,research_eligible)
        SELECT %s,%s,'DUKASCOPY_TICK_BID_ASK',%s,'UTC',%s,%s,%s,%s,%s,%s,%s,%s,
          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'BID_ASK_FULL','UNVERIFIED','UNVERIFIED',%s,1,0,0,1,0
        WHERE NOT EXISTS(SELECT 1 FROM app.market_candles_m1 WHERE market_id=%s AND timestamp_utc=%s AND source='DUKASCOPY_TICK_BID_ASK')""",
        [(_market:=str(market["market_id"]),r.timestamp_utc,vendor_symbol,
          r.bid_open,r.bid_high,r.bid_low,r.bid_close,r.ask_open,r.ask_high,r.ask_low,r.ask_close,
          (r.bid_open+r.ask_open)/2,(r.bid_high+r.ask_high)/2,(r.bid_low+r.ask_low)/2,(r.bid_close+r.ask_close)/2,
          r.ask_open-r.bid_open,r.ask_close-r.bid_close,
          min(r.ask_open-r.bid_open,r.ask_close-r.bid_close),
          max(r.ask_open-r.bid_open,r.ask_close-r.bid_close),
          ((r.ask_open-r.bid_open)+(r.ask_close-r.bid_close))/2,r.tick_count,batch_id,_market,r.timestamp_utc)
         for r in accepted])
        cursor.execute("""UPDATE app.historical_import_batches SET actual_start_utc=%s,actual_end_utc=%s,row_count=%s,
          accepted_count=%s,rejected_count=%s,status='IMPORTED',updated_at_utc=SYSUTCDATETIME() WHERE import_batch_id=%s""",
          (accepted[0].timestamp_utc if accepted else None,accepted[-1].timestamp_utc if accepted else None,
           rows_read,len(accepted),rejected,batch_id))
        connection.commit()
    return {"status":"IMPORTED","import_batch_id":batch_id,"rows_read":rows_read,
            "accepted_m1":len(accepted),"rejected_ticks":rejected,"checksum":checksum,
            "quality_state":"UNVERIFIED","research_eligible":False}
