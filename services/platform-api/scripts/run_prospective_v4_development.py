"""Run and freeze only the preregistered V4 development hypothesis."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_development_tournament import chronological_development_split, trade_metrics
from app.prospective_v4_hypothesis import (
    FEATURE_ORDER, HYPOTHESIS_VERSION, TRADE_PROBABILITY_THRESHOLD,
    derived_features, model_factory, should_trade, target,
)
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_v4_executable_outcomes import OUTPUT, PROTOCOL, ROOT
from scripts.verify_prospective_v4_executable_outcomes import verify_result


REPORT = ROOT / "docs/audits/AUREX_PROSPECTIVE_V4_DEVELOPMENT_REPORT.json"
ARTIFACT_DIR = ROOT / "docs/audits/artifacts"


def _verified_inputs() -> tuple[dict, dict]:
    from scripts.freeze_prospective_v4_executable_outcomes import (
        ATR_AMENDMENT, COHORT, COST_AUTHORITY, ECONOMIC,
    )
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    cohort = json.loads(COHORT.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    amendment = json.loads(ATR_AMENDMENT.read_text(encoding="utf-8"))
    costs = json.loads(COST_AUTHORITY.read_text(encoding="utf-8"))
    verify_result(frozen, cohort, protocol, economic, amendment, costs)
    return protocol, frozen


def _complete_members(frozen: dict, market: str, policy: str) -> tuple[list[dict], dict]:
    members = [row for row in frozen["members"]
               if row["market"] == market and row["hypothesis_eligible"]]
    outcomes = [row for row in frozen["outcomes"] if row["market"] == market
                and row["execution_policy_version"] == policy and row["status"] == "EVALUATED"]
    keyed = {(row["opportunity_id"], row["cost_sensitivity"]): row for row in outcomes}
    complete = [row for row in members if all(
        (row["opportunity_id"], sensitivity) in keyed
        for sensitivity in ("NORMAL_P75", "STRESSED_P95"))]
    return complete, keyed


def run() -> dict:
    if REPORT.exists():
        raise FileExistsError("V4 development report is immutable")
    protocol, frozen = _verified_inputs()
    policy = str(protocol["execution_policy"])
    market_reports, binaries = [], []
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for market in protocol["markets"]:
        members, outcomes = _complete_members(frozen, market, policy)
        training, assessment = chronological_development_split(
            members, purge_minutes=int(protocol["boundary_purge_minutes"]))
        summary = {"market": market, "joined": next(
            item["joined"] for item in frozen["markets"] if item["market"] == market),
            "hypothesis_eligible": len(members), "training_count": len(training),
            "assessment_count": len(assessment), "candidate_frozen": False}
        if not training or not assessment:
            summary.update({"status": "INSUFFICIENT_CHRONOLOGICAL_SPLIT", "gates_passed": False})
            market_reports.append(summary)
            continue
        x_train = np.asarray([derived_features(row["features"],
            1 if row["fixed_direction"] == "LONG" else -1) for row in training], dtype=float)
        x_assessment = np.asarray([derived_features(row["features"],
            1 if row["fixed_direction"] == "LONG" else -1) for row in assessment], dtype=float)
        y_train = np.asarray([target(
            float(outcomes[(row["opportunity_id"], "NORMAL_P75")]["net_return"]),
            float(outcomes[(row["opportunity_id"], "STRESSED_P95")]["net_return"]))
            for row in training], dtype=int)
        summary["training_class_counts"] = dict(sorted(Counter(int(v) for v in y_train).items()))
        if len(set(y_train)) < 2:
            summary.update({"status": "SINGLE_CLASS_TRAINING", "gates_passed": False})
            market_reports.append(summary)
            continue
        model = model_factory()
        model.fit(x_train, y_train)
        class_one = list(model.classes_).index(1)
        probabilities = model.predict_proba(x_assessment)[:, class_one]
        decisions = [should_trade(value) for value in probabilities]
        metrics = {}
        for sensitivity in ("NORMAL_P75", "STRESSED_P95"):
            returns = [float(outcomes[(row["opportunity_id"], sensitivity)]["net_return"])
                       for row, execute in zip(assessment, decisions) if execute]
            metrics[sensitivity] = trade_metrics(returns, decisions.count(False))
        checks = {sensitivity: {
            "minimum_trades": item["trade_count"] >= 20,
            "profit_factor": item["profit_factor"] is not None and item["profit_factor"] > 1,
            "positive_expectancy": item["trade_expectancy"] is not None and item["trade_expectancy"] > 0,
            "maximum_drawdown": item["max_compounded_drawdown"] <= 0.03,
        } for sensitivity, item in metrics.items()}
        passed = all(all(values.values()) for values in checks.values())
        assessment_rows = [{"opportunity_id": row["opportunity_id"],
            "decision_at_utc": row["decision_at_utc"],
            "probability": float(probability), "trade": bool(execute)}
            for row, probability, execute in zip(assessment, probabilities, decisions)]
        summary.update({"status": "DEVELOPMENT_PASSED" if passed else "DEVELOPMENT_REJECTED",
            "assessment_first_decision_utc": assessment[0]["decision_at_utc"],
            "trade_probability_threshold": TRADE_PROBABILITY_THRESHOLD,
            "assessment_action_counts": {"TRADE": decisions.count(True), "NO_TRADE": decisions.count(False)},
            "metrics": metrics, "checks": checks, "gates_passed": passed,
            "assessment_predictions_sha256": canonical_sha256(assessment_rows)})
        if passed:
            path = ARTIFACT_DIR / f"AUREX_TREND_PULLBACK_META_V1_{market}.joblib"
            if path.exists():
                raise FileExistsError(f"V4 candidate binary already exists: {market}")
            payload = {"model": model, "market": market, "hypothesis_version": HYPOTHESIS_VERSION,
                "execution_policy": policy, "feature_order": FEATURE_ORDER,
                "threshold": TRADE_PROBABILITY_THRESHOLD,
                "training_opportunity_ids_sha256": canonical_sha256(
                    [row["opportunity_id"] for row in training])}
            joblib.dump(payload, path)
            summary.update({"candidate_frozen": True, "artifact_file": path.name,
                "artifact_sha256": sha256(path.read_bytes()).hexdigest()})
            binaries.append(path.name)
        market_reports.append(summary)
    report = {"authority": "V4_DEVELOPMENT_ONLY_NONPROMOTABLE",
        "protocol_sha256": canonical_sha256(protocol),
        "outcome_manifest_sha256": frozen["outcome_manifest_sha256"],
        "hypothesis_version": HYPOTHESIS_VERSION, "execution_policy": policy,
        "feature_order": FEATURE_ORDER, "model": protocol["model"],
        "model_parameters": protocol["model_parameters"],
        "trade_probability_threshold": TRADE_PROBABILITY_THRESHOLD,
        "markets": market_reports, "frozen_binaries": binaries,
        "validation_accessed": False, "holdout_accessed": False,
        "model_promotion": "NONE", "broker_submission_authority": False}
    report["report_sha256"] = canonical_sha256(report)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({"report_sha256": result["report_sha256"],
        "markets": [{key: row.get(key) for key in (
            "market", "status", "hypothesis_eligible", "training_count",
            "assessment_count", "assessment_action_counts", "gates_passed", "candidate_frozen")}
            for row in result["markets"]], "validation_accessed": False,
        "holdout_accessed": False}, indent=2))
