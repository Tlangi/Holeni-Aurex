"""Verify selected binaries and replay predictions from frozen development data."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_development_tournament import action_target
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_selected_prospective_models import (
    ARTIFACT_DIR, FREEZE_PROTOCOL, MANIFEST, TOURNAMENT, selected_training_rows,
)
from scripts.freeze_prospective_executable_outcomes import ECONOMIC, OUTPUT, PROTOCOL


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    freeze_protocol = json.loads(FREEZE_PROTOCOL.read_text(encoding="utf-8"))
    tournament = json.loads(TOURNAMENT.read_text(encoding="utf-8"))
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    cohort = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    stored = manifest["manifest_sha256"]
    if canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"}) != stored:
        raise ValueError("Selected model manifest hash mismatch")
    if (manifest["authority"] != "FROZEN_NONPROMOTABLE_PROSPECTIVE_SELECTED_MODELS"
            or manifest["freeze_protocol_sha256"] != canonical_sha256(freeze_protocol)
            or manifest["tournament_report_sha256"] != tournament["report_sha256"]
            or manifest["outcome_manifest_sha256"] != frozen["outcome_manifest_sha256"]
            or manifest["cohort_protocol_sha256"] != canonical_sha256(cohort)):
        raise ValueError("Selected model provenance mismatch")
    if (manifest["validation_accessed"] is not False or manifest["holdout_accessed"] is not False
            or manifest["model_promotion"] != "NONE"
            or manifest["broker_submission_authority"] is not False):
        raise ValueError("Selected model freeze exceeded authority")
    selected = {row["market"]: row["selected_development_candidate"]
                for row in tournament["markets"] if row["selected_development_candidate"]}
    if set(selected) != {row["market"] for row in manifest["models"]}:
        raise ValueError("Binary market set differs from selected development candidates")
    for entry in manifest["models"]:
        market = entry["market"]
        if (entry["family"] != selected[market]["family"]
                or entry["model"] != selected[market]["model"]):
            raise ValueError("Selected family or model changed")
        rows = selected_training_rows(frozen, economic, market)
        if len(rows) != entry["training_count"]:
            raise ValueError("Training membership count mismatch")
        names = manifest["feature_names"]
        keyed = {(row["opportunity_id"], row["direction"]): row
                 for row in frozen["outcomes"] if row["market"] == market
                 and row["execution_policy_version"] == entry["family"]
                 and row["cost_sensitivity"] == "NORMAL_P75"}
        x = np.asarray([[float(row["features"][name]) for name in names] for row in rows], dtype=float)
        targets = [action_target(
            float(keyed[(row["opportunity_id"], "LONG")]["net_return"]),
            float(keyed[(row["opportunity_id"], "SHORT")]["net_return"])) for row in rows]
        training = [{"opportunity_id": row["opportunity_id"],
                     "decision_at_utc": row["decision_at_utc"],
                     "evidence_sha256": row["evidence_sha256"],
                     "features": [float(row["features"][name]) for name in names],
                     "target": target} for row, target in zip(rows, targets)]
        if (canonical_sha256(training) != entry["training_sha256"]
                or canonical_sha256([row["opportunity_id"] for row in rows])
                != entry["training_opportunity_ids_sha256"]):
            raise ValueError("Frozen training evidence changed")
        path = ARTIFACT_DIR / entry["artifact_file"]
        if path.name != f"AUREX_SELECTED_PROSPECTIVE_{market}_V1.joblib" or not path.is_file():
            raise ValueError("Selected binary path mismatch")
        if sha256(path.read_bytes()).hexdigest() != entry["artifact_sha256"]:
            raise ValueError("Selected binary hash mismatch; refusing to load")
        payload = joblib.load(path)
        if (payload["market"] != market or payload["family"] != entry["family"]
                or payload["model_name"] != entry["model"]
                or payload["feature_names"] != names
                or payload["training_sha256"] != entry["training_sha256"]):
            raise ValueError("Selected binary metadata mismatch")
        predictions = [int(value) for value in payload["model"].predict(x)]
        if canonical_sha256(predictions) != entry["training_predictions_sha256"]:
            raise ValueError("Selected binary replay mismatch")
    print(json.dumps({"status": "VERIFIED_FROZEN_NONPROMOTABLE",
        "manifest_sha256": stored, "selected_models": len(manifest["models"]),
        "validation_accessed": False, "holdout_accessed": False}, indent=2))


if __name__ == "__main__":
    main()
