from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone

from app.config import Settings
from app.database import open_database


TRIAGE_VERSION = "HISTORICAL_FAILURE_TRIAGE_V1"
_COVERAGE = re.compile(r"coverage=([0-9.]+)%")
_RECENT_GAPS = re.compile(r"recent_gap_count=(\d+)")


def classify_failure(error_code: str | None, detail: str | None) -> dict[str, object]:
    """Classify terminal collection failures without making them research eligible."""
    code = str(error_code or "UNKNOWN")
    message = str(detail or "")
    if "no candles" in message.lower():
        reason = "EMPTY_VENDOR_PARTITION"
        action = "VERIFY_VENDOR_AVAILABILITY_OR_SYMBOL_MAPPING"
    elif "COMPLETENESS_OR_RECENT_GAPS" in message:
        coverage_match = _COVERAGE.search(message)
        gap_match = _RECENT_GAPS.search(message)
        coverage = float(coverage_match.group(1)) if coverage_match else None
        recent_gaps = int(gap_match.group(1)) if gap_match else None
        if recent_gaps:
            reason = "RECENT_UNEXPECTED_GAPS"
            action = "RECOVER_MISSING_MINUTES_AND_REVALIDATE"
        else:
            reason = "BELOW_COVERAGE_THRESHOLD"
            action = "REVIEW_CALENDAR_AND_RECOVER_MISSING_MINUTES"
        return {"reason_code": reason, "required_action": action,
                "coverage_percent": coverage, "recent_gap_count": recent_gaps}
    else:
        reason = f"UNCLASSIFIED_{code.upper()}"
        action = "MANUAL_REVIEW"
    return {"reason_code": reason, "required_action": action,
            "coverage_percent": None, "recent_gap_count": None}


def build_failed_partition_report(settings: Settings) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT j.backfill_job_id,m.symbol,j.vendor,j.vendor_symbol,
                      j.partition_start_utc,j.partition_end_utc,j.attempt_count,
                      j.last_error_code,j.last_error_detail
               FROM app.historical_backfill_jobs j
               JOIN app.markets m ON m.market_id=j.market_id
               WHERE j.status='FAILED'
               ORDER BY m.symbol,j.partition_start_utc,j.backfill_job_id"""
        )
        rows = cursor.fetchall()

    partitions = []
    for row in rows:
        classification = classify_failure(row["last_error_code"], row["last_error_detail"])
        partitions.append({
            "backfill_job_id": str(row["backfill_job_id"]),
            "symbol": str(row["symbol"]), "vendor": str(row["vendor"]),
            "vendor_symbol": str(row["vendor_symbol"]),
            "partition_start_utc": row["partition_start_utc"].isoformat(),
            "partition_end_utc": row["partition_end_utc"].isoformat(),
            "attempt_count": int(row["attempt_count"]),
            "error_code": str(row["last_error_code"] or "UNKNOWN"),
            "error_detail": str(row["last_error_detail"] or ""),
            **classification,
            "prospective_evidence_allowed": False,
            "research_eligible": False,
        })
    canonical = json.dumps(partitions, sort_keys=True, separators=(",", ":"))
    reasons = Counter(str(row["reason_code"]) for row in partitions)
    markets = Counter(str(row["symbol"]) for row in partitions)
    return {
        "triage_version": TRIAGE_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_DIAGNOSTIC",
        "failed_partition_count": len(partitions),
        "prospective_joined_credit": 0,
        "training_gate_effect": "NONE",
        "partition_set_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "reason_counts": dict(sorted(reasons.items())),
        "market_counts": dict(sorted(markets.items())),
        "partitions": partitions,
    }
