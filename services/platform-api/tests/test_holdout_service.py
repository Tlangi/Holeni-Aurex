from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.holdout_service import (
    ReserveResearchLineageRequest,
    _effective_costs,
    evidence_gates,
    select_holdout_split,
)


def _frame(rows: int) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="15min", tz="UTC")
    close = np.linspace(100, 101, rows)
    return pd.DataFrame({
        "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
        "tick_volume": np.ones(rows), "observed_spread_bps": np.nan,
    }, index=index)


def test_holdout_split_is_chronological_and_respects_minimum() -> None:
    development, holdout = select_holdout_split(
        _frame(3000), fraction=0.20, minimum_holdout_rows=500,
        minimum_development_rows=2000,
    )
    assert len(development) == 2400
    assert len(holdout) == 600
    assert development.index.max() < holdout.index.min()


def test_holdout_split_fails_before_weakening_development_floor() -> None:
    with pytest.raises(ValueError, match="Insufficient pre-holdout"):
        select_holdout_split(
            _frame(2300), fraction=0.20, minimum_holdout_rows=500,
            minimum_development_rows=2000,
        )


def test_lineage_reservation_requires_a_predeclared_market_target() -> None:
    request = ReserveResearchLineageRequest(
        market="GERMANY40",
        hypothesis="Opening-session momentum persists after realistic transaction costs.",
        target_mode="COST_AWARE_RETURN",
        target_horizon_bars=4,
    )
    assert request.target_mode == "COST_AWARE_RETURN"
    assert request.target_horizon_bars == 4


def test_empirical_spread_fills_missing_cost_without_lowering_configured_floor() -> None:
    prepared = _effective_costs(_frame(3), fallback_spread=0.02, configured_bps=1.0)
    assert (prepared["effective_cost_bps"] >= 1.0).all()
    assert prepared["effective_cost_bps"].equals(prepared["observed_spread_bps"])


def test_holdout_gate_requires_every_independent_evidence_class() -> None:
    settings = Settings(_env_file=None)
    metrics = {"trade_count": 40, "expectancy": 0.001, "profit_factor": 1.2, "max_drawdown": 0.02}
    gates = evidence_gates(
        settings, auc=0.55, metrics=metrics, calibration_error=0.1,
        feature_drift_score=0.5, regime_coverage=0.75, baseline_expectancy=0.0005,
    )
    assert all(gates.values())
    metrics["max_drawdown"] = 0.031
    assert not evidence_gates(
        settings, auc=0.55, metrics=metrics, calibration_error=0.1,
        feature_drift_score=0.5, regime_coverage=0.75, baseline_expectancy=0.0005,
    )["maximum_drawdown"]
