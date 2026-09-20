"""Independently verify frozen prospective executable development outcomes."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_prospective_executable_outcomes import (
    ATR_AMENDMENT, COST_AUTHORITY, ECONOMIC, OUTPUT, PROTOCOL, ROOT,
    _utc, assert_development_membership,
)


def verify_result(result: dict, joined: dict, protocol: dict, economic: dict,
                  amendment: dict, costs: dict) -> dict:
    stored = result["outcome_manifest_sha256"]
    if canonical_sha256({k: v for k, v in result.items() if k != "outcome_manifest_sha256"}) != stored:
        raise ValueError("Prospective outcome manifest hash mismatch")
    for key, source in (("prospective_protocol_sha256", protocol),
                        ("economic_protocol_sha256", economic),
                        ("atr_amendment_sha256", amendment),
                        ("cost_authority_sha256", costs)):
        if result[key] != canonical_sha256(source):
            raise ValueError(f"Frozen authority mismatch: {key}")
    if result["source_join_snapshot_sha256"] != joined["snapshot_sha256"]:
        raise ValueError("Source join mismatch")
    if result["authority"] != "FROZEN_NONPROMOTABLE_PROSPECTIVE_EXECUTABLE_OUTCOMES":
        raise ValueError("Unexpected outcome authority")
    if any(result[key] is not False for key in (
            "validation_accessed", "holdout_accessed", "model_training_performed",
            "broker_submission_authority")):
        raise ValueError("Outcome freeze exceeded authority")
    members = assert_development_membership(protocol, joined)
    source_ids = {row["opportunity_id"] for row in members}
    frozen_ids = [row["opportunity_id"] for row in result["members"]]
    if len(frozen_ids) != len(source_ids) or set(frozen_ids) != source_ids:
        raise ValueError("Frozen cohort differs from every JOINED source opportunity")
    if any(_utc(row["decision_at_utc"]) >= _utc(protocol["development_end_exclusive_utc"])
           for row in result["members"]):
        raise ValueError("Non-development member")
    source_by_id = {row["opportunity_id"]: row for row in members}
    for row in result["members"]:
        original = source_by_id[row["opportunity_id"]]
        for key in ("atr_snapshot_sha256", "feature_snapshot_sha256", "ig_m1_path_sha256"):
            if row[key] != original[key]:
                raise ValueError(f"Member evidence mismatch: {key}")
        expected = canonical_sha256({"source_join_snapshot_sha256": joined["snapshot_sha256"],
            "opportunity_id": row["opportunity_id"],
            "atr_snapshot_sha256": row["atr_snapshot_sha256"],
            "feature_snapshot_sha256": row["feature_snapshot_sha256"],
            "ig_m1_path_sha256": row["ig_m1_path_sha256"]})
        if expected != row["evidence_sha256"]:
            raise ValueError("Member evidence digest mismatch")
    allowed = {(family["id"], sensitivity, direction)
               for family in economic["policy_families"]
               for sensitivity in ("NORMAL_P75", "STRESSED_P95")
               for direction in ("LONG", "SHORT")}
    outcomes = result["outcomes"]
    if len(outcomes) != len(source_ids) * len(allowed):
        raise ValueError("Incomplete prospective outcome matrix")
    ids = [row["prediction_id"] for row in outcomes]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate policy-sensitive outcome identity")
    combinations = Counter((row["opportunity_id"], row["execution_policy_version"],
                            row["cost_sensitivity"], row["direction"]) for row in outcomes)
    if (set(combinations) != {(opportunity, *policy) for opportunity in source_ids for policy in allowed}
            or any(count != 1 for count in combinations.values())):
        raise ValueError("Outcome matrix has missing or duplicate combinations")
    member_by_id = {row["opportunity_id"]: row for row in result["members"]}
    for row in outcomes:
        member = member_by_id[row["opportunity_id"]]
        if (row["dataset_sha256"] != member["evidence_sha256"]
                or row["research_version"] != protocol["protocol_version"]
                or row["feature_snapshot_sha256"] != member["feature_snapshot_sha256"]
                or row["ig_m1_path_sha256"] != member["ig_m1_path_sha256"]):
            raise ValueError("Outcome member provenance mismatch")
        if row["status"] == "EVALUATED":
            if (row["net_return"] is None or row["gross_return"] is None
                    or row["commission_cost_return"] != 0
                    or row["financing_cost_return"] != 0
                    or row["financing_rollovers"] != 0):
                raise ValueError("Invalid evaluated CFD cost result")
        elif row["net_return"] is not None or row["economic_label"] != "UNVERIFIABLE":
            raise ValueError("Unverifiable outcome gained a return")
    by_market = Counter(row["market"] for row in outcomes)
    for market in result["markets"]:
        if (by_market[market["market"]] != market["outcome_count"]
                or market["outcome_count"] != market["joined"] * len(allowed)
                or market["minimum_met"] != (market["joined"] >= protocol["minimum_joined_per_market"])):
            raise ValueError("Market outcome summary mismatch")
    return {"status": "VERIFIED_NONPROMOTABLE", "outcome_manifest_sha256": stored,
            "joined_opportunities": len(source_ids), "outcome_count": len(outcomes),
            "evaluated_count": sum(row["status"] == "EVALUATED" for row in outcomes),
            "markets_meeting_minimum": sum(market["minimum_met"] for market in result["markets"]),
            "validation_accessed": False, "holdout_accessed": False}


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    amendment = json.loads(ATR_AMENDMENT.read_text(encoding="utf-8"))
    costs = json.loads(COST_AUTHORITY.read_text(encoding="utf-8"))
    source = ROOT / "docs/audits" / protocol["source_join_snapshot_file"]
    joined = json.loads(source.read_text(encoding="utf-8"))
    result = json.loads(OUTPUT.read_text(encoding="utf-8"))
    print(json.dumps(verify_result(result, joined, protocol, economic, amendment, costs), indent=2))


if __name__ == "__main__":
    main()
