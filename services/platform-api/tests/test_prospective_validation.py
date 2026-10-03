from app.prospective_validation import replay_metrics


def _members(count=12):
    return [{"opportunity_id": f"o{i}"} for i in range(count)]


def _outcomes(count=12, normal=0.01, stressed=0.005):
    rows = []
    for i in range(count):
        for sensitivity, value in (("NORMAL_P75", normal), ("STRESSED_P95", stressed)):
            observed = -abs(value) / 2 if i % 4 == 0 else value
            rows.append({"opportunity_id": f"o{i}", "execution_policy_version": "FAMILY",
                         "cost_sensitivity": sensitivity, "direction": "LONG",
                         "status": "EVALUATED", "net_return": observed})
    return rows


def test_locked_replay_passes_only_both_cost_sensitivities():
    result = replay_metrics(_members(), _outcomes(), [1] * 12,
                            family="FAMILY", minimum_trades=10)
    assert result["validation_passed"] is True
    assert result["metrics"]["NORMAL_P75"]["trade_count"] == 12


def test_locked_replay_fails_negative_stressed_economics():
    result = replay_metrics(_members(), _outcomes(stressed=-0.005), [1] * 12,
                            family="FAMILY", minimum_trades=10)
    assert result["validation_passed"] is False


def test_locked_replay_retains_unverifiable_trade_as_incomplete():
    outcomes = _outcomes()
    outcomes[0]["status"] = "UNVERIFIABLE"
    result = replay_metrics(_members(), outcomes, [1] * 12,
                            family="FAMILY", minimum_trades=10)
    assert result["validation_passed"] is False
    assert result["non_evaluable_predicted_trades"]["NORMAL_P75"] == 1
