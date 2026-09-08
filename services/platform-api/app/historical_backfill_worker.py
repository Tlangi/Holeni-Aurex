from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from threading import Event

from app.config import Settings
from app.dukascopy_tick_import import import_dukascopy_ticks
from app.email_delivery import send_email
from app.historical_backfill import (claim_completion_notification, claim_next, download_partition,
                                     record_completion_notification, recover_stale_claims,
                                     resource_gate, update_job)
from app.historical_validation import validate_partition

logger=logging.getLogger("aurex.historical_backfill")


class HistoricalBackfillWorker:
    def __init__(self,settings:Settings,stopped:Event,project_root:Path) -> None:
        self.settings,self.stopped,self.project_root=settings,stopped,project_root
        self.output_root=project_root/"dukascopy"/"backfill"
        self.cli=project_root/"dukascopy"/"node_modules"/".bin"/"dukascopy-node.cmd"

    def run(self) -> None:
        recovered=recover_stale_claims(self.settings)
        if recovered:
            logger.warning("recovered stale historical jobs",extra={"operation":"backfill.recovery","result":recovered})
        while not self.stopped.is_set():
            if not self.settings.historical_backfill_enabled:
                self.stopped.wait(self.settings.historical_backfill_poll_seconds); continue
            allowed,reason=resource_gate(self.settings,self.project_root)
            if not allowed:
                logger.warning("backfill paused",extra={"operation":"backfill.resource_gate","result":reason})
                self.stopped.wait(self.settings.historical_backfill_poll_seconds); continue
            job=claim_next(self.settings)
            if not job:
                self.stopped.wait(self.settings.historical_backfill_poll_seconds); continue
            job_id=str(job["backfill_job_id"])
            try:
                path=download_partition(self.cli,self.output_root,job)
                update_job(self.settings,job_id,"VALIDATING",output_path=str(path))
                result=import_dukascopy_ticks(self.settings,symbol=self._symbol(str(job["market_id"])),path=path,
                    vendor_symbol=str(job["vendor_symbol"]),requested_start=job["partition_start_utc"].replace(tzinfo=timezone.utc),
                    requested_end=job["partition_end_utc"].replace(tzinfo=timezone.utc))
                validation=validate_partition(self.settings,str(result["import_batch_id"]))
                if validation["status"] != "VALIDATED":
                    raise RuntimeError("PARTITION_VALIDATION_FAILED")
                update_job(self.settings,job_id,"COMPLETE",import_batch_id=str(result["import_batch_id"]))
                logger.info("partition imported as unverified evidence",extra={"operation":"backfill.partition","result":"COMPLETE"})
            except Exception as exc:
                retry=int(job["attempt_count"])<self.settings.historical_backfill_max_attempts
                update_job(self.settings,job_id,"RETRY_PENDING" if retry else "FAILED",
                           error_code=type(exc).__name__,error_detail=str(exc))
                logger.exception("historical partition failed")
            self._notify_if_finished()
            self.stopped.wait(5)

    def _symbol(self,market_id:str) -> str:
        from app.database import open_database
        with open_database(self.settings) as connection:
            cursor=connection.cursor(); cursor.execute("SELECT symbol FROM app.markets WHERE market_id=%s",(market_id,))
            row=cursor.fetchone()
        if not row: raise ValueError("market disappeared during backfill")
        return str(row[0])

    def _notify_if_finished(self) -> None:
        if not self.settings.smtp_configured:
            return
        recipient=self.settings.trade_report_recipient or self.settings.owner_email or self.settings.smtp_from_email
        if not recipient:
            return
        summary=claim_completion_notification(self.settings)
        if not summary:
            return
        failed=int(summary["failed"]); outcome="completed successfully" if not failed else f"completed with {failed} failed partition(s)"
        try:
            send_email(self.settings,recipient=recipient,subject="Aurex historical backfill finished",
                       plain_text=f"The Aurex historical backfill {outcome}. Completed: {summary['complete']} of {summary['total']}. Research eligibility still requires the independent validation gates shown in Aurex Research.")
            record_completion_notification(self.settings,str(summary["notification_key"]),sent=True)
        except Exception as exc:
            # Notification delivery must never turn a successfully imported partition into a retry.
            record_completion_notification(self.settings,str(summary["notification_key"]),sent=False,error_detail=str(exc))
            logger.exception("historical backfill completion email failed")
