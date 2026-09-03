from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

# Avoid Windows physical-core probing noise and keep research CPU-bounded before
# importing any sklearn-compatible native model library.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier
from catboost import CatBoostClassifier
from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.database import open_database
from app.instrument_registry import normalized_symbol
from app.model_pipeline import Evaluation, _market_frame, chronological_evaluate
from app.model_governance import (
    LABEL_HORIZON_BARS,
    LABEL_DEFINITION_HASH,
    LABEL_VERSION,
    VALIDATION_POLICY_VERSION,
    development_gate_evidence,
    purge_rows_for_horizon,
    source_identity,
)
from app.research_regimes import REGIME_VERSION
from app.research_protocol import (
    DisagreementAwareEnsemble,
    PROTOCOL_VERSION,
    TARGET_CATALOG,
    selective_walk_forward_evaluate,
)

TOURNAMENT_VERSION = "MODEL_TOURNAMENT_V3_OPEN_SOURCE_STRICT"
FEATURE_VERSION = "FEATURES_V1"


class ModelTournamentRequest(BaseModel):
    market: str = Field(default="USDJPY", max_length=20)
    notes: str = Field(default="Audited challenger comparison; no holdout or execution", max_length=1000)

    @field_validator("market")
    @classmethod
    def supported_market(cls, value: str) -> str:
        try:
            normalized = normalized_symbol(value)
        except ValueError as exc:
            raise ValueError("Unsupported tournament market")
        return normalized


@dataclass(frozen=True)
class Challenger:
    key: str
    name: str
    complexity: int
    factory: Callable[[], object]
    configuration: dict[str, object]


def challengers(max_threads: int = 2) -> tuple[Challenger, ...]:
    """Return deterministic, locally supported challengers from least to most complex."""
    return (
        Challenger(
            "LOGISTIC_REGRESSION", "Logistic regression", 1,
            lambda: make_pipeline(
                StandardScaler(),
                LogisticRegression(C=0.25, class_weight="balanced", max_iter=1000, random_state=42),
            ), {"C": 0.25, "class_weight": "balanced", "scaled": True},
        ),
        Challenger(
            "RANDOM_FOREST", "Random forest", 2,
            lambda: RandomForestClassifier(
                n_estimators=240, max_depth=6, min_samples_leaf=20,
                max_features="sqrt", class_weight="balanced_subsample",
                random_state=42, n_jobs=1,
            ), {"trees": 240, "max_depth": 6, "min_samples_leaf": 20},
        ),
        Challenger(
            "AUREX_HIST_GRADIENT_BOOSTING", "Aurex histogram gradient boosting", 3,
            lambda: HistGradientBoostingClassifier(
                max_depth=3, learning_rate=0.05, max_iter=200,
                l2_regularization=1, random_state=42,
            ), {"max_depth": 3, "learning_rate": 0.05, "iterations": 200, "l2": 1},
        ),
        Challenger(
            "LIGHTGBM", "LightGBM", 4,
            lambda: LGBMClassifier(
                objective="binary", n_estimators=250, learning_rate=0.04,
                num_leaves=15, max_depth=5, min_child_samples=30,
                subsample=0.80, subsample_freq=1, colsample_bytree=0.80,
                reg_alpha=0.10, reg_lambda=1.0, random_state=42,
                n_jobs=max_threads, verbosity=-1, deterministic=True, force_col_wise=True,
            ),
            {"n_estimators": 250, "learning_rate": 0.04, "num_leaves": 15,
             "max_depth": 5, "subsample": 0.8, "colsample_bytree": 0.8,
             "reg_alpha": 0.1, "reg_lambda": 1.0, "threads": max_threads},
        ),
        Challenger(
            "XGBOOST", "XGBoost", 5,
            lambda: XGBClassifier(
                objective="binary:logistic", n_estimators=250, learning_rate=0.04,
                max_depth=4, min_child_weight=10, subsample=0.80,
                colsample_bytree=0.80, reg_alpha=0.10, reg_lambda=1.0,
                random_state=42, n_jobs=max_threads, tree_method="hist",
                eval_metric="logloss", verbosity=0,
            ),
            {"n_estimators": 250, "learning_rate": 0.04, "max_depth": 4,
             "min_child_weight": 10, "subsample": 0.8, "colsample_bytree": 0.8,
             "reg_alpha": 0.1, "reg_lambda": 1.0, "threads": max_threads},
        ),
        Challenger(
            "CATBOOST", "CatBoost", 6,
            lambda: CatBoostClassifier(
                loss_function="Logloss", iterations=250, learning_rate=0.04,
                depth=5, l2_leaf_reg=3.0, random_seed=42, verbose=False,
                thread_count=max_threads, allow_writing_files=False,
            ),
            {"iterations": 250, "learning_rate": 0.04, "depth": 5,
             "l2_leaf_reg": 3.0, "threads": max_threads},
        ),
    )


def selective_challengers(max_threads: int = 2) -> tuple[Challenger, ...]:
    binary = challengers(max_threads)
    replacements = {
        "LIGHTGBM": Challenger(
            "LIGHTGBM", "LightGBM", 4,
            lambda: LGBMClassifier(
                objective="multiclass", num_class=3, n_estimators=250, learning_rate=0.04,
                num_leaves=15, max_depth=5, min_child_samples=30, subsample=0.80,
                subsample_freq=1, colsample_bytree=0.80, reg_alpha=0.10, reg_lambda=1.0,
                random_state=42, n_jobs=max_threads, verbosity=-1, deterministic=True,
                force_col_wise=True),
            {"objective": "multiclass", "num_class": 3, "n_estimators": 250,
             "learning_rate": 0.04, "max_depth": 5, "threads": max_threads}),
        "XGBOOST": Challenger(
            "XGBOOST", "XGBoost", 5,
            lambda: XGBClassifier(
                objective="multi:softprob", num_class=3, n_estimators=250, learning_rate=0.04,
                max_depth=4, min_child_weight=10, subsample=0.80, colsample_bytree=0.80,
                reg_alpha=0.10, reg_lambda=1.0, random_state=42, n_jobs=max_threads,
                tree_method="hist", eval_metric="mlogloss", verbosity=0),
            {"objective": "multi:softprob", "num_class": 3, "n_estimators": 250,
             "learning_rate": 0.04, "max_depth": 4, "threads": max_threads}),
        "CATBOOST": Challenger(
            "CATBOOST", "CatBoost", 6,
            lambda: CatBoostClassifier(
                loss_function="MultiClass", iterations=250, learning_rate=0.04, depth=5,
                l2_leaf_reg=3.0, random_seed=42, verbose=False, thread_count=max_threads,
                allow_writing_files=False),
            {"loss_function": "MultiClass", "iterations": 250, "learning_rate": 0.04,
             "depth": 5, "threads": max_threads}),
    }
    base = tuple(replacements.get(item.key, item) for item in binary)
    lookup = {item.key: item for item in base}
    ensemble = Challenger(
        "CALIBRATED_DISAGREEMENT_ENSEMBLE", "Calibrated disagreement ensemble", 7,
        lambda: DisagreementAwareEnsemble((
            lookup["LOGISTIC_REGRESSION"].factory(),
            lookup["AUREX_HIST_GRADIENT_BOOSTING"].factory(),
            lookup["LIGHTGBM"].factory(),
        )),
        {"members": ["LOGISTIC_REGRESSION", "AUREX_HIST_GRADIENT_BOOSTING", "LIGHTGBM"],
         "vote": "SOFT_AVERAGE", "disagreement_action": "HOLD"},
    )
    return (*base, ensemble)


def run_selective_tournament(
    frame, symbol: str, settings: Settings, *,
    candidate_set: tuple[Challenger, ...] | None = None,
    target_set: tuple[object, ...] | None = None,
) -> dict[str, object]:
    """Compare market-specific ternary targets and challengers on development only."""
    market = symbol.upper()
    if market not in TARGET_CATALOG:
        raise ValueError("Unsupported selective tournament market")
    candidates = candidate_set or selective_challengers(settings.max_research_cpu_threads)
    targets = target_set or TARGET_CATALOG[market]
    outcomes = []
    for specification in targets:
        for challenger in candidates:
            result = selective_walk_forward_evaluate(
                frame, specification, estimator_factory=challenger.factory,
                minimum_rows=settings.model_minimum_rows,
                configured_cost_bps=settings.model_round_trip_cost_bps,
                walk_forward_windows=settings.model_walk_forward_windows,
            )
            result.pop("_model", None)
            outcomes.append({
                "candidate": challenger.key, "candidate_name": challenger.name,
                "complexity": challenger.complexity, "configuration": challenger.configuration,
                **result,
            })
    ranked = sorted(outcomes, key=lambda item: (
        bool(item["eligible_to_freeze"]),
        float(item["bootstrap_expectancy"]["lower_95"]),
        float(item["metrics"]["expectancy"] or 0),
        float(item["metrics"]["profit_factor"] or 0),
        -int(item["complexity"]),
    ), reverse=True)
    return {
        "tournament_version": "SELECTIVE_MARKET_TOURNAMENT_V1",
        "market": market, "selection_scope": "DEVELOPMENT_ONLY",
        "research_leader": ranked[0]["candidate"],
        "leader_target_sha256": ranked[0]["target_specification"]["sha256"],
        "leader_passed_all_development_gates": bool(ranked[0]["eligible_to_freeze"]),
        "candidates": ranked, "holdout_consumed": False,
        "promotable": False, "execution_enabled": False,
    }


def run_and_record_selective_tournament(
    settings: Settings, tenant_id: str, symbol: str, *, notes: str | None = None,
) -> dict[str, object]:
    """Run the target-bound V4 tournament on reserved development data only."""
    market_symbol = symbol.upper()
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.market_id,sv.version,sv.features_version
               FROM app.markets m CROSS JOIN app.strategy_versions sv
               JOIN app.strategies s ON s.strategy_id=sv.strategy_id
               WHERE m.symbol=%s AND m.enabled=1 AND s.strategy_name='Conservative FX Demo'
                 AND sv.version='1.0'""", (market_symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError("Enabled market and strategy version are required")
        market_id = str(market["market_id"])
        cursor.execute(
            """SELECT TOP (1) l.research_lineage_id,l.development_start_utc,l.development_end_utc,
                      l.holdout_start_utc,l.research_target_spec_id,l.research_protocol_version,
                      l.model_families_json,
                      s.target_sha256,s.configuration_json,s.target_version,s.horizon_bars
               FROM app.research_lineages l
               JOIN app.research_target_specs s
                 ON s.research_target_spec_id=l.research_target_spec_id
               WHERE l.tenant_id=%s AND l.market_id=%s AND l.status='RESERVED'
               ORDER BY l.created_at_utc DESC""", (tenant_id, market_id),
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise ValueError("Reserve a target-bound immutable lineage before running the selective tournament")
        if str(lineage["research_protocol_version"] or "") != PROTOCOL_VERSION:
            raise ValueError("Reserved lineage does not use the current selective research protocol")
        target = next((
            item for item in TARGET_CATALOG[market_symbol]
            if item.digest == str(lineage["target_sha256"])
        ), None)
        if target is None:
            raise ValueError("Reserved target checksum does not match the immutable target catalog")
        cursor.execute(
            """SELECT TOP (1) passed,dataset_sha256,evaluated_at_utc
               FROM app.dataset_boundary_audits
               WHERE tenant_id=%s AND market_id=%s AND research_target_spec_id=%s
                 AND research_lineage_id=%s
               ORDER BY evaluated_at_utc DESC""",
            (tenant_id, market_id, str(lineage["research_target_spec_id"]),
             str(lineage["research_lineage_id"])),
        )
        audit = cursor.fetchone()
        if not audit or not bool(audit["passed"]):
            raise ValueError("A passing leakage and chronological-boundary audit is required")
        cursor.execute(
            """SELECT TOP (1) version FROM app.cost_model_versions
               WHERE market_id=%s AND status='CURRENT' ORDER BY created_at_utc DESC""",
            (market_id,),
        )
        cost = cursor.fetchone()
        frame = _market_frame(cursor, market_id)
    if not cost:
        raise ValueError("A current empirical cost model is required for a selective tournament")
    development_start = pd.Timestamp(lineage["development_start_utc"])
    development_end = pd.Timestamp(lineage["development_end_utc"])
    development_start = development_start.tz_localize("UTC") if development_start.tzinfo is None else development_start.tz_convert("UTC")
    development_end = development_end.tz_localize("UTC") if development_end.tzinfo is None else development_end.tz_convert("UTC")
    frame = frame.loc[(frame.index >= development_start) & (frame.index <= development_end)].copy()
    holdout_start = pd.Timestamp(lineage["holdout_start_utc"])
    holdout_start = holdout_start.tz_localize("UTC") if holdout_start.tzinfo is None else holdout_start.tz_convert("UTC")
    if frame.empty or frame.index.max() >= holdout_start:
        raise ValueError("Reserved development boundary is invalid or reaches the holdout")

    requested_families = set(json.loads(str(lineage["model_families_json"])))
    candidate_set = tuple(
        item for item in selective_challengers(settings.max_research_cpu_threads)
        if item.key in requested_families
    )
    if not candidate_set:
        raise ValueError("Reserved lineage contains no supported selective challenger")
    outcome = run_selective_tournament(
        frame, market_symbol, settings, candidate_set=candidate_set, target_set=(target,),
    )
    identity = source_identity()
    configuration = {
        "tournament_version": outcome["tournament_version"],
        "research_protocol_version": PROTOCOL_VERSION,
        "research_lineage_id": str(lineage["research_lineage_id"]),
        "research_target_spec_id": str(lineage["research_target_spec_id"]),
        "target_sha256": target.digest,
        "target": target.configuration(),
        "candidate_keys": [item.key for item in candidate_set],
        "minimum_rows": settings.model_minimum_rows,
        "walk_forward_windows": settings.model_walk_forward_windows,
        "configured_cost_bps": settings.model_round_trip_cost_bps,
        "reserved_holdout_excluded": True,
        "development_start_utc": frame.index.min().isoformat(),
        "development_end_utc": frame.index.max().isoformat(),
        "development_rows": len(frame),
        "boundary_audit_dataset_sha256": str(audit["dataset_sha256"]),
    }
    configuration_hash = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode(),
    ).hexdigest()
    experiment_id = str(uuid4())
    candidates = outcome["candidates"]
    validation_start = candidates[0]["windows"][0]["validation_start"]
    validation_end = candidates[0]["windows"][-1]["validation_end"]
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT app.research_experiments
                 (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                  model_version,regime_version,cost_model_version,retrain_type,training_start_utc,
                  training_end_utc,validation_start_utc,validation_end_utc,configuration_hash,status,
                  notes,outcome_json,completed_at_utc,research_lineage_id,validation_policy_version,
                  label_horizon_bars,label_horizon_minutes,label_definition_hash,code_commit,dirty_worktree,
                  research_target_spec_id,research_protocol_version)
               VALUES(%s,%s,%s,%s,%s,%s,NULL,%s,%s,'MODEL_TOURNAMENT',%s,%s,%s,%s,%s,
                      'COMPLETED',%s,%s,SYSUTCDATETIME(),%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (experiment_id, tenant_id, market_id, str(market["version"]),
             str(market["features_version"] or FEATURE_VERSION), target.version,
             REGIME_VERSION, str(cost["version"]), frame.index.min().to_pydatetime(),
             frame.index.max().to_pydatetime(), validation_start, validation_end,
             configuration_hash, notes or "Target-bound selective development tournament",
             json.dumps({**outcome, "configuration": configuration,
                         "source_identity": identity}, default=str),
             str(lineage["research_lineage_id"]), VALIDATION_POLICY_VERSION,
             target.horizon_bars, target.horizon_bars * 15, target.digest,
             str(identity["source_identity"]), int(bool(identity["dirty_worktree"])),
             str(lineage["research_target_spec_id"]), PROTOCOL_VERSION),
        )
        connection.commit()
    return {"experiment_id": experiment_id, **outcome}


def _feature_importance(model: object) -> list[dict[str, float | str]]:
    values = None
    if hasattr(model, "feature_importances_"):
        values = getattr(model, "feature_importances_")
    elif hasattr(model, "named_steps"):
        final = list(getattr(model, "named_steps").values())[-1]
        if hasattr(final, "coef_"):
            values = abs(final.coef_[0])
    if values is None:
        return []
    numeric = [abs(float(value)) for value in values]
    total = sum(numeric) or 1.0
    from app.model_pipeline import FEATURES
    return sorted(
        ({"feature": feature, "importance": value / total}
         for feature, value in zip(FEATURES, numeric)),
        key=lambda item: float(item["importance"]), reverse=True,
    )


def _candidate_evidence(
    challenger: Challenger, evaluation: Evaluation, settings: Settings,
    *, acceptance_auc: float,
) -> dict[str, object]:
    metrics = evaluation.metrics
    policy = development_gate_evidence(settings, evaluation, acceptance_auc=acceptance_auc)
    stability = policy.positive_window_fraction
    gates = policy.gates
    return {
        "key": challenger.key,
        "name": challenger.name,
        "complexity": challenger.complexity,
        "configuration": challenger.configuration,
        "eligible_for_freeze_research": all(gates.values()),
        "auc": evaluation.auc,
        "pr_auc": evaluation.pr_auc,
        "log_loss": evaluation.log_loss,
        "brier_score": evaluation.brier_score,
        "calibration_error": evaluation.calibration_error,
        "feature_drift_score": evaluation.feature_drift_score,
        "regime_coverage": evaluation.regime_coverage,
        "positive_window_fraction": stability,
        "worst_window_expectancy": min(float(item["expectancy"] or 0) for item in evaluation.windows),
        "metrics": metrics,
        "windows": evaluation.windows,
        "baselines": evaluation.baselines,
        "regimes": evaluation.regimes,
        "calibration_buckets": evaluation.calibration_buckets,
        "selective_thresholds": evaluation.selective_thresholds,
        "feature_importance": _feature_importance(evaluation.model),
        "gates": gates,
    }


def run_tournament(
    frame, settings: Settings, *, minimum_rows: int | None = None,
    acceptance_auc: float = 0.52,
) -> dict[str, object]:
    """Compare challengers on identical purged expanding windows.

    This function performs development research only. It never reads a reserved
    holdout, writes a model artifact, changes model status, or enables execution.
    """
    evidence_floor = minimum_rows or settings.model_minimum_rows
    if evidence_floor < settings.model_minimum_rows:
        raise ValueError("Tournament cannot lower the configured evidence floor")
    results = []
    for challenger in challengers(settings.max_research_cpu_threads):
        evaluation = chronological_evaluate(
            frame, minimum_rows=evidence_floor,
            walk_forward_windows=settings.model_walk_forward_windows,
            round_trip_cost_bps=settings.model_round_trip_cost_bps,
            purge_gap_rows=purge_rows_for_horizon(LABEL_HORIZON_BARS),
            estimator_factory=challenger.factory,
        )
        results.append(_candidate_evidence(challenger, evaluation, settings, acceptance_auc=acceptance_auc))

    # Selection is made only on development windows. Prefer a fully gated model;
    # ties favour stable net evidence and then the simpler model.
    ranked = sorted(
        results,
        key=lambda item: (
            bool(item["eligible_for_freeze_research"]),
            float(item["positive_window_fraction"]),
            float(item["metrics"]["expectancy"] or 0),
            float(item["metrics"]["profit_factor"] or 0),
            float(item["auc"]),
            -int(item["complexity"]),
        ),
        reverse=True,
    )
    leader = ranked[0]
    selective = []
    for candidate in results:
        for threshold in candidate["selective_thresholds"]:
            selective.append({"candidate": candidate["key"], **threshold})
    selective.sort(key=lambda item: (
        float(item["positive_window_fraction"]), float(item["expectancy"] or 0),
        float(item["profit_factor"] or 0), -float(item["max_drawdown"] or 0),
    ), reverse=True)
    return {
        "tournament_version": TOURNAMENT_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_scope": "DEVELOPMENT_ONLY",
        "selection_policy": "all gates, stability, expectancy, profit factor, AUC, simpler model",
        "purge_gap_rows": purge_rows_for_horizon(LABEL_HORIZON_BARS),
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "buy_threshold": 0.70,
        "sell_threshold": 0.30,
        "research_leader": leader["key"],
        "selective_research_leader": {
            "candidate": selective[0]["candidate"], "upper": selective[0]["upper"],
            "lower": selective[0]["lower"], "metrics": {
                key: selective[0][key] for key in (
                    "trade_count", "profit_factor", "expectancy", "max_drawdown",
                    "positive_window_fraction", "worst_window_expectancy",
                )
            },
        },
        "leader_passed_all_development_gates": leader["eligible_for_freeze_research"],
        "candidates": ranked,
        "deferred_challengers": {
            "Qlib": "research adapter only; not an execution authority",
            "foundation_models": "defer until versioned forecasts can be captured without holdout leakage",
            "reinforcement_learning": "excluded because simulator exploitation risk is not yet controlled",
        },
        "promotable": False,
        "holdout_consumed": False,
        "execution_enabled": False,
    }


def run_and_record_tournament(
    settings: Settings, tenant_id: str, symbol: str, *, notes: str | None = None,
) -> dict[str, object]:
    market_symbol = symbol.upper()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT m.market_id,sv.version,sv.features_version
               FROM app.markets m CROSS JOIN app.strategy_versions sv
               JOIN app.strategies s ON s.strategy_id=sv.strategy_id
               WHERE m.symbol=%s AND m.enabled=1 AND s.strategy_name='Conservative FX Demo'
                 AND sv.version='1.0'""", (market_symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError("Enabled market and strategy version are required")
        market_id, strategy_version, feature_version = market
        frame = _market_frame(cursor, str(market_id))
        cursor.execute(
            """SELECT TOP (1) research_lineage_id,development_start_utc,development_end_utc,
                      holdout_start_utc
               FROM app.research_lineages
               WHERE tenant_id=%s AND market_id=%s AND status='RESERVED'
               ORDER BY created_at_utc DESC""", (tenant_id, str(market_id)),
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise ValueError("Reserve an immutable research lineage before running a tournament")
        lineage_id, development_start, development_end, holdout_start = lineage
        frame = frame.loc[
            (frame.index >= development_start.replace(tzinfo=timezone.utc)) &
            (frame.index <= development_end.replace(tzinfo=timezone.utc))
        ].copy()
        cursor.execute(
            """SELECT TOP (1) version FROM app.cost_model_versions
               WHERE market_id=%s AND status='CURRENT' ORDER BY created_at_utc DESC""",
            (str(market_id),),
        )
        cost = cursor.fetchone()
    if not cost:
        raise ValueError("A current empirical cost model is required for a tournament")

    outcome = run_tournament(frame, settings)
    configuration = {
        "tournament_version": TOURNAMENT_VERSION,
        "symbol": market_symbol,
        "candidate_keys": [item.key for item in challengers(settings.max_research_cpu_threads)],
        "candidate_configurations": {
            item.key: item.configuration for item in challengers(settings.max_research_cpu_threads)
        },
        "development_gates": {
            "acceptance_auc": settings.model_acceptance_auc,
            "minimum_trades": settings.model_minimum_trades,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown_pct": min(
                settings.model_max_drawdown_pct, settings.holdout_maximum_drawdown_pct,
            ),
            "maximum_calibration_error": 0.20,
            "maximum_feature_drift": 1.0,
            "minimum_regime_coverage": 0.50,
            "minimum_positive_window_fraction": 2 / 3,
        },
        "minimum_rows": settings.model_minimum_rows,
        "walk_forward_windows": settings.model_walk_forward_windows,
        "round_trip_cost_bps": settings.model_round_trip_cost_bps,
        "purge_gap_rows": purge_rows_for_horizon(LABEL_HORIZON_BARS),
        "label_horizon_bars": LABEL_HORIZON_BARS,
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "thresholds": [0.30, 0.70],
        "selective_threshold_grid": [[0.45, 0.55], [0.40, 0.60], [0.35, 0.65], [0.30, 0.70]],
        "max_research_cpu_threads": settings.max_research_cpu_threads,
        "source_start": frame.index.min().isoformat(),
        "source_end": frame.index.max().isoformat(),
        "source_rows": len(frame),
        "reserved_holdout_excluded": True,
        "research_lineage_id": str(lineage_id),
    }
    configuration_hash = hashlib.sha256(
        json.dumps(configuration, sort_keys=True).encode(),
    ).hexdigest()
    experiment_id = str(uuid4())
    identity = source_identity()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT app.research_experiments
                 (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                  model_version,regime_version,cost_model_version,retrain_type,training_start_utc,
                  training_end_utc,validation_start_utc,validation_end_utc,configuration_hash,status,
                  notes,outcome_json,completed_at_utc,research_lineage_id,validation_policy_version,
                  label_horizon_bars,label_horizon_minutes,label_definition_hash,code_commit,dirty_worktree)
               VALUES(%s,%s,%s,%s,%s,%s,NULL,%s,%s,'MODEL_TOURNAMENT',%s,%s,%s,%s,%s,
                      'COMPLETED',%s,%s,SYSUTCDATETIME(),%s,%s,%s,%s,%s,%s,%s)""",
            (experiment_id, tenant_id, str(market_id), str(strategy_version),
             str(feature_version or FEATURE_VERSION), LABEL_VERSION,
             REGIME_VERSION, str(cost[0]),
             frame.index.min().to_pydatetime(), frame.index.max().to_pydatetime(),
             outcome["candidates"][0]["windows"][0]["validation_start"],
             outcome["candidates"][0]["windows"][-1]["validation_end"],
             configuration_hash, notes or "Audited development-only model tournament",
             json.dumps({**outcome, "source_identity": identity}, default=str),
             str(lineage_id), VALIDATION_POLICY_VERSION, LABEL_HORIZON_BARS,
             LABEL_HORIZON_BARS * 15, LABEL_DEFINITION_HASH,
             str(identity["source_identity"]), int(bool(identity["dirty_worktree"]))),
        )
        connection.commit()
    return {"experiment_id": experiment_id, "market": market_symbol, **outcome}
