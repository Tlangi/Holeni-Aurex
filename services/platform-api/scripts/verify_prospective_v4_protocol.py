"""Verify that the V4 registration is chronological, bounded and fail-closed."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V4.json"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(protocol: dict[str, object]) -> dict[str, object]:
    expected_markets = ["EURUSD", "GBPUSD", "USDJPY"]
    if (
        protocol.get("authority") != "PRE_REGISTERED_NONPROMOTABLE_PROSPECTIVE_RESEARCH"
        or protocol.get("protocol_version") != "AUREX_PROSPECTIVE_EXECUTABLE_COHORT_V4"
        or protocol.get("hypothesis_version") != "TREND_PULLBACK_META_V1"
        or protocol.get("markets") != expected_markets
        or protocol.get("outcome_access_before_registration") is not False
        or protocol.get("holdout_access_before_validation_pass") is not False
        or protocol.get("historical_backfill_credit") is not False
        or protocol.get("model_promotion") != "NONE"
        or protocol.get("broker_submission_authority") is not False
    ):
        raise ValueError("V4_PROTOCOL_AUTHORITY_INVALID")
    registered = utc(str(protocol["registered_at_utc"]))
    development_start = utc(str(protocol["development_start_inclusive_utc"]))
    development_end = utc(str(protocol["development_end_exclusive_utc"]))
    development_horizon = utc(str(protocol["development_outcome_horizon_complete_utc"]))
    validation_start = utc(str(protocol["validation_start_inclusive_utc"]))
    validation_end = utc(str(protocol["validation_end_exclusive_utc"]))
    validation_horizon = utc(str(protocol["validation_outcome_horizon_complete_utc"]))
    holdout_start = utc(str(protocol["holdout_start_inclusive_utc"]))
    holdout_end = utc(str(protocol["holdout_end_exclusive_utc"]))
    holdout_horizon = utc(str(protocol["holdout_outcome_horizon_complete_utc"]))
    purge = timedelta(minutes=int(protocol["boundary_purge_minutes"]))
    if not (
        registered < development_start < development_end
        and development_horizon == development_end + purge
        and validation_start == development_horizon
        and validation_start < validation_end
        and validation_horizon == validation_end + purge
        and holdout_start == validation_horizon
        and holdout_start < holdout_end
        and holdout_horizon == holdout_end + purge
    ):
        raise ValueError("V4_PROTOCOL_CHRONOLOGY_INVALID")
    if (
        protocol.get("execution_policy") != "ATR_STOP_1_TARGET_1_5R_60M_V1"
        or protocol.get("model") != "STANDARD_SCALER_PLUS_LOGISTIC_REGRESSION"
        or float(protocol.get("trade_probability_threshold", 0)) != 0.65
    ):
        raise ValueError("V4_HYPOTHESIS_NOT_FIXED")
    return {
        "status": "VERIFIED_V4_PREREGISTRATION",
        "registered_before_development": True,
        "validation_locked_until_utc": protocol["validation_outcome_horizon_complete_utc"],
        "holdout_locked_until_utc": protocol["holdout_outcome_horizon_complete_utc"],
        "model_promotion": "NONE",
        "broker_submission_authority": False,
    }


def main() -> dict[str, object]:
    result = verify(json.loads(PROTOCOL.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
