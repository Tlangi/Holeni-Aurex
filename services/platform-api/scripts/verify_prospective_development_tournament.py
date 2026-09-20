"""Verify the development tournament's frozen inputs and authority limits."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_executable_outcomes import OUTPUT, ROOT


REPORT = ROOT / "docs/audits/AUREX_PROSPECTIVE_DEVELOPMENT_TOURNAMENT_V1.json"
PREREG = ROOT / "docs/research/AUREX_PROSPECTIVE_DEVELOPMENT_TOURNAMENT_V1.json"


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if canonical_sha256({k: v for k, v in report.items() if k != "report_sha256"}) != report["report_sha256"]:
        raise ValueError("Development tournament report hash mismatch")
    if (report["tournament_protocol_sha256"] != canonical_sha256(prereg)
            or report["outcome_manifest_sha256"] != frozen["outcome_manifest_sha256"]
            or report["authority"] != "NONPROMOTABLE_DEVELOPMENT_ONLY_TOURNAMENT"):
        raise ValueError("Development tournament source authority mismatch")
    if (report["validation_accessed"] is not False or report["holdout_accessed"] is not False
            or report["model_promotion"] != "NONE"
            or report["broker_submission_authority"] is not False):
        raise ValueError("Development tournament exceeded authority")
    source_counts = {row["market"]: row["joined"] for row in frozen["markets"]}
    if {row["market"]: row["joined"] for row in report["markets"]} != source_counts:
        raise ValueError("Tournament market membership mismatch")
    families = {row["execution_policy_version"] for row in frozen["outcomes"]}
    for market in report["markets"]:
        if market["common_evaluable"] > market["joined"]:
            raise ValueError("Comparison cohort exceeds frozen membership")
        if market["status"] == "DEVELOPMENT_ONLY_COMPLETE":
            if len(market["candidates"]) != 9:
                raise ValueError("Incomplete three-family three-model comparison")
            if market["training_count"] < 30 or market["assessment_count"] < 15:
                raise ValueError("Insufficient chronological development split")
        selected = market["selected_development_candidate"]
        if selected is not None:
            if selected["family"] not in families:
                raise ValueError("Unregistered selected policy family")
            matching = [candidate for candidate in market["candidates"]
                        if candidate["family"] == selected["family"]
                        and candidate["model"] == selected["model"]]
            if len(matching) != 1 or not matching[0]["development_selectable"]:
                raise ValueError("Selected candidate did not pass development gates")
    print(json.dumps({"status": "VERIFIED_DEVELOPMENT_ONLY",
        "report_sha256": report["report_sha256"],
        "markets_assessed": sum(m["status"] == "DEVELOPMENT_ONLY_COMPLETE" for m in report["markets"]),
        "markets_with_development_candidate": sum(m["selected_development_candidate"] is not None
                                                  for m in report["markets"]),
        "validation_accessed": False, "holdout_accessed": False}, indent=2))


if __name__ == "__main__":
    main()
