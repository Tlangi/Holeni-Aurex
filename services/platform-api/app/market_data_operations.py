from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.database import open_database


def read_market_data_operations(
    settings: Settings, *, quarantine_limit: int = 50, recovery_limit: int = 50,
) -> dict[str, object]:
    quarantine_limit = max(1, min(quarantine_limit, 200))
    recovery_limit = max(1, min(recovery_limit, 200))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            f"""SELECT TOP ({quarantine_limit}) q.market_data_quarantine_id,m.symbol,q.provider,
                       q.source_reference,q.source_sha256,q.source_row_number,q.rejection_code,
                       q.rejection_detail,q.status,q.observed_at_utc,q.reviewed_at_utc
                FROM app.market_data_quarantine q JOIN app.markets m ON m.market_id=q.market_id
                ORDER BY q.observed_at_utc DESC"""
        )
        quarantine = [_row(item) for item in cursor.fetchall()]
        cursor.execute(
            f"""SELECT TOP ({recovery_limit}) r.market_data_recovery_job_id,m.symbol,r.timeframe,
                       r.gap_start_utc,r.gap_end_utc,r.maximum_requested_rows,r.status,
                       r.attempt_count,r.retry_after_utc,r.last_error_code,r.created_at_utc,
                       r.completed_at_utc
                FROM app.market_data_recovery_jobs r JOIN app.markets m ON m.market_id=r.market_id
                ORDER BY r.created_at_utc DESC"""
        )
        recovery = [_row(item) for item in cursor.fetchall()]
        cursor.execute(
            """SELECT status,COUNT(1) count FROM app.market_data_quarantine GROUP BY status"""
        )
        quarantine_summary = {str(item["status"]): int(item["count"])
                              for item in cursor.fetchall()}
        cursor.execute(
            """SELECT status,COUNT(1) count FROM app.market_data_recovery_jobs GROUP BY status"""
        )
        recovery_summary = {str(item["status"]): int(item["count"])
                            for item in cursor.fetchall()}
    return {"quarantine_summary": quarantine_summary, "recovery_summary": recovery_summary,
            "quarantine": quarantine, "recovery_jobs": recovery,
            "synthetic_fill_allowed": False, "execution_enabled": False}


def _row(item: dict[str, object]) -> dict[str, object]:
    return {key: (value.replace(tzinfo=timezone.utc).isoformat()
                  if isinstance(value, datetime) else str(value)
                  if key.endswith("_id") and value is not None else value)
            for key, value in item.items()}
