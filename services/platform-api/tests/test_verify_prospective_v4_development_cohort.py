from scripts.verify_prospective_v4_development_cohort import verify


def test_v4_frozen_development_cohort_verifies() -> None:
    result = verify()
    assert result["status"] == "VERIFIED_V4_DEVELOPMENT_COHORT"
    assert all(item["minimum_met"] for item in result["markets"])
