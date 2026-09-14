import asyncio

from app import main
from app import scheduler as scheduler_module
from app.config import Settings


def test_account_sync_scheduler_starts_even_when_database_was_unready_at_startup(monkeypatch):
    events = []

    class Scheduler:
        def __init__(self, settings):
            events.append("created")

        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(main, "AccountSyncScheduler", Scheduler)
    monkeypatch.setattr(main, "operational_schema_ready", lambda settings: False)

    async def run():
        async with main.lifespan(main.app):
            assert events == ["created", "started"]

    asyncio.run(run())
    assert events == ["created", "started", "stopped"]


def test_scheduler_waits_for_schema_then_authenticates_and_syncs(monkeypatch):
    """A database outage cannot trigger IG login; recovery resumes the same worker."""
    events = []
    schema_ready = iter((False, True))

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        async def wait(self):
            if not self.stopped:
                raise TimeoutError

    class Client:
        def __init__(self, settings):
            events.append("client_created")

        def authenticate(self):
            events.append("authenticated")

        def close(self):
            events.append("closed")

    stop = Stop()
    worker = scheduler_module.AccountSyncScheduler(Settings(_env_file=None))
    worker._stop = stop

    def check_schema(settings):
        result = next(schema_ready)
        events.append(f"schema_{result}")
        return result

    def sync(settings, *, correlation_id, client):
        events.append("synced")
        stop.stopped = True

    async def no_delay(seconds):
        return None

    monkeypatch.setattr(scheduler_module, "operational_schema_ready", check_schema)
    monkeypatch.setattr(scheduler_module, "IGDemoClient", Client)
    monkeypatch.setattr(scheduler_module, "sync_ig_demo", sync)
    monkeypatch.setattr(scheduler_module, "mark_stale_components", lambda settings: None)
    monkeypatch.setattr(scheduler_module.asyncio, "sleep", no_delay)

    asyncio.run(worker._run())

    assert events == ["schema_False", "schema_True", "client_created", "authenticated", "synced"]
