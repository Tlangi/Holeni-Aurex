from datetime import datetime, timezone

import pytest

from scripts.freeze_prospective_v3_development_cohort import validate_protocol
from scripts.freeze_prospective_v3_executable_outcomes import assert_development_membership
from app.research_cohort_eligibility import canonical_sha256


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


def test_v3_outcome_membership_is_bound_to_immutable_cohort() -> None:
    protocol = _protocol()
    protocol.update({
        "markets": ["EURUSD"],
        "validation_start_inclusive_utc": "2026-10-08T00:00:00Z",
        "holdout_start_inclusive_utc": "2026-10-15T00:00:00Z",
    })
    cohort = {
        "authority": "IMMUTABLE_NONPROMOTABLE_V3_DEVELOPMENT_COHORT",
        "protocol_sha256": canonical_sha256(protocol),
        "markets": [{"market": "EURUSD", "joined": 1}],
        "members": [{
            "market": "EURUSD",
            "decision_at_utc": "2026-10-07T17:45:00Z",
            "opportunity_id": "example",
        }],
    }
    assert assert_development_membership(protocol, cohort) == cohort["members"]


def test_v3_outcome_membership_rejects_post_development_decision() -> None:
    protocol = _protocol()
    protocol.update({
        "markets": ["EURUSD"],
        "validation_start_inclusive_utc": "2026-10-08T00:00:00Z",
        "holdout_start_inclusive_utc": "2026-10-15T00:00:00Z",
    })
    cohort = {
        "authority": "IMMUTABLE_NONPROMOTABLE_V3_DEVELOPMENT_COHORT",
        "protocol_sha256": canonical_sha256(protocol),
        "markets": [{"market": "EURUSD", "joined": 1}],
        "members": [{
            "market": "EURUSD",
            "decision_at_utc": "2026-10-07T18:00:00Z",
            "opportunity_id": "late",
        }],
    }
    with pytest.raises(ValueError, match="non-development"):
        assert_development_membership(protocol, cohort)
