"""Link and selectively revalidate failed historical partitions without download."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.historical_backfill import (failed_jobs_for_revalidation,
                                     link_failed_jobs_to_import_evidence, update_job)
from app.historical_validation import VALIDATION_VERSION, validate_partition, validation_failure_detail
from app.m1_m5_reconciliation import reconcile_batch_to_accepted_m5
from app.research_cohort_eligibility import canonical_sha256
from app.timeframe_fallback import persist_batch_cross_timeframe_recovery


ROOT = Path(__file__).resolve().parents[3]


def run(*, apply: bool, markets: set[str] | None = None,
        calendar_candidates_only: bool = False) -> dict[str, object]:
    settings = get_settings()
    linked = link_failed_jobs_to_import_evidence(settings) if apply else 0
    jobs = failed_jobs_for_revalidation(settings)
    if markets:
        jobs = [job for job in jobs if str(job["symbol"]) in markets]
    if calendar_candidates_only:
        jobs = [job for job in jobs
                if job["requested_start_utc"] is not None and job["requested_end_utc"] is not None
                and (job["requested_end_utc"] - job["requested_start_utc"]).total_seconds() <= 86400]
    results = []
    if apply:
        for job in jobs:
            job_id = str(job["backfill_job_id"])
            batch_id = str(job["import_batch_id"])
            try:
                validation = validate_partition(settings, batch_id)
                if validation["status"] == "VALIDATED":
                    reconciliation = reconcile_batch_to_accepted_m5(settings, batch_id)
                    recovery = persist_batch_cross_timeframe_recovery(settings, batch_id)
                    update_job(settings, job_id, "COMPLETE", import_batch_id=batch_id)
                    results.append({"job_id": job_id, "import_batch_id": batch_id,
                        "market": job["symbol"], "status": "COMPLETE",
                        "coverage_percentage": validation["coverage_percentage"],
                        "m5_source": reconciliation["primary"]["m5_source"],
                        "cross_timeframe_recovery": recovery})
                else:
                    detail = validation_failure_detail(validation)
                    update_job(settings, job_id, "FAILED", error_code="RuntimeError",
                               error_detail=detail, import_batch_id=batch_id)
                    results.append({"job_id": job_id, "import_batch_id": batch_id,
                        "market": job["symbol"], "status": "STILL_FAILED",
                        "coverage_percentage": validation["coverage_percentage"],
                        "detail": detail})
            except Exception as exc:
                # Infrastructure failure is not new partition evidence. Keep the
                # linked job and its last governed validation result unchanged.
                results.append({"job_id": job_id, "import_batch_id": batch_id,
                    "market": job["symbol"], "status": "ERROR",
                    "error_type": type(exc).__name__, "detail": str(exc)[:500]})
    report = {"authority": "HISTORICAL_FAILED_PARTITION_SELECTIVE_REVALIDATION",
        "mode": "APPLY" if apply else "DRY_RUN", "validation_version": VALIDATION_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "linked_legacy_jobs": linked, "market_filter": sorted(markets) if markets else None,
        "calendar_candidates_only": calendar_candidates_only,
        "eligible_job_count": len(jobs),
        "download_performed": False, "model_training_performed": False,
        "broker_submission_authority": False, "results": results}
    report["report_sha256"] = canonical_sha256(report)
    if apply:
        output = ROOT / "docs/audits" / (
            f"AUREX_HISTORICAL_SELECTIVE_REVALIDATION_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
            f"{report['report_sha256'][:12]}.json")
        if output.exists():
            raise FileExistsError(output)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["artifact_path"] = str(output)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write evidence links and revalidate eligible failed jobs")
    parser.add_argument("--market", action="append", default=[],
                        help="Selectively revalidate one market; may be repeated")
    parser.add_argument("--calendar-candidates-only", action="store_true",
                        help="Limit work to partitions no longer than one day")
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, markets=set(args.market) or None,
                         calendar_candidates_only=args.calendar_candidates_only), indent=2))
