from datetime import datetime, timezone

import pytest

from scripts.freeze_prospective_v3_validation import assert_validation_ready


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_v3_validation_remains_closed_before_outcome_horizon() -> None:
    protocol = {"validation_outcome_horizon_complete_utc": "2026-10-15T02:00:00Z"}
    with pytest.raises(RuntimeError, match="outcome_horizon_incomplete"):
        assert_validation_ready(protocol, now_utc=_utc("2026-10-15T01:59:59Z"))


def test_v3_validation_opens_at_registered_outcome_horizon() -> None:
    protocol = {"validation_outcome_horizon_complete_utc": "2026-10-15T02:00:00Z"}
    assert_validation_ready(protocol, now_utc=_utc("2026-10-15T02:00:00Z"))


def test_v3_validation_rejects_naive_clock() -> None:
    protocol = {"validation_outcome_horizon_complete_utc": "2026-10-15T02:00:00Z"}
    with pytest.raises(ValueError, match="naive"):
        assert_validation_ready(protocol, now_utc=datetime(2026, 10, 15, 2))
