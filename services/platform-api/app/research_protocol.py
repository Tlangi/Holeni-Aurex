from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, clone

from app.model_pipeline import FEATURES, add_features, trading_metrics
from app.research_regimes import market_session, trend_regime, volatility_regimes


PROTOCOL_VERSION = "AUREX_SELECTIVE_RESEARCH_V4"
TARGET_VERSION = "COST_VOLATILITY_TERNARY_V1"
AUDIT_VERSION = "CHRONOLOGICAL_LEAKAGE_AUDIT_V1"


@dataclass(frozen=True)
class TargetSpecification:
    symbol: str
    horizon_bars: int
    mode: str
    minimum_edge_bps: float
    safety_buffer_bps: float
    volatility_multiplier: float
    maximum_adverse_bps: float
    regular_session_only: bool = True
    version: str = TARGET_VERSION

    def configuration(self) -> dict[str, object]:
        return asdict(self)

    @property
    def digest(self) -> str:
        payload = json.dumps(self.configuration(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


TARGET_CATALOG: dict[str, tuple[TargetSpecification, ...]] = {
    "EURUSD": (
        TargetSpecification("EURUSD", 4, "COST_AWARE_RETURN", 1.0, 0.5, 0.0, 10.0),
        TargetSpecification("EURUSD", 8, "VOLATILITY_ADJUSTED", 1.0, 0.5, 0.35, 14.0),
    ),
    "GBPUSD": (
        TargetSpecification("GBPUSD", 4, "COST_AWARE_RETURN", 1.2, 0.7, 0.0, 12.0),
        TargetSpecification("GBPUSD", 8, "VOLATILITY_ADJUSTED", 1.2, 0.7, 0.40, 16.0),
    ),
    "USDJPY": (
        TargetSpecification("USDJPY", 6, "COST_AWARE_RETURN", 1.0, 0.6, 0.0, 12.0),
        TargetSpecification("USDJPY", 12, "VOLATILITY_ADJUSTED", 1.0, 0.6, 0.35, 18.0),
    ),
    "GERMANY40": (
        TargetSpecification("GERMANY40", 4, "COST_AWARE_RETURN", 1.5, 1.0, 0.0, 18.0, True),
        TargetSpecification("GERMANY40", 8, "VOLATILITY_ADJUSTED", 1.5, 1.0, 0.45, 25.0, True),
    ),
}


class DisagreementAwareEnsemble(ClassifierMixin, BaseEstimator):
    """Soft-voting research ensemble whose member disagreement forces HOLD."""

    def __init__(self, estimators: tuple[object, ...]):
        self.estimators = estimators

    def fit(self, features: pd.DataFrame, target: pd.Series) -> "DisagreementAwareEnsemble":
        self.models_ = [clone(estimator).fit(features, target) for estimator in self.estimators]
        self.classes_ = np.asarray(sorted({int(value) for value in target.unique()}))
        return self

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        aligned = []
        for model in self.models_:
            raw = model.predict_proba(features)
            lookup = {int(value): index for index, value in enumerate(model.classes_)}
            aligned.append(np.column_stack([
                raw[:, lookup[int(value)]] if int(value) in lookup else np.zeros(len(features))
                for value in self.classes_
            ]))
        return np.mean(aligned, axis=0)

    def member_disagreement(self, features: pd.DataFrame) -> np.ndarray:
        predictions = np.vstack([model.predict(features) for model in self.models_])
        return np.any(predictions != predictions[0], axis=0)


def target_catalog() -> dict[str, list[dict[str, object]]]:
    return {symbol: [spec.configuration() | {"sha256": spec.digest} for spec in specs]
            for symbol, specs in TARGET_CATALOG.items()}


def _segments(frame: pd.DataFrame, interval: pd.Timedelta) -> pd.Series:
    ordered = frame.sort_index()
    boundaries = ordered.index.to_series().diff().ne(interval)
    if "provider" in ordered.columns:
        provider = ordered["provider"].astype(str)
        boundaries = boundaries | provider.ne(provider.shift(1))
    return boundaries.cumsum()


def build_selective_target(
    frame: pd.DataFrame, specification: TargetSpecification, *,
    configured_cost_bps: float,
) -> pd.DataFrame:
    """Return causal features and a BUY/SELL/HOLD research target.

    Future path values exist only long enough to construct labels and are never
    included in ``FEATURES`` or returned under a feature-like name.
    """
    if specification.horizon_bars < 1:
        raise ValueError("Target horizon must be positive")
    prepared = frame.sort_index().copy()
    observed = prepared.get("observed_spread_bps", pd.Series(np.nan, index=prepared.index))
    prepared["effective_cost_bps"] = np.maximum(
        observed.fillna(configured_cost_bps).clip(lower=0).to_numpy(float), configured_cost_bps,
    )
    featured = add_features(prepared, labelled=False)
    outputs: list[pd.DataFrame] = []
    for _, segment in featured.groupby(_segments(featured, pd.Timedelta(15, unit="min"))):
        data = segment.copy()
        horizon = specification.horizon_bars
        close = data["close"].astype(float)
        future_close = close.shift(-horizon)
        future_return_bps = (future_close / close - 1) * 10000
        future_high = pd.concat([data["high"].shift(-step) for step in range(1, horizon + 1)], axis=1).max(axis=1)
        future_low = pd.concat([data["low"].shift(-step) for step in range(1, horizon + 1)], axis=1).min(axis=1)
        long_adverse_bps = (1 - future_low / close) * 10000
        short_adverse_bps = (future_high / close - 1) * 10000
        volatility_edge = data["atr_pct"].astype(float) * 10000 * specification.volatility_multiplier
        threshold = np.maximum.reduce([
            np.full(len(data), specification.minimum_edge_bps),
            data["effective_cost_bps"].to_numpy(float) + specification.safety_buffer_bps,
            volatility_edge.to_numpy(float),
        ])
        labels = pd.Series("HOLD", index=data.index, dtype="object")
        buy = (future_return_bps > threshold) & (long_adverse_bps <= specification.maximum_adverse_bps)
        sell = (-future_return_bps > threshold) & (short_adverse_bps <= specification.maximum_adverse_bps)
        labels = labels.mask(buy & ~sell, "BUY").mask(sell & ~buy, "SELL")
        data["target_action"] = labels
        data["target"] = labels.map({"HOLD": 0, "BUY": 1, "SELL": 2})
        data["future_return"] = future_return_bps / 10000
        data["delayed_future_return"] = future_close / close.shift(-1) - 1
        data["target_threshold_bps"] = threshold
        data = data.iloc[:-horizon] if len(data) > horizon else data.iloc[0:0]
        outputs.append(data.dropna(subset=FEATURES + ["target", "future_return"]))
    return pd.concat(outputs).sort_index() if outputs else featured.iloc[0:0].copy()


def leakage_boundary_audit(
    raw: pd.DataFrame, featured: pd.DataFrame, *, specification: TargetSpecification,
    windows: Sequence[dict[str, object]] = (), holdout_start: datetime | None = None,
) -> dict[str, object]:
    interval = pd.Timedelta(15, unit="min")
    gates: dict[str, bool] = {
        "raw_index_monotonic": bool(raw.index.is_monotonic_increasing),
        "raw_timestamps_unique": bool(raw.index.is_unique),
        "featured_timestamps_unique": bool(featured.index.is_unique),
        "feature_allowlist_only": all(name in featured.columns for name in FEATURES),
        "future_values_excluded_from_features": not any(
            token in name.lower() for name in FEATURES for token in ("future", "target", "lead")
        ),
    }
    provider_boundaries = 0
    boundary_violations = 0
    ordered = raw.sort_index()
    if "provider" in ordered.columns:
        changes = ordered["provider"].astype(str).ne(ordered["provider"].astype(str).shift(1))
        provider_boundaries = max(0, int(changes.sum()) - 1)
        for timestamp in ordered.index[changes][1:]:
            warmup = pd.date_range(timestamp, periods=13, freq=interval)
            boundary_violations += int(any(value in featured.index for value in warmup))
    gates["provider_boundaries_reset_features"] = boundary_violations == 0
    fold_violations = 0
    purge_violations = 0
    holdout_violations = 0
    for window in windows:
        training_end = pd.Timestamp(window["training_end"])
        validation_start = pd.Timestamp(window["validation_start"])
        if training_end >= validation_start:
            fold_violations += 1
        if validation_start - training_end < interval * (specification.horizon_bars + 1):
            purge_violations += 1
        if holdout_start is not None and pd.Timestamp(window["validation_end"]) >= pd.Timestamp(holdout_start):
            holdout_violations += 1
    gates["walk_forward_chronological"] = fold_violations == 0
    gates["label_horizon_purged"] = purge_violations == 0
    gates["reserved_holdout_excluded"] = holdout_violations == 0
    return {
        "audit_version": AUDIT_VERSION,
        "passed": all(gates.values()),
        "gates": gates,
        "raw_rows": len(raw), "feature_rows": len(featured),
        "provider_boundaries": provider_boundaries,
        "provider_boundary_violations": boundary_violations,
        "fold_overlap_violations": fold_violations,
        "purge_violations": purge_violations,
        "holdout_access_violations": holdout_violations,
        "target_spec_sha256": specification.digest,
    }


def development_only_calibrated_probabilities(
    estimator_factory: Callable[[], object], training: pd.DataFrame, validation: pd.DataFrame,
    *, horizon_bars: int,
) -> tuple[object, np.ndarray, dict[str, object]]:
    """Fit model and sigmoid calibration without using validation observations."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    calibration_rows = max(100, int(len(training) * 0.20))
    split = len(training) - calibration_rows
    fit = training.iloc[:max(0, split - horizon_bars)]
    calibration = training.iloc[split:]
    required_classes = {0, 1, 2}
    if (len(fit) < 300 or set(fit["target"].astype(int).unique()) != required_classes or
            set(calibration["target"].astype(int).unique()) != required_classes):
        raise ValueError("Development fit and calibration partitions must contain BUY, SELL and HOLD")
    estimator = estimator_factory()
    estimator.fit(fit[FEATURES], fit["target"].astype(int))
    calibrated = CalibratedClassifierCV(FrozenEstimator(estimator), method="sigmoid")
    calibrated.fit(calibration[FEATURES], calibration["target"].astype(int))
    probabilities = calibrated.predict_proba(validation[FEATURES])
    return calibrated, probabilities, {
        "fit_rows": len(fit), "calibration_rows": len(calibration),
        "calibration_start": calibration.index.min().isoformat(),
        "calibration_end": calibration.index.max().isoformat(),
        "validation_used_for_calibration": False,
    }


def fit_selective_development_model(
    estimator_factory: Callable[[], object], development: pd.DataFrame, *, horizon_bars: int,
) -> tuple[object, dict[str, object]]:
    """Fit and calibrate the final frozen model using development evidence only."""
    calibration_rows = max(100, int(len(development) * 0.20))
    split = len(development) - calibration_rows
    fit = development.iloc[:max(0, split - horizon_bars)]
    calibration = development.iloc[split:]
    required_classes = {0, 1, 2}
    if (len(fit) < 300 or set(fit["target"].astype(int).unique()) != required_classes or
            set(calibration["target"].astype(int).unique()) != required_classes):
        raise ValueError("Development fit and calibration partitions must contain BUY, SELL and HOLD")
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.frozen import FrozenEstimator

    estimator = estimator_factory()
    estimator.fit(fit[FEATURES], fit["target"].astype(int))
    calibrated = CalibratedClassifierCV(FrozenEstimator(estimator), method="sigmoid")
    calibrated.fit(calibration[FEATURES], calibration["target"].astype(int))
    buy_moves = development.loc[development["target"] == 1, "future_return"].abs() * 10000
    sell_moves = development.loc[development["target"] == 2, "future_return"].abs() * 10000
    return calibrated, {
        "fit_rows": len(fit), "calibration_rows": len(calibration),
        "calibration_start": calibration.index.min().isoformat(),
        "calibration_end": calibration.index.max().isoformat(),
        "validation_used_for_calibration": False,
        "buy_move_bps": float(buy_moves.median()) if len(buy_moves) else None,
        "sell_move_bps": float(sell_moves.median()) if len(sell_moves) else None,
    }


def selective_directions_from_edges(
    probabilities: np.ndarray, classes: np.ndarray, validation: pd.DataFrame,
    specification: TargetSpecification, *, buy_move_bps: float, sell_move_bps: float,
) -> tuple[np.ndarray, list[dict[str, float | str]]]:
    class_index = {int(value): index for index, value in enumerate(classes)}
    hold_p = probabilities[:, class_index[0]] if 0 in class_index else np.zeros(len(probabilities))
    buy_p = probabilities[:, class_index[1]] if 1 in class_index else np.zeros(len(probabilities))
    sell_p = probabilities[:, class_index[2]] if 2 in class_index else np.zeros(len(probabilities))
    costs = validation["effective_cost_bps"].to_numpy(float) + specification.safety_buffer_bps
    buy_edge = buy_p * buy_move_bps - sell_p * sell_move_bps - costs
    sell_edge = sell_p * sell_move_bps - buy_p * buy_move_bps - costs
    directions = np.where(
        (buy_p > sell_p) & (buy_p > hold_p) & (buy_edge > 0), 1,
        np.where((sell_p > buy_p) & (sell_p > hold_p) & (sell_edge > 0), -1, 0),
    )
    explanations = [{
        "decision": "BUY" if direction == 1 else "SELL" if direction == -1 else "HOLD",
        "buy_probability": float(bp), "sell_probability": float(sp), "hold_probability": float(hp),
        "buy_edge_bps": float(be), "sell_edge_bps": float(se), "cost_floor_bps": float(cost),
        "reason": "POSITIVE_NET_EDGE" if direction else "EDGE_DOES_NOT_CLEAR_COST_AND_BUFFER",
    } for direction, bp, sp, hp, be, se, cost in zip(
        directions, buy_p, sell_p, hold_p, buy_edge, sell_edge, costs, strict=True,
    )]
    return directions.astype(int), explanations


def selective_directions(
    probabilities: np.ndarray, classes: np.ndarray, training: pd.DataFrame,
    validation: pd.DataFrame, specification: TargetSpecification,
) -> tuple[np.ndarray, list[dict[str, float | str]]]:
    buy_moves = training.loc[training["target"] == 1, "future_return"].abs() * 10000
    sell_moves = training.loc[training["target"] == 2, "future_return"].abs() * 10000
    fallback = max(specification.minimum_edge_bps, float(training["atr_pct"].median()) * 10000)
    buy_move = float(buy_moves.median()) if len(buy_moves) else fallback
    sell_move = float(sell_moves.median()) if len(sell_moves) else fallback
    return selective_directions_from_edges(
        probabilities, classes, validation, specification,
        buy_move_bps=buy_move, sell_move_bps=sell_move,
    )


def apply_ensemble_disagreement(model: object, features: pd.DataFrame, directions: np.ndarray) -> np.ndarray:
    frozen = getattr(model, "estimator", None)
    underlying = getattr(frozen, "estimator", frozen)
    if underlying is not None and hasattr(underlying, "member_disagreement"):
        directions = directions.copy()
        directions[underlying.member_disagreement(features[FEATURES])] = 0
    return directions


def block_bootstrap_expectancy(
    future_returns: np.ndarray, directions: np.ndarray, costs_bps: np.ndarray, *,
    samples: int = 1000, block_size: int = 8, seed: int = 42,
) -> dict[str, float | int]:
    selected = directions != 0
    net = future_returns[selected] * directions[selected] - costs_bps[selected] / 10000
    if not len(net):
        return {"samples": samples, "trade_count": 0, "mean": 0.0, "lower_95": 0.0, "upper_95": 0.0}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        blocks = []
        while sum(len(block) for block in blocks) < len(net):
            start = int(rng.integers(0, max(1, len(net) - block_size + 1)))
            blocks.append(net[start:start + block_size])
        means.append(float(np.mean(np.concatenate(blocks)[:len(net)])))
    return {"samples": samples, "trade_count": len(net), "mean": float(np.mean(net)),
            "lower_95": float(np.percentile(means, 2.5)),
            "upper_95": float(np.percentile(means, 97.5))}


def cost_stress_evidence(frame: pd.DataFrame, directions: np.ndarray) -> list[dict[str, object]]:
    observed = frame["effective_cost_bps"].to_numpy(float)
    finite = observed[np.isfinite(observed)]
    quantiles = np.percentile(finite, [50, 75, 90, 95]) if len(finite) else np.zeros(4)
    scenarios = [("SPREAD_P50", quantiles[0], 0.0, False),
                 ("SPREAD_P75", quantiles[1], 0.0, False),
                 ("SPREAD_P90", quantiles[2], 0.0, False),
                 ("SPREAD_P95", quantiles[3], 0.0, False),
                 ("P95_PLUS_SLIPPAGE", quantiles[3], 1.0, False),
                 ("P95_DELAY_ONE_CANDLE", quantiles[3], 1.0, True),
                 ("P95_OVERNIGHT_FUNDING", quantiles[3], 1.5, False)]
    results = []
    for name, spread, extra, delayed in scenarios:
        returns = frame["delayed_future_return" if delayed else "future_return"].fillna(0).to_numpy(float)
        metrics = trading_metrics(returns, directions, round_trip_cost_bps=np.full(len(frame), spread + extra))
        results.append({"scenario": name, "spread_bps": float(spread),
                        "additional_cost_bps": extra, "entry_delay_bars": int(delayed), **metrics})
    return results


def regime_slices(frame: pd.DataFrame, directions: np.ndarray, symbol: str) -> list[dict[str, object]]:
    evidence = frame.copy()
    evidence["volatility_regime"] = volatility_regimes(evidence["atr_pct"])
    evidence["trend_regime"] = [trend_regime(float(gap), float(atr))
                                for gap, atr in zip(evidence["ema_gap"], evidence["atr_pct"], strict=True)]
    evidence["session"] = [market_session(symbol, value.to_pydatetime()) for value in evidence.index]
    results = []
    for dimension in ("volatility_regime", "trend_regime", "session"):
        for bucket, rows in evidence.groupby(dimension):
            indexes = evidence.index.get_indexer(rows.index)
            metrics = trading_metrics(rows["future_return"].to_numpy(float), directions[indexes],
                                      round_trip_cost_bps=rows["effective_cost_bps"].to_numpy(float))
            results.append({"dimension": dimension, "bucket": str(bucket),
                            "observation_count": len(rows), **metrics})
    return results


def _multiclass_calibration_error(
    targets: np.ndarray, probabilities: np.ndarray, classes: np.ndarray, bins: int = 10,
) -> float:
    errors = []
    for column, class_value in enumerate(classes):
        actual = (targets == int(class_value)).astype(float)
        predicted = probabilities[:, column]
        error = 0.0
        for lower in np.linspace(0, 1, bins, endpoint=False):
            upper = lower + 1 / bins
            selected = (predicted >= lower) & (predicted < upper if upper < 1 else predicted <= upper)
            if np.any(selected):
                error += float(np.mean(selected)) * abs(
                    float(np.mean(predicted[selected])) - float(np.mean(actual[selected]))
                )
        errors.append(error)
    return float(max(errors, default=1.0))


def selective_walk_forward_evaluate(
    frame: pd.DataFrame, specification: TargetSpecification, *,
    estimator_factory: Callable[[], object], minimum_rows: int,
    configured_cost_bps: float, walk_forward_windows: int = 3,
    validation_fraction: float = 0.20, holdout_start: datetime | None = None,
) -> dict[str, object]:
    """Evaluate one predeclared candidate on purged development windows only."""
    data = build_selective_target(frame, specification, configured_cost_bps=configured_cost_bps)
    if len(data) < minimum_rows:
        raise ValueError(f"Need at least {minimum_rows} selective feature rows; found {len(data)}")
    if walk_forward_windows < 2 or walk_forward_windows > 10:
        raise ValueError("Walk-forward windows must be between 2 and 10")
    initial = int(len(data) * (1 - validation_fraction * 2))
    window_size = (len(data) - initial) // walk_forward_windows
    if initial < 600 or window_size < 100:
        raise ValueError("Selective chronological windows are too small")
    windows = []
    validation_frames: list[pd.DataFrame] = []
    direction_sets: list[np.ndarray] = []
    probability_sets: list[np.ndarray] = []
    target_sets: list[np.ndarray] = []
    explanation_counts: dict[str, int] = {}
    calibration_evidence = []
    final_model = None
    for number in range(walk_forward_windows):
        end = initial + number * window_size
        validation_end = len(data) if number == walk_forward_windows - 1 else end + window_size
        training = data.iloc[:end - specification.horizon_bars]
        validation = data.iloc[end:validation_end]
        model, probabilities, calibration = development_only_calibrated_probabilities(
            estimator_factory, training, validation, horizon_bars=specification.horizon_bars,
        )
        directions, explanations = selective_directions(
            probabilities, model.classes_, training, validation, specification,
        )
        frozen = getattr(model, "estimator", None)
        underlying = getattr(frozen, "estimator", frozen)
        if underlying is not None and hasattr(underlying, "member_disagreement"):
            disagreement = underlying.member_disagreement(validation[FEATURES])
            directions[disagreement] = 0
            for index in np.flatnonzero(disagreement):
                explanations[int(index)]["decision"] = "HOLD"
                explanations[int(index)]["reason"] = "ENSEMBLE_MEMBER_DISAGREEMENT"
        metrics = trading_metrics(
            validation["future_return"].to_numpy(float), directions,
            round_trip_cost_bps=validation["effective_cost_bps"].to_numpy(float),
        )
        window = {
            "window_number": number + 1, "training_rows": len(training),
            "validation_rows": len(validation), "purge_gap_rows": specification.horizon_bars,
            "training_start": training.index.min().to_pydatetime(),
            "training_end": training.index.max().to_pydatetime(),
            "validation_start": validation.index.min().to_pydatetime(),
            "validation_end": validation.index.max().to_pydatetime(),
            "hold_fraction": float(np.mean(directions == 0)), **metrics,
        }
        windows.append(window)
        validation_frames.append(validation)
        direction_sets.append(directions)
        probability_sets.append(probabilities)
        target_sets.append(validation["target"].to_numpy(int))
        calibration_evidence.append(calibration)
        for explanation in explanations:
            reason = str(explanation["reason"])
            explanation_counts[reason] = explanation_counts.get(reason, 0) + 1
        final_model = model
    combined = pd.concat(validation_frames)
    directions = np.concatenate(direction_sets)
    probabilities = np.concatenate(probability_sets)
    targets = np.concatenate(target_sets)
    metrics = trading_metrics(
        combined["future_return"].to_numpy(float), directions,
        round_trip_cost_bps=combined["effective_cost_bps"].to_numpy(float),
    )
    bootstrap = block_bootstrap_expectancy(
        combined["future_return"].to_numpy(float), directions,
        combined["effective_cost_bps"].to_numpy(float),
    )
    stresses = cost_stress_evidence(combined, directions)
    regimes = regime_slices(combined, directions, specification.symbol)
    audit = leakage_boundary_audit(
        frame, data, specification=specification, windows=windows, holdout_start=holdout_start,
    )
    positive_windows = sum(float(item["expectancy"] or 0) > 0 for item in windows)
    p90 = next(item for item in stresses if item["scenario"] == "SPREAD_P90")
    gates = {
        "leakage_boundary_audit": bool(audit["passed"]),
        "buy_sell_hold_class_coverage": set(np.unique(targets)) == {0, 1, 2},
        "minimum_trades": int(metrics["trade_count"] or 0) >= 30,
        "positive_aggregate_expectancy": float(metrics["expectancy"] or 0) > 0,
        "positive_window_majority": positive_windows / len(windows) >= 2 / 3,
        "no_single_window_dependency": min(float(item["expectancy"] or 0) for item in windows) > 0,
        "bootstrap_lower_bound_positive": float(bootstrap["lower_95"]) > 0,
        "p90_spread_stress_positive": float(p90["expectancy"] or 0) > 0,
        "calibration_error": _multiclass_calibration_error(
            targets, probabilities, final_model.classes_ if final_model is not None else np.array([]),
        ) <= 0.20,
    }
    return {
        "protocol_version": PROTOCOL_VERSION,
        "selection_scope": "DEVELOPMENT_ONLY",
        "target_specification": specification.configuration() | {"sha256": specification.digest},
        "feature_version": "FEATURES_V1_PROVIDER_BOUNDARY_RESET",
        "metrics": metrics, "windows": windows, "bootstrap_expectancy": bootstrap,
        "cost_stress": stresses, "regimes": regimes,
        "calibration_error": _multiclass_calibration_error(
            targets, probabilities, final_model.classes_ if final_model is not None else np.array([]),
        ),
        "calibration_evidence": calibration_evidence,
        "hold_fraction": float(np.mean(directions == 0)),
        "decision_reason_counts": explanation_counts,
        "target_distribution": {name: int((combined["target_action"] == name).sum())
                                for name in ("BUY", "SELL", "HOLD")},
        "leakage_audit": audit, "gates": gates,
        "eligible_to_freeze": all(gates.values()),
        "holdout_consumed": False, "execution_enabled": False,
        "deferred_regimes": {
            "risk_on_off": "requires a timestamp-aligned audited macro/risk dataset",
            "high_impact_event_window": "requires point-in-time event snapshots",
        },
        "_model": final_model,
    }


LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    "RESEARCH": {"ELIGIBLE_TO_FREEZE", "REJECTED"},
    "ELIGIBLE_TO_FREEZE": {"FROZEN", "REJECTED"},
    "FROZEN": {"HOLDOUT_REVIEW", "REJECTED"},
    "HOLDOUT_REVIEW": {"OWNER_APPROVED", "REJECTED"},
    "OWNER_APPROVED": {"FORWARD_SHADOW", "REJECTED"},
    "FORWARD_SHADOW": {"PROMOTED", "REJECTED"},
    "PROMOTED": {"SUSPENDED"},
    "SUSPENDED": {"FORWARD_SHADOW", "REJECTED"},
    "REJECTED": set(),
}


def validate_lifecycle_transition(from_state: str, to_state: str) -> None:
    if to_state not in LIFECYCLE_TRANSITIONS.get(from_state, set()):
        raise ValueError(f"Invalid candidate lifecycle transition: {from_state} -> {to_state}")
