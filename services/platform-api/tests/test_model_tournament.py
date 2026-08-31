from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.config import Settings
from app.model_pipeline import chronological_evaluate
from app.model_tournament import Challenger, ModelTournamentRequest, challengers, run_selective_tournament, run_tournament


def _frame(rows: int = 2300) -> pd.DataFrame:
    index = pd.DatetimeIndex([
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * value)
        for value in range(rows)
    ])
    movement = np.sin(np.arange(rows) / 11) * 0.00035 + np.cos(np.arange(rows) / 37) * 0.00008
    close = 1.10 + np.cumsum(movement)
    return pd.DataFrame({
        "open": close - movement / 2,
        "high": close + 0.00025,
        "low": close - 0.00025,
        "close": close,
        "tick_volume": 100 + np.arange(rows) % 60,
        "observed_spread_bps": np.full(rows, 1.2),
    }, index=index)


def test_walk_forward_purges_forward_label_horizon() -> None:
    evaluation = chronological_evaluate(_frame(900), minimum_rows=700, purge_gap_rows=4)
    for window in evaluation.windows:
        assert window["purge_gap_rows"] == 4
        assert window["training_end"] + timedelta(minutes=75) == window["validation_start"]


def test_tournament_compares_supported_models_without_promotion() -> None:
    settings = Settings(model_minimum_trades=1)
    result = run_tournament(_frame(), settings)
    assert {item["key"] for item in result["candidates"]} == {item.key for item in challengers()}
    assert result["selection_scope"] == "DEVELOPMENT_ONLY"
    assert result["holdout_consumed"] is False
    assert result["promotable"] is False
    assert result["execution_enabled"] is False
    assert all("walk_forward_stability" in item["gates"] for item in result["candidates"])
    assert all("pr_auc" in item and "log_loss" in item for item in result["candidates"])
    assert all("configuration" in item for item in result["candidates"])
    assert result["selective_research_leader"]["candidate"] in {item.key for item in challengers()}


def test_tournament_request_normalizes_supported_market() -> None:
    request = ModelTournamentRequest(market=" usdjpy ")
    assert request.market == "USDJPY"


def test_selective_tournament_is_market_specific_and_never_promotes() -> None:
    candidate = Challenger(
        "LOGISTIC_ONLY", "Logistic only", 1,
        lambda: __import__("sklearn.linear_model", fromlist=["LogisticRegression"]).LogisticRegression(
            max_iter=500, random_state=42,
        ), {},
    )
    settings = Settings(model_minimum_rows=2000, model_walk_forward_windows=3)
    from app.research_protocol import TARGET_CATALOG
    result = run_selective_tournament(
        _frame(2400), "EURUSD", settings, candidate_set=(candidate,),
        target_set=(TARGET_CATALOG["EURUSD"][0],),
    )
    assert result["market"] == "EURUSD"
    assert result["selection_scope"] == "DEVELOPMENT_ONLY"
    assert result["holdout_consumed"] is False
    assert result["execution_enabled"] is False
