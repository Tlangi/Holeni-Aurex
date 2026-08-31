from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# joblib cannot query physical cores through WMIC on this Windows Server image.
# Supplying the logical count avoids a noisy warning without changing model logic.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

from app.config import Settings
from app.database import open_database
from app.research_regimes import REGIME_VERSION
from app.model_governance import (
    FEATURE_VERSION,
    LABEL_HORIZON_BARS,
    LABEL_VERSION,
    VALIDATION_POLICY_VERSION,
    development_gate_evidence,
    purge_rows_for_horizon,
    source_identity,
)

FEATURES = ["ret1", "ret4", "ema_gap", "rsi", "atr_pct", "range_pct", "volume_z"]
MODEL_ROOT = Path(__file__).resolve().parents[1] / "models"


@dataclass(frozen=True)
class Evaluation:
    model: object
    auc: float
    pr_auc: float
    log_loss: float
    training_rows: int
    validation_rows: int
    training_start: datetime
    training_end: datetime
    validation_start: datetime
    validation_end: datetime
    metrics: dict[str, float | int | None]
    windows: list[dict[str, object]]
    baselines: list[dict[str, object]]
    brier_score: float
    calibration_error: float
    feature_drift_score: float
    regime_coverage: float
    regimes: list[dict[str, object]]
    calibration_buckets: list[dict[str, float | int]]
    selective_thresholds: list[dict[str, object]]


def add_features(
    frame: pd.DataFrame, *, horizon: int = LABEL_HORIZON_BARS, labelled: bool,
    expected_interval: pd.Timedelta | None = None,
) -> pd.DataFrame:
    data = frame.sort_index().copy()
    if data.empty:
        return data
    if expected_interval is None:
        expected_interval = pd.Timedelta(15, unit="min")
    gaps = data.index.to_series().diff().ne(expected_interval)
    if "provider" in data.columns:
        # A provider transition is an explicit information boundary even when
        # both providers happen to have adjacent timestamps.
        gaps = gaps | data["provider"].astype(str).ne(data["provider"].astype(str).shift(1))
    segments = gaps.cumsum()
    prepared = [
        _add_features_segment(segment, horizon=horizon, labelled=labelled)
        for _, segment in data.groupby(segments)
    ]
    populated = [segment for segment in prepared if not segment.empty]
    return pd.concat(populated).sort_index() if populated else data.iloc[0:0].copy()


def _add_features_segment(frame: pd.DataFrame, *, horizon: int, labelled: bool) -> pd.DataFrame:
    data = frame.copy()
    close, high, low = data["close"], data["high"], data["low"]
    data["ret1"] = close.pct_change()
    data["ret4"] = close.pct_change(4)
    data["ema_gap"] = close.ewm(span=12, adjust=False).mean() / close.ewm(span=26, adjust=False).mean() - 1
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    ratio = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + ratio)
    data["rsi"] = rsi.mask((loss == 0) & (gain > 0), 100).mask((gain == 0) & (loss > 0), 0)
    data["rsi"] = data["rsi"].mask((gain == 0) & (loss == 0), 50)
    previous = close.shift(1)
    true_range = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    data["atr"] = true_range.rolling(14).mean()
    data["atr_pct"] = data["atr"] / close
    data["range_pct"] = (high - low) / close
    volume = data["tick_volume"].astype(float)
    data["volume_z"] = (
        (volume - volume.rolling(50).mean()) / volume.rolling(50).std().replace(0, np.nan)
    ).fillna(0)
    if labelled:
        future = close.shift(-horizon)
        data["target"] = np.where(future.notna(), (future > close).astype(float), np.nan)
        data["future_return"] = future / close - 1
    required = FEATURES + (["target", "future_return"] if labelled else [])
    return data.replace([np.inf, -np.inf], np.nan).dropna(subset=required)


def trading_metrics(
    future_returns: np.ndarray, directions: np.ndarray, *, round_trip_cost_bps: float | np.ndarray,
) -> dict[str, float | int | None]:
    trades = directions != 0
    signed = future_returns * directions
    costs = (np.full(len(future_returns), float(round_trip_cost_bps))
             if np.isscalar(round_trip_cost_bps) else np.asarray(round_trip_cost_bps, dtype=float))
    if len(costs) != len(future_returns):
        raise ValueError("Transaction-cost evidence must align with return observations")
    net = signed[trades] - costs[trades] / 10000.0
    count = int(len(net))
    if count == 0:
        return {"trade_count": 0, "win_rate": 0.0, "average_win": 0.0, "average_loss": 0.0,
                "expectancy": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0,
                "sharpe_ratio": None, "sortino_ratio": None,
                "precision_buy": None, "precision_sell": None}
    wins, losses = net[net > 0], net[net < 0]
    gross_win, gross_loss = float(wins.sum()), float(-losses.sum())
    curve = np.cumsum(net)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], curve)))
    drawdowns = peaks[1:] - curve
    deviation = float(np.std(net, ddof=1)) if count > 1 else 0.0
    downside = net[net < 0]
    downside_deviation = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    buy = directions == 1
    sell = directions == -1
    return {
        "trade_count": count, "win_rate": float(np.mean(net > 0)),
        "average_win": float(np.mean(wins)) if len(wins) else 0.0,
        "average_loss": float(np.mean(losses)) if len(losses) else 0.0,
        "expectancy": float(np.mean(net)),
        "profit_factor": gross_win / gross_loss if gross_loss else (999.0 if gross_win else 0.0),
        "max_drawdown": float(np.max(drawdowns)) if len(drawdowns) else 0.0,
        "sharpe_ratio": float(np.mean(net) / deviation * np.sqrt(252)) if deviation else None,
        "sortino_ratio": float(np.mean(net) / downside_deviation * np.sqrt(252)) if downside_deviation else None,
        "precision_buy": float(np.mean(future_returns[buy] > 0)) if np.any(buy) else None,
        "precision_sell": float(np.mean(future_returns[sell] < 0)) if np.any(sell) else None,
    }


def _safe_auc(target: np.ndarray, probabilities: np.ndarray) -> float:
    return float(roc_auc_score(target, probabilities)) if len(np.unique(target)) > 1 else 0.5


def _calibration_error(target: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    error = 0.0
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        selected = (probabilities >= lower) & (probabilities < upper if upper < 1 else probabilities <= upper)
        if np.any(selected):
            error += float(np.mean(selected)) * abs(float(np.mean(probabilities[selected])) - float(np.mean(target[selected])))
    return error


def _calibration_buckets(
    target: np.ndarray, probabilities: np.ndarray, bins: int = 10,
) -> list[dict[str, float | int]]:
    results = []
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        selected = (probabilities >= lower) & (probabilities < upper if upper < 1 else probabilities <= upper)
        if np.any(selected):
            results.append({
                "lower": float(lower), "upper": float(upper),
                "predicted_probability": float(np.mean(probabilities[selected])),
                "actual_frequency": float(np.mean(target[selected])),
                "sample_count": int(np.sum(selected)),
            })
    return results


def _selective_threshold_results(
    returns: list[np.ndarray], probabilities: list[np.ndarray], costs: list[np.ndarray],
) -> list[dict[str, object]]:
    results = []
    for upper in (0.55, 0.60, 0.65, 0.70):
        lower = 1 - upper
        window_metrics = []
        all_directions = []
        for window_returns, window_probabilities, window_costs in zip(returns, probabilities, costs):
            directions = np.where(
                window_probabilities >= upper, 1,
                np.where(window_probabilities <= lower, -1, 0),
            )
            all_directions.append(directions)
            window_metrics.append(trading_metrics(
                window_returns, directions, round_trip_cost_bps=window_costs,
            ))
        aggregate = trading_metrics(
            np.concatenate(returns), np.concatenate(all_directions),
            round_trip_cost_bps=np.concatenate(costs),
        )
        profitable = sum(float(item["expectancy"] or 0) > 0 for item in window_metrics)
        results.append({
            "upper": upper, "lower": lower, **aggregate,
            "positive_window_fraction": profitable / len(window_metrics),
            "worst_window_expectancy": min(float(item["expectancy"] or 0) for item in window_metrics),
            "worst_window_profit_factor": min(float(item["profit_factor"] or 0) for item in window_metrics),
            "windows": window_metrics,
        })
    return results


def _feature_drift(training: pd.DataFrame, validation: pd.DataFrame) -> float:
    scores = []
    for feature in FEATURES:
        scale = max(float(training[feature].std()), 1e-9)
        scores.append(min(5.0, abs(float(validation[feature].mean()) - float(training[feature].mean())) / scale))
    return float(np.mean(scores))


def _regime_results(frame: pd.DataFrame, directions: np.ndarray, *, round_trip_cost_bps: float) -> list[dict[str, object]]:
    volatility_cut = float(frame["atr_pct"].median())
    trend_cut = float(frame["ema_gap"].abs().median())
    regimes = {
        "LOW_VOLATILITY": frame["atr_pct"].to_numpy(float) <= volatility_cut,
        "HIGH_VOLATILITY": frame["atr_pct"].to_numpy(float) > volatility_cut,
        "RANGING": frame["ema_gap"].abs().to_numpy(float) <= trend_cut,
        "TRENDING": frame["ema_gap"].abs().to_numpy(float) > trend_cut,
    }
    returns = frame["future_return"].to_numpy(float)
    results = []
    for name, selected in regimes.items():
        metrics = trading_metrics(
            returns[selected], directions[selected],
            round_trip_cost_bps=frame["effective_cost_bps"].to_numpy(float)[selected],
        )
        results.append({"name": name, "observation_count": int(np.sum(selected)), **metrics})
    return results


def _baseline_results(
    frames: list[pd.DataFrame], *, round_trip_cost_bps: float,
) -> list[dict[str, object]]:
    future = np.concatenate([frame["future_return"].to_numpy(float) for frame in frames])
    costs = np.concatenate([frame["effective_cost_bps"].to_numpy(float) for frame in frames])
    sma = np.concatenate([np.where(frame["ema_gap"].to_numpy(float) > 0, 1, -1) for frame in frames])
    momentum = np.concatenate([np.where(frame["ret4"].to_numpy(float) > 0, 1, -1) for frame in frames])
    random = np.random.default_rng(42).choice([-1, 1], size=len(future))
    items = [("ALWAYS_HOLD", np.zeros(len(future), dtype=int)), ("SMA", sma),
             ("MOMENTUM", momentum), ("RANDOM", random)]
    return [{"name": name, **trading_metrics(future, direction, round_trip_cost_bps=costs)}
            for name, direction in items]


def chronological_evaluate(
    frame: pd.DataFrame, *, minimum_rows: int = 2000, validation_fraction: float = 0.2,
    walk_forward_windows: int = 3, round_trip_cost_bps: float = 1.0,
    purge_gap_rows: int | None = None, estimator_factory: Callable[[], object] | None = None,
) -> Evaluation:
    if purge_gap_rows is None:
        purge_gap_rows = purge_rows_for_horizon(LABEL_HORIZON_BARS)
    prepared = frame.copy()
    observed = prepared.get("observed_spread_bps", pd.Series(0.0, index=prepared.index)).fillna(0).clip(lower=0)
    prepared["effective_cost_bps"] = np.maximum(observed.to_numpy(float), round_trip_cost_bps)
    data = add_features(prepared, labelled=True)
    if len(data) < minimum_rows:
        raise ValueError(f"Need at least {minimum_rows} feature-complete rows; found {len(data)}")
    if walk_forward_windows < 2 or walk_forward_windows > 10:
        raise ValueError("Walk-forward windows must be between 2 and 10")
    if purge_gap_rows < 0 or purge_gap_rows > 100:
        raise ValueError("Purge gap rows must be between 0 and 100")
    initial = int(len(data) * (1 - validation_fraction * 2))
    window_size = (len(data) - initial) // walk_forward_windows
    if initial < 500 or window_size < 100:
        raise ValueError("Chronological train/validation windows are too small")
    windows: list[dict[str, object]] = []
    validations: list[pd.DataFrame] = []
    all_returns: list[np.ndarray] = []
    all_directions: list[np.ndarray] = []
    all_probabilities: list[np.ndarray] = []
    all_targets: list[np.ndarray] = []
    all_costs: list[np.ndarray] = []
    drift_scores: list[float] = []
    final_model = None
    for number in range(walk_forward_windows):
        end = initial + number * window_size
        validation_end = len(data) if number == walk_forward_windows - 1 else end + window_size
        # The target looks four candles ahead. Purging those rows prevents the
        # last training labels from reading prices in the validation interval.
        training, validation = data.iloc[:end - purge_gap_rows], data.iloc[end:validation_end]
        if training.empty:
            raise ValueError("Purge gap removed the complete training window")
        model = estimator_factory() if estimator_factory else HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1, random_state=42,
        )
        model.fit(training[FEATURES], training["target"].astype(int))
        probabilities = model.predict_proba(validation[FEATURES])[:, 1]
        directions = np.where(probabilities >= 0.70, 1, np.where(probabilities <= 0.30, -1, 0))
        returns = validation["future_return"].to_numpy(float)
        metrics = trading_metrics(
            returns, directions,
            round_trip_cost_bps=validation["effective_cost_bps"].to_numpy(float),
        )
        windows.append({"window_number": number + 1, "training_rows": len(training),
                        "purge_gap_rows": purge_gap_rows,
                        "validation_rows": len(validation), "training_start": training.index[0].to_pydatetime(),
                        "training_end": training.index[-1].to_pydatetime(),
                        "validation_start": validation.index[0].to_pydatetime(),
                        "validation_end": validation.index[-1].to_pydatetime(),
                        "auc": _safe_auc(validation["target"].to_numpy(int), probabilities), **metrics})
        validations.append(validation)
        all_returns.append(returns)
        all_directions.append(directions)
        all_probabilities.append(probabilities)
        all_targets.append(validation["target"].to_numpy(int))
        all_costs.append(validation["effective_cost_bps"].to_numpy(float))
        drift_scores.append(_feature_drift(training, validation))
        final_model = model
    aggregate = trading_metrics(np.concatenate(all_returns), np.concatenate(all_directions),
                                round_trip_cost_bps=np.concatenate(all_costs))
    auc = float(np.average([float(item["auc"]) for item in windows],
                           weights=[int(item["validation_rows"]) for item in windows]))
    baselines = _baseline_results(validations, round_trip_cost_bps=round_trip_cost_bps)
    combined_validation = pd.concat(validations)
    combined_directions = np.concatenate(all_directions)
    probabilities = np.concatenate(all_probabilities)
    targets = np.concatenate(all_targets)
    selective_thresholds = _selective_threshold_results(all_returns, all_probabilities, all_costs)
    regimes = _regime_results(combined_validation, combined_directions,
                              round_trip_cost_bps=round_trip_cost_bps)
    regime_coverage = float(np.mean([int(item["observation_count"]) >= 100 for item in regimes]))
    assert final_model is not None
    return Evaluation(
        final_model, auc, float(average_precision_score(targets, probabilities)),
        float(log_loss(targets, probabilities, labels=[0, 1])),
        int(windows[-1]["training_rows"]), sum(int(item["validation_rows"]) for item in windows),
        windows[-1]["training_start"], windows[-1]["training_end"],
        windows[0]["validation_start"], windows[-1]["validation_end"], aggregate, windows, baselines,
        float(np.mean((probabilities-targets) ** 2)), _calibration_error(targets, probabilities),
        float(np.mean(drift_scores)), regime_coverage, regimes,
        _calibration_buckets(targets, probabilities), selective_thresholds,
    )


def _market_frame(cursor: object, market_id: str) -> pd.DataFrame:
    cursor.execute(
        """SELECT open_time_utc,[open],high,low,[close],tick_count,source,
                  CASE WHEN spread_close IS NOT NULL AND [close]>0
                       THEN spread_close/[close]*10000 END observed_spread_bps
           FROM app.candles
           WHERE market_id=%s AND timeframe='M15' AND completed=1 AND quality_status='PASS'
             AND is_regular_session=1
           ORDER BY open_time_utc""",
        (market_id,),
    )
    rows = cursor.fetchall()
    columns = ["time", "open", "high", "low", "close", "tick_volume", "provider", "observed_spread_bps"]
    if rows and isinstance(rows[0], dict):
        frame = pd.DataFrame(rows).rename(columns={
            "open_time_utc": "time", "tick_count": "tick_volume", "source": "provider",
        })[columns]
    else:
        frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    frame = frame.set_index("time")
    for column in ("open", "high", "low", "close", "tick_volume", "observed_spread_bps"):
        frame[column] = pd.to_numeric(frame[column])
    return frame


def train_all_markets(
    settings: Settings, *, minimum_rows: int = 2000, acceptance_auc: float = 0.52,
    retrain_type: str = "SCHEDULED_RETRAIN", material_change: str | None = None,
) -> list[dict[str, object]]:
    if minimum_rows < settings.model_minimum_rows:
        raise ValueError("Training cannot lower the configured 2,000-row evidence floor")
    if retrain_type not in {"SCHEDULED_RETRAIN", "RESEARCH_RETRAIN"}:
        raise ValueError("Unsupported retraining type")
    if retrain_type == "RESEARCH_RETRAIN" and not (material_change or "").strip():
        raise ValueError("Research retraining requires an explicitly versioned material change")
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT sv.strategy_version_id,m.market_id,m.symbol
               FROM app.strategy_versions sv JOIN app.strategies s ON s.strategy_id=sv.strategy_id
               CROSS JOIN app.markets m
               WHERE s.strategy_name='Conservative FX Demo' AND sv.version='1.0' AND m.enabled=1"""
        )
        markets = cursor.fetchall()
        for strategy_version_id, market_id, symbol in markets:
            frame = _market_frame(cursor, str(market_id))
            if frame.empty or len(frame) < minimum_rows + 60:
                outcomes.append({"symbol": symbol, "result": "BLOCKED", "reason": "INSUFFICIENT_CANDLES", "rows": len(frame)})
                continue
            cursor.execute(
                """SELECT TOP (1) me.validation_end_utc
                   FROM app.model_versions mv
                   JOIN app.model_evaluations me ON me.model_version_id=mv.model_version_id
                   WHERE mv.market_id=%s AND mv.strategy_version_id=%s
                   ORDER BY me.evaluated_at_utc DESC""",
                (str(market_id), str(strategy_version_id)),
            )
            prior = cursor.fetchone()
            latest_candle = frame.index[-1].to_pydatetime()
            if prior and retrain_type == "SCHEDULED_RETRAIN":
                previous_end = prior[0].replace(tzinfo=timezone.utc)
                new_rows = int((frame.index > previous_end).sum())
                if new_rows < settings.model_minimum_new_rows:
                    outcomes.append({"symbol": symbol, "result": "CURRENT",
                                     "reason": "INSUFFICIENT_NEW_M15_DATA", "rows": len(frame),
                                     "new_rows": new_rows,
                                     "required_new_rows": settings.model_minimum_new_rows})
                    continue
            evaluation = chronological_evaluate(
                frame, minimum_rows=minimum_rows,
                walk_forward_windows=settings.model_walk_forward_windows,
                round_trip_cost_bps=settings.model_round_trip_cost_bps,
            )
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            version = f"trained-{stamp}-{uuid.uuid4().hex[:6]}"
            artifact = MODEL_ROOT / f"{symbol}-{version}.joblib"
            identity = source_identity()
            joblib.dump({
                "model": evaluation.model, "features": FEATURES, "horizon": LABEL_HORIZON_BARS,
                "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION,
                "validation_policy_version": VALIDATION_POLICY_VERSION, **identity,
            }, artifact)
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            metrics = evaluation.metrics
            gate_evidence = development_gate_evidence(
                settings, evaluation, acceptance_auc=acceptance_auc,
            )
            baseline_outperformed = gate_evidence.gates["baseline_outperformance"]
            passed = gate_evidence.passed
            model_id, evaluation_id = str(uuid.uuid4()), str(uuid.uuid4())
            try:
                cursor.execute(
                    """INSERT app.model_versions
                       (model_version_id,strategy_version_id,market_id,model_name,version,artifact_path,
                        artifact_sha256,validation_auc,training_rows,status)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (model_id, str(strategy_version_id), str(market_id), f"{symbol} HGB", version,
                     str(artifact.resolve()), digest, evaluation.auc, evaluation.training_rows,
                     "CANDIDATE" if passed else "REJECTED"),
                )
                cursor.execute(
                    """INSERT app.model_evaluations
                       (model_evaluation_id,model_version_id,training_rows,validation_rows,
                        training_start_utc,training_end_utc,validation_start_utc,validation_end_utc,
                        validation_auc,acceptance_auc,result,walk_forward_windows,trade_count,win_rate,
                        profit_factor,expectancy,max_drawdown,sharpe_ratio,sortino_ratio,precision_buy,
                        precision_sell,baseline_outperformed,cost_assumption_bps,failure_reason,
                        brier_score,calibration_error,feature_drift_score,regime_coverage)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (evaluation_id, model_id, evaluation.training_rows, evaluation.validation_rows,
                     evaluation.training_start, evaluation.training_end, evaluation.validation_start,
                     evaluation.validation_end, evaluation.auc, acceptance_auc,
                     "PASSED" if passed else "REJECTED", len(evaluation.windows), metrics["trade_count"],
                     metrics["win_rate"], metrics["profit_factor"], metrics["expectancy"],
                     metrics["max_drawdown"], metrics["sharpe_ratio"], metrics["sortino_ratio"],
                     metrics["precision_buy"], metrics["precision_sell"], baseline_outperformed,
                     settings.model_round_trip_cost_bps, None if passed else "ENHANCED_VALIDATION_GATE_FAILED",
                     evaluation.brier_score, evaluation.calibration_error,
                     evaluation.feature_drift_score, evaluation.regime_coverage),
                )
                for window in evaluation.windows:
                    cursor.execute(
                        """INSERT app.model_walk_forward_windows
                           (walk_forward_window_id,model_evaluation_id,window_number,training_start_utc,
                            training_end_utc,validation_start_utc,validation_end_utc,training_rows,
                            validation_rows,auc,trade_count,win_rate,profit_factor,expectancy,max_drawdown,
                            sharpe_ratio,sortino_ratio,precision_buy,precision_sell)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (str(uuid.uuid4()), evaluation_id, window["window_number"], window["training_start"],
                         window["training_end"], window["validation_start"], window["validation_end"],
                         window["training_rows"], window["validation_rows"], window["auc"],
                         window["trade_count"], window["win_rate"], window["profit_factor"],
                         window["expectancy"], window["max_drawdown"], window["sharpe_ratio"],
                         window["sortino_ratio"], window["precision_buy"], window["precision_sell"]),
                    )
                for baseline in evaluation.baselines:
                    cursor.execute(
                        """INSERT app.model_baseline_results
                           (baseline_result_id,model_evaluation_id,baseline_name,trade_count,win_rate,
                            profit_factor,expectancy,max_drawdown) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (str(uuid.uuid4()), evaluation_id, baseline["name"], baseline["trade_count"],
                         baseline["win_rate"], baseline["profit_factor"], baseline["expectancy"],
                         baseline["max_drawdown"]),
                    )
                for regime in evaluation.regimes:
                    cursor.execute(
                        """INSERT app.model_regime_results
                           (model_regime_result_id,model_evaluation_id,regime_name,observation_count,
                            trade_count,win_rate,expectancy) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                        (str(uuid.uuid4()), evaluation_id, regime["name"], regime["observation_count"],
                         regime["trade_count"], regime["win_rate"], regime["expectancy"]),
                    )
                if retrain_type == "RESEARCH_RETRAIN":
                    cursor.execute("SELECT TOP (1) tenant_id FROM app.engine_controls ORDER BY tenant_id")
                    tenant = cursor.fetchone()
                    cursor.execute(
                        """SELECT TOP (1) version FROM app.cost_model_versions
                           WHERE market_id=%s ORDER BY created_at_utc DESC""", (str(market_id),),
                    )
                    cost_version = cursor.fetchone()
                    experiment_config = {
                        "material_change": material_change, "minimum_rows": minimum_rows,
                        "acceptance_auc": acceptance_auc, "walk_forward_windows": settings.model_walk_forward_windows,
                        "cost_bps": settings.model_round_trip_cost_bps,
                    }
                    config_hash = hashlib.sha256(json.dumps(experiment_config, sort_keys=True).encode()).hexdigest()
                    cursor.execute(
                        """INSERT app.research_experiments
                             (experiment_id,tenant_id,market_id,strategy_version,feature_version,
                              label_version,model_version,regime_version,cost_model_version,retrain_type,
                              training_start_utc,training_end_utc,validation_start_utc,validation_end_utc,
                              configuration_hash,status,notes,outcome_json,completed_at_utc)
                           VALUES(%s,%s,%s,'1.0','FEATURES_V1',%s,%s,%s,%s,'RESEARCH_RETRAIN',
                                  %s,%s,%s,%s,%s,%s,%s,%s,SYSUTCDATETIME())""",
                        (str(uuid.uuid4()), str(tenant[0]), str(market_id), LABEL_VERSION,
                         version, REGIME_VERSION, str(cost_version[0]) if cost_version else "CONFIGURED_BPS_FALLBACK",
                         evaluation.training_start, evaluation.training_end, evaluation.validation_start,
                         evaluation.validation_end, config_hash, "COMPLETED" if passed else "REJECTED",
                         material_change, json.dumps({"auc": evaluation.auc, "development_passed": passed,
                                                     "validation_policy_version": VALIDATION_POLICY_VERSION,
                                                     "gates": gate_evidence.gates,
                                                     "source_identity": identity,
                                                     "metrics": metrics}, default=str)),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                artifact.unlink(missing_ok=True)
                raise
            outcomes.append({"symbol": symbol, "result": "DEVELOPMENT_PASSED" if passed else "REJECTED",
                             "auc": round(evaluation.auc, 6), "training_rows": evaluation.training_rows,
                             "validation_rows": evaluation.validation_rows, "version": version,
                             "trade_count": metrics["trade_count"], "expectancy": metrics["expectancy"],
                             "profit_factor": metrics["profit_factor"], "walk_forward_windows": len(evaluation.windows),
                             "baseline_outperformed": baseline_outperformed,
                             "validation_policy_version": VALIDATION_POLICY_VERSION,
                             "holdout_required": passed, "owner_approval_required": passed})
    return outcomes
