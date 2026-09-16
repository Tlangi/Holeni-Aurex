"""Verify the immutable prospective continuity snapshot and safety limits."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.research_cohort_eligibility import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = ROOT / "docs/audits/AUREX_PROSPECTIVE_M15_CONTINUITY_SNAPSHOT_2026-09-16.json"
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_M15_CONTINUITY_PROTOCOL_V1.json"


def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    stored = snapshot.pop("snapshot_sha256")
    if canonical_sha256(snapshot) != stored:
        raise ValueError("Prospective snapshot hash mismatch")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if snapshot["protocol_sha256"] != canonical_sha256(protocol):
        raise ValueError("Prospective protocol hash mismatch")
    if snapshot["historical_rows_rewritten"] is not False or \
            snapshot["model_training_performed"] is not False or \
            snapshot["broker_submission_authority"] is not False:
        raise ValueError("Prospective snapshot exceeded authority")
    print(json.dumps({"status": "VERIFIED_NONPROMOTABLE",
        "snapshot_sha256": stored, "market_count": len(snapshot["markets"]),
        "targets_reached": sum(row["target_reached"] for row in snapshot["markets"]),
        "historical_rows_rewritten": False, "model_training_performed": False}, indent=2))


if __name__ == "__main__":
    main()
