from datetime import datetime, time, timedelta, timezone

import pandas as pd
import pytest

from app.config import Settings
from app.model_pipeline import train_all_markets
from app.replay_engine import ReplayRequest
from app.research_evidence import _segment_stats, _stats
from app.research_labels import EconomicLabelPolicy, economic_path_labels
from app.research_regimes import confidence_bucket, market_session, trend_regime, volatility_regimes


def fx_market() -> dict[str, object]:
    return {"calendar_code": "FX_24X5", "market_timezone": "UTC",
            "session_open_local": None, "session_close_local": None}


def test_provider_segment_does_not_penalise_weekend_boundary() -> None:
    friday = datetime(2026, 8, 21, 20, 45, tzinfo=timezone.utc)
    monday = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    stats = _segment_stats([friday, monday], 15, fx_market(), set())
    assert stats["expected"] == 2
    assert stats["completeness"] == 1.0
    assert stats["gaps"] == []


def test_provider_segment_reports_unexpected_regular_session_gap() -> None:
    start = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    stats = _segment_stats([start, start + timedelta(minutes=30)], 15, fx_market(), set())
    assert stats["expected"] == 3
    assert stats["actual"] == 2
    assert stats["largest"] == 15


@pytest.mark.parametrize(("symbol", "hour", "expected"), [
    ("EURUSD", 2, "ASIA"), ("EURUSD", 8, "LONDON"),
    ("EURUSD", 13, "LONDON_NEW_YORK_OVERLAP"), ("EURUSD", 18, "NEW_YORK"),
])
def test_fx_session_classification(symbol: str, hour: int, expected: str) -> None:
    assert market_session(symbol, datetime(2026, 8, 24, hour, tzinfo=timezone.utc)) == expected


def test_germany_session_uses_berlin_timezone() -> None:
    assert market_session("GERMANY40", datetime(2026, 8, 24, 7, 15, tzinfo=timezone.utc)) == "OPENING"


@pytest.mark.parametrize(("gap", "atr", "expected"), [
    (0.001, 0.001, "STRONG_UPTREND"), (0.0003, 0.001, "UPTREND"),
    (0.0001, 0.001, "RANGE"), (-0.0003, 0.001, "DOWNTREND"),
    (-0.001, 0.001, "STRONG_DOWNTREND"),
])
def test_trend_regimes_are_explainable(gap: float, atr: float, expected: str) -> None:
    assert trend_regime(gap, atr) == expected


def test_volatility_regime_does_not_use_future_values() -> None:
    values = pd.Series([0.001 + index / 1_000_000 for index in range(250)])
    baseline = volatility_regimes(values)
    changed = values.copy(); changed.iloc[220:] = 99
    revised = volatility_regimes(changed)
    assert baseline.iloc[:220].equals(revised.iloc[:220])


def test_confidence_boundaries_are_configurable() -> None:
    boundaries = (0.5, 0.55, 0.6, 0.7, 1.0)
    assert confidence_bucket(0.58, boundaries) == "0.55-0.60"
    assert confidence_bucket(0.91, boundaries) == "0.70-1.00"


def test_economic_label_requires_movement_beyond_cost_and_edge() -> None:
    index = pd.date_range("2026-01-01", periods=6, freq="15min", tz="UTC")
    frame = pd.DataFrame({"close": [100] * 6, "high": [100, 100.02, 100.08, 100, 100, 100],
                          "low": [100, 99.99, 99.98, 100, 100, 100]}, index=index)
    labels = economic_path_labels(frame, EconomicLabelPolicy(horizon=2, minimum_edge_bps=3,
                                                               transaction_cost_bps=2,
                                                               maximum_adverse_bps=3))
    assert labels.iloc[0] == "LONG_OPPORTUNITY"
    assert labels.iloc[-1] != labels.iloc[-1]  # NaN holdout tail


def test_cost_percentiles_are_deterministic() -> None:
    evidence = _stats(pd.Series([1, 2, 3, 4, 10], dtype=float).to_numpy())
    assert evidence["median"] == 3
    assert evidence["p75"] == 4
    assert evidence["maximum"] == 10


def test_research_replay_request_accepts_from_alias_and_remains_diagnostic() -> None:
    request = ReplayRequest.model_validate({"symbol": "EURUSD", "mode": "TECHNICAL_DIAGNOSTIC",
                                             "from": "2026-01-01T00:00:00Z",
                                             "use_latest_model": True, "max_candles": 100000})
    assert request.from_utc is not None
    assert request.mode == "TECHNICAL_DIAGNOSTIC"


def test_research_retrain_requires_material_change_before_database_access() -> None:
    with pytest.raises(ValueError, match="material change"):
        train_all_markets(Settings(), retrain_type="RESEARCH_RETRAIN")
