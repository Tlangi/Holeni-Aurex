from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.ig_demo import IGDemoClient, IGDemoUnavailable
from app.market_calendar import operational_session_state
from app.market_intelligence import _persist_m5, aggregate_m15_history


def schedule_bounded_recovery_jobs(
    settings: Settings, *, force_transient_retry: bool = False,
) -> list[dict[str, object]]:
    """Register only small, recent, execution-blocking gaps for bounded recovery."""
    now = datetime.now(timezone.utc)
    outcomes = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT g.data_quality_gap_id,g.market_id,g.timeframe,g.gap_start_utc,g.gap_end_utc,
                      m.symbol,m.calendar_code,m.market_timezone,m.session_open_local,m.session_close_local
               FROM app.data_quality_gaps g JOIN app.markets m ON m.market_id=g.market_id
               WHERE g.execution_blocking=1 AND g.resolved_at_utc IS NULL
                 AND g.classification='LIVE_STREAM_INTERRUPTION'
                 AND g.gap_end_utc>=DATEADD(hour,-24,SYSUTCDATETIME())
               ORDER BY g.gap_start_utc"""
        )
        for gap in cursor.fetchall():
            interval = 5 if gap["timeframe"] == "M5" else 15
            output_rows = int((gap["gap_end_utc"] - gap["gap_start_utc"]).total_seconds() // (interval * 60)) + 1
            requested = output_rows * 3 if gap["timeframe"] == "M15" else output_rows
            if requested > 64:
                outcomes.append({"symbol": gap["symbol"], "status": "MANUAL_REVIEW_REQUIRED",
                                 "requested_rows": requested})
                continue
            cursor.execute(
                "SELECT holiday_date,session_close_local FROM app.market_holidays WHERE calendar_code=%s",
                (str(gap["calendar_code"]),),
            )
            holidays = {row["holiday_date"]: row["session_close_local"] for row in cursor.fetchall()}
            session = operational_session_state(
                now, calendar_code=str(gap["calendar_code"]),
                market_timezone=str(gap["market_timezone"]),
                session_open=gap["session_open_local"], session_close=gap["session_close_local"],
                holidays=holidays,
            )
            status = "QUEUED" if session.should_receive_data else "SESSION_DEFERRED"
            cursor.execute(
                """SELECT market_data_recovery_job_id,status,last_error_code FROM app.market_data_recovery_jobs
                   WHERE market_id=%s AND timeframe=%s AND gap_start_utc=%s AND gap_end_utc=%s""",
                (str(gap["market_id"]), gap["timeframe"], gap["gap_start_utc"], gap["gap_end_utc"]),
            )
            current = cursor.fetchone()
            if current:
                transient_retry = (
                    force_transient_retry and current["status"] == "FAILED" and
                    str(current.get("last_error_code") or "") in
                    {"IG_UNREACHABLE", "IG_DEMO_UNAVAILABLE", "IGDemoUnavailable", "DATA_UNAVAILABLE"}
                )
                should_requeue = (current["status"] in {"SESSION_DEFERRED", "COMPLETED"}
                                  or transient_retry) and session.should_receive_data
                if should_requeue:
                    cursor.execute(
                        """UPDATE app.market_data_recovery_jobs SET status='QUEUED',retry_after_utc=NULL,
                                  maximum_requested_rows=%s
                           WHERE market_data_recovery_job_id=%s""",
                        (requested, str(current["market_data_recovery_job_id"])),
                    )
                effective_status = "QUEUED" if should_requeue else str(current["status"])
                outcomes.append({"symbol": gap["symbol"], "status": effective_status,
                                 "requested_rows": requested})
                continue
            cursor.execute(
                """INSERT app.market_data_recovery_jobs
                     (market_data_recovery_job_id,market_id,timeframe,gap_start_utc,gap_end_utc,
                      maximum_requested_rows,status,retry_after_utc)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), str(gap["market_id"]), gap["timeframe"], gap["gap_start_utc"],
                 gap["gap_end_utc"], requested, status,
                 session.grace_until_utc if status == "SESSION_DEFERRED" else None),
            )
            outcomes.append({"symbol": gap["symbol"], "status": status,
                             "requested_rows": requested})
        connection.commit()
    return outcomes


def process_one_bounded_recovery(settings: Settings) -> dict[str, object] | None:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """;WITH claimable AS (
                   SELECT TOP (1) * FROM app.market_data_recovery_jobs WITH (UPDLOCK,READPAST,ROWLOCK)
                   WHERE status='QUEUED' AND (retry_after_utc IS NULL OR retry_after_utc<=SYSUTCDATETIME())
                   ORDER BY created_at_utc
               )
               UPDATE claimable SET status='RUNNING',attempt_count=attempt_count+1
               OUTPUT inserted.market_data_recovery_job_id,inserted.market_id,
                      inserted.maximum_requested_rows,inserted.timeframe,
                      inserted.gap_start_utc,inserted.gap_end_utc"""
        )
        job = cursor.fetchone()
        connection.commit()
    if not job:
        return None
    job_id, market_id = str(job["market_data_recovery_job_id"]), str(job["market_id"])
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            cursor.execute("SELECT symbol,ig_epic FROM app.markets WHERE market_id=%s", (market_id,))
            market = cursor.fetchone()
        if not market:
            raise ValueError("Recovery market no longer exists")
        with IGDemoClient(settings) as client:
            recovery_end = job["gap_end_utc"] + (
                timedelta(minutes=10) if job["timeframe"] == "M15" else timedelta(0)
            )
            prices = client.historical_prices_range(
                str(market["ig_epic"]),
                start_utc=job["gap_start_utc"].replace(tzinfo=timezone.utc),
                end_utc=recovery_end.replace(tzinfo=timezone.utc),
                page_size=max(1, int(job["maximum_requested_rows"])),
            )
        persisted = _persist_m5(settings, market_id, prices)
        aggregate_m15_history(
            settings, market_id, start_utc=job["gap_start_utc"], end_utc=recovery_end,
        )
        with open_database(settings) as connection:
            verify = connection.cursor()
            verify.execute(
                """SELECT COUNT(DISTINCT open_time_utc) FROM app.candles
                   WHERE market_id=%s AND timeframe=%s AND completed=1
                     AND open_time_utc BETWEEN %s AND %s""",
                (market_id, job["timeframe"], job["gap_start_utc"], job["gap_end_utc"]),
            )
            recovered = int(verify.fetchone()[0] or 0)
            required = (int(job["maximum_requested_rows"]) // 3
                        if job["timeframe"] == "M15" else int(job["maximum_requested_rows"]))
            if recovered >= required:
                verify.execute(
                    """UPDATE app.data_quality_gaps SET resolved_at_utc=SYSUTCDATETIME()
                           ,recovery_result='RECOVERED',recovery_assessed_at_utc=SYSUTCDATETIME(),
                            current_execution_relevant_until_utc=NULL
                       WHERE market_id=%s AND timeframe=%s AND resolved_at_utc IS NULL
                         AND gap_start_utc=%s AND gap_end_utc=%s""",
                    (market_id, job["timeframe"], job["gap_start_utc"], job["gap_end_utc"]),
                )
            connection.commit()
        if recovered < required:
            raise IGDemoUnavailable("IG demo did not return every requested recovery candle",
                                    error_code="DATA_UNAVAILABLE")
        status, error, retry = "COMPLETED", f"RECOVERED_{recovered}_ACCEPTED_{persisted['accepted']}", None
        recovery_result = "RECOVERED"
    except IGDemoUnavailable as exc:
        quota = exc.error_code == "error.public-api.exceeded-account-historical-data-allowance"
        status = "QUOTA_DEFERRED" if quota else "FAILED"
        error = exc.error_code or ("IG_UNREACHABLE" if "unreachable" in str(exc).lower()
                                   else "IG_DEMO_UNAVAILABLE")
        retry = datetime.now(timezone.utc) + (timedelta(days=7) if quota else timedelta(hours=6))
        recovery_result = "BROKER_DATA_UNAVAILABLE" if error == "DATA_UNAVAILABLE" else "UNRESOLVED"
    except Exception as exc:
        status, error, retry = "FAILED", type(exc).__name__, datetime.now(timezone.utc) + timedelta(hours=6)
        recovery_result = "UNRESOLVED"
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.market_data_recovery_jobs SET status=%s,last_error_code=%s,
                      retry_after_utc=%s,completed_at_utc=CASE WHEN %s='COMPLETED'
                        THEN SYSUTCDATETIME() ELSE NULL END
               WHERE market_data_recovery_job_id=%s""", (status, error, retry, status, job_id),
        )
        if recovery_result != "RECOVERED":
            cursor.execute(
                """UPDATE app.data_quality_gaps SET recovery_result=%s,
                          recovery_assessed_at_utc=SYSUTCDATETIME(),
                          current_execution_relevant_until_utc=DATEADD(hour,%s,gap_end_utc)
                   WHERE market_id=%s AND timeframe=%s AND resolved_at_utc IS NULL
                     AND gap_start_utc=%s AND gap_end_utc=%s""",
                (recovery_result, int(settings.execution_gap_lookback_hours), market_id,
                 job["timeframe"], job["gap_start_utc"], job["gap_end_utc"]),
            )
        connection.commit()
    return {"job_id": job_id, "status": status, "detail": error}
