from datetime import datetime, timezone

import pytest

from scripts.freeze_prospective_v3_development_cohort import validate_protocol


def _protocol() -> dict[str, object]:
    return {
        "authority": "PRE_REGISTERED_NONPROMOTABLE_PROSPECTIVE_RESEARCH",
        "protocol_version": "AUREX_PROSPECTIVE_EXECUTABLE_COHORT_V3",
        "outcome_access_before_registration": False,
        "model_promotion": "NONE",
        "broker_submission_authority": False,
        "development_start_inclusive_utc": "2026-09-30T02:00:00Z",
        "development_end_exclusive_utc": "2026-10-07T18:00:00Z",
        "development_outcome_horizon_complete_utc": "2026-10-07T20:00:00Z",
        "registered_at_utc": "2026-10-07T20:01:53Z",
    }


def test_v3_cohort_protocol_accepts_completed_development_horizon() -> None:
    start, end = validate_protocol(_protocol())
    assert start == datetime(2026, 9, 30, 2, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 7, 18, tzinfo=timezone.utc)


def test_v3_cohort_protocol_rejects_registration_before_horizon_completion() -> None:
    protocol = _protocol()
    protocol["registered_at_utc"] = "2026-10-07T19:59:59Z"
    with pytest.raises(ValueError, match="chronology"):
        validate_protocol(protocol)
