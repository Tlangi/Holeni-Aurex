import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import logging
from uuid import uuid4

from app.config import Settings
from app.database import DatabaseUnavailable, open_database, operational_schema_ready
from app.ig_demo import IGDemoClient, IGDemoUnavailable, ig_error_category
from app.ig_sync import SyncAlreadyRunning, sync_ig_demo

logger = logging.getLogger("aurex.scheduler")


class AccountSyncScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._client: IGDemoClient | None = None

    def start(self) -> None:
        if self._task or not self.settings.background_sync_enabled:
            return
        self._task = asyncio.create_task(self._run(), name="aurex-account-sync")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client:
            self._client.close()
            self._client = None

    async def _run(self) -> None:
        await asyncio.sleep(5)
        failures = 0
        while not self._stop.is_set():
            correlation_id = str(uuid4())
            try:
                if not await asyncio.to_thread(operational_schema_ready, self.settings):
                    raise DatabaseUnavailable("Operational schema is not ready for account sync")
                if self._client is None:
                    self._client = IGDemoClient(self.settings)
                    await asyncio.to_thread(self._client.authenticate)
                await asyncio.to_thread(
                    sync_ig_demo, self.settings, correlation_id=correlation_id,
                    client=self._client,
                )
                if self.settings.experimental_demo_configured:
                    from app.experimental_demo import enforce_experimental_max_holding
                    await asyncio.to_thread(enforce_experimental_max_holding, self.settings)
                failures = 0
            except SyncAlreadyRunning:
                logger.info(
                    "scheduled sync skipped because a worker owns the lock",
                    extra={
                        "correlation_id": correlation_id,
                        "worker": "account_sync_scheduler",
                        "operation": "ig.sync.schedule",
                        "result": "SKIPPED_LOCKED",
                    },
                )
            except IGDemoUnavailable as exc:
                failures += 1
                category = ig_error_category(exc.error_code)
                logger.warning(
                    "scheduled sync failed",
                    extra={
                        "correlation_id": correlation_id,
                        "worker": "account_sync_scheduler",
                        "operation": "ig.sync.schedule",
                        "result": category,
                    },
                )
                if self._client:
                    self._client.close()
                    self._client = None
                if category in {"AUTHENTICATION", "SESSION"}:
                    await asyncio.to_thread(
                        mark_authentication_blocked, self.settings,
                        exc.error_code or category, category=category,
                    )
                    logger.error(
                        "scheduled IG login disabled until API restart",
                        extra={
                            "worker": "account_sync_scheduler",
                            "operation": "ig.auth.circuit_breaker",
                            "result": exc.error_code,
                        },
                    )
                    break
            except DatabaseUnavailable:
                # A transient database outage must not make account sync wait
                # through the exponential IG-error backoff after recovery.
                failures = 0
                logger.warning(
                    "scheduled sync waiting for operational database",
                    extra={"correlation_id": correlation_id, "worker": "account_sync_scheduler",
                           "operation": "ig.sync.schedule", "result": "DATABASE_UNAVAILABLE"},
                )
            except Exception as exc:
                failures += 1
                logger.warning(
                    "scheduled sync failed",
                    extra={
                        "correlation_id": correlation_id,
                        "worker": "account_sync_scheduler",
                        "operation": "ig.sync.schedule",
                        "result": type(exc).__name__,
                    },
                )
            await asyncio.to_thread(mark_stale_components, self.settings)
            delay = min(self.settings.account_sync_seconds * (2**failures), 3600)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass


def mark_stale_components(settings: Settings) -> None:
    """Turn freshness into an operational state that future risk gates can consume."""
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE app.platform_components
                SET status='STALE',
                    status_detail=N'No successful account sync inside freshness limit'
                WHERE component_code='ig_demo'
                  AND status NOT IN ('DISABLED', 'ERROR')
                  AND DATEDIFF(SECOND, checked_at_utc, SYSUTCDATETIME()) > %s;
                """,
                (settings.stale_after_seconds,),
            )
            connection.commit()
    except Exception:
        logger.error(
            "freshness check could not update the account-sync state",
            extra={
                "worker": "account_sync_scheduler",
                "operation": "component.freshness",
                "result": "DATABASE_UNAVAILABLE",
            },
        )


def mark_authentication_blocked(
    settings: Settings, error_code: str, *, category: str = "AUTHENTICATION",
) -> None:
    """Open the login circuit after a credential/account rejection."""
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """UPDATE app.platform_components
                   SET status='ERROR',status_detail=%s,checked_at_utc=SYSUTCDATETIME()
                   WHERE component_code IN ('ig_demo','market_feed')""",
                (f"IG {category.lower()} circuit open: {error_code}"[:300],),
            )
            connection.commit()
    except DatabaseUnavailable:
        logger.error(
            "could not persist IG authentication circuit state",
            extra={"operation": "ig.auth.circuit_breaker", "result": "DATABASE_UNAVAILABLE"},
        )
