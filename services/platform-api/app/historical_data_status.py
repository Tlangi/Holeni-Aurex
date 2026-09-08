from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

from app.config import Settings
from app.database import open_database

SAST=ZoneInfo("Africa/Johannesburg")


def _iso(value: object) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _sast(value: object) -> str | None:
    return value.replace(tzinfo=timezone.utc).astimezone(SAST).isoformat() if value else None


def read_historical_data_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT 1 ok FROM app.trading_accounts WHERE tenant_id=%s", (tenant_id,))
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute("""SELECT m.symbol,'M1' timeframe,COUNT(c.timestamp_utc) row_count,
            MIN(c.timestamp_utc) earliest_utc,MAX(c.timestamp_utc) latest_utc,
            SUM(CASE WHEN c.price_completeness='BID_ASK_FULL' THEN 1 ELSE 0 END) bid_ask_rows,
            SUM(CASE WHEN c.research_eligible=1 THEN 1 ELSE 0 END) research_eligible_rows,
            COUNT(DISTINCT c.source) source_count
            FROM app.markets m LEFT JOIN app.market_candles_m1 c ON c.market_id=m.market_id
            WHERE m.enabled=1 AND m.research_enabled=1 GROUP BY m.symbol
            UNION ALL
            SELECT m.symbol,'M5',COUNT(c.timestamp_utc),MIN(c.timestamp_utc),MAX(c.timestamp_utc),
            SUM(CASE WHEN c.price_completeness='BID_ASK_FULL' THEN 1 ELSE 0 END),
            SUM(CASE WHEN c.research_eligible=1 THEN 1 ELSE 0 END),COUNT(DISTINCT c.source)
            FROM app.markets m LEFT JOIN app.market_candles_m5 c ON c.market_id=m.market_id
            WHERE m.enabled=1 AND m.research_enabled=1 GROUP BY m.symbol ORDER BY symbol,timeframe""")
        datasets = [{**row,"row_count":int(row["row_count"] or 0),
                     "bid_ask_rows":int(row["bid_ask_rows"] or 0),
                     "research_eligible_rows":int(row["research_eligible_rows"] or 0),
                     "source_count":int(row["source_count"] or 0),
                     "earliest_utc":_iso(row["earliest_utc"]),"latest_utc":_iso(row["latest_utc"]),
                     "earliest_sast":_sast(row["earliest_utc"]),"latest_sast":_sast(row["latest_utc"])}
                    for row in cursor.fetchall()]
        cursor.execute("""SELECT m.symbol,x.vendor,x.vendor_symbol,x.instrument_equivalence,
            x.price_completeness_preference,x.qualification_allowed,x.review_status,x.verified_at_utc
            FROM app.instrument_source_mappings x JOIN app.markets m ON m.market_id=x.market_id
            ORDER BY m.symbol,x.vendor""")
        mappings = [{**row,"qualification_allowed":bool(row["qualification_allowed"]),
                     "verified_at_utc":_iso(row["verified_at_utc"])} for row in cursor.fetchall()]
        cursor.execute("""SELECT TOP(100) b.import_batch_id,m.symbol,b.vendor,b.vendor_symbol,b.source_format,
            b.price_completeness,b.requested_start_utc,b.requested_end_utc,b.actual_start_utc,b.actual_end_utc,
            b.row_count,b.accepted_count,b.rejected_count,b.duplicate_count,b.gap_count,b.status,b.error_code,
            b.updated_at_utc FROM app.historical_import_batches b JOIN app.markets m ON m.market_id=b.market_id
            ORDER BY b.updated_at_utc DESC""")
        batches = [{**row,
                    "requested_start_utc":_iso(row["requested_start_utc"]),
                    "requested_start_sast":_sast(row["requested_start_utc"]),
                    "requested_end_utc":_iso(row["requested_end_utc"]),
                    "requested_end_sast":_sast(row["requested_end_utc"]),
                    "actual_start_utc":_iso(row["actual_start_utc"]),
                    "actual_start_sast":_sast(row["actual_start_utc"]),
                    "actual_end_utc":_iso(row["actual_end_utc"]),
                    "actual_end_sast":_sast(row["actual_end_utc"]),
                    "updated_at_utc":_iso(row["updated_at_utc"]),
                    "updated_at_sast":_sast(row["updated_at_utc"])} for row in cursor.fetchall()]
        cursor.execute("""SELECT j.backfill_job_id,m.symbol,j.vendor,j.vendor_symbol,j.partition_start_utc,
            j.partition_end_utc,j.source_format,j.status,j.attempt_count,j.last_error_code,j.updated_at_utc
            FROM app.historical_backfill_jobs j JOIN app.markets m ON m.market_id=j.market_id
            ORDER BY j.priority,j.partition_start_utc""")
        jobs = [{**row,
                 "partition_start_utc":_iso(row["partition_start_utc"]),
                 "partition_start_sast":_sast(row["partition_start_utc"]),
                 "partition_end_utc":_iso(row["partition_end_utc"]),
                 "partition_end_sast":_sast(row["partition_end_utc"]),
                 "updated_at_utc":_iso(row["updated_at_utc"]),
                 "updated_at_sast":_sast(row["updated_at_utc"])} for row in cursor.fetchall()]
        cursor.execute("""SELECT status,COUNT(*) item_count FROM app.historical_backfill_jobs GROUP BY status""")
        counts={str(row["status"]):int(row["item_count"]) for row in cursor.fetchall()}
        total=sum(counts.values()); complete=counts.get("COMPLETE",0); failed=counts.get("FAILED",0)
        active=sum(counts.get(state,0) for state in ("DOWNLOADING","DOWNLOADED","VALIDATING","IMPORTED"))
        pending=counts.get("NOT_STARTED",0)+counts.get("RETRY_PENDING",0)
        if total and complete+failed==total:
            campaign_state="COMPLETED_WITH_FAILURES" if failed else "COMPLETE"
        elif active:
            campaign_state="RUNNING"
        elif pending:
            campaign_state="QUEUED"
        else:
            campaign_state="EMPTY"
    return {"status":"HISTORICAL_DATA_FOUNDATION","queue_summary":{"state":campaign_state,
            "total":total,"complete":complete,"failed":failed,"active":active,"pending":pending,
            "done":bool(total and complete+failed==total)},"datasets":datasets,"mappings":mappings,
            "batches":batches,"jobs":jobs,"source_priority":["DUKASCOPY_TICK_BID_ASK","DUKASCOPY_BAR",
            "HISTDATA_TICK_BID_ASK","HISTDATA_M1_BID","OTHER_VERIFIED"],
            "alpha_vantage_primary":False,"germany40_proxy_only":True,"execution_enabled":False}
