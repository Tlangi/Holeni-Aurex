from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


LABEL_HORIZON_BARS = 4
LABEL_HORIZON_MINUTES = 60
LABEL_DEFINITION = "target=1 iff close[t+4] > close[t], using completed regular-session M15 candles"
LABEL_VERSION = "FUTURE_CLOSE_DIRECTION_4_M15_V2"
LABEL_DEFINITION_HASH = hashlib.sha256(LABEL_DEFINITION.encode()).hexdigest()
FEATURE_VERSION = "FEATURES_V1"
FEATURE_WARMUP_ROWS = 13
VALIDATION_POLICY_VERSION = "MODEL_VALIDATION_POLICY_V2"
HOLDOUT_POLICY_VERSION = "FROZEN_HOLDOUT_V2"


def purge_rows_for_horizon(horizon_bars: int = LABEL_HORIZON_BARS) -> int:
    if horizon_bars < 1:
        raise ValueError("Label horizon must be at least one bar")
    return horizon_bars


def feature_complete_rows(segment_rows: int, *, labelled: bool = True,
                          horizon_bars: int = LABEL_HORIZON_BARS) -> int:
    """Exact count implied by add_features for one uninterrupted candle segment."""
    trailing = horizon_bars if labelled else 0
    return max(0, int(segment_rows) - FEATURE_WARMUP_ROWS - trailing)


@dataclass(frozen=True)
class DevelopmentGateEvidence:
    gates: dict[str, bool]
    positive_window_fraction: float
    minimum_window_trades_observed: int
    minimum_window_trades_required: int
    best_baseline_expectancy: float

    @property
    def passed(self) -> bool:
        return all(self.gates.values())


def development_gate_evidence(settings: object, evaluation: object,
                              *, acceptance_auc: float | None = None) -> DevelopmentGateEvidence:
    metrics: Mapping[str, object] = evaluation.metrics
    windows: Sequence[Mapping[str, object]] = evaluation.windows
    baselines: Sequence[Mapping[str, object]] = evaluation.baselines
    best_baseline = max(float(item.get("expectancy") or 0) for item in baselines)
    positive_windows = sum(float(item.get("expectancy") or 0) > 0 for item in windows)
    positive_fraction = positive_windows / len(windows) if windows else 0.0
    minimum_per_window = max(5, int(getattr(settings, "model_minimum_trades")) // max(1, len(windows)))
    observed_per_window = min((int(item.get("trade_count") or 0) for item in windows), default=0)
    gates = {
        "auc": float(evaluation.auc) >= float(
            acceptance_auc if acceptance_auc is not None else getattr(settings, "model_acceptance_auc")
        ),
        "minimum_trades": int(metrics.get("trade_count") or 0) >= int(getattr(settings, "model_minimum_trades")),
        "minimum_trades_each_window": observed_per_window >= minimum_per_window,
        "positive_expectancy": float(metrics.get("expectancy") or 0) > 0,
        "profit_factor": float(metrics.get("profit_factor") or 0) >= float(
            getattr(settings, "holdout_minimum_profit_factor")
        ),
        "maximum_drawdown": float(metrics.get("max_drawdown") or 0) <= min(
            float(getattr(settings, "model_max_drawdown_pct")),
            float(getattr(settings, "holdout_maximum_drawdown_pct")),
        ) / 100,
        "baseline_outperformance": float(metrics.get("expectancy") or 0) > best_baseline,
        "calibration": float(evaluation.calibration_error) <= float(
            getattr(settings, "holdout_maximum_calibration_error")
        ),
        "feature_drift": float(evaluation.feature_drift_score) <= float(
            getattr(settings, "holdout_maximum_feature_drift")
        ),
        "regime_coverage": float(evaluation.regime_coverage) >= float(
            getattr(settings, "holdout_minimum_regime_coverage")
        ),
        "walk_forward_stability": positive_fraction >= (2 / 3),
    }
    return DevelopmentGateEvidence(
        gates, positive_fraction, observed_per_window, minimum_per_window, best_baseline,
    )


def source_identity(workspace: Path | None = None) -> dict[str, object]:
    """Return a commit when available, otherwise a deterministic source snapshot identity."""
    root = workspace or Path(__file__).resolve().parents[3]
    try:
        commit = subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-c", f"safe.directory={root.as_posix()}", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip())
        return {"source_identity": commit, "identity_type": "GIT_COMMIT", "dirty_worktree": dirty}
    except (OSError, subprocess.SubprocessError):
        digest = hashlib.sha256()
        app_root = Path(__file__).resolve().parent
        for path in sorted(app_root.glob("*.py")):
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
        return {
            "source_identity": f"SNAPSHOT:{digest.hexdigest()}",
            "identity_type": "SOURCE_SNAPSHOT",
            "dirty_worktree": True,
        }


def lineage_configuration_hash(configuration: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(configuration, sort_keys=True, default=str).encode()).hexdigest()
