from hashlib import sha256
import json

import pytest

from app.frozen_economic_bridge import compare_frozen_cohort


def frozen_row(*, valid: bool):
    prediction = {
        "prediction_id": "a" * 64, "decision_utc": "2026-09-08T07:00:00+00:00",
        "direction": "LONG", "probability": 0.72, "direction_label": 1,
        "gross_four_bar_return": 0.0003,
        "status": "TIME_EXIT" if valid else "INVALID",
    }
    if valid:
        prediction.update(net_return=0.0002, net_r=0.4)
    else:
        prediction["reason"] = "M1_ENTRY_MISSING"
    payload = {
        "prediction": prediction,
        "broker_execution_path_available": valid,
        "research_vendor_path_possible": True,
        "m1_coverage": {"classification": "COMPLETE_IG_PATH" if valid else "BROKER_EXECUTION_PATH_UNAVAILABLE_VENDOR_RESEARCH_ONLY",
                        "ig_valid_m1_count": 60 if valid else 0,
                        "first_missing_ig_m1": None if valid else "2026-09-08T07:15:00+00:00"},
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"prediction_id": "a" * 64, "outcome_sha256": digest, "payload": payload}


MANIFEST = {"authority": "NONPROMOTABLE_RESEARCH_ONLY", "market": "GBPUSD",
            "selected_prediction_ids": ["a" * 64]}


def test_valid_path_compares_same_id_but_cannot_tune_one_observation():
    result = compare_frozen_cohort(MANIFEST, [frozen_row(valid=True)])
    assert result["ig_evaluable"] == 1
    assert result["development_tuning"] == "BLOCKED_INSUFFICIENT_IG_PATHS"
    assert result["comparisons"][0]["cost_aware_net_return_label"] is True
    assert result["comparisons"][0]["first_hit_positive_r_label"] is True
    assert result["model_promotion"] == "NOT_AUTHORIZED"


def test_vendor_path_never_becomes_ig_outcome():
    result = compare_frozen_cohort(MANIFEST, [frozen_row(valid=False)])
    comparison = result["comparisons"][0]
    assert comparison["dukascopy_research_path_present"] is True
    assert comparison["executable_net_return"] is None
    assert comparison["first_hit_outcome"] is None
    assert comparison["net_r"] is None
    assert result["ig_evaluable"] == 0


def test_modified_outcome_is_rejected():
    row = frozen_row(valid=True)
    row["payload"]["prediction"]["net_r"] = 9
    with pytest.raises(ValueError, match="hash mismatch"):
        compare_frozen_cohort(MANIFEST, [row])


def test_prediction_id_mismatch_is_rejected():
    row = frozen_row(valid=True)
    row["prediction_id"] = "b" * 64
    with pytest.raises(ValueError, match="prediction ID"):
        compare_frozen_cohort(MANIFEST, [row])
