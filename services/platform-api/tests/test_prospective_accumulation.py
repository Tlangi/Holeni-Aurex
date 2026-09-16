import pytest

from app.prospective_accumulation import evidence_sha256, transition_key, transition_status


def _row(reason):
    return {"opportunity_id": "a" * 64, "reason": reason, "market": "EURUSD"}


@pytest.mark.parametrize(("reason", "status"), [
    ("ATR:INSUFFICIENT_COMPLETED_BARS", "ATR_PENDING"),
    ("FEATURE:SOURCE_AUTHORITY_OR_TRANSITION", "FEATURE_PENDING"),
    ("FUNDING_BOUNDARY_IN_MAX_HORIZON", "ROLLOVER_BLOCKED"),
    ("IG_PATH:HORIZON_NOT_YET_COMPLETE", "PATH_PENDING"),
    ("IG_PATH:IG_M1_MISSING", "PATH_BLOCKED"),
    ("JOINED_TRAINING_INPUT_READY", "JOINED"),
])
def test_transition_mapping_is_explicit(reason, status):
    assert transition_status(_row(reason)) == status


def test_transition_identity_is_idempotent_per_opportunity_and_status():
    row = _row("ATR:INSUFFICIENT_COMPLETED_BARS")
    assert transition_key(row, "ATR_PENDING") == transition_key(row, "ATR_PENDING")
    assert transition_key(row, "ATR_PENDING") != transition_key(row, "FEATURE_PENDING")
    assert len(evidence_sha256(row)) == 64
