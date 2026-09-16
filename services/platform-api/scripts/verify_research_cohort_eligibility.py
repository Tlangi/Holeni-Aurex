"""Independently reproduce the frozen, non-promotable eligibility register."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import build_eligibility_register, canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
UNIVERSE = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"
COSTS = ROOT / "docs/research/AUREX_CFD_COST_EVIDENCE_GAPS_V1.json"
REGISTER = ROOT / "docs/audits/AUREX_FROZEN_RESEARCH_COHORT_ELIGIBILITY_2026-09-16.json"


def main() -> None:
    frozen = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    stored_universe_hash = frozen.pop("manifest_sha256")
    if canonical_sha256(frozen) != stored_universe_hash:
        raise ValueError("Frozen universe manifest hash mismatch")
    frozen["manifest_sha256"] = stored_universe_hash
    costs = json.loads(COSTS.read_text(encoding="utf-8"))
    stored = json.loads(REGISTER.read_text(encoding="utf-8"))
    rebuilt = build_eligibility_register(frozen, costs)
    if rebuilt != stored:
        raise ValueError("Eligibility register is not reproducible")
    if (stored["holdout_accessed"] is not False or
            stored["economic_outcomes_calculated"] is not False or
            stored["model_training_performed"] is not False):
        raise ValueError("Eligibility artifact exceeded its authority")
    print(json.dumps({
        "status": "VERIFIED_NONPROMOTABLE",
        "eligibility_manifest_sha256": stored["eligibility_manifest_sha256"],
        "opportunity_count": len(stored["opportunities"]),
        "feature_and_path_ready": sum(m["feature_and_path_ready"] for m in stored["markets"]),
        "net_label_eligible": sum(m["net_label_eligible"] for m in stored["markets"]),
        "holdout_accessed": False,
        "economic_outcomes_calculated": False,
        "model_training_performed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
