from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.config import Settings
from app.database import open_database
from app.research_evidence import sync_cost_models, sync_quality_evidence
from app.research_protocol_store import run_protocol_boundary_audits
from app.model_tournament import run_and_record_selective_tournament


WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def update_job_progress(
    settings: Settings, job_id: str, *, phase: str, phase_number: int,
    completed: int, total: int, message: str,
) -> None:
    completed = max(0, min(completed, total))
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.research_jobs SET current_phase=%s,phase_number=%s,total_phases=%s,
                 completed_work_units=CASE WHEN ISNULL(completed_work_units,0)>%s THEN completed_work_units ELSE %s END,
                 total_work_units=%s,progress_message=%s,last_heartbeat_utc=SYSUTCDATETIME(),
                 eta_seconds=CASE WHEN %s>0 AND started_at_utc IS NOT NULL
                   THEN CONVERT(int,DATEDIFF(second,started_at_utc,SYSUTCDATETIME())*1.0/%s*(%s-%s)) ELSE NULL END,
                 eta_confidence=CASE WHEN %s>=2 THEN 'MEDIUM' WHEN %s>=1 THEN 'LOW' ELSE NULL END,
                 eta_basis=CASE WHEN %s>0 THEN 'Measured throughput from completed work units in this job' ELSE 'Not enough progress to estimate' END
               WHERE research_job_id=%s AND status='RUNNING';
               INSERT app.research_job_phase_history
                 (research_job_id,phase,phase_number,completed_work_units,total_work_units,status_message)
               VALUES(%s,%s,%s,%s,%s,%s);""",
            (phase, phase_number, total, completed, completed, total, message,
             completed, completed or 1, total, completed, completed, completed, completed,
             job_id, job_id, phase, phase_number, completed, total, message),
        )
        connection.commit()


def _heartbeat(settings: Settings, job_id: str, stopped: threading.Event) -> None:
    while not stopped.wait(15):
        try:
            with open_database(settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE app.research_jobs SET last_heartbeat_utc=SYSUTCDATETIME(),
                         lease_expires_at_utc=DATEADD(minute,60,SYSUTCDATETIME())
                       WHERE research_job_id=%s AND lease_owner=%s AND status='RUNNING'""",
                    (job_id, WORKER_ID),
                )
                connection.commit()
        except Exception:
            pass


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


def enqueue_protocol_audit(settings: Settings, tenant_id: str, user_id: str) -> dict[str, object]:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    job_id = str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT configuration_hash FROM app.research_lineages WHERE tenant_id=%s
               ORDER BY market_id,created_at_utc""", (tenant_id,),
        )
        lineage_identity = ":".join(str(row["configuration_hash"]) for row in cursor.fetchall()) or "NO_LINEAGE"
        key = hashlib.sha256(
            f"{tenant_id}:PROTOCOL_AUDIT:{bucket}:{lineage_identity}".encode(),
        ).hexdigest()
        cursor.execute(
            """SELECT research_job_id,status,progress_message FROM app.research_jobs
               WHERE tenant_id=%s AND idempotency_key=%s""", (tenant_id, key),
        )
        current = cursor.fetchone()
        if current:
            return {"job_id": str(current["research_job_id"]), "status": current["status"],
                    "message": current["progress_message"] or "Protocol audit already registered",
                    "execution_enabled": False}
        cursor.execute(
            """INSERT app.research_jobs
                 (research_job_id,tenant_id,job_type,request_json,status,idempotency_key,
                  requested_by_user_id,progress_message)
               VALUES(%s,%s,'PROTOCOL_AUDIT','{}','QUEUED',%s,%s,
                      'Waiting for leakage and boundary audit')""",
            (job_id, tenant_id, key, user_id),
        )
        connection.commit()
    return {"job_id": job_id, "status": "QUEUED", "message": "Protocol audit queued",
            "execution_enabled": False}


def enqueue_selective_tournament(
    settings: Settings, tenant_id: str, user_id: str, market: str, notes: str,
) -> dict[str, object]:
    symbol = market.strip().upper()
    request = {"market": symbol, "notes": notes}
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (1) research_lineage_id,configuration_hash,market_id
               FROM app.research_lineages WHERE tenant_id=%s
                 AND market_id=(SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1)
                 AND status='RESERVED' AND research_target_spec_id IS NOT NULL
               ORDER BY created_at_utc DESC""", (tenant_id, symbol),
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise ValueError("Reserve a target-bound immutable lineage before queueing a tournament")
        key = hashlib.sha256(
            f"{tenant_id}:SELECTIVE_TOURNAMENT:{lineage['configuration_hash']}".encode(),
        ).hexdigest()
        cursor.execute(
            """SELECT research_job_id,status,progress_message FROM app.research_jobs
               WHERE tenant_id=%s AND idempotency_key=%s""", (tenant_id, key),
        )
        current = cursor.fetchone()
        if current:
            return {"job_id": str(current["research_job_id"]), "status": current["status"],
                    "message": current["progress_message"] or "Tournament already registered",
                    "execution_enabled": False}
        job_id = str(uuid4())
        cursor.execute(
            """INSERT app.research_jobs
                 (research_job_id,tenant_id,job_type,request_json,status,idempotency_key,
                  requested_by_user_id,progress_message,market_id,timeframe,model_family)
               VALUES(%s,%s,'SELECTIVE_TOURNAMENT',%s,'QUEUED',%s,%s,
                      'Waiting for target-bound development tournament',%s,'M15','GOVERNED_CATALOGUE')""",
            (job_id, tenant_id, json.dumps(request), key, user_id, str(lineage["market_id"])),
        )
        connection.commit()
    return {"job_id": job_id, "status": "QUEUED", "message": "Selective tournament queued",
            "market": symbol, "execution_enabled": False}


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
                   lease_expires_at_utc=DATEADD(minute,60,SYSUTCDATETIME()),
                   started_at_utc=COALESCE(started_at_utc,SYSUTCDATETIME()),progress_message='Preparing job',
                   current_phase='PREPARING',phase_number=1,total_phases=3,completed_work_units=0,
                   total_work_units=3,last_heartbeat_utc=SYSUTCDATETIME()
               OUTPUT inserted.research_job_id,inserted.tenant_id,inserted.job_type,inserted.request_json""",
            (WORKER_ID,),
        )
        job = cursor.fetchone()
        connection.commit()
    if not job:
        return None
    job_id = str(job["research_job_id"])
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(target=_heartbeat, args=(settings, job_id, heartbeat_stop), daemon=True)
    heartbeat_thread.start()
    try:
        update_job_progress(settings, job_id, phase="EXECUTING", phase_number=2,
                            completed=1, total=3, message=f"Executing {job['job_type']}")
        if job["job_type"] == "EVIDENCE_SYNC":
            quality = sync_quality_evidence(settings)
            costs = sync_cost_models(settings)
            result = {"quality_markets": len(quality), "cost_markets": len(costs),
                      "execution_enabled": False}
            message = "Evidence refresh completed"
        elif job["job_type"] == "PROTOCOL_AUDIT":
            audits = run_protocol_boundary_audits(settings, str(job["tenant_id"]))
            result = {"audit_count": len(audits),
                      "passed": sum(item.get("status") == "PASS" for item in audits),
                      "failed": sum(item.get("status") == "FAIL" for item in audits),
                      "execution_enabled": False}
            message = "Leakage and boundary audit completed"
        elif job["job_type"] == "SELECTIVE_TOURNAMENT":
            request = json.loads(job["request_json"])
            tournament = run_and_record_selective_tournament(
                settings, str(job["tenant_id"]), str(request["market"]),
                notes=str(request.get("notes") or "Target-bound selective tournament"),
            )
            candidates = list(tournament.get("candidates") or [])
            fold_count = max((len(item.get("windows") or []) for item in candidates), default=0)
            with open_database(settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE app.research_jobs SET records_processed=%s,folds_completed=%s,total_folds=%s,
                         candidates_completed=%s,total_candidates=%s,feature_version=%s,dataset_identifier=%s
                       WHERE research_job_id=%s AND lease_owner=%s""",
                    (int(tournament.get("development_rows") or 0), fold_count, fold_count,
                     len(candidates), len(candidates), tournament.get("feature_version"),
                     tournament.get("configuration_hash"), job_id, WORKER_ID),
                )
                connection.commit()
            result = {
                "experiment_id": tournament["experiment_id"],
                "market": tournament["market"],
                "research_leader": tournament["research_leader"],
                "leader_target_sha256": tournament["leader_target_sha256"],
                "leader_passed_all_development_gates": tournament[
                    "leader_passed_all_development_gates"
                ],
                "holdout_consumed": False, "execution_enabled": False,
            }
            message = "Selective development tournament completed"
        else:
            raise ValueError("Unsupported durable research job type")
        update_job_progress(settings, job_id, phase="PERSISTING_OUTPUT", phase_number=3,
                            completed=2, total=3, message="Persisting governed output and metadata")
        status, error = "SUCCEEDED", None
    except Exception as exc:
        result = {"execution_enabled": False}
        status, message, error = "FAILED", "Research job failed", f"{type(exc).__name__}: {exc}"
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """UPDATE app.research_jobs SET status=%s,progress_message=%s,result_json=%s,
                      error_message=%s,completed_at_utc=SYSUTCDATETIME(),lease_owner=NULL,
                      lease_expires_at_utc=NULL,last_heartbeat_utc=SYSUTCDATETIME(),
                      current_phase=%s,phase_number=3,total_phases=3,
                      completed_work_units=CASE WHEN %s='SUCCEEDED' THEN 3 ELSE completed_work_units END,
                      total_work_units=3,eta_seconds=CASE WHEN %s='SUCCEEDED' THEN 0 ELSE NULL END,
                      eta_confidence=CASE WHEN %s='SUCCEEDED' THEN 'HIGH' ELSE NULL END,
                      failure_code=CASE WHEN %s='FAILED' THEN 'RESEARCH_JOB_FAILED' ELSE NULL END
                    WHERE research_job_id=%s AND lease_owner=%s""",
            (status, message, json.dumps(result), error,
             "COMPLETED" if status == "SUCCEEDED" else "FAILED", status, status, status, status,
             job_id, WORKER_ID),
        )
        connection.commit()
    return {"job_id": job_id, "status": status, "message": message, **result}


def read_research_jobs(settings: Settings, tenant_id: str, limit: int = 20) -> dict[str, object]:
    limit = max(1, min(limit, 100))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            f"""SELECT TOP ({limit}) j.research_job_id,j.job_type,j.status,j.attempt_count,j.progress_message,
                       j.error_message,j.warning_message,j.failure_code,j.created_at_utc,j.started_at_utc,
                       j.completed_at_utc,j.current_phase,j.phase_number,j.total_phases,
                       j.completed_work_units,j.total_work_units,j.records_processed,j.folds_completed,
                       j.total_folds,j.candidates_completed,j.total_candidates,j.trials_completed,j.total_trials,
                       j.last_heartbeat_utc,j.eta_seconds,j.eta_confidence,j.eta_basis,j.timeframe,j.model_family,
                       j.code_version,j.feature_version,j.dataset_identifier,m.symbol AS market,
                       CASE WHEN j.status='RUNNING' AND ISNULL(j.last_heartbeat_utc,j.started_at_utc)<DATEADD(minute,-2,SYSUTCDATETIME())
                            THEN 'STALLED' ELSE j.status END AS effective_status,
                       CASE WHEN j.started_at_utc IS NULL THEN NULL ELSE DATEDIFF(second,j.started_at_utc,COALESCE(j.completed_at_utc,SYSUTCDATETIME())) END AS elapsed_seconds
                FROM app.research_jobs j LEFT JOIN app.markets m ON m.market_id=j.market_id
                WHERE j.tenant_id=%s ORDER BY j.created_at_utc DESC""", (tenant_id,),
        )
        jobs = [{key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value)
                 for key, value in row.items()} for row in cursor.fetchall()]
    active = next((item for item in jobs if item["effective_status"] in {"QUEUED", "RUNNING", "STALLED"}), None)
    latest_success = next((item for item in jobs if item["status"] == "SUCCEEDED"), None)
    return {"active_job": active, "latest_successful_job": latest_success, "jobs": jobs,
            "system_status": "STALLED" if active and active["effective_status"] == "STALLED" else "ACTIVE" if active else "IDLE",
            "stale_after_seconds": 120, "execution_enabled": False,
            "governance_notice": "Training completion does not validate a model or enable trading."}


def read_research_job_detail(settings: Settings, tenant_id: str, job_id: str) -> dict[str, object]:
    summary = read_research_jobs(settings, tenant_id, 100)
    job = next((item for item in summary["jobs"] if str(item["research_job_id"]) == job_id), None)
    if not job:
        raise ValueError("Research job not found")
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT phase,status_message,phase_number,completed_work_units,total_work_units,recorded_at_utc
               FROM app.research_job_phase_history WHERE research_job_id=%s ORDER BY recorded_at_utc""",
            (job_id,),
        )
        phases = [{key: (value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value)
                   for key, value in row.items()} for row in cursor.fetchall()]
    return {"job": job, "phases": phases, "execution_enabled": False,
            "governance_notice": summary["governance_notice"]}
