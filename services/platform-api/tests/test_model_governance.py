from dataclasses import dataclass

from app.config import Settings
from app.model_governance import (
    LABEL_DEFINITION_HASH,
    LABEL_HORIZON_BARS,
    development_gate_evidence,
    feature_complete_rows,
    purge_rows_for_horizon,
)


@dataclass
class EvaluationStub:
    auc: float = 0.60
    calibration_error: float = 0.10
    feature_drift_score: float = 0.50
    regime_coverage: float = 0.75
    metrics: dict | None = None
    windows: list | None = None
    baselines: list | None = None

    def __post_init__(self) -> None:
        self.metrics = self.metrics or {
            "trade_count": 30, "expectancy": 0.001, "profit_factor": 1.2,
            "max_drawdown": 0.02,
        }
        self.windows = self.windows or [
            {"trade_count": 10, "expectancy": 0.001},
            {"trade_count": 10, "expectancy": 0.001},
            {"trade_count": 10, "expectancy": 0.001},
        ]
        self.baselines = self.baselines or [{"expectancy": 0.0005}]


def test_feature_row_count_and_purge_share_the_label_horizon() -> None:
    assert purge_rows_for_horizon() == LABEL_HORIZON_BARS == 4
    assert feature_complete_rows(100) == 83
    assert feature_complete_rows(16) == 0
    assert len(LABEL_DEFINITION_HASH) == 64


def test_canonical_gate_requires_each_walk_forward_window_to_have_trades() -> None:
    settings = Settings(_env_file=None)
    evidence = development_gate_evidence(settings, EvaluationStub())
    assert evidence.passed
    weak = EvaluationStub(windows=[
        {"trade_count": 15, "expectancy": 0.001},
        {"trade_count": 0, "expectancy": 0.001},
        {"trade_count": 15, "expectancy": 0.001},
    ])
    evidence = development_gate_evidence(settings, weak)
    assert not evidence.gates["minimum_trades_each_window"]
    assert not evidence.passed
