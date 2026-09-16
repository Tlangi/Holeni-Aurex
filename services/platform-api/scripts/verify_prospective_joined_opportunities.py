"""Verify one immutable prospective opportunity-join snapshot."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_opportunity_join import JOIN_VERSION
from app.research_cohort_eligibility import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ROOT / "docs/audits/AUREX_PROSPECTIVE_JOINED_OPPORTUNITIES_SNAPSHOT_2026-09-16.json"
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_M15_CONTINUITY_PROTOCOL_V1.json"


def main(path: Path = DEFAULT) -> None:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    stored = snapshot.pop("snapshot_sha256")
    if canonical_sha256(snapshot) != stored:
        raise ValueError("Prospective join snapshot hash mismatch")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if snapshot["protocol_sha256"] != canonical_sha256(protocol):
        raise ValueError("Prospective join protocol mismatch")
    if snapshot["join_version"] != JOIN_VERSION:
        raise ValueError("Prospective join version mismatch")
    if any(snapshot[key] is not False for key in ("historical_rows_rewritten",
            "validation_accessed", "holdout_accessed", "economic_outcomes_calculated",
            "model_training_performed", "broker_submission_authority")):
        raise ValueError("Prospective join exceeded its authority")
    identities = [row["opportunity_id"] for row in snapshot["opportunities"]]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate prospective opportunity identity")
    joined = Counter(row["market"] for row in snapshot["opportunities"] if row["status"] == "JOINED")
    for market in snapshot["markets"]:
        if joined[market["market"]] != market["joined_opportunities"]:
            raise ValueError("Joined market summary mismatch")
        if market["target_reached"] != (market["joined_opportunities"] >= snapshot["minimum_joined_per_market"]):
            raise ValueError("Target state mismatch")
    print(json.dumps({"status": "VERIFIED_NONPROMOTABLE",
        "snapshot_sha256": stored, "prospective_m15": len(identities),
        "joined_opportunities": sum(joined.values()),
        "markets_target_reached": sum(row["target_reached"] for row in snapshot["markets"]),
        "historical_rows_rewritten": False, "model_training_performed": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT)
    main(parser.parse_args().path.resolve())
