from app.prospective_development_tournament import (
    action_target, chronological_development_split, complete_comparison_members,
    trade_metrics,
)


def test_chronological_purge_keeps_assessment_after_training_horizon():
    rows = [{"opportunity_id": str(i),
             "decision_at_utc": f"2026-09-18T{i:02d}:00:00+00:00"} for i in range(10)]
    training, assessment = chronological_development_split(rows, purge_minutes=120)
    assert [row["opportunity_id"] for row in assessment] == ["7", "8", "9"]
    assert [row["opportunity_id"] for row in training] == ["0", "1", "2", "3", "4"]


def test_identical_policy_cohort_excludes_ambiguous_member():
    members = [{"opportunity_id": "a"}, {"opportunity_id": "b"}]
    outcomes = [{"opportunity_id": opportunity, "status": "EVALUATED" if opportunity == "a" else "AMBIGUOUS",
                 "execution_policy_version": "P", "cost_sensitivity": sensitivity,
                 "direction": direction}
                for opportunity in ("a", "b")
                for sensitivity in ("NORMAL_P75", "STRESSED_P95")
                for direction in ("LONG", "SHORT")]
    assert complete_comparison_members(members, outcomes, ["P"]) == [members[0]]


def test_no_trade_wins_ties_and_empty_trade_metrics_cannot_pass_pf_gate():
    assert action_target(-0.01, -0.02) == 0
    assert action_target(0.01, 0.01) == 1
    assert trade_metrics([], 5)["profit_factor"] is None
