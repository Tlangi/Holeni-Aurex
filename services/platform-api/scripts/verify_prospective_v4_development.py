"""Independently verify the immutable V4 development-only report."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_v4_hypothesis import (
    FEATURE_ORDER, HYPOTHESIS_VERSION, TRADE_PROBABILITY_THRESHOLD,
)
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_v4_executable_outcomes import OUTPUT, PROTOCOL, ROOT
from scripts.run_prospective_v4_development import REPORT


def verify() -> dict[str, object]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    outcomes = json.loads(OUTPUT.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    claimed_hash = report.pop("report_sha256")
    if canonical_sha256(report) != claimed_hash:
        raise ValueError("V4 development report hash mismatch")
    if report["protocol_sha256"] != canonical_sha256(protocol):
        raise ValueError("V4 development protocol hash mismatch")
    if report["outcome_manifest_sha256"] != outcomes["outcome_manifest_sha256"]:
        raise ValueError("V4 development outcome authority mismatch")
    if report["hypothesis_version"] != HYPOTHESIS_VERSION:
        raise ValueError("V4 hypothesis changed")
    if report["feature_order"] != FEATURE_ORDER:
        raise ValueError("V4 feature order changed")
    if report["execution_policy"] != protocol["execution_policy"]:
        raise ValueError("V4 execution policy changed")
    if report["model"] != protocol["model"] or report["model_parameters"] != protocol["model_parameters"]:
        raise ValueError("V4 model specification changed")
    if report["trade_probability_threshold"] != TRADE_PROBABILITY_THRESHOLD:
        raise ValueError("V4 threshold changed")
    if report["validation_accessed"] or report["holdout_accessed"]:
        raise ValueError("V4 later window was accessed")
    if report["model_promotion"] != "NONE" or report["broker_submission_authority"]:
        raise ValueError("V4 development report grants forbidden authority")

    frozen = []
    for market in report["markets"]:
        passed = bool(market.get("gates_passed", False))
        if "checks" in market:
            recomputed = all(all(values.values()) for values in market["checks"].values())
            if passed != recomputed:
                raise ValueError(f"V4 gate mismatch: {market['market']}")
        if bool(market["candidate_frozen"]) != passed:
            raise ValueError(f"V4 candidate freeze mismatch: {market['market']}")
        if passed:
            artifact = ROOT / "docs/audits/artifacts" / market["artifact_file"]
            if not artifact.exists() or sha256(artifact.read_bytes()).hexdigest() != market["artifact_sha256"]:
                raise ValueError(f"V4 candidate artifact mismatch: {market['market']}")
            frozen.append(market["market"])
    if sorted(report["frozen_binaries"]) != sorted(
            market["artifact_file"] for market in report["markets"] if market["candidate_frozen"]):
        raise ValueError("V4 frozen binary manifest mismatch")
    return {"status": "VERIFIED_V4_DEVELOPMENT_REPORT", "report_sha256": claimed_hash,
            "candidate_markets": frozen, "validation_accessed": False, "holdout_accessed": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
