import asyncio

from app import main


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
