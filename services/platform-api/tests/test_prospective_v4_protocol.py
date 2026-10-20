import json
from pathlib import Path

import pytest

from scripts.verify_prospective_v4_protocol import verify


ROOT = Path(__file__).resolve().parents[3]


def protocol() -> dict[str, object]:
    return json.loads((ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V4.json")
                      .read_text(encoding="utf-8"))


def test_v4_protocol_is_chronological_and_fail_closed() -> None:
    result = verify(protocol())
    assert result["status"] == "VERIFIED_V4_PREREGISTRATION"
    assert result["model_promotion"] == "NONE"
    assert result["broker_submission_authority"] is False


def test_v4_protocol_rejects_early_holdout_access() -> None:
    changed = protocol()
    changed["holdout_access_before_validation_pass"] = True
    with pytest.raises(ValueError, match="V4_PROTOCOL_AUTHORITY_INVALID"):
        verify(changed)


def test_v4_protocol_rejects_boundary_drift() -> None:
    changed = protocol()
    changed["validation_start_inclusive_utc"] = "2026-10-27T19:15:00Z"
    with pytest.raises(ValueError, match="V4_PROTOCOL_CHRONOLOGY_INVALID"):
        verify(changed)
