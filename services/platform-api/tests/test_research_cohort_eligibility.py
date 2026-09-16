from app.research_cohort_eligibility import build_eligibility_register


def _frozen(feature="COMPLETE", path="COMPLETE_IG_M1_PATH"):
    return {"authority": "FROZEN_NONPROMOTABLE_DEVELOPMENT_UNIVERSE",
            "manifest_sha256": "a" * 64, "protocol_sha256": "b" * 64,
            "economic_outcomes_frozen": False, "holdout_accessed": False,
            "markets": [{"market": "EURUSD", "opportunities": [{
                "opportunity_id": "one", "market": "EURUSD",
                "decision_at_utc": "2026-09-10T12:00:00+00:00",
                "feature_status": feature, "feature_failure_reason": "LATE" if feature != "COMPLETE" else None,
                "feature_snapshot_sha256": "c" * 64, "ig_path_status": path,
                "ig_path_failure_reason": "GAP" if path != "COMPLETE_IG_M1_PATH" else None,
                "source_ig_m1_path_sha256": "d" * 64}]}]}


def _costs(commission="UNVERIFIED", financing="UNVERIFIED"):
    return {"authority": "COST_EVIDENCE_GAP_REGISTER", "protocol_sha256": "b" * 64,
            "markets": {"EURUSD": {"commission": commission, "financing": financing}}}


def test_complete_data_remains_blocked_by_unknown_commission():
    result = build_eligibility_register(_frozen(), _costs())
    row = result["opportunities"][0]
    assert row["status"] == "BLOCKED"
    assert row["reason"] == "COST:COMMISSION_UNVERIFIED"
    assert result["markets"][0]["feature_and_path_ready"] == 1
    assert result["markets"][0]["net_label_eligible"] == 0


def test_gate_reason_order_preserves_data_failure_before_cost_failure():
    result = build_eligibility_register(_frozen(feature="UNVERIFIABLE"), _costs())
    assert result["opportunities"][0]["reason"] == "FEATURE:LATE"


def test_authoritative_costs_make_complete_data_label_eligible():
    result = build_eligibility_register(
        _frozen(), _costs(commission="AUTHORITATIVE", financing="AUTHORITATIVE"))
    assert result["opportunities"][0]["status"] == "ELIGIBLE"
    assert result["economic_outcomes_calculated"] is False
