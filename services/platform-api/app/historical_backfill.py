from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from app.config import Settings
from app.database import open_database


MARKET_PRIORITY = {
    "USDJPY": 0, "EURUSD": 1, "GBPUSD": 2, "EURJPY": 3, "GBPJPY": 4,
    "XAUUSD": 5, "AUDJPY": 6, "USDZAR": 7, "GERMANY40": 8,
}


def _next_month(value: datetime) -> datetime:
    return value.replace(year=value.year + (value.month == 12), month=1 if value.month == 12 else value.month + 1)


def recent_month_boundaries(now_utc: datetime, months: int = 3) -> tuple[datetime, datetime]:
    """Return current month plus the preceding one or two calendar months."""
    if months not in (2, 3):
        raise ValueError("Historical M1 backfill must cover two or three recent months")
    end = now_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    start = end.replace(day=1, hour=0, minute=0)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    return start, end


def partition_priority(symbol: str, partition_start: datetime, campaign_end: datetime) -> int:
    """Markets follow governance priority while months run newest first."""
    age = (campaign_end.year - partition_start.year) * 12 + campaign_end.month - partition_start.month
    return MARKET_PRIORITY.get(symbol, 99) * 1_000 + max(0, age)


def enqueue_phase(settings: Settings, *, start_utc: datetime, end_utc: datetime,
                  vendor: str = "DUKASCOPY") -> dict[str, object]:
    """Idempotently enqueue monthly partitions for every authoritative research market."""
    start = start_utc.astimezone(timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end = end_utc.astimezone(timezone.utc)
    created = 0
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute("""SELECT m.market_id,m.symbol,x.vendor_symbol FROM app.markets m
          JOIN app.instrument_source_mappings x ON x.market_id=m.market_id AND x.vendor=%s
          WHERE m.enabled=1 AND m.research_enabled=1
          ORDER BY m.symbol""",(vendor,))
        markets=cursor.fetchall()
        for market in markets:
            point=start
            while point<end:
                boundary=min(_next_month(point),end)
                cursor.execute("""IF NOT EXISTS(SELECT 1 FROM app.historical_backfill_jobs WHERE market_id=%s
                  AND vendor=%s AND source_format='TICK_CSV' AND partition_start_utc=%s
                  AND status<>'SUPERSEDED')
                  BEGIN INSERT app.historical_backfill_jobs(backfill_job_id,market_id,vendor,vendor_symbol,
                    partition_start_utc,partition_end_utc,source_format,priority,status)
                  VALUES(%s,%s,%s,%s,%s,%s,'TICK_CSV',%s,'NOT_STARTED'); SELECT 1 created END ELSE SELECT 0 created""",
                  (str(market["market_id"]),vendor,point,str(uuid4()),str(market["market_id"]),vendor,
                   str(market["vendor_symbol"]),point,boundary,
                   partition_priority(str(market["symbol"]), point, end)))
                created += int(cursor.fetchone()["created"])
                point=boundary
        connection.commit()
    return {"status":"QUEUED","vendor":vendor,"markets":len(markets),"partitions_created":created,
            "priority_market":"USDJPY","execution_enabled":False}


def reconcile_recent_campaign(settings: Settings, *, now_utc: datetime | None = None,
                              vendor: str = "DUKASCOPY") -> dict[str, object]:
    """Retire only unfinished obsolete work and enqueue the current bounded campaign.

    Completed jobs and their immutable evidence are deliberately retained.
    """
    start, end = recent_month_boundaries(now_utc or datetime.now(timezone.utc),
                                         settings.historical_backfill_recent_months)
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.historical_backfill_jobs
               SET status='SUPERSEDED',last_error_code='OUTSIDE_ACTIVE_WINDOW',
                   last_error_detail='Retained but excluded by rolling recent-M1 policy',
                   updated_at_utc=SYSUTCDATETIME()
               WHERE vendor=%s AND status IN ('NOT_STARTED','RETRY_PENDING')
                 AND (partition_end_utc<=%s OR partition_start_utc>=%s)""",
            (vendor, start, end),
        )
        superseded = int(cursor.rowcount or 0)
        cursor.execute(
            """;WITH duplicates AS (
                 SELECT backfill_job_id,status,ROW_NUMBER() OVER(
                   PARTITION BY market_id,vendor,source_format,partition_start_utc
                   ORDER BY partition_end_utc DESC,created_at_utc DESC) duplicate_rank
                 FROM app.historical_backfill_jobs
                 WHERE vendor=%s AND status IN ('NOT_STARTED','RETRY_PENDING')
                   AND partition_end_utc>%s AND partition_start_utc<%s)
               UPDATE duplicates SET status='SUPERSEDED'
               WHERE duplicate_rank>1""",
            (vendor, start, end),
        )
        superseded += int(cursor.rowcount or 0)
        connection.commit()
    queued = enqueue_phase(settings, start_utc=start, end_utc=end, vendor=vendor)
    # Campaign priorities are policy, not immutable evidence. Older unfinished
    # rows may carry priorities from a previous campaign and must be rebased so
    # USD/JPY remains the governed first market after a rolling-window update.
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT j.backfill_job_id,j.partition_start_utc,m.symbol
               FROM app.historical_backfill_jobs j
               JOIN app.markets m ON m.market_id=j.market_id
               WHERE j.vendor=%s AND j.status IN ('NOT_STARTED','RETRY_PENDING')
                 AND j.partition_end_utc>%s AND j.partition_start_utc<%s""",
            (vendor, start, end),
        )
        unfinished = cursor.fetchall()
        for job in unfinished:
            cursor.execute(
                "UPDATE app.historical_backfill_jobs SET priority=%s,updated_at_utc=SYSUTCDATETIME() WHERE backfill_job_id=%s",
                (partition_priority(str(job["symbol"]), job["partition_start_utc"], end),
                 str(job["backfill_job_id"])),
            )
        connection.commit()
    return {**queued, "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
            "target_months": settings.historical_backfill_recent_months,
            "priorities_rebased": len(unfinished),
            "superseded_unfinished": superseded}


def claim_next(settings: Settings) -> dict[str, object] | None:
    """Atomically claim one partition; stale DOWNLOADING work is never double-claimed."""
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute(""";WITH candidate AS (SELECT TOP(1) * FROM app.historical_backfill_jobs
          WITH(UPDLOCK,READPAST,ROWLOCK) WHERE status IN ('NOT_STARTED','RETRY_PENDING')
          AND (next_attempt_at_utc IS NULL OR next_attempt_at_utc<=SYSUTCDATETIME()) ORDER BY priority,partition_start_utc DESC)
          UPDATE candidate SET status='DOWNLOADING',attempt_count=attempt_count+1,claimed_at_utc=SYSUTCDATETIME(),
            heartbeat_at_utc=SYSUTCDATETIME(),updated_at_utc=SYSUTCDATETIME()
          OUTPUT inserted.backfill_job_id,inserted.market_id,inserted.vendor,inserted.vendor_symbol,
            inserted.partition_start_utc,inserted.partition_end_utc,inserted.source_format,inserted.attempt_count""")
        row=cursor.fetchone(); connection.commit()
    return row


def recover_stale_claims(settings: Settings, *, stale_after_minutes: int = 180) -> int:
    """Return abandoned in-flight jobs to the retry queue after the download timeout window."""
    with open_database(settings) as connection:
        cursor=connection.cursor()
        cursor.execute("""UPDATE app.historical_backfill_jobs
          SET status='RETRY_PENDING',last_error_code='STALE_WORKER_CLAIM',
            last_error_detail='Recovered after worker heartbeat expired',
            next_attempt_at_utc=SYSUTCDATETIME(),claimed_at_utc=NULL,
            updated_at_utc=SYSUTCDATETIME()
          WHERE status IN ('DOWNLOADING','VALIDATING')
            AND COALESCE(heartbeat_at_utc,claimed_at_utc,updated_at_utc)
                < DATEADD(minute,-%s,SYSUTCDATETIME())""",(stale_after_minutes,))
        recovered=int(cursor.rowcount or 0)
        connection.commit()
    return recovered


def resource_gate(settings: Settings, work_root: Path) -> tuple[bool, str]:
    free_gb = shutil.disk_usage(work_root).free / (1024**3)
    if free_gb < settings.historical_backfill_min_free_gb:
        return False, "INSUFFICIENT_DISK_SPACE"
    try:
        with open_database(settings) as connection:
            cursor=connection.cursor(as_dict=True)
            cursor.execute("""SELECT MAX(c.open_time_utc) latest FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id
              WHERE c.timeframe='M5' AND c.completed=1 AND m.enabled=1 AND m.research_enabled=1""")
            latest=cursor.fetchone()["latest"]
        if not latest or datetime.now(timezone.utc)-latest.replace(tzinfo=timezone.utc)>timedelta(minutes=20):
            return False,"LIVE_FEED_NOT_CURRENT"
    except Exception:
        return False,"DATABASE_UNAVAILABLE"
    return True,"PASS"


def update_job(settings: Settings, job_id: str, status: str, *, error_code: str | None = None,
               error_detail: str | None = None, output_path: str | None = None,
               import_batch_id: str | None = None) -> None:
    with open_database(settings) as connection:
        cursor=connection.cursor()
        cursor.execute("""UPDATE app.historical_backfill_jobs SET status=%s,last_error_code=%s,last_error_detail=%s,
          output_path=COALESCE(%s,output_path),import_batch_id=COALESCE(%s,import_batch_id),
          heartbeat_at_utc=SYSUTCDATETIME(),completed_at_utc=CASE WHEN %s IN ('COMPLETE','FAILED') THEN SYSUTCDATETIME() ELSE NULL END,
          next_attempt_at_utc=CASE WHEN %s='RETRY_PENDING' THEN DATEADD(minute,15*attempt_count,SYSUTCDATETIME()) ELSE NULL END,
          updated_at_utc=SYSUTCDATETIME() WHERE backfill_job_id=%s""",
          (status,error_code,(error_detail or "")[:1000] or None,output_path,import_batch_id,status,status,job_id))
        connection.commit()


def queue_summary(settings: Settings) -> dict[str, int | bool]:
    start,end=recent_month_boundaries(datetime.now(timezone.utc),settings.historical_backfill_recent_months)
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute("""SELECT status,COUNT(*) item_count FROM app.historical_backfill_jobs
          WHERE partition_end_utc>%s AND partition_start_utc<%s AND status<>'SUPERSEDED'
          GROUP BY status""",(start,end))
        counts={str(row["status"]):int(row["item_count"]) for row in cursor.fetchall()}
        cursor.execute("SELECT COUNT(*) item_count FROM app.historical_backfill_jobs WHERE status='SUPERSEDED'")
        superseded=int(cursor.fetchone()["item_count"])
    total=sum(counts.values()); complete=counts.get("COMPLETE",0); failed=counts.get("FAILED",0)
    return {"total":total,"complete":complete,"failed":failed,
            "superseded":superseded,"done":bool(total and complete+failed==total)}


def claim_progress_notification(settings: Settings) -> dict[str, object] | None:
    """Claim one issue or 10% milestone update; routine polling stays silent."""
    summary = queue_summary(settings)
    total = int(summary["total"]); complete = int(summary["complete"])
    failed = int(summary["failed"]); terminal = complete + failed
    if not total or bool(summary["done"]):
        return None
    milestone = (terminal * 10 // total) * 10
    candidates = []
    if failed:
        candidates.append((f"HISTORICAL_BACKFILL_V2:ISSUE:{total}:{failed}", "ISSUE"))
    if milestone >= 10:
        candidates.append((f"HISTORICAL_BACKFILL_V2:PROGRESS:{total}:{milestone}",
                           f"PROGRESS_{milestone}_PERCENT"))
    if not candidates:
        return None
    with open_database(settings) as connection:
        cursor = connection.cursor()
        for key, state in candidates:
            cursor.execute(
                """IF EXISTS(SELECT 1 FROM app.historical_backfill_notifications WITH(UPDLOCK,HOLDLOCK)
                              WHERE notification_key=%s AND delivery_status='FAILED'
                                AND claimed_at_utc<DATEADD(minute,-15,SYSUTCDATETIME()))
                   BEGIN
                     UPDATE app.historical_backfill_notifications SET delivery_status='CLAIMED',
                       claimed_at_utc=SYSUTCDATETIME(),error_detail=NULL WHERE notification_key=%s; SELECT 1
                   END
                   ELSE IF NOT EXISTS(SELECT 1 FROM app.historical_backfill_notifications WITH(UPDLOCK,HOLDLOCK)
                                      WHERE notification_key=%s)
                   BEGIN
                     INSERT app.historical_backfill_notifications(notification_key,terminal_state,total_partitions,
                       complete_partitions,failed_partitions,claimed_at_utc,delivery_status)
                     VALUES(%s,%s,%s,%s,%s,SYSUTCDATETIME(),'CLAIMED'); SELECT 1
                   END ELSE SELECT 0""",
                (key, key, key, key, state, total, complete, failed),
            )
            if bool(cursor.fetchone()[0]):
                connection.commit()
                return {**summary, "notification_key": key, "terminal_state": state,
                        "terminal": terminal, "percent": terminal * 100 // total}
        connection.commit()
    return None


def claim_completion_notification(settings: Settings) -> dict[str, object] | None:
    """Atomically claim the terminal queue notice once, including failure completion."""
    summary = queue_summary(settings)
    if not summary["done"]:
        return None
    terminal_state = "COMPLETED_WITH_FAILURES" if int(summary["failed"]) else "COMPLETED"
    key = f"HISTORICAL_BACKFILL_V1:{summary['total']}:{terminal_state}"
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """IF EXISTS(SELECT 1 FROM app.historical_backfill_notifications WITH(UPDLOCK,HOLDLOCK)
                          WHERE notification_key=%s AND delivery_status='FAILED'
                            AND claimed_at_utc<DATEADD(minute,-15,SYSUTCDATETIME()))
               BEGIN
                 UPDATE app.historical_backfill_notifications SET delivery_status='CLAIMED',
                   claimed_at_utc=SYSUTCDATETIME(),error_detail=NULL WHERE notification_key=%s; SELECT 1
               END
               ELSE IF NOT EXISTS(SELECT 1 FROM app.historical_backfill_notifications WITH(UPDLOCK,HOLDLOCK)
                                  WHERE notification_key=%s)
               BEGIN
                 INSERT app.historical_backfill_notifications(notification_key,terminal_state,total_partitions,
                   complete_partitions,failed_partitions,claimed_at_utc,delivery_status)
                 VALUES(%s,%s,%s,%s,%s,SYSUTCDATETIME(),'CLAIMED'); SELECT 1
               END ELSE SELECT 0""",
            (key, key, key, key, terminal_state, summary["total"], summary["complete"], summary["failed"]),
        )
        claimed = bool(cursor.fetchone()[0])
        connection.commit()
    return {**summary, "notification_key": key, "terminal_state": terminal_state} if claimed else None


def record_completion_notification(settings: Settings, notification_key: str, *, sent: bool,
                                   error_detail: str | None = None) -> None:
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.historical_backfill_notifications
               SET delivery_status=%s,sent_at_utc=CASE WHEN %s=1 THEN SYSUTCDATETIME() ELSE NULL END,
                   error_detail=%s WHERE notification_key=%s""",
            ("SENT" if sent else "FAILED", int(sent), (error_detail or "")[:1000] or None, notification_key),
        )
        connection.commit()


def download_partition(cli: Path, output_root: Path, job: dict[str, object]) -> Path:
    """Download a monthly partition as resumable bounded UTC-day slices."""
    job_id=str(job["backfill_job_id"]); output_root.mkdir(parents=True,exist_ok=True)
    daily_root=output_root/"daily"/job_id; daily_root.mkdir(parents=True,exist_ok=True)
    point=job["partition_start_utc"]
    boundary=job["partition_end_utc"]
    daily_files: list[Path] = []
    while point < boundary:
        day_end=min(point+timedelta(days=1),boundary)
        filename=f"{str(job['vendor_symbol']).lower()}-{point:%Y%m%d}.csv"
        marker=daily_root/f"{filename}.done"
        candidates=(daily_root/filename,daily_root/f"{filename}.csv")
        result=next((path for path in candidates if path.is_file()),candidates[0])
        if not marker.is_file():
            for candidate in candidates:
                if candidate.is_file():
                    candidate.unlink()
            command=[str(cli),"-i",str(job["vendor_symbol"]).lower(),
                     "-from",point.strftime("%Y-%m-%d"),"-to",day_end.strftime("%Y-%m-%d"),
                     "-t","tick","-p","bid","-utc","0","-f","csv","-dir",str(daily_root),
                     "-bs","1","-bp","2500","-r","3","-rp","15000","-fr","-fn",filename]
            completed=subprocess.run(command,capture_output=True,text=True,timeout=900,check=False,
                                     creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if completed.returncode:
                detail=(completed.stderr or completed.stdout or "no downloader diagnostics")[-700:]
                raise RuntimeError(f"DOWNLOADER_EXIT_{completed.returncode}:{point:%Y-%m-%d}: {detail}")
            result=next((path for path in candidates if path.is_file()),None)
            if result is None:
                # Closed days can legitimately produce no payload. Retain an
                # explicit empty slice plus marker so restarts do not retry it.
                result=candidates[0]; result.touch()
            marker.touch()
        daily_files.append(result)
        point=day_end
    target=output_root/f"{job_id}.csv.csv"
    partial=target.with_suffix(target.suffix+".partial")
    data_rows=0
    with partial.open("wb") as combined:
        combined.write(b"timestamp,askPrice,bidPrice\n")
        for path in daily_files:
            with path.open("rb") as source:
                first=True
                for line in source:
                    if first:
                        first=False
                        if line.lower().startswith(b"timestamp,"):
                            continue
                    if line.strip():
                        combined.write(line if line.endswith(b"\n") else line+b"\n")
                        data_rows += 1
    if not data_rows:
        partial.unlink(missing_ok=True)
        raise RuntimeError("DOWNLOAD_OUTPUT_MISSING")
    partial.replace(target)
    return target
