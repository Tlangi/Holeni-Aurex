"""Run the preregistered development-only tournament on frozen economic outcomes."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.prospective_development_tournament import run_development_comparison
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_executable_outcomes import ECONOMIC, OUTPUT, ROOT
from scripts.verify_prospective_executable_outcomes import main as verify_outcomes


PREREG = ROOT / "docs/research/AUREX_PROSPECTIVE_DEVELOPMENT_TOURNAMENT_V1.json"
REPORT = ROOT / "docs/audits/AUREX_PROSPECTIVE_DEVELOPMENT_TOURNAMENT_V1.json"


def main() -> None:
    if REPORT.exists():
        raise FileExistsError("Development tournament artifact is immutable")
    verify_outcomes()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    if (prereg["authority"] != "PRE_REGISTERED_DEVELOPMENT_ONLY_MODEL_COMPARISON"
            or prereg["outcome_manifest_sha256"] != frozen["outcome_manifest_sha256"]
            or prereg["validation_accessed"] is not False
            or prereg["holdout_accessed"] is not False):
        raise ValueError("Tournament preregistration or frozen outcome mismatch")
    comparison = run_development_comparison(frozen, prereg, economic)
    report = {"authority": "NONPROMOTABLE_DEVELOPMENT_ONLY_TOURNAMENT",
        "tournament_protocol_sha256": canonical_sha256(prereg),
        "outcome_manifest_sha256": frozen["outcome_manifest_sha256"],
        **comparison}
    report["report_sha256"] = canonical_sha256(report)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report_sha256": report["report_sha256"],
        "markets": [{key: market[key] for key in ("market", "status", "joined",
                     "common_evaluable", "selected_development_candidate")}
                    for market in report["markets"]],
        "validation_accessed": False, "holdout_accessed": False}, indent=2))


if __name__ == "__main__":
    main()
