"""Freeze data/cost eligibility without calculating outcomes or training."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import build_eligibility_register

ROOT = Path(__file__).resolve().parents[3]
UNIVERSE = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"
COSTS = ROOT / "docs/research/AUREX_CFD_COST_EVIDENCE_GAPS_V1.json"
OUTPUT = ROOT / "docs/audits/AUREX_FROZEN_RESEARCH_COHORT_ELIGIBILITY_2026-09-16.json"


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError("Eligibility register is immutable; use a new version/path")
    frozen = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    costs = json.loads(COSTS.read_text(encoding="utf-8"))
    result = build_eligibility_register(frozen, costs)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "authority", "eligibility_version", "source_universe_manifest_sha256",
        "cost_evidence_sha256", "eligibility_manifest_sha256")}, indent=2))
    print(json.dumps(result["markets"], indent=2))


if __name__ == "__main__":
    main()
