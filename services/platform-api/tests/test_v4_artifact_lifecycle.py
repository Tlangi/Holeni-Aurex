from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from app.holdout_service import _selective_labelable_count
from app.model_pipeline import FEATURES, add_features
from app.research_protocol import (
    PROTOCOL_VERSION,
    TARGET_CATALOG,
    build_selective_target,
    fit_selective_development_model,
    selective_directions_from_edges,
    validate_lifecycle_transition,
)
from app.shadow_engine import _signal


def _frame(rows: int = 1200) -> pd.DataFrame:
    index = pd.DatetimeIndex([
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * number)
        for number in range(rows)
    ])
    movement = np.sin(np.arange(rows) / 9) * 0.00045 + np.cos(np.arange(rows) / 31) * 0.00012
    close = 1.10 + np.cumsum(movement)
    return pd.DataFrame({
        "open": close - movement / 2, "high": close + 0.0003,
        "low": close - 0.0003, "close": close,
        "tick_volume": 100 + np.arange(rows) % 50,
        "observed_spread_bps": np.full(rows, 1.0),
        "effective_cost_bps": np.full(rows, 1.0), "provider": "TEST",
    }, index=index)


def test_v4_calibrated_artifact_contract_produces_selective_signal() -> None:
    specification = TARGET_CATALOG["EURUSD"][0]
    development = build_selective_target(
        _frame(), specification, configured_cost_bps=1.0,
    )
    model, calibration = fit_selective_development_model(
        lambda: LogisticRegression(max_iter=500, random_state=42),
        development, horizon_bars=specification.horizon_bars,
    )
    edges = {
        "buy_move_bps": float(calibration["buy_move_bps"] or 3.0),
        "sell_move_bps": float(calibration["sell_move_bps"] or 3.0),
    }
    validation = development.iloc[-20:]
    probabilities = model.predict_proba(validation[FEATURES])
    directions, explanations = selective_directions_from_edges(
        probabilities, model.classes_, validation, specification, **edges,
    )
    assert len(directions) == len(validation)
    assert {item["decision"] for item in explanations} <= {"BUY", "SELL", "HOLD"}

    bundle = {
        "model": model, "features": FEATURES, "horizon": specification.horizon_bars,
        "research_protocol_version": PROTOCOL_VERSION,
        "target_specification": specification.configuration() | {"sha256": specification.digest},
        "edge_parameters": edges, "fallback_spread": 1.0,
    }
    direction, confidence, atr = _signal(_frame(), bundle, 0.70, 0.30)
    assert direction in {"BUY", "SELL", "HOLD"}
    assert 0 <= confidence <= 1
    assert atr > 0


def test_v4_lifecycle_is_ordered_and_holdout_rows_are_segment_safe() -> None:
    for source, destination in (
        ("RESEARCH", "ELIGIBLE_TO_FREEZE"), ("ELIGIBLE_TO_FREEZE", "FROZEN"),
        ("FROZEN", "HOLDOUT_REVIEW"), ("HOLDOUT_REVIEW", "OWNER_APPROVED"),
        ("OWNER_APPROVED", "FORWARD_SHADOW"), ("FORWARD_SHADOW", "PROMOTED"),
    ):
        validate_lifecycle_transition(source, destination)
    causal = add_features(_frame(80), labelled=False)
    assert _selective_labelable_count(causal, 4) == len(causal) - 4
