"""Independently verify the immutable V4 development membership artifact."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_v4_development_cohort import OUTPUT_PATH, PROTOCOL_PATH


def verify() -> dict[str, object]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    artifact = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    expected_hash = artifact.pop("cohort_sha256")
    if canonical_sha256(artifact) != expected_hash:
        raise ValueError("V4 cohort artifact hash mismatch")
    if artifact["protocol_sha256"] != canonical_sha256(protocol):
        raise ValueError("V4 cohort protocol hash mismatch")
    if any(artifact[key] for key in (
        "economic_outcomes_calculated", "model_training_performed",
        "validation_accessed", "holdout_accessed",
    )):
        raise ValueError("V4 cohort exceeded membership-freeze authority")
    if artifact["model_promotion"] != "NONE" or artifact["broker_submission_authority"] is not False:
        raise ValueError("V4 cohort granted forbidden authority")
    identities = [row["opportunity_id"] for row in artifact["members"]]
    if len(identities) != len(set(identities)):
        raise ValueError("V4 cohort contains duplicate opportunity identities")
    counts = Counter(row["market"] for row in artifact["members"])
    expected = {row["market"]: row["joined"] for row in artifact["markets"]}
    if dict(sorted(counts.items())) != dict(sorted(expected.items())):
        raise ValueError("V4 cohort summary differs from members")
    minimum = int(protocol["minimum_joined_per_market"])
    if any(counts[market] < minimum for market in protocol["markets"]):
        raise ValueError("V4 cohort does not meet the preregistered market minimum")
    return {"status": "VERIFIED_V4_DEVELOPMENT_COHORT",
            "cohort_sha256": expected_hash, "markets": artifact["markets"]}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
