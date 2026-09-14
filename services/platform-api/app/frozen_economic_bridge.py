"""Read-only interpretation of an immutable, non-promotable research cohort.

Never infer an IG execution outcome from vendor candles or a directional label.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json

VALID_OUTCOMES = frozenset({"TARGET_FIRST", "STOP_FIRST", "TIME_EXIT"})
MIN_DEVELOPMENT_IG_PATHS = 30


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compare_frozen_cohort(manifest: dict, stored_rows: list[dict]) -> dict:
    """Check hashes/IDs and report label-to-trade evidence without selecting a strategy."""
    if manifest.get("authority") != "NONPROMOTABLE_RESEARCH_ONLY":
        raise ValueError("Unexpected cohort authority")
    selected = manifest.get("selected_prediction_ids")
    if not isinstance(selected, list) or len(selected) != len(set(selected)):
        raise ValueError("Invalid frozen prediction IDs")
    by_id = {}
    for stored in stored_rows:
        payload = stored["payload"]
        if sha256(_canonical(payload).encode()).hexdigest() != stored["outcome_sha256"]:
            raise ValueError("Frozen outcome hash mismatch")
        prediction = payload["prediction"]
        prediction_id = prediction["prediction_id"]
        if prediction_id in by_id or prediction_id != stored["prediction_id"]:
            raise ValueError("Duplicate or mismatched prediction ID")
        by_id[prediction_id] = payload
    if set(by_id) != set(selected):
        raise ValueError("Frozen prediction set mismatch")

    comparisons = []
    for prediction_id in selected:
        payload = by_id[prediction_id]
        p = payload["prediction"]
        coverage = payload["m1_coverage"]
        status = p["status"]
        broker_path = bool(payload["broker_execution_path_available"])
        if broker_path != (status in VALID_OUTCOMES):
            raise ValueError("Broker-path status mismatch")
        direction = p["direction"]
        if direction not in {"LONG", "SHORT"}:
            raise ValueError("Frozen trade direction invalid")
        label = int(p["direction_label"])
        if label not in {0, 1}:
            raise ValueError("Frozen direction label invalid")
        net_return = p.get("net_return") if broker_path else None
        net_r = p.get("net_r") if broker_path else None
        if broker_path and (net_return is None or net_r is None):
            raise ValueError("Valid IG path lacks executable economics")
        comparisons.append({
            "prediction_id": prediction_id,
            "decision_utc": p["decision_utc"],
            "direction": direction,
            "probability": p["probability"],
            "four_bar_direction_label": label,
            "direction_matches_four_bar_label": (label == 1) if direction == "LONG" else (label == 0),
            "gross_four_bar_return": p["gross_four_bar_return"],
            "ig_path_status": status if broker_path else "UNAVAILABLE",
            "ig_path_reason": None if broker_path else p.get("reason"),
            "ig_m1_coverage_class": coverage["classification"],
            "ig_valid_m1_minutes": coverage["ig_valid_m1_count"],
            "first_missing_ig_m1": coverage["first_missing_ig_m1"],
            "dukascopy_research_path_present": bool(payload["research_vendor_path_possible"]),
            "executable_net_return": net_return,
            "first_hit_outcome": status if broker_path else None,
            "net_r": net_r,
            "cost_aware_net_return_label": (net_return > 0) if broker_path else None,
            "first_hit_positive_r_label": (net_r > 0) if broker_path else None,
        })
    evaluable = sum(r["ig_path_status"] != "UNAVAILABLE" for r in comparisons)
    return {
        "authority": "READ_ONLY_NONPROMOTABLE_RESEARCH",
        "market": manifest["market"],
        "selected": len(comparisons),
        "ig_evaluable": evaluable,
        "ig_unavailable": len(comparisons) - evaluable,
        "coverage_reasons": dict(Counter(r["ig_m1_coverage_class"] for r in comparisons)),
        "development_tuning": "PERMITTED" if evaluable >= MIN_DEVELOPMENT_IG_PATHS else "BLOCKED_INSUFFICIENT_IG_PATHS",
        "model_promotion": "NOT_AUTHORIZED",
        "holdout_accessed": False,
        "comparisons": comparisons,
    }
