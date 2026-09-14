from app.model_governance_status import model_governance_blocker


def test_model_governance_blocker_reports_actual_next_gate() -> None:
    assert model_governance_blocker({}) == "NO_DEVELOPMENT_PASSED_MODEL"
    assert model_governance_blocker({"development_passed": 1}) == "NO_HOLDOUT_PASSED_MODEL"
    assert model_governance_blocker({
        "development_passed": 1, "owner_review_required": 1,
    }) == "OWNER_MODEL_APPROVAL_REQUIRED"
    assert model_governance_blocker({
        "development_passed": 1, "owner_review_required": 1, "governed_model": 1,
    }) is None
