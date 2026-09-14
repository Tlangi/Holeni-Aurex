import pandas as pd
import pytest

from app.multi_timeframe_research import (
    EconomicLabelPolicy, ResearchArchitecture, cfd_net_opportunity,
    completed_context_join, same_cohort_bridge,
)


def test_context_join_never_uses_unfinished_m15_bar():
    signal = pd.DataFrame({"close": [1.0, 1.1, 1.2]}, index=pd.date_range("2026-09-07T08:00Z", periods=3, freq="5min"))
    context = pd.DataFrame({"close": [9.0, 10.0]}, index=pd.date_range("2026-09-07T07:45Z", periods=2, freq="15min"))
    joined = completed_context_join(signal, context, signal_timeframe="M5", context_timeframe="M15")
    assert joined["m15_close"].tolist() == [9.0, 9.0, 10.0]
    assert joined.iloc[0]["_context_open_at"] == pd.Timestamp("2026-09-07T07:45Z")


def test_economic_label_uses_executable_bid_ask_and_abstains_for_small_move():
    signal = pd.DataFrame(index=pd.DatetimeIndex(["2026-09-07T08:00Z", "2026-09-07T09:00Z"]))
    minutes = pd.date_range("2026-09-07T08:05Z", periods=120, freq="min")
    execution = pd.DataFrame({"bid_close": 1.0, "ask_close": 1.0001}, index=minutes)
    execution.loc["2026-09-07T09:04Z", "bid_close"] = 1.0005
    execution.loc["2026-09-07T09:04Z", "ask_close"] = 1.0006
    result = cfd_net_opportunity(signal, execution, EconomicLabelPolicy())
    assert result.iloc[0]["label"] == "LONG"
    assert result.iloc[1]["label"] == "NO_TRADE"


def test_missing_m1_path_is_unknown_not_fabricated():
    signal = pd.DataFrame(index=pd.DatetimeIndex(["2026-09-07T08:00Z"]))
    minutes = pd.date_range("2026-09-07T08:05Z", periods=60, freq="min").delete(20)
    execution = pd.DataFrame({"bid_close": 1.0, "ask_close": 1.0001}, index=minutes)
    result = cfd_net_opportunity(signal, execution, EconomicLabelPolicy())
    assert result.iloc[0]["label"] == "UNKNOWN"


def test_same_cohort_bridge_rejects_missing_outcome_and_duplicate_prediction():
    prediction = pd.DataFrame([{"prediction_timestamp": 1, "fold_id": 1, "dataset_row_id": "a", "probability": 0.8}])
    outcome = pd.DataFrame([{"prediction_timestamp": 1, "fold_id": 1, "dataset_row_id": "a", "net_return": -0.01}])
    joined = same_cohort_bridge(prediction, outcome, experiment_id="e1", market="GBPUSD", dataset_hash="a" * 64)
    assert joined.iloc[0]["net_return"] == -0.01
    with pytest.raises(ValueError, match="Missing prediction"):
        same_cohort_bridge(prediction, outcome.iloc[0:0], experiment_id="e1", market="GBPUSD", dataset_hash="a" * 64)
    with pytest.raises(ValueError, match="unique"):
        same_cohort_bridge(pd.concat([prediction, prediction]), outcome, experiment_id="e1", market="GBPUSD", dataset_hash="a" * 64)


def test_architecture_rejects_m1_primary_and_versions_metadata():
    assert ResearchArchitecture("M5", ("M15",)).digest() != ResearchArchitecture("M15").digest()
    with pytest.raises(ValueError, match="Signal timeframe"):
        ResearchArchitecture("M1")
