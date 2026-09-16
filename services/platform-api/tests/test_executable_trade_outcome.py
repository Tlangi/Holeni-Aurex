from datetime import datetime, timezone

import pandas as pd
import pytest

from app.executable_trade_outcome import (
    CostPolicy, Decision, ExecutionPolicy, LABEL_VERSION, evaluate_trade,
)


def _decision(direction="LONG", **changes):
    values = dict(market="GBPUSD", decision_at_utc=datetime(2026, 9, 15, 12, 5,
                          tzinfo=timezone.utc), feature_cutoff_at_utc=datetime(
                          2026, 9, 15, 12, 5, tzinfo=timezone.utc),
                  feature_version="M1_M5_M15_POINT_IN_TIME_V1",
                  research_version="NONPROMOTABLE_V1", dataset_sha256="a" * 64,
                  direction=direction)
    values.update(changes)
    return Decision(**values)


def _policy(**changes):
    values = dict(version="ATR_DECLARED_STOP_TARGET_V1", stop_distance=0.001,
                  target_distance=0.002, max_holding_minutes=3)
    values.update(changes)
    return ExecutionPolicy(**values)


def _cost(**changes):
    values = dict(version="GBPUSD_DECLARED_CFD_COSTS_V1",
                  slippage_bps_per_side=1, commission_bps_round_trip=0,
                  financing_bps_per_day=0)
    values.update(changes)
    return CostPolicy(**values)


def _path():
    times = pd.date_range("2026-09-15T12:05:00Z", periods=3, freq="min")
    return pd.DataFrame({
        "bid_open": [1.1000] * 3, "bid_high": [1.1005] * 3,
        "bid_low": [1.0998] * 3, "bid_close": [1.1004] * 3,
        "ask_open": [1.1002] * 3, "ask_high": [1.1007] * 3,
        "ask_low": [1.1000] * 3, "ask_close": [1.1006] * 3,
        "source": ["IG_LIGHTSTREAMER"] * 3, "completed": [True] * 3,
    }, index=times)


def test_long_target_uses_ask_entry_bid_first_hit_and_cost_decomposition():
    bars = _path()
    bars.loc[bars.index[1], "bid_high"] = 1.1023
    bars.loc[bars.index[1], "ask_high"] = 1.1025
    result = evaluate_trade(_decision(), _policy(), _cost(), bars)
    assert result["status"] == "EVALUATED"
    assert result["exit_reason"] == "TARGET"
    assert result["economic_label"] == "PROFITABLE_LONG"
    assert result["executable_entry"] == pytest.approx(1.1002)
    assert result["executable_exit"] == pytest.approx(1.1022)
    assert result["gross_mid_directional_return"] is None
    assert result["spread_cost_return"] is None
    assert result["net_return"] == pytest.approx(
        result["gross_return"] - result["slippage_cost_return"]
        - result["commission_cost_return"]
        - result["financing_cost_return"])
    assert result["label_version"] == LABEL_VERSION


def test_short_stop_uses_bid_entry_ask_exit_and_adverse_open_gap():
    bars = _path()
    bars.loc[bars.index[1], ["ask_open", "ask_high", "ask_low", "ask_close"]] = [
        1.1020, 1.1025, 1.1018, 1.1021]
    bars.loc[bars.index[1], ["bid_open", "bid_high", "bid_low", "bid_close"]] = [
        1.1018, 1.1023, 1.1016, 1.1019]
    result = evaluate_trade(_decision("SHORT"), _policy(), _cost(), bars)
    assert result["exit_reason"] == "STOP"
    assert result["executable_entry"] == 1.1000
    assert result["executable_exit"] == 1.1020
    assert result["net_return"] < 0


def test_short_target_uses_ask_low_not_bid_low():
    bars = _path()
    bars.loc[bars.index[1], ["bid_low", "ask_low"]] = [1.0978, 1.0980]
    result = evaluate_trade(_decision("SHORT"), _policy(), _cost(), bars)
    assert result["exit_reason"] == "TARGET"
    assert result["executable_exit"] == pytest.approx(1.0980)


def test_same_bar_both_hit_has_no_net_label_or_favourable_order():
    bars = _path()
    bars.loc[bars.index[1], ["bid_high", "ask_high", "bid_low", "ask_low"]] = [
        1.1023, 1.1025, 1.0989, 1.0991]
    result = evaluate_trade(_decision(), _policy(), _cost(), bars)
    assert result["status"] == "AMBIGUOUS"
    assert result["economic_label"] == "UNVERIFIABLE"
    assert result["net_return"] is None
    assert result["reason"] == "BOTH_BARRIERS_SAME_M1"


@pytest.mark.parametrize("change,reason", [
    (lambda b: b.drop(b.index[0]), "BROKER_M1_ENTRY_MISSING"),
    (lambda b: b.drop(b.index[1]), "BROKER_M1_PATH_GAP"),
    (lambda b: b.assign(source="DUKASCOPY_RESEARCH"),
     "BROKER_M1_QUOTE_OR_SOURCE_INVALID"),
    (lambda b: b.assign(ask_open=1.0999), "BROKER_M1_QUOTE_OR_SOURCE_INVALID"),
    (lambda b: b.assign(completed=False), "BROKER_M1_QUOTE_OR_SOURCE_INVALID"),
])
def test_missing_or_nonbroker_path_is_unverifiable(change, reason):
    bars = change(_path())
    result = evaluate_trade(_decision(), _policy(), _cost(), bars)
    assert result["status"] == "UNVERIFIABLE"
    assert result["reason"] == reason
    assert result["net_return"] is None


def test_unknown_cost_is_not_zero_or_profitable():
    result = evaluate_trade(_decision(), _policy(),
                            _cost(financing_bps_per_day=None), _path())
    assert result["reason"] == "COST_COMPONENT_UNVERIFIED"
    assert result["net_return"] is None


def test_financing_requires_known_rollover_and_intraday_does_not_accrue_fee():
    bars = _path()
    normal = evaluate_trade(_decision(), _policy(), _cost(), bars)
    unknown = evaluate_trade(_decision(), _policy(),
                             _cost(version="UNKNOWN_ROLLOVER_V1",
                                   financing_bps_per_day=12), bars)
    assert unknown["reason"] == "COST_COMPONENT_UNVERIFIED"
    financed = evaluate_trade(_decision(), _policy(),
                              _cost(version="OVERNIGHT_V1", financing_bps_per_day=12,
                                    financing_rollover_hour_utc=0), bars)
    assert financed["financing_cost_return"] == 0
    assert financed["net_return"] == normal["net_return"]
    assert financed["prediction_id"] != normal["prediction_id"]


def test_known_overnight_rollover_charges_once():
    bars = _path()
    bars.index = pd.date_range("2026-09-15T23:59:00Z", periods=3, freq="min")
    decision = _decision(decision_at_utc=datetime(2026, 9, 15, 23, 59,
                                                 tzinfo=timezone.utc))
    result = evaluate_trade(decision, _policy(),
                            _cost(financing_bps_per_day=12,
                                  financing_rollover_hour_utc=0), bars)
    assert result["exit_reason"] == "TIME_EXIT"
    assert result["financing_rollovers"] == 1
    assert result["financing_cost_return"] == pytest.approx(12 / 10000)


def test_no_trade_and_lookahead_rejection():
    result = evaluate_trade(_decision("NO_TRADE"), _policy(), _cost(), _path())
    assert result["economic_label"] == "NO_TRADE"
    assert result["net_return"] is None
    with pytest.raises(ValueError, match="lookahead"):
        _decision(feature_cutoff_at_utc=datetime(2026, 9, 15, 12, 6,
                                                tzinfo=timezone.utc))


def test_decision_between_m1_opens_uses_next_open_and_requires_it():
    decision = _decision(decision_at_utc=datetime(2026, 9, 15, 12, 5, 30,
                                                 tzinfo=timezone.utc))
    bars = _path().drop(_path().index[1])
    result = evaluate_trade(decision, _policy(), _cost(), bars)
    assert result["eligible_entry_at_utc"].startswith("2026-09-15T12:06")
    assert result["reason"] == "BROKER_M1_ENTRY_MISSING"


def test_session_boundary_exits_at_last_regular_bid_close():
    bars = _path()
    result = evaluate_trade(_decision(), _policy(), _cost(), bars,
        regular_session=lambda at: at.minute <= 5)
    assert result["exit_reason"] == "SESSION_EXIT"
    assert result["executable_exit"] == pytest.approx(1.1004)


def test_research_outcome_does_not_change_trading_controls(monkeypatch):
    # The evaluator has no DB, IG or trading-control dependency to mutate.
    import app.executable_trade_outcome as module
    assert not any(name in vars(module) for name in (
        "open_database", "IGDemoClient", "submit_order", "arm_programme"))
