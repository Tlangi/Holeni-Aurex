"""Verify the immutable development outcome artifact and its authority limits."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
OUTCOMES = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_DEVELOPMENT_OUTCOMES_2026-09-16.json"
UNIVERSE = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"
AMENDMENT = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1_ATR_AMENDMENT.json"
COSTS = ROOT / "docs/research/AUREX_IG_ZA_COST_AUTHORITY_V1.json"


def main() -> None:
    result = json.loads(OUTCOMES.read_text(encoding="utf-8"))
    stored = result.pop("outcome_manifest_sha256")
    if canonical_sha256(result) != stored:
        raise ValueError("Outcome manifest hash mismatch")
    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT.read_text(encoding="utf-8"))
    costs = json.loads(COSTS.read_text(encoding="utf-8"))
    if result["source_universe_manifest_sha256"] != universe["manifest_sha256"]:
        raise ValueError("Outcome source universe mismatch")
    if result["protocol_amendment_sha256"] != canonical_sha256(amendment):
        raise ValueError("ATR amendment hash mismatch")
    if result["cost_authority_sha256"] != canonical_sha256(costs):
        raise ValueError("Cost authority hash mismatch")
    if any(result[key] is not False for key in (
            "holdout_accessed", "validation_accessed", "model_training_performed",
            "broker_submission_authority")):
        raise ValueError("Outcome artifact exceeded research authority")
    ids = [row["prediction_id"] for row in result["outcomes"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate policy-sensitive outcome identity")
    allowed_sensitivity = {"NORMAL_P75", "STRESSED_P95"}
    if any(row["status"] != "EVALUATED" or row["cost_sensitivity"] not in allowed_sensitivity
           or row["commission_cost_return"] != 0 or row["financing_cost_return"] != 0
           or row["financing_rollovers"] != 0 for row in result["outcomes"]):
        raise ValueError("Unexpected outcome or cost state")
    by_market = Counter(row["market"] for row in result["outcomes"])
    for market in result["markets"]:
        if by_market[market["market"]] != market["outcome_count"]:
            raise ValueError("Market outcome summary mismatch")
        if market["tournament_minimum_met"]:
            raise ValueError("Current frozen outcome cohort must not unlock tournament")
    print(json.dumps({"status": "VERIFIED_NONPROMOTABLE",
        "outcome_manifest_sha256": stored, "outcome_count": len(ids),
        "opportunities_with_outcomes": len({row["opportunity_id"] for row in result["outcomes"]}),
        "markets_meeting_tournament_minimum": 0,
        "holdout_accessed": False, "validation_accessed": False,
        "model_training_performed": False}, indent=2))


if __name__ == "__main__":
    main()
