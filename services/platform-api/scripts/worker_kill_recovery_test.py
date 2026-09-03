"""Controlled fake-broker worker kill using real SQL transaction orchestration."""
from __future__ import annotations

import multiprocessing as mp
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402


def crashed_worker(run_id: str, resource: str, ready: mp.Event) -> None:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor()
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("""DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=%s,
          @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=0; SELECT @r""", (resource,))
        if int(cursor.fetchone()[0]) < 0:
            raise RuntimeError("fixture worker could not acquire reservation")
        cursor.execute("""INSERT app.sync_runs(sync_run_id,correlation_id,worker,status,started_at_utc)
          VALUES(%s,%s,'fake_broker_worker','RUNNING',SYSUTCDATETIME())""", (run_id, run_id))
        ready.set()
        time.sleep(60)


if __name__ == "__main__":
    run_id, resource = str(uuid4()), f"aurex:fake-worker-kill:{uuid4()}"
    ready = mp.Event()
    process = mp.Process(target=crashed_worker, args=(run_id, resource, ready))
    process.start()
    if not ready.wait(15):
        process.terminate(); process.join()
        raise SystemExit("Worker did not reach the simulated post-acceptance persistence window")
    process.terminate()
    process.join(15)
    with open_database(get_settings()) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM app.sync_runs WHERE sync_run_id=%s", (run_id,))
        orphaned = int(cursor.fetchone()[0])
        cursor.execute("BEGIN TRANSACTION")
        cursor.execute("""DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=%s,
          @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=0; SELECT @r""", (resource,))
        recovered_lock = int(cursor.fetchone()[0]) >= 0
        connection.rollback()
    if orphaned or not recovered_lock or process.exitcode == 0:
        raise SystemExit("FAIL: killed worker state was not safely rolled back/recoverable")
    print({"status":"PASS","broker":"SIMULATED","real_sql":True,"worker_killed":True,
           "uncommitted_state_rolled_back":True,"reservation_recoverable":True,
           "broker_orders_submitted":0})
