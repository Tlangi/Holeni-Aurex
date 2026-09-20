from datetime import datetime, timezone

import pytest

from app.prospective_evaluation_readiness import evaluation_readiness


WINDOWS = {"authority": "PRE_REGISTERED_CLOSED_FUTURE_EVALUATION_WINDOWS",
           "validation_start_utc": "2026-09-23T00:00:00Z",
           "validation_end_exclusive_utc": "2026-09-30T00:00:00Z",
           "holdout_start_utc": "2026-09-30T00:00:00Z",
           "holdout_end_exclusive_utc": "2026-10-07T00:00:00Z",
           "max_outcome_horizon_minutes": 120}


def utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_validation_waits_for_closed_window_and_full_outcome_horizon():
    result = evaluation_readiness(WINDOWS, phase="validation", now_utc=utc("2026-09-30T01:59:59Z"))
    assert result["status"] == "BLOCKED"
    assert result["validation_or_holdout_accessed"] is False
    result = evaluation_readiness(WINDOWS, phase="validation", now_utc=utc("2026-09-30T02:00:00Z"))
    assert result["status"] == "READY_FOR_SEPARATE_GOVERNED_FREEZE"


def test_holdout_requires_closed_window_and_validation_report():
    result = evaluation_readiness(WINDOWS, phase="holdout", now_utc=utc("2026-10-07T02:00:00Z"))
    assert result["reason"] == "VALIDATION_REPORT_NOT_FROZEN"
    result = evaluation_readiness(WINDOWS, phase="holdout", now_utc=utc("2026-10-07T02:00:00Z"),
                                  validation_report_frozen=True)
    assert result["status"] == "READY_FOR_SEPARATE_GOVERNED_FREEZE"


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="aware UTC"):
        evaluation_readiness(WINDOWS, phase="validation", now_utc=datetime(2026, 9, 30))
