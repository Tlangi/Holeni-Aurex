from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from threading import Event
from time import monotonic

from app.broker_rules import sync_broker_market_rules
from app.config import Settings
from app.database import open_database
from app.forward_evidence import capture_forward_evidence, run_market_quality_audits
from app.model_pipeline import train_all_markets
from app.macro_intelligence import generate_market_decisions, sync_official_macro_sources
from app.research_evidence import sync_cost_models, sync_quality_evidence
from app.market_recovery import process_one_bounded_recovery, schedule_bounded_recovery_jobs
from app.research_jobs import process_one_research_job
from app.shadow_engine import run_shadow_cycle

logger = logging.getLogger("aurex.shadow_worker")


class ShadowTradingWorker:
    """Continuous signal/risk/intent worker with no broker order capability."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stop_event = Event()
        self._last_rules = 0.0
        self._last_training = 0.0
        self._last_macro = 0.0
        self._last_evidence = 0.0
        self._last_quality = 0.0

    def stop(self) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        self._component("trading_engine", "CURRENT", "Shadow worker started; broker submission is unavailable")
        while not self.stop_event.is_set():
            started = monotonic()
            try:
                self.run_once()
            except Exception as exc:
                logger.exception(
                    "shadow worker cycle failed",
                    extra={"worker": "shadow_trading", "operation": "shadow.cycle", "result": type(exc).__name__},
                )
                self._component("trading_engine", "DEGRADED", "Shadow worker cycle failed; no order was submitted")
            elapsed = monotonic() - started
            self.stop_event.wait(max(1.0, self.settings.shadow_cycle_seconds - elapsed))
        self._component("trading_engine", "DISABLED", "Shadow worker stopped")

    def run_once(self) -> list[dict[str, object]]:
        with open_database(self.settings) as lock_connection:
            lock_cursor = lock_connection.cursor()
            lock_cursor.execute(
                """DECLARE @result int;
                   EXEC @result=sys.sp_getapplock @Resource='aurex:shadow-worker-cycle',
                        @LockMode='Exclusive',@LockOwner='Session',@LockTimeout=0;
                   SELECT @result;"""
            )
            if int(lock_cursor.fetchone()[0]) < 0:
                logger.info(
                    "shadow cycle skipped because another worker owns the lock",
                    extra={"worker": "shadow_trading", "operation": "shadow.cycle", "result": "SKIPPED_LOCKED"},
                )
                return [{"result": "SKIPPED_LOCKED"}]
            try:
                return self._run_locked_cycle()
            finally:
                lock_cursor.execute(
                    "EXEC sys.sp_releaseapplock @Resource='aurex:shadow-worker-cycle',@LockOwner='Session'"
                )

    def _run_locked_cycle(self) -> list[dict[str, object]]:
        now_clock = monotonic()
        try:
            process_one_research_job(self.settings)
        except Exception as exc:
            logger.warning(
                "durable research job check failed",
                extra={"worker": "shadow_trading", "operation": "research_jobs.claim",
                       "result": type(exc).__name__},
            )
        if now_clock - self._last_rules >= self.settings.broker_rule_sync_seconds:
            self._synchronize_rules()
            self._last_rules = now_clock
        if now_clock - self._last_quality >= self.settings.market_quality_check_seconds:
            self._audit_market_quality()
            self._last_quality = now_clock
        if now_clock - self._last_training >= self.settings.model_training_check_seconds:
            self._train_models()
            self._last_training = now_clock
        if now_clock - self._last_macro >= self.settings.macro_sync_seconds:
            self._synchronize_macro()
            self._last_macro = now_clock
        all_tenants = self._all_tenant_ids()
        for tenant_id in all_tenants:
            try:
                generate_market_decisions(self.settings, tenant_id)
            except Exception as exc:
                logger.warning(
                    "market decision generation failed",
                    extra={"worker": "shadow_trading", "operation": "macro.decisions", "result": type(exc).__name__},
                )
        tenants = self._tenant_ids()
        all_outcomes: list[dict[str, object]] = []
        for tenant_id in tenants:
            outcomes = run_shadow_cycle(self.settings, tenant_id)
            all_outcomes.extend({"tenant_id": tenant_id, **item} for item in outcomes)
        if now_clock - self._last_evidence >= self.settings.forward_evidence_seconds:
            for tenant_id in all_tenants:
                try:
                    capture_forward_evidence(self.settings, tenant_id)
                except Exception as exc:
                    logger.warning(
                        "forward evidence capture failed",
                        extra={"worker": "shadow_trading", "operation": "forward_evidence.capture",
                               "result": type(exc).__name__},
                    )
            self._last_evidence = now_clock
        blocked = sum(1 for item in all_outcomes if item.get("result") == "BLOCKED")
        self._component(
            "trading_engine", "CURRENT",
            f"Shadow worker running; outcomes={len(all_outcomes)}, blocked={blocked}; broker submission unavailable",
        )
        logger.info(
            "shadow cycle completed",
            extra={"worker": "shadow_trading", "operation": "shadow.cycle", "result": f"OUTCOMES_{len(all_outcomes)}"},
        )
        return all_outcomes

    def _audit_market_quality(self) -> None:
        try:
            outcomes = run_market_quality_audits(self.settings)
            segment_outcomes = sync_quality_evidence(self.settings)
            cost_outcomes = sync_cost_models(self.settings)
            recovery_jobs = schedule_bounded_recovery_jobs(self.settings)
            recovery = process_one_bounded_recovery(self.settings)
            failed = sum(1 for item in outcomes if item.get("status") == "FAIL")
            logger.info(
                "market quality audits completed",
                extra={"worker": "shadow_trading", "operation": "market_quality.audit",
                       "result": f"CHECKS_{len(outcomes)}_SEGMENTS_{len(segment_outcomes)}_COSTS_{len(cost_outcomes)}_RECOVERY_{len(recovery_jobs)}_{'RUN' if recovery else 'IDLE'}_FAILED_{failed}"},
            )
        except Exception as exc:
            logger.warning(
                "market quality audits failed",
                extra={"worker": "shadow_trading", "operation": "market_quality.audit",
                       "result": type(exc).__name__},
            )

    def _synchronize_rules(self) -> None:
        try:
            result = sync_broker_market_rules(self.settings)
            synchronized = len(result.get("markets") or [])
            self._component("risk_engine", "CURRENT", f"Broker sizing rules current for {synchronized} markets")
        except Exception as exc:
            self._component("risk_engine", "DEGRADED", "Broker sizing rules unavailable; risk approval blocked")
            logger.warning(
                "broker rule synchronization failed",
                extra={"worker": "shadow_trading", "operation": "broker_rules.sync", "result": type(exc).__name__},
            )

    def _train_models(self) -> None:
        try:
            outcomes = train_all_markets(
                self.settings,
                minimum_rows=self.settings.model_minimum_rows,
                acceptance_auc=self.settings.model_acceptance_auc,
            )
            logger.info(
                "chronological model check completed",
                extra={"worker": "shadow_trading", "operation": "models.train_validate", "result": f"MARKETS_{len(outcomes)}"},
            )
        except Exception as exc:
            logger.warning(
                "chronological model check failed",
                extra={"worker": "shadow_trading", "operation": "models.train_validate", "result": type(exc).__name__},
            )

    def _synchronize_macro(self) -> None:
        try:
            result = sync_official_macro_sources(self.settings)
            logger.info(
                "official macro intelligence synchronized",
                extra={"worker": "shadow_trading", "operation": "macro.sync", "result": str(result.get("status"))},
            )
        except Exception as exc:
            self._component("macro_intelligence", "DEGRADED", "Official-source synchronization failed; macro decisions fail closed")
            logger.warning(
                "official macro synchronization failed",
                extra={"worker": "shadow_trading", "operation": "macro.sync", "result": type(exc).__name__},
            )

    def _tenant_ids(self) -> list[str]:
        with open_database(self.settings) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT tenant_id FROM app.engine_controls WHERE mode='SHADOW' AND new_orders_enabled=0")
            return [str(row[0]) for row in cursor.fetchall()]

    def _all_tenant_ids(self) -> list[str]:
        with open_database(self.settings) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT tenant_id FROM app.engine_controls")
            return [str(row[0]) for row in cursor.fetchall()]

    def _component(self, code: str, status: str, detail: str) -> None:
        try:
            with open_database(self.settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """UPDATE app.platform_components SET status=%s,status_detail=%s,
                       checked_at_utc=SYSUTCDATETIME() WHERE component_code=%s""",
                    (status, detail[:300], code),
                )
                connection.commit()
        except Exception:
            logger.exception("could not update worker component state")
