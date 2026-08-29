from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.model_pipeline import add_features, chronological_evaluate, trading_metrics


def test_chronological_evaluation_never_leaks_validation_into_training() -> None:
    rows = 900
    index = pd.DatetimeIndex(
        [datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(rows)]
    )
    movement = np.sin(np.arange(rows) / 8) * 0.0004 + 0.00005
    close = 1.1 + np.cumsum(movement)
    frame = pd.DataFrame(
        {"open": close - movement / 2, "high": close + 0.0003, "low": close - 0.0003,
         "close": close, "tick_volume": 100 + (np.arange(rows) % 40)}, index=index
    )
    evaluation = chronological_evaluate(frame, minimum_rows=700)
    assert evaluation.training_rows > evaluation.validation_rows
    assert 0 <= evaluation.auc <= 1
    assert 0 <= evaluation.pr_auc <= 1
    assert evaluation.log_loss >= 0
    assert len(evaluation.windows) == 3
    assert all(window["training_end"] < window["validation_start"] for window in evaluation.windows)
    assert all(evaluation.windows[index]["validation_end"] < evaluation.windows[index + 1]["validation_start"]
               for index in range(2))
    assert {item["name"] for item in evaluation.baselines} == {"ALWAYS_HOLD", "SMA", "MOMENTUM", "RANDOM"}
    assert 0 <= evaluation.brier_score <= 1
    assert 0 <= evaluation.calibration_error <= 1
    assert evaluation.feature_drift_score >= 0
    assert sum(item["sample_count"] for item in evaluation.calibration_buckets) == evaluation.validation_rows
    assert [item["upper"] for item in evaluation.selective_thresholds] == [0.55, 0.60, 0.65, 0.70]
    assert {item["name"] for item in evaluation.regimes} == {
        "LOW_VOLATILITY", "HIGH_VOLATILITY", "RANGING", "TRENDING",
    }


def test_transaction_costs_reduce_expectancy_and_can_turn_winners_negative() -> None:
    returns = np.array([0.001, 0.001, -0.0002])
    directions = np.array([1, 1, 1])
    free = trading_metrics(returns, directions, round_trip_cost_bps=0)
    costly = trading_metrics(returns, directions, round_trip_cost_bps=10)
    assert float(costly["expectancy"]) < float(free["expectancy"])
    assert int(costly["trade_count"]) == 3


def test_features_and_labels_do_not_cross_market_data_gaps() -> None:
    first = pd.date_range("2026-01-05T08:00:00Z", periods=80, freq="15min")
    second = pd.date_range("2026-01-07T08:00:00Z", periods=80, freq="15min")
    index = first.append(second)
    close = 1.1 + np.arange(len(index)) * 0.00001
    frame = pd.DataFrame(
        {"open": close, "high": close + 0.0002, "low": close - 0.0002,
         "close": close, "tick_volume": np.full(len(index), 100)}, index=index,
    )
    featured = add_features(frame, labelled=True)
    assert not any(timestamp in featured.index for timestamp in first[-4:])
    assert not any(timestamp in featured.index for timestamp in second[:13])


def test_optional_spread_nulls_use_cost_fallback_instead_of_dropping_training_rows() -> None:
    index = pd.date_range("2026-01-05T08:00:00Z", periods=100, freq="15min")
    close = 1.1 + np.arange(len(index)) * 0.00001
    frame = pd.DataFrame(
        {"open": close, "high": close + 0.0002, "low": close - 0.0002,
         "close": close, "tick_volume": np.full(len(index), 100),
         "observed_spread_bps": np.full(len(index), np.nan)}, index=index,
    )
    assert len(add_features(frame, labelled=True)) > 50
