from scripts.verify_prospective_v4_development import verify


def test_frozen_v4_development_report_verifies_without_later_window_access():
    result = verify()
    assert result["status"] == "VERIFIED_V4_DEVELOPMENT_REPORT"
    assert result["candidate_markets"] == []
    assert result["validation_accessed"] is False
    assert result["holdout_accessed"] is False
