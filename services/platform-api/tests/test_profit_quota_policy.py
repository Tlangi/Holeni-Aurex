from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.model_pipeline import trading_metrics


def test_profit_quota_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="DAILY_PROFIT_TARGET_IS_PROHIBITED"):
        Settings(daily_profit_target_enabled=True)


def test_normalized_metrics_separate_gross_edge_from_cost_drag() -> None:
    metrics = trading_metrics(
        np.asarray([0.0020, -0.0005, 0.0010]),
        np.asarray([1, 1, 0]),
        round_trip_cost_bps=5,
    )
    assert metrics["hold_rate"] == pytest.approx(1 / 3)
    assert float(metrics["gross_expectancy"]) > float(metrics["net_expectancy"])
    assert float(metrics["cost_drag"]) == pytest.approx(0.0005)
    assert metrics["profit_factor"] == metrics["net_profit_factor"]


def test_local_tradingagents_prompt_prohibits_quota_chasing() -> None:
    worker = Path(__file__).resolve().parents[3] / "integrations" / "tradingagents" / "aurex_worker.py"
    content = worker.read_text(encoding="utf-8").lower()
    assert "never chase a daily profit quota" in content
    assert "hold and no-trade days are valid" in content
    assert "treat leverage as" in content
