from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from app.config import Settings
from app.database import open_database


def _next_month(value: datetime) -> datetime:
    return value.replace(year=value.year + (value.month == 12), month=1 if value.month == 12 else value.month + 1)


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
          ORDER BY CASE WHEN m.symbol='USDJPY' THEN 0 ELSE 1 END,m.symbol""",(vendor,))
        markets=cursor.fetchall()
        for market_index,market in enumerate(markets):
            point=start
            while point<end:
                boundary=min(_next_month(point),end)
                cursor.execute("""IF NOT EXISTS(SELECT 1 FROM app.historical_backfill_jobs WHERE market_id=%s
                  AND vendor=%s AND source_format='TICK_CSV' AND partition_start_utc=%s AND partition_end_utc=%s)
                  BEGIN INSERT app.historical_backfill_jobs(backfill_job_id,market_id,vendor,vendor_symbol,
                    partition_start_utc,partition_end_utc,source_format,priority,status)
                  VALUES(%s,%s,%s,%s,%s,%s,'TICK_CSV',%s,'NOT_STARTED'); SELECT 1 created END ELSE SELECT 0 created""",
                  (str(market["market_id"]),vendor,point,boundary,str(uuid4()),str(market["market_id"]),vendor,
                   str(market["vendor_symbol"]),point,boundary,market_index*100_000_000+int(point.timestamp())))
                created += int(cursor.fetchone()["created"])
                point=boundary
        connection.commit()
    return {"status":"QUEUED","vendor":vendor,"markets":len(markets),"partitions_created":created,
            "priority_market":"USDJPY","execution_enabled":False}


def claim_next(settings: Settings) -> dict[str, object] | None:
    """Atomically claim one partition; stale DOWNLOADING work is never double-claimed."""
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute(""";WITH candidate AS (SELECT TOP(1) * FROM app.historical_backfill_jobs
          WITH(UPDLOCK,READPAST,ROWLOCK) WHERE status IN ('NOT_STARTED','RETRY_PENDING')
          AND (next_attempt_at_utc IS NULL OR next_attempt_at_utc<=SYSUTCDATETIME()) ORDER BY priority,partition_start_utc)
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
    with open_database(settings) as connection:
        cursor=connection.cursor(as_dict=True)
        cursor.execute("SELECT status,COUNT(*) item_count FROM app.historical_backfill_jobs GROUP BY status")
        counts={str(row["status"]):int(row["item_count"]) for row in cursor.fetchall()}
    total=sum(counts.values()); complete=counts.get("COMPLETE",0); failed=counts.get("FAILED",0)
    return {"total":total,"complete":complete,"failed":failed,
            "done":bool(total and complete+failed==total)}


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
            """IF NOT EXISTS(SELECT 1 FROM app.historical_backfill_notifications WITH(UPDLOCK,HOLDLOCK)
                              WHERE notification_key=%s)
               BEGIN
                 INSERT app.historical_backfill_notifications(notification_key,terminal_state,total_partitions,
                   complete_partitions,failed_partitions,claimed_at_utc,delivery_status)
                 VALUES(%s,%s,%s,%s,%s,SYSUTCDATETIME(),'CLAIMED'); SELECT 1
               END ELSE SELECT 0""",
            (key, key, terminal_state, summary["total"], summary["complete"], summary["failed"]),
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
    job_id=str(job["backfill_job_id"]); output_root.mkdir(parents=True,exist_ok=True)
    filename=f"{job_id}.csv"
    start=job["partition_start_utc"].strftime("%Y-%m-%d")
    end=job["partition_end_utc"].strftime("%Y-%m-%d")
    command=[str(cli),"-i",str(job["vendor_symbol"]).lower(),"-from",start,"-to",end,
             "-t","tick","-p","bid","-utc","0","-f","csv","-dir",str(output_root),
             "-bs","1","-bp","2500","-r","3","-rp","15000","-fr","-fn",filename]
    for candidate in (output_root/filename,output_root/f"{filename}.csv"):
        if candidate.is_file():
            candidate.unlink()
    completed=subprocess.run(command,capture_output=True,text=True,timeout=7200,check=False,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if completed.returncode:
        detail=(completed.stderr or completed.stdout or "no downloader diagnostics")[-700:]
        raise RuntimeError(f"DOWNLOADER_EXIT_{completed.returncode}: {detail}")
    candidates=[output_root/filename,output_root/f"{filename}.csv"]
    result=next((path for path in candidates if path.is_file()),None)
    if result is None or result.stat().st_size==0:
        raise RuntimeError("DOWNLOAD_OUTPUT_MISSING")
    return result
