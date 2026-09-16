"""Pure gate evaluation for a frozen executable-research universe.

This module does not read markets, calculate outcomes, train models, or grant
broker authority.  It explains why a frozen opportunity may or may not enter a
future economic-label cohort.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json


ELIGIBILITY_VERSION = "EXECUTABLE_RESEARCH_COHORT_ELIGIBILITY_V1"


def canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             default=str).encode()).hexdigest()


def assess_opportunity(opportunity: dict[str, object],
                       cost_evidence: dict[str, object]) -> dict[str, object]:
    """Return ordered, fail-closed gates for one already-frozen opportunity."""
    market = str(opportunity["market"])
    evidence = cost_evidence["markets"].get(market)
    gates = {
        "feature_snapshot": opportunity.get("feature_status") == "COMPLETE",
        "ig_m1_120m_path": opportunity.get("ig_path_status") == "COMPLETE_IG_M1_PATH",
        "commission_authority": bool(evidence and evidence.get("commission") == "AUTHORITATIVE"),
        "financing_authority": bool(evidence and evidence.get("financing") == "AUTHORITATIVE"),
    }
    if not gates["feature_snapshot"]:
        reason = f"FEATURE:{opportunity.get('feature_failure_reason') or 'UNVERIFIABLE'}"
    elif not gates["ig_m1_120m_path"]:
        reason = f"IG_PATH:{opportunity.get('ig_path_failure_reason') or 'UNVERIFIABLE'}"
    elif not gates["commission_authority"]:
        reason = "COST:COMMISSION_UNVERIFIED"
    elif not gates["financing_authority"]:
        reason = "COST:FINANCING_UNVERIFIED"
    else:
        reason = "ELIGIBLE_FOR_DIRECTION_POLICY_LABELING"
    return {
        "opportunity_id": opportunity["opportunity_id"],
        "market": market,
        "decision_at_utc": opportunity["decision_at_utc"],
        "feature_snapshot_sha256": opportunity.get("feature_snapshot_sha256"),
        "source_ig_m1_path_sha256": opportunity.get("source_ig_m1_path_sha256"),
        "gates": gates,
        "status": "ELIGIBLE" if all(gates.values()) else "BLOCKED",
        "reason": reason,
    }


def build_eligibility_register(frozen: dict[str, object],
                               cost_evidence: dict[str, object]) -> dict[str, object]:
    if frozen.get("authority") != "FROZEN_NONPROMOTABLE_DEVELOPMENT_UNIVERSE":
        raise ValueError("Unsupported frozen-universe authority")
    if frozen.get("economic_outcomes_frozen") is not False or frozen.get("holdout_accessed") is not False:
        raise ValueError("Eligibility requires an outcome-free development universe")
    if cost_evidence.get("authority") != "COST_EVIDENCE_GAP_REGISTER":
        raise ValueError("Cost evidence must remain explicitly non-authoritative")
    if cost_evidence.get("protocol_sha256") != frozen.get("protocol_sha256"):
        raise ValueError("Cost evidence and frozen universe use different protocols")

    markets = []
    all_rows = []
    for market_group in frozen["markets"]:
        rows = [assess_opportunity(row, cost_evidence)
                for row in market_group["opportunities"]]
        all_rows.extend(rows)
        reasons = Counter(row["reason"] for row in rows)
        markets.append({
            "market": market_group["market"],
            "opportunity_count": len(rows),
            "feature_and_path_ready": sum(
                row["gates"]["feature_snapshot"] and row["gates"]["ig_m1_120m_path"]
                for row in rows),
            "net_label_eligible": sum(row["status"] == "ELIGIBLE" for row in rows),
            "blocking_reasons": dict(sorted(reasons.items())),
        })
    result = {
        "authority": "FROZEN_NONPROMOTABLE_ELIGIBILITY_REGISTER",
        "eligibility_version": ELIGIBILITY_VERSION,
        "source_universe_manifest_sha256": frozen["manifest_sha256"],
        "protocol_sha256": frozen["protocol_sha256"],
        "cost_evidence_sha256": canonical_sha256(cost_evidence),
        "holdout_accessed": False,
        "economic_outcomes_calculated": False,
        "model_training_performed": False,
        "markets": markets,
        "opportunities": all_rows,
    }
    result["eligibility_manifest_sha256"] = canonical_sha256(result)
    return result
