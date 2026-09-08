from pathlib import Path
from threading import Event

from app.config import Settings
from app.historical_backfill_worker import HistoricalBackfillWorker


def test_worker_is_single_concurrency_and_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    stopped=Event(); stopped.set()
    monkeypatch.setattr("app.historical_backfill_worker.recover_stale_claims",lambda *_: 0)
    monkeypatch.setattr("app.historical_backfill_worker.claim_next",lambda *_: (_ for _ in ()).throw(AssertionError()))
    HistoricalBackfillWorker(Settings(),stopped,tmp_path).run()


def test_worker_has_no_broker_execution_capability(tmp_path: Path) -> None:
    worker=HistoricalBackfillWorker(Settings(),Event(),tmp_path)
    assert not hasattr(worker,"broker") and not hasattr(worker,"submit")


def test_worker_recovers_abandoned_claims_on_start(monkeypatch, tmp_path: Path) -> None:
    stopped=Event(); stopped.set(); calls=[]
    monkeypatch.setattr("app.historical_backfill_worker.recover_stale_claims",lambda settings: calls.append(settings) or 1)
    HistoricalBackfillWorker(Settings(),stopped,tmp_path).run()
    assert len(calls)==1


def test_completion_notification_is_checked_after_terminal_failure(monkeypatch, tmp_path: Path) -> None:
    settings=Settings(historical_backfill_enabled=True,historical_backfill_poll_seconds=15)
    stopped=Event(); updates=[]; notices=[]
    job={"backfill_job_id":"job","attempt_count":settings.historical_backfill_max_attempts,
         "market_id":"market","vendor_symbol":"usdjpy","partition_start_utc":None,
         "partition_end_utc":None}
    monkeypatch.setattr("app.historical_backfill_worker.recover_stale_claims",lambda *_: 0)
    monkeypatch.setattr("app.historical_backfill_worker.resource_gate",lambda *_: (True,"PASS"))
    monkeypatch.setattr("app.historical_backfill_worker.claim_next",lambda *_: job if not updates else stopped.set())
    monkeypatch.setattr("app.historical_backfill_worker.download_partition",lambda *_: (_ for _ in ()).throw(RuntimeError("final failure")))
    monkeypatch.setattr("app.historical_backfill_worker.update_job",lambda *args,**kwargs: updates.append((args,kwargs)))
    worker=HistoricalBackfillWorker(settings,stopped,tmp_path)
    monkeypatch.setattr(worker,"_notify_if_finished",lambda: notices.append(True))
    worker.run()
    assert updates[0][0][2] == "FAILED"
    assert notices == [True]
