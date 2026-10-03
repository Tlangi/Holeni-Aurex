"""Verify the immutable locked-model validation report without SQL access."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_validation import replay_metrics
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_validation import OUTPUT, PROTOCOL, WINDOWS
from scripts.freeze_selected_prospective_models import ARTIFACT_DIR, MANIFEST


def main() -> dict[str, object]:
    report = json.loads(OUTPUT.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    windows = json.loads(WINDOWS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stored = report["validation_report_sha256"]
    if canonical_sha256({k: v for k, v in report.items() if k != "validation_report_sha256"}) != stored:
        raise ValueError("Validation report hash mismatch")
    if (report["authority"] != "FROZEN_LOCKED_MODEL_PROSPECTIVE_VALIDATION"
            or report["validation_protocol_sha256"] != canonical_sha256(protocol)
            or report["evaluation_windows_sha256"] != canonical_sha256(windows)
            or report["selected_model_manifest_sha256"] != manifest["manifest_sha256"]
            or report["model_training_performed"] is not False
            or report["model_retuning_performed"] is not False
            or report["holdout_accessed"] is not False
            or report["model_promotion"] != "NONE"
            or report["broker_submission_authority"] is not False):
        raise ValueError("Validation report provenance or authority mismatch")
    entries = {row["market"]: row for row in manifest["models"]}
    members = {market: sorted(
        [row for row in report["members"] if row["market"] == market],
        key=lambda row: (row["decision_at_utc"], row["opportunity_id"])) for market in entries}
    outcomes = {market: [row for row in report["outcomes"] if row["market"] == market]
                for market in entries}
    for summary in report["markets"]:
        market = summary["market"]
        entry = entries[market]
        artifact = ARTIFACT_DIR / entry["artifact_file"]
        if sha256(artifact.read_bytes()).hexdigest() != entry["artifact_sha256"]:
            raise ValueError(f"Selected model binary hash mismatch: {market}")
        payload = joblib.load(artifact)
        x = np.asarray([[float(row["features"][name]) for name in manifest["feature_names"]]
                        for row in members[market]], dtype=float)
        predictions = [int(value) for value in payload["model"].predict(x)] if len(x) else []
        if canonical_sha256(predictions) != summary["prediction_sha256"]:
            raise ValueError(f"Validation prediction replay mismatch: {market}")
        replay = replay_metrics(members[market], outcomes[market], predictions,
            family=entry["family"], minimum_trades=int(protocol["minimum_evaluable_trades"]))
        for key in ("prediction_action_counts", "metrics", "non_evaluable_predicted_trades",
                    "validation_passed"):
            if replay[key] != summary[key]:
                raise ValueError(f"Validation metric replay mismatch: {market}:{key}")
    result = {"status": "VERIFIED_LOCKED_VALIDATION", "validation_report_sha256": stored,
        "selected_markets": len(report["markets"]),
        "passed_markets": sum(bool(row["validation_passed"]) for row in report["markets"]),
        "holdout_accessed": False, "model_promotion": "NONE"}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
