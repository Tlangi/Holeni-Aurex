"""Fit and freeze only the five selected development models, without future data."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import sklearn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_development_tournament import (
    action_target, complete_comparison_members, selected_model_factory,
)
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_executable_outcomes import ECONOMIC, OUTPUT, PROTOCOL, ROOT, _utc
from scripts.verify_prospective_development_tournament import main as verify_tournament
from scripts.verify_prospective_executable_outcomes import main as verify_outcomes


FREEZE_PROTOCOL = ROOT / "docs/research/AUREX_SELECTED_PROSPECTIVE_MODEL_FREEZE_V1.json"
TOURNAMENT = ROOT / "docs/audits/AUREX_PROSPECTIVE_DEVELOPMENT_TOURNAMENT_V1.json"
MANIFEST = ROOT / "docs/audits/AUREX_SELECTED_PROSPECTIVE_MODELS_V1.json"
ARTIFACT_DIR = ROOT / "docs/audits/artifacts"


def selected_training_rows(frozen: dict, economic: dict, market: str) -> list[dict]:
    families = [family["id"] for family in economic["policy_families"]]
    members = [row for row in frozen["members"] if row["market"] == market]
    outcomes = [row for row in frozen["outcomes"] if row["market"] == market]
    return sorted(complete_comparison_members(members, outcomes, families),
                  key=lambda row: (row["decision_at_utc"], row["opportunity_id"]))


def freeze() -> dict:
    if MANIFEST.exists():
        raise FileExistsError("Selected prospective model manifest is immutable")
    verify_outcomes()
    verify_tournament()
    prereg = json.loads(FREEZE_PROTOCOL.read_text(encoding="utf-8"))
    tournament = json.loads(TOURNAMENT.read_text(encoding="utf-8"))
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    cohort_protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if (prereg["authority"] != "PRE_REGISTERED_NONPROMOTABLE_SELECTED_MODEL_FREEZE"
            or prereg["source_tournament_report_sha256"] != tournament["report_sha256"]
            or prereg["source_outcome_manifest_sha256"] != frozen["outcome_manifest_sha256"]
            or prereg["validation_start_utc"] != cohort_protocol["validation_start_utc"]
            or prereg["holdout_start_utc"] != cohort_protocol["holdout_start_utc"]):
        raise ValueError("Selected model freeze preregistration mismatch")
    choices = [(market["market"], market["selected_development_candidate"])
               for market in tournament["markets"]
               if market["selected_development_candidate"] is not None]
    if len(choices) != 5:
        raise ValueError("Expected exactly five preselected development candidates")
    features = tournament["feature_names"]
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for market, _ in choices:
        if (ARTIFACT_DIR / f"AUREX_SELECTED_PROSPECTIVE_{market}_V1.joblib").exists():
            raise FileExistsError(f"Selected prospective binary already exists: {market}")
    summaries = []
    for market, choice in choices:
        rows = selected_training_rows(frozen, economic, market)
        if len(rows) < cohort_protocol["minimum_joined_per_market"]:
            raise ValueError(f"Selected market fell below the governed minimum: {market}")
        if any(_utc(row["decision_at_utc"]) >= _utc(cohort_protocol["development_end_exclusive_utc"])
               for row in rows):
            raise ValueError("Selected model training crossed the development boundary")
        by_key = {(outcome["opportunity_id"], outcome["direction"]): outcome
                  for outcome in frozen["outcomes"] if outcome["market"] == market
                  and outcome["execution_policy_version"] == choice["family"]
                  and outcome["cost_sensitivity"] == "NORMAL_P75"}
        x = np.asarray([[float(row["features"][feature]) for feature in features]
                        for row in rows], dtype=float)
        y = np.asarray([action_target(
            float(by_key[(row["opportunity_id"], "LONG")]["net_return"]),
            float(by_key[(row["opportunity_id"], "SHORT")]["net_return"]))
            for row in rows], dtype=int)
        if not np.isfinite(x).all() or len(set(y)) < 2:
            raise ValueError(f"Frozen training features or classes invalid: {market}")
        model = selected_model_factory(choice["model"])
        model.fit(x, y)
        predictions = [int(value) for value in model.predict(x)]
        training = [{"opportunity_id": row["opportunity_id"],
                     "decision_at_utc": row["decision_at_utc"],
                     "evidence_sha256": row["evidence_sha256"],
                     "features": [float(row["features"][feature]) for feature in features],
                     "target": int(target)} for row, target in zip(rows, y)]
        path = ARTIFACT_DIR / f"AUREX_SELECTED_PROSPECTIVE_{market}_V1.joblib"
        payload = {"model": model, "market": market, "family": choice["family"],
                   "model_name": choice["model"], "feature_names": features,
                   "training_sha256": canonical_sha256(training)}
        joblib.dump(payload, path)
        summaries.append({"market": market, "family": choice["family"],
            "model": choice["model"], "artifact_file": path.name,
            "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
            "training_count": len(rows), "training_first_decision_utc": rows[0]["decision_at_utc"],
            "training_last_decision_utc": rows[-1]["decision_at_utc"],
            "training_sha256": canonical_sha256(training),
            "training_opportunity_ids_sha256": canonical_sha256([row["opportunity_id"] for row in rows]),
            "training_predictions_sha256": canonical_sha256(predictions),
            "training_class_counts": {str(value): int(sum(y == value)) for value in sorted(set(y))}})
    manifest = {"authority": "FROZEN_NONPROMOTABLE_PROSPECTIVE_SELECTED_MODELS",
        "freeze_protocol_sha256": canonical_sha256(prereg),
        "tournament_report_sha256": tournament["report_sha256"],
        "outcome_manifest_sha256": frozen["outcome_manifest_sha256"],
        "cohort_protocol_sha256": canonical_sha256(cohort_protocol),
        "feature_names": features, "python_version": sys.version.split()[0],
        "scikit_learn_version": sklearn.__version__, "joblib_version": joblib.__version__,
        "training_source": "FROZEN_DEVELOPMENT_ONLY",
        "validation_accessed": False, "holdout_accessed": False,
        "model_promotion": "NONE", "broker_submission_authority": False,
        "models": summaries}
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest_sha256": manifest["manifest_sha256"],
            "models": [{key: row[key] for key in ("market", "family", "model", "training_count",
                       "artifact_sha256")} for row in summaries],
            "validation_accessed": False, "holdout_accessed": False}


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
