"""Read-only independent hash, membership and cutoff check of frozen universe."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json"
UNIVERSE = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    frozen = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    assert frozen["protocol_sha256"] == sha256(_canonical(protocol).encode()).hexdigest()
    stored = frozen.pop("manifest_sha256")
    assert stored == sha256(_canonical(frozen).encode()).hexdigest()
    assert frozen["authority"] == "FROZEN_NONPROMOTABLE_DEVELOPMENT_UNIVERSE"
    assert not frozen["holdout_accessed"] and not frozen["model_training_performed"]
    assert not frozen["economic_outcomes_frozen"] and not frozen["broker_submission_authority"]
    assert [market["market"] for market in frozen["markets"]] == sorted(protocol["markets"])
    ids = set()
    for market in frozen["markets"]:
        opportunities = market["opportunities"]
        assert len(opportunities) == market["all_completed_m15_opportunities"]
        for item in opportunities:
            assert item["opportunity_id"] not in ids
            ids.add(item["opportunity_id"])
            assert item["market"] == market["market"] and item["economic_label"] is None
            assert item["economic_label_authority"] == "NONE_OUTCOMES_NOT_YET_FROZEN"
            assert item["decision_at_utc"] < frozen["validation_start_utc"]
            assert item["m15_completed_at_utc"] <= item["decision_at_utc"]
            if item["feature_status"] == "COMPLETE":
                assert all(value <= item["decision_at_utc"]
                           for value in item["feature_cutoffs_utc"].values())
                payload = {"market": item["market"],
                           "feature_version": frozen["feature_version"],
                           "decision_at_utc": item["decision_at_utc"],
                           "feature_cutoffs_utc": item["feature_cutoffs_utc"],
                           "source_identity": item["feature_source_identity"],
                           "features": item["feature_values"]}
                assert item["feature_snapshot_sha256"] == sha256(_canonical(payload).encode()).hexdigest()
            if item["ig_path_status"] == "COMPLETE_IG_M1_PATH":
                assert item["ig_path_complete_minutes"] == 120
                assert len(item["source_ig_m1_path_sha256"]) == 64
    print(json.dumps({"status": "VERIFIED_NONPROMOTABLE", "manifest_sha256": stored,
        "protocol_sha256": frozen["protocol_sha256"],
        "market_count": len(frozen["markets"]), "opportunity_count": len(ids),
        "holdout_accessed": False, "economic_outcomes_frozen": False}, indent=2))


if __name__ == "__main__":
    main()
