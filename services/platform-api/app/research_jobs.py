from __future__ import annotations

import hashlib
import json
import os
import socket
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.database import open_database
from app.research_evidence import sync_cost_models, sync_quality_evidence


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def enqueue_evidence_refresh(settings: Settings, tenant_id: str, user_id: str) -> dict[str, object]:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    key = hashlib.sha256(f"{tenant_id}:EVIDENCE_SYNC:{bucket}".encode()).hexdigest()
    job_id = str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT research_job_id,status,progress_message FROM app.research_jobs
               WHERE tenant_id=%s AND idempotency_key=%s""", (tenant_id, key),
        )
        current = cursor.fetchone()
        if current:
            return {"job_id": str(current["research_job_id"]), "status": current["status"],
                    "message": current["progress_message"] or "Evidence refresh already registered",
                    "execution_enabled": False}
        cursor.execute(
            """INSERT app.research_jobs
                 (research_job_id,tenant_id,job_type,request_json,status,idempotency_key,
                  requested_by_user_id,progress_message)
               VALUES(%s,%s,'EVIDENCE_SYNC','{}','QUEUED',%s,%s,'Waiting for research worker')""",
            (job_id, tenant_id, key, user_id),
        )
        connection.commit()
    return {"job_id": job_id, "status": "QUEUED", "message": "Evidence refresh queued",
            "execution_enabled": False}


def process_one_research_job(settings: Settings) -> dict[str, object] | None:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """;WITH claimable AS (
                   SELECT TOP (1) * FROM app.research_jobs WITH (UPDLOCK,READPAST,ROWLOCK)
                   WHERE status='QUEUED' OR (status='RUNNING' AND lease_expires_at_utc<SYSUTCDATETIME())
                   ORDER BY created_at_utc
               )
               UPDATE claimable SET status='RUNNING',attempt_count=attempt_count+1,lease_owner=%s,
                   lease_expires_at_utc=DATEADD(minute,10,SYSUTCDATETIME()),
                   started_at_utc=COALESCE(started_at_utc,SYSUTCDATETIME()),progress_message='Running'
               OUTPUT inserted.research_job_id,inserted.tenant_id,inserted.job_type,inserted.request_json""",
            (WORKER_ID,),
        )
        job = cursor.fetchone()
        connection.commit()
    if not job:
        return None
    job_id = str(job["research_job_id"])
    try:
        if job["job_type"] != "EVIDENCE_SYNC":
            raise ValueError("Unsupported durable research job type")
        quality = sync_quality_evidence(settings)
        costs = sync_cost_models(settings)
        result = {"quality_markets": len(quality), "cost_markets": len(costs),
                  "execution_enabled": False}
        status, message, error = "SUCCEEDED", "Evidence refresh completed", None
    except Exception as exc:
        result = {"execution_enabled": False}
        status, message, error = "FAILED", "Evidence refresh failed", type(exc).__name__
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.research_jobs SET status=%s,progress_message=%s,result_json=%s,
                      error_message=%s,completed_at_utc=SYSUTCDATETIME(),lease_owner=NULL,
                      lease_expires_at_utc=NULL WHERE research_job_id=%s AND lease_owner=%s""",
            (status, message, json.dumps(result), error, job_id, WORKER_ID),
        )
        connection.commit()
    return {"job_id": job_id, "status": status, "message": message, **result}


def read_research_jobs(settings: Settings, tenant_id: str, limit: int = 20) -> dict[str, object]:
    limit = max(1, min(limit, 100))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            f"""SELECT TOP ({limit}) research_job_id,job_type,status,attempt_count,progress_message,
                       error_message,created_at_utc,started_at_utc,completed_at_utc
                FROM app.research_jobs WHERE tenant_id=%s ORDER BY created_at_utc DESC""", (tenant_id,),
        )
        jobs = [{key: (value.isoformat() if isinstance(value, datetime) else value)
                 for key, value in row.items()} for row in cursor.fetchall()]
    return {"jobs": jobs, "execution_enabled": False}
