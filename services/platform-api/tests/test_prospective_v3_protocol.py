from datetime import datetime
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_v3_boundaries_and_authority_are_frozen_before_future_windows() -> None:
    protocol = json.loads((
        ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V3.json"
    ).read_text(encoding="utf-8"))
    assert protocol["markets"] == ["EURUSD", "GBPUSD", "USDJPY"]
    assert protocol["outcome_access_before_registration"] is False
    assert protocol["model_promotion"] == "NONE"
    assert protocol["broker_submission_authority"] is False
    assert (
        _utc(protocol["development_start_inclusive_utc"])
        < _utc(protocol["development_end_exclusive_utc"])
        <= _utc(protocol["development_outcome_horizon_complete_utc"])
        < _utc(protocol["validation_start_inclusive_utc"])
        < _utc(protocol["validation_end_exclusive_utc"])
        <= _utc(protocol["validation_outcome_horizon_complete_utc"])
        < _utc(protocol["holdout_end_exclusive_utc"])
        <= _utc(protocol["holdout_outcome_horizon_complete_utc"])
    )
    assert protocol["holdout_start_inclusive_utc"] == protocol["validation_end_exclusive_utc"]
