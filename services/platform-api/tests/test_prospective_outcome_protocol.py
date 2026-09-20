import pytest

from scripts.freeze_prospective_executable_outcomes import assert_development_membership


def _protocol():
    return {"authority": "PRE_REGISTERED_NONPROMOTABLE_PROSPECTIVE_RESEARCH",
            "outcome_access_before_registration": False,
            "source_join_snapshot_sha256": "a" * 64,
            "development_end_exclusive_utc": "2026-09-19T00:00:00Z",
            "validation_start_utc": "2026-09-23T00:00:00Z",
            "holdout_start_utc": "2026-09-30T00:00:00Z"}


def test_membership_uses_every_joined_row_only():
    source = {"snapshot_sha256": "a" * 64,
              "markets": [{"joined_opportunities": 1}],
              "opportunities": [
                  {"status": "JOINED", "decision_at_utc": "2026-09-18T20:00:00Z"},
                  {"status": "ACCUMULATING", "decision_at_utc": "2026-09-18T20:15:00Z"}]}
    assert len(assert_development_membership(_protocol(), source)) == 1


def test_later_decision_cannot_enter_frozen_development():
    source = {"snapshot_sha256": "a" * 64,
              "markets": [{"joined_opportunities": 1}],
              "opportunities": [{"status": "JOINED",
                                 "decision_at_utc": "2026-09-19T00:00:00Z"}]}
    with pytest.raises(ValueError, match="non-development"):
        assert_development_membership(_protocol(), source)


def test_source_hash_change_blocks_outcomes():
    source = {"snapshot_sha256": "b" * 64, "markets": [], "opportunities": []}
    with pytest.raises(ValueError, match="mismatch"):
        assert_development_membership(_protocol(), source)
