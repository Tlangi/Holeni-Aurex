from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.model_pipeline import FEATURES
from app.research_protocol import (
    DisagreementAwareEnsemble,
    TARGET_CATALOG,
    block_bootstrap_expectancy,
    build_selective_target,
    cost_stress_evidence,
    development_only_calibrated_probabilities,
    leakage_boundary_audit,
    selective_walk_forward_evaluate,
    selective_directions,
    target_catalog,
    validate_lifecycle_transition,
)


def _frame(rows: int = 800) -> pd.DataFrame:
    index = pd.date_range("2025-01-06T08:00:00Z", periods=rows, freq="15min")
    movement = np.sin(np.arange(rows) / 9) * 0.00035 + np.cos(np.arange(rows) / 31) * 0.00008
    close = 1.1 + np.cumsum(movement)
    return pd.DataFrame({
        "open": close - movement / 2, "high": close + 0.0003,
        "low": close - 0.0003, "close": close,
        "tick_volume": 100 + np.arange(rows) % 50,
        "observed_spread_bps": np.full(rows, 1.2),
        "provider": ["DUKASCOPY"] * (rows // 2) + ["IG_LIGHTSTREAMER"] * (rows - rows // 2),
    }, index=index)


def test_market_target_catalog_is_versioned_market_specific_and_ternary() -> None:
    catalog = target_catalog()
    assert set(catalog) == {
        "EURUSD", "GBPUSD", "USDJPY", "GERMANY40",
        "GBPJPY", "EURJPY", "XAUUSD", "AUDJPY", "USDZAR",
    }
    assert catalog["XAUUSD"][0]["minimum_edge_bps"] > catalog["EURUSD"][0]["minimum_edge_bps"]
    assert catalog["USDZAR"][0]["safety_buffer_bps"] > catalog["GBPJPY"][0]["safety_buffer_bps"]
    assert len({spec.horizon_bars for specs in TARGET_CATALOG.values() for spec in specs}) > 1
    assert all(item["sha256"] for specs in catalog.values() for item in specs)
    germany = build_selective_target(_frame(), TARGET_CATALOG["GERMANY40"][0], configured_cost_bps=1.0)
    assert set(germany["target_action"].unique()) <= {"BUY", "SELL", "HOLD"}
    assert not any(column in FEATURES for column in ("future_return", "target", "target_action"))


def test_boundary_audit_detects_clean_provider_resets_and_purged_folds() -> None:
    raw = _frame()
    spec = TARGET_CATALOG["EURUSD"][0]
    featured = build_selective_target(raw, spec, configured_cost_bps=1.0)
    split = 500
    window = {
        "training_end": featured.index[split - spec.horizon_bars - 1],
        "validation_start": featured.index[split],
        "validation_end": featured.index[-1],
    }
    audit = leakage_boundary_audit(raw, featured, specification=spec, windows=[window],
                                   holdout_start=featured.index[-1] + timedelta(days=1))
    assert audit["passed"]
    assert audit["provider_boundaries"] == 1
    assert audit["provider_boundary_violations"] == 0


def test_calibration_uses_development_rows_only_and_cost_gate_can_hold() -> None:
    data = build_selective_target(_frame(1000), TARGET_CATALOG["EURUSD"][0], configured_cost_bps=1.0)
    training, validation = data.iloc[:650], data.iloc[660:]
    factory = lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=42))
    model, probabilities, evidence = development_only_calibrated_probabilities(
        factory, training, validation, horizon_bars=4,
    )
    assert evidence["validation_used_for_calibration"] is False
    directions, explanations = selective_directions(
        probabilities, model.classes_, training, validation, TARGET_CATALOG["EURUSD"][0],
    )
    assert len(directions) == len(validation)
    assert {item["decision"] for item in explanations} <= {"BUY", "SELL", "HOLD"}
    assert all("cost_floor_bps" in item for item in explanations)


def test_bootstrap_and_cost_stress_are_deterministic_and_cost_aware() -> None:
    returns = np.array([0.001, -0.0004, 0.0008, 0.0002])
    directions = np.array([1, 1, -1, 0])
    costs = np.full(4, 1.0)
    first = block_bootstrap_expectancy(returns, directions, costs, samples=200)
    second = block_bootstrap_expectancy(returns, directions, costs, samples=200)
    assert first == second
    data = build_selective_target(_frame(), TARGET_CATALOG["EURUSD"][0], configured_cost_bps=1.0)
    scenarios = cost_stress_evidence(data, np.zeros(len(data), dtype=int))
    assert {item["scenario"] for item in scenarios} >= {
        "SPREAD_P50", "SPREAD_P75", "SPREAD_P90", "SPREAD_P95",
        "P95_PLUS_SLIPPAGE", "P95_DELAY_ONE_CANDLE", "P95_OVERNIGHT_FUNDING",
    }


def test_candidate_lifecycle_rejects_skips() -> None:
    validate_lifecycle_transition("RESEARCH", "ELIGIBLE_TO_FREEZE")
    with pytest.raises(ValueError, match="Invalid candidate lifecycle transition"):
        validate_lifecycle_transition("RESEARCH", "PROMOTED")


def test_disagreement_ensemble_exposes_member_conflict() -> None:
    data = build_selective_target(_frame(), TARGET_CATALOG["EURUSD"][0], configured_cost_bps=1.0)
    ensemble = DisagreementAwareEnsemble((
        make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=1)),
        make_pipeline(StandardScaler(), LogisticRegression(C=0.2, max_iter=500, random_state=2)),
    )).fit(data[FEATURES], data["target"].astype(int))
    assert ensemble.predict_proba(data.iloc[:10][FEATURES]).shape[0] == 10
    assert ensemble.member_disagreement(data.iloc[:10][FEATURES]).dtype == bool


def test_selective_walk_forward_produces_strong_development_only_evidence() -> None:
    factory = lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=42))
    result = selective_walk_forward_evaluate(
        _frame(1400), TARGET_CATALOG["EURUSD"][0], estimator_factory=factory,
        minimum_rows=1000, configured_cost_bps=1.0,
    )
    assert result["selection_scope"] == "DEVELOPMENT_ONLY"
    assert result["holdout_consumed"] is False
    assert result["execution_enabled"] is False
    assert len(result["windows"]) == 3
    assert result["leakage_audit"]["passed"]
    assert result["bootstrap_expectancy"]["samples"] == 1000
    assert "p90_spread_stress_positive" in result["gates"]
    assert 0 <= result["hold_fraction"] <= 1
