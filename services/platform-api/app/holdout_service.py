from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from app.config import Settings
from app.database import open_database
from app.model_pipeline import (
    FEATURES,
    MODEL_ROOT,
    _baseline_results,
    _calibration_error,
    _feature_drift,
    _market_frame,
    _regime_results,
    _safe_auc,
    add_features,
    chronological_evaluate,
    trading_metrics,
)
from app.research_regimes import REGIME_VERSION
from app.model_governance import (
    HOLDOUT_POLICY_VERSION,
    LABEL_DEFINITION_HASH,
    LABEL_HORIZON_BARS,
    LABEL_HORIZON_MINUTES,
    LABEL_VERSION,
    VALIDATION_POLICY_VERSION,
    development_gate_evidence,
    purge_rows_for_horizon,
    source_identity,
)
from app.research_protocol_store import insert_lifecycle_event
from app.research_protocol import (
    PROTOCOL_VERSION,
    TARGET_CATALOG,
    TargetSpecification,
    _multiclass_calibration_error,
    apply_ensemble_disagreement,
    block_bootstrap_expectancy,
    build_selective_target,
    cost_stress_evidence,
    fit_selective_development_model,
    leakage_boundary_audit,
    regime_slices,
    selective_directions_from_edges,
)


FEATURE_VERSION_FALLBACK = "FEATURES_V1"
HORIZON = LABEL_HORIZON_BARS
SELECTIVE_MODEL_FAMILIES = {
    "LOGISTIC_REGRESSION", "RANDOM_FOREST", "AUREX_HIST_GRADIENT_BOOSTING",
    "LIGHTGBM", "XGBOOST", "CATBOOST", "CALIBRATED_DISAGREEMENT_ENSEMBLE",
}


class FreezeCandidateRequest(BaseModel):
    market: str = Field(default="GERMANY40", pattern="^(EURUSD|GBPUSD|USDJPY|GERMANY40)$")
    holdout_fraction: float | None = Field(default=None, ge=0.10, le=0.30)
    notes: str = Field(default="Frozen candidate for single-use final holdout", max_length=1000)


class EvaluateHoldoutRequest(BaseModel):
    candidate_id: str
    acknowledgement: str = Field(
        default="CONSUME HOLDOUT ONCE",
        pattern="^CONSUME HOLDOUT ONCE$",
    )


class ApproveHoldoutRequest(BaseModel):
    candidate_id: str
    acknowledgement: str = Field(
        pattern="^I APPROVE THIS EXACT HOLDOUT-PASSED ARTIFACT FOR FORWARD SHADOW ONLY$",
    )


class ReserveResearchLineageRequest(BaseModel):
    market: str = Field(pattern="^(EURUSD|GBPUSD|USDJPY|GERMANY40)$")
    hypothesis: str = Field(min_length=20, max_length=1000)
    chosen_features: list[str] = Field(default_factory=lambda: list(FEATURES))
    model_families: list[str] = Field(default_factory=lambda: sorted(SELECTIVE_MODEL_FAMILIES))
    target_mode: str = Field(pattern="^(COST_AWARE_RETURN|VOLATILITY_ADJUSTED)$")
    target_horizon_bars: int = Field(ge=1, le=96)
    holdout_fraction: float | None = Field(default=None, ge=0.10, le=0.30)


def _serial(value: object) -> object:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _frame_digest(frame: pd.DataFrame) -> str:
    columns = ["open", "high", "low", "close", "tick_volume", "observed_spread_bps"]
    if "provider" in frame.columns:
        columns.append("provider")
    canonical = frame[columns].copy().sort_index()
    canonical.index = canonical.index.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return hashlib.sha256(canonical.to_csv(index=True, float_format="%.12g").encode()).hexdigest()


def select_holdout_split(
    frame: pd.DataFrame, *, fraction: float, minimum_holdout_rows: int, minimum_development_rows: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        raise ValueError("No market data is available")
    holdout_count = max(minimum_holdout_rows, int(math.ceil(len(frame) * fraction)))
    if len(frame) - holdout_count < minimum_development_rows + 60:
        raise ValueError("Insufficient pre-holdout development data")
    holdout_start = frame.index[-holdout_count]
    development = frame.loc[frame.index < holdout_start].copy()
    holdout = frame.loc[frame.index >= holdout_start].copy()
    if development.index.max() >= holdout.index.min():
        raise ValueError("Holdout split is not chronological")
    return development, holdout


def evidence_gates(
    settings: Settings, *, auc: float, metrics: dict[str, object], calibration_error: float,
    feature_drift_score: float, regime_coverage: float, baseline_expectancy: float,
) -> dict[str, bool]:
    return {
        "auc": auc >= settings.model_acceptance_auc,
        "minimum_trades": int(metrics.get("trade_count") or 0) >= settings.holdout_minimum_trades,
        "positive_expectancy": float(metrics.get("expectancy") or 0) > 0,
        "profit_factor": float(metrics.get("profit_factor") or 0) >= settings.holdout_minimum_profit_factor,
        "maximum_drawdown": float(metrics.get("max_drawdown") or 0) <= settings.holdout_maximum_drawdown_pct / 100,
        "baseline_outperformance": float(metrics.get("expectancy") or 0) > baseline_expectancy,
        "calibration": calibration_error <= settings.holdout_maximum_calibration_error,
        "feature_drift": feature_drift_score <= settings.holdout_maximum_feature_drift,
        "regime_coverage": regime_coverage >= settings.holdout_minimum_regime_coverage,
    }


def _effective_costs(frame: pd.DataFrame, fallback_spread: float, configured_bps: float) -> pd.DataFrame:
    prepared = frame.copy()
    observed = prepared.get("observed_spread_bps", pd.Series(np.nan, index=prepared.index))
    empirical = fallback_spread / prepared["close"].astype(float) * 10000.0
    evidence = np.maximum(
        observed.fillna(empirical).clip(lower=0).to_numpy(float), configured_bps,
    )
    prepared["observed_spread_bps"] = evidence
    prepared["effective_cost_bps"] = evidence
    return prepared


def _utc_timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _target_specification(symbol: str, digest: str) -> TargetSpecification:
    specification = next((item for item in TARGET_CATALOG[symbol] if item.digest == digest), None)
    if specification is None:
        raise ValueError("Target checksum does not match the immutable catalog")
    return specification


def _selective_multiclass_auc(
    targets: np.ndarray, probabilities: np.ndarray, model_classes: np.ndarray,
) -> float:
    present = np.unique(targets)
    if len(present) < 2:
        return 0.5
    if not set(int(value) for value in present).issubset(
        set(int(value) for value in model_classes)
    ):
        return 0.5
    columns = [int(np.where(model_classes == value)[0][0]) for value in present]
    selected = probabilities[:, columns]
    if len(present) == 2:
        binary = (targets == present[1]).astype(int)
        return float(roc_auc_score(binary, selected[:, 1]))
    selected = selected / np.maximum(selected.sum(axis=1, keepdims=True), 1e-12)
    return float(roc_auc_score(targets, selected, labels=present,
                               multi_class="ovr", average="weighted"))


def _selective_labelable_count(causal: pd.DataFrame, horizon_bars: int) -> int:
    if causal.empty:
        return 0
    elapsed_minutes = causal.index.to_series().diff().dt.total_seconds().div(60)
    boundaries = elapsed_minutes.ne(15.0)
    if "provider" in causal.columns:
        provider = causal["provider"].astype(str)
        boundaries = boundaries | provider.ne(provider.shift(1))
    return int(sum(max(0, len(group) - horizon_bars)
                   for _, group in causal.groupby(boundaries.cumsum())))


def selective_partition_evidence(
    settings: Settings, development: pd.DataFrame, holdout: pd.DataFrame, *,
    specification: TargetSpecification, fallback_spread: float,
) -> tuple[int, int]:
    """Count usable development and holdout rows without exposing holdout labels."""
    development_features = build_selective_target(
        _effective_costs(
            development, fallback_spread, settings.model_round_trip_cost_bps,
        ),
        specification,
        configured_cost_bps=settings.model_round_trip_cost_bps,
    )
    holdout_causal = add_features(
        _effective_costs(
            holdout, fallback_spread, settings.model_round_trip_cost_bps,
        ),
        labelled=False,
    )
    return len(development_features), _selective_labelable_count(
        holdout_causal, specification.horizon_bars,
    )


def _freeze_selective_candidate(
    settings: Settings, tenant_id: str, request: FreezeCandidateRequest,
) -> dict[str, object]:
    """Freeze only the exact passing leader of a target-bound V4 tournament."""
    symbol = request.market.upper()
    from app.model_tournament import selective_challengers

    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (1) l.*,m.symbol,sv.strategy_version_id,sv.version strategy_version,
                      sv.features_version,s.target_sha256,s.configuration_json
               FROM app.research_lineages l JOIN app.markets m ON m.market_id=l.market_id
               JOIN app.research_target_specs s ON s.research_target_spec_id=l.research_target_spec_id
               CROSS JOIN app.strategy_versions sv JOIN app.strategies st ON st.strategy_id=sv.strategy_id
               WHERE l.tenant_id=%s AND m.symbol=%s AND l.status='RESERVED'
                 AND l.research_protocol_version=%s AND st.strategy_name='Conservative FX Demo'
                 AND sv.version='1.0' ORDER BY l.created_at_utc DESC""",
            (tenant_id, symbol, PROTOCOL_VERSION),
        )
        lineage = cursor.fetchone()
        if not lineage:
            raise ValueError("A reserved Selective V4 lineage is required")
        cursor.execute(
            """SELECT TOP (1) experiment_id,outcome_json,configuration_hash,completed_at_utc
               FROM app.research_experiments WHERE tenant_id=%s AND market_id=%s
                 AND research_lineage_id=%s AND research_target_spec_id=%s
                 AND research_protocol_version=%s AND retrain_type='MODEL_TOURNAMENT'
                 AND status='COMPLETED' ORDER BY completed_at_utc DESC""",
            (tenant_id, str(lineage["market_id"]), str(lineage["research_lineage_id"]),
             str(lineage["research_target_spec_id"]), PROTOCOL_VERSION),
        )
        tournament = cursor.fetchone()
        if not tournament:
            raise ValueError("A completed target-bound selective tournament is required")
        cursor.execute(
            """SELECT TOP (1) c.version,b.p75_spread
               FROM app.cost_model_versions c JOIN app.cost_model_buckets b
                 ON b.cost_model_version_id=c.cost_model_version_id
               WHERE c.market_id=%s AND c.status='CURRENT' AND b.bucket_type='OVERALL'
               ORDER BY c.created_at_utc DESC""", (str(lineage["market_id"]),),
        )
        cost = cursor.fetchone()
        frame = _market_frame(cursor, str(lineage["market_id"]))
    if not cost:
        raise ValueError("A current empirical cost model is required")

    outcome = json.loads(str(tournament["outcome_json"]))
    if not bool(outcome.get("leader_passed_all_development_gates")):
        raise ValueError("The selective tournament leader failed one or more development gates")
    leader_key = str(outcome.get("research_leader") or "")
    target_digest = str(outcome.get("leader_target_sha256") or "")
    if target_digest != str(lineage["target_sha256"]):
        raise ValueError("Tournament leader target does not match the reserved lineage")
    leader = next((item for item in outcome.get("candidates", [])
                   if item.get("candidate") == leader_key
                   and item.get("target_specification", {}).get("sha256") == target_digest), None)
    if not leader or not bool(leader.get("eligible_to_freeze")) or not all(leader.get("gates", {}).values()):
        raise ValueError("Recorded tournament leader is not eligible to freeze")
    challenger = next((item for item in selective_challengers(settings.max_research_cpu_threads)
                       if item.key == leader_key), None)
    if challenger is None:
        raise ValueError("Recorded challenger is unavailable in this source version")
    specification = _target_specification(symbol, target_digest)
    development_raw = frame.loc[
        (frame.index >= _utc_timestamp(lineage["development_start_utc"])) &
        (frame.index <= _utc_timestamp(lineage["development_end_utc"]))
    ].copy()
    holdout_raw = frame.loc[
        (frame.index >= _utc_timestamp(lineage["holdout_start_utc"])) &
        (frame.index <= _utc_timestamp(lineage["holdout_end_utc"]))
    ].copy()
    if development_raw.empty or holdout_raw.empty or development_raw.index.max() >= holdout_raw.index.min():
        raise ValueError("Reserved chronological partitions are invalid")
    fallback_spread = float(cost["p75_spread"])
    development = build_selective_target(
        _effective_costs(development_raw, fallback_spread, settings.model_round_trip_cost_bps),
        specification, configured_cost_bps=settings.model_round_trip_cost_bps,
    )
    holdout_causal = add_features(
        _effective_costs(holdout_raw, fallback_spread, settings.model_round_trip_cost_bps),
        labelled=False,
    )
    expected_holdout_rows = _selective_labelable_count(
        holdout_causal, specification.horizon_bars,
    )
    if len(development) < settings.model_minimum_rows:
        raise ValueError("Feature-complete development evidence is below the configured floor")
    if expected_holdout_rows < settings.holdout_minimum_rows:
        raise ValueError("Untouched feature-complete holdout evidence is below the configured floor")
    audit = leakage_boundary_audit(
        development_raw, development, specification=specification,
        windows=leader.get("windows", []), holdout_start=holdout_raw.index.min().to_pydatetime(),
    )
    if not audit["passed"]:
        raise ValueError("Current development data failed the frozen leakage-boundary audit")
    model, calibration = fit_selective_development_model(
        challenger.factory, development, horizon_bars=specification.horizon_bars,
    )
    fallback_move = max(specification.minimum_edge_bps, float(development["atr_pct"].median()) * 10000)
    edge_parameters = {
        "buy_move_bps": float(calibration["buy_move_bps"] or fallback_move),
        "sell_move_bps": float(calibration["sell_move_bps"] or fallback_move),
    }
    development_digest, holdout_digest = _frame_digest(development_raw), _frame_digest(holdout_raw)
    configuration = {
        "research_protocol_version": PROTOCOL_VERSION,
        "tournament_experiment_id": str(tournament["experiment_id"]),
        "tournament_configuration_hash": str(tournament["configuration_hash"]),
        "research_lineage_id": str(lineage["research_lineage_id"]),
        "research_target_spec_id": str(lineage["research_target_spec_id"]),
        "target": specification.configuration(), "target_sha256": specification.digest,
        "challenger_key": leader_key, "challenger_configuration": challenger.configuration,
        "edge_parameters": edge_parameters, "calibration": calibration,
        "development_data_sha256": development_digest, "holdout_data_sha256": holdout_digest,
        "holdout_labels_inspected_at_freeze": False,
    }
    configuration_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    candidate_id, experiment_id = str(uuid4()), str(uuid4())
    candidate_version = f"v4-{symbol.lower()}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{candidate_id[:6]}"
    artifact_root = MODEL_ROOT / "holdout"
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_root / f"{candidate_version}.joblib"
    joblib.dump({
        "model": model, "features": FEATURES, "horizon": specification.horizon_bars,
        "research_protocol_version": PROTOCOL_VERSION,
        "target_specification": specification.configuration() | {"sha256": specification.digest},
        "challenger_key": leader_key, "edge_parameters": edge_parameters,
        "fallback_spread": fallback_spread, "configuration": configuration,
        "development_data_sha256": development_digest, "holdout_data_sha256": holdout_digest,
    }, artifact_path)
    artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """INSERT app.research_experiments
                     (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                      model_version,regime_version,cost_model_version,retrain_type,training_start_utc,
                      training_end_utc,holdout_start_utc,holdout_end_utc,configuration_hash,status,
                      notes,outcome_json,research_lineage_id,validation_policy_version,label_horizon_bars,
                      label_horizon_minutes,label_definition_hash,research_target_spec_id,research_protocol_version)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'HOLDOUT_CANDIDATE',%s,%s,%s,%s,%s,'REGISTERED',
                          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (experiment_id, tenant_id, str(lineage["market_id"]), str(lineage["strategy_version"]),
                 str(lineage["features_version"] or FEATURE_VERSION_FALLBACK), specification.version,
                 candidate_version, REGIME_VERSION, str(cost["version"]),
                 development.index.min().to_pydatetime(), development.index.max().to_pydatetime(),
                 holdout_raw.index.min().to_pydatetime(), holdout_raw.index.max().to_pydatetime(),
                 configuration_hash, request.notes,
                 json.dumps({"validation": leader, "validation_passed": True,
                             "holdout_consumed": False}, default=_serial),
                 str(lineage["research_lineage_id"]), VALIDATION_POLICY_VERSION,
                 specification.horizon_bars, specification.horizon_bars * 15, specification.digest,
                 str(lineage["research_target_spec_id"]), PROTOCOL_VERSION),
            )
            cursor.execute(
                """INSERT app.holdout_candidates
                     (holdout_candidate_id,experiment_id,tenant_id,market_id,strategy_version_id,
                      candidate_version,feature_version,label_version,regime_version,cost_model_version,
                      artifact_path,artifact_sha256,configuration_hash,development_data_sha256,
                      holdout_data_sha256,development_start_utc,development_end_utc,holdout_start_utc,
                      holdout_end_utc,development_rows,holdout_rows,validation_json,validation_passed,
                      status,notes,research_lineage_id,validation_policy_version,label_horizon_bars,
                      label_definition_hash,research_target_spec_id,research_protocol_version,
                      tournament_experiment_id,challenger_key)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,
                          'FROZEN',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (candidate_id, experiment_id, tenant_id, str(lineage["market_id"]),
                 str(lineage["strategy_version_id"]), candidate_version,
                 str(lineage["features_version"] or FEATURE_VERSION_FALLBACK), specification.version,
                 REGIME_VERSION, str(cost["version"]), str(artifact_path.resolve()), artifact_digest,
                 configuration_hash, development_digest, holdout_digest,
                 development_raw.index.min().to_pydatetime(), development_raw.index.max().to_pydatetime(),
                 holdout_raw.index.min().to_pydatetime(), holdout_raw.index.max().to_pydatetime(),
                 len(development), expected_holdout_rows, json.dumps(leader, default=_serial), request.notes,
                 str(lineage["research_lineage_id"]), VALIDATION_POLICY_VERSION,
                 specification.horizon_bars, specification.digest,
                 str(lineage["research_target_spec_id"]), PROTOCOL_VERSION,
                 str(tournament["experiment_id"]), leader_key),
            )
            cursor.execute(
                "UPDATE app.research_lineages SET status='CANDIDATE_FROZEN' WHERE research_lineage_id=%s AND status='RESERVED'",
                (str(lineage["research_lineage_id"]),),
            )
            if cursor.rowcount != 1:
                raise ValueError("Research lineage changed while freezing the candidate")
            evidence = {"artifact_sha256": artifact_digest, "tournament_experiment_id": str(tournament["experiment_id"]),
                        "target_sha256": specification.digest, "challenger_key": leader_key,
                        "development_gates": leader["gates"], "holdout_consumed": False,
                        "execution_enabled": False}
            insert_lifecycle_event(cursor, tenant_id=tenant_id, market_id=str(lineage["market_id"]),
                research_lineage_id=str(lineage["research_lineage_id"]), holdout_candidate_id=candidate_id,
                from_state="RESEARCH", to_state="ELIGIBLE_TO_FREEZE",
                reason="Exact target-bound tournament leader passed all development gates", evidence=evidence)
            insert_lifecycle_event(cursor, tenant_id=tenant_id, market_id=str(lineage["market_id"]),
                research_lineage_id=str(lineage["research_lineage_id"]), holdout_candidate_id=candidate_id,
                from_state="ELIGIBLE_TO_FREEZE", to_state="FROZEN",
                reason="Calibrated multiclass artifact and partition checksums frozen", evidence=evidence)
            connection.commit()
    except Exception:
        artifact_path.unlink(missing_ok=True)
        raise
    return {"status": "FROZEN", "candidate_id": candidate_id, "candidate_version": candidate_version,
            "market": symbol, "challenger": leader_key, "target_sha256": specification.digest,
            "development_rows": len(development), "holdout_rows": expected_holdout_rows,
            "holdout_consumed": False, "promotable": False, "execution_enabled": False}


def _validation_evidence(settings: Settings, evaluation: object) -> tuple[dict[str, object], dict[str, bool]]:
    policy = development_gate_evidence(settings, evaluation)
    gates = policy.gates
    evidence = {
        "auc": evaluation.auc,
        "training_rows": evaluation.training_rows,
        "validation_rows": evaluation.validation_rows,
        "training_start_utc": evaluation.training_start,
        "training_end_utc": evaluation.training_end,
        "validation_start_utc": evaluation.validation_start,
        "validation_end_utc": evaluation.validation_end,
        "metrics": evaluation.metrics,
        "baselines": evaluation.baselines,
        "brier_score": evaluation.brier_score,
        "calibration_error": evaluation.calibration_error,
        "feature_drift_score": evaluation.feature_drift_score,
        "regime_coverage": evaluation.regime_coverage,
        "regimes": evaluation.regimes,
        "gates": gates,
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "minimum_window_trades_observed": policy.minimum_window_trades_observed,
        "minimum_window_trades_required": policy.minimum_window_trades_required,
    }
    return evidence, gates


def reserve_research_lineage(
    settings: Settings, tenant_id: str, user_id: str, user_role: str,
    request: ReserveResearchLineageRequest,
) -> dict[str, object]:
    if user_role.lower() not in {"owner", "administrator", "admin"}:
        raise PermissionError("Owner role is required")
    unknown = sorted(set(request.chosen_features) - set(FEATURES))
    if unknown:
        raise ValueError(f"Unknown feature(s): {', '.join(unknown)}")
    unknown_models = sorted(set(request.model_families) - SELECTIVE_MODEL_FAMILIES)
    if unknown_models:
        raise ValueError(f"Unknown model family/families: {', '.join(unknown_models)}")
    if not request.model_families:
        raise ValueError("At least one predeclared model family is required")
    symbol = request.market.upper()
    target_specification = next((
        specification for specification in TARGET_CATALOG[symbol]
        if specification.mode == request.target_mode
        and specification.horizon_bars == request.target_horizon_bars
    ), None)
    if target_specification is None:
        allowed = ", ".join(
            f"{item.mode}/{item.horizon_bars}" for item in TARGET_CATALOG[symbol]
        )
        raise ValueError(f"Target is not predeclared for {symbol}; allowed: {allowed}")
    fraction = request.holdout_fraction or settings.holdout_fraction
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
        market = cursor.fetchone()
        if not market:
            raise ValueError("Enabled market is required")
        market_id = str(market["market_id"])
        cursor.execute(
            """SELECT research_target_spec_id FROM app.research_target_specs
               WHERE market_id=%s AND target_sha256=%s AND active=1""",
            (market_id, target_specification.digest),
        )
        target_row = cursor.fetchone()
        if not target_row:
            raise ValueError("Run the selective research protocol audit before reserving a lineage")
        target_spec_id = str(target_row["research_target_spec_id"])
        cursor.execute(
            """SELECT TOP (1) c.version,b.p75_spread
               FROM app.cost_model_versions c JOIN app.cost_model_buckets b
                 ON b.cost_model_version_id=c.cost_model_version_id
               WHERE c.market_id=%s AND c.status='CURRENT' AND b.bucket_type='OVERALL'
               ORDER BY c.created_at_utc DESC""", (market_id,),
        )
        cost = cursor.fetchone()
        if not cost:
            raise ValueError("A current empirical cost model is required")
        cursor.execute(
            """SELECT TOP (1) research_lineage_id FROM app.research_lineages
               WHERE tenant_id=%s AND market_id=%s
                 AND status IN ('RESERVED','CANDIDATE_FROZEN','HOLDOUT_CONSUMED','OWNER_REVIEW_REQUIRED')
               ORDER BY created_at_utc DESC""", (tenant_id, market_id),
        )
        if cursor.fetchone():
            raise ValueError("An open research lineage already reserves this market's holdout")
        frame = _market_frame(cursor, market_id)
        development, holdout = select_holdout_split(
            frame, fraction=fraction, minimum_holdout_rows=settings.holdout_minimum_rows,
            minimum_development_rows=settings.model_minimum_rows,
        )
        development_feature_rows, holdout_labelable_rows = selective_partition_evidence(
            settings, development, holdout, specification=target_specification,
            fallback_spread=float(cost["p75_spread"]),
        )
        if development_feature_rows < settings.model_minimum_rows:
            raise ValueError(
                "Insufficient target-eligible development evidence: "
                f"need {settings.model_minimum_rows}, found {development_feature_rows}"
            )
        if holdout_labelable_rows < settings.holdout_minimum_rows:
            raise ValueError(
                "Insufficient causal holdout evidence: "
                f"need {settings.holdout_minimum_rows}, found {holdout_labelable_rows}"
            )
        identity = source_identity()
        configuration = {
            "market": symbol, "hypothesis": request.hypothesis,
            "chosen_features": request.chosen_features, "model_families": request.model_families,
            "research_protocol_version": PROTOCOL_VERSION,
            "research_target_spec_id": target_spec_id,
            "target_specification": target_specification.configuration(),
            "target_sha256": target_specification.digest,
            "validation_policy_version": VALIDATION_POLICY_VERSION,
            "feature_version": FEATURE_VERSION_FALLBACK, "label_version": target_specification.version,
            "label_horizon_bars": target_specification.horizon_bars,
            "label_horizon_minutes": target_specification.horizon_bars * 15,
            "label_definition_hash": target_specification.digest,
            "cost_model_version": str(cost["version"]),
            "development_start_utc": development.index.min().isoformat(),
            "development_end_utc": development.index.max().isoformat(),
            "holdout_start_utc": holdout.index.min().isoformat(),
            "holdout_end_utc": holdout.index.max().isoformat(),
            "development_feature_rows": development_feature_rows,
            "holdout_labelable_rows": holdout_labelable_rows,
        }
        configuration_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
        lineage_id = str(uuid4())
        cursor.execute(
            """INSERT app.research_lineages
                 (research_lineage_id,tenant_id,market_id,hypothesis,chosen_features_json,
                  model_families_json,validation_policy_version,feature_version,label_version,
                  label_horizon_bars,label_horizon_minutes,label_definition_hash,cost_model_version,
                  source_identity,dirty_worktree,configuration_hash,development_start_utc,
                  development_end_utc,holdout_start_utc,holdout_end_utc,status,created_by_user_id,
                  research_target_spec_id,research_protocol_version)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RESERVED',%s,%s,%s)""",
            (lineage_id, tenant_id, market_id, request.hypothesis,
             json.dumps(request.chosen_features), json.dumps(request.model_families),
             VALIDATION_POLICY_VERSION, FEATURE_VERSION_FALLBACK, target_specification.version,
             target_specification.horizon_bars, target_specification.horizon_bars * 15,
             target_specification.digest, str(cost["version"]),
             str(identity["source_identity"]), int(bool(identity["dirty_worktree"])),
             configuration_hash, development.index.min().to_pydatetime(), development.index.max().to_pydatetime(),
             holdout.index.min().to_pydatetime(), holdout.index.max().to_pydatetime(), user_id,
             target_spec_id, PROTOCOL_VERSION),
        )
        connection.commit()
    return {
        "status": "RESERVED", "research_lineage_id": lineage_id, "market": symbol,
        "development_rows": len(development), "holdout_rows": len(holdout),
        "development_feature_rows": development_feature_rows,
        "holdout_labelable_rows": holdout_labelable_rows,
        "holdout_start_utc": holdout.index.min().isoformat(),
        "holdout_end_utc": holdout.index.max().isoformat(),
        "target": target_specification.configuration() | {"sha256": target_specification.digest},
        "research_protocol_version": PROTOCOL_VERSION,
        "holdout_consumed": False, "execution_enabled": False,
    }


def freeze_candidate(
    settings: Settings, tenant_id: str, request: FreezeCandidateRequest,
) -> dict[str, object]:
    symbol = request.market.upper()
    fraction = request.holdout_fraction or settings.holdout_fraction
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT m.market_id,sv.strategy_version_id,sv.version,sv.features_version
               FROM app.markets m CROSS JOIN app.strategy_versions sv
               JOIN app.strategies s ON s.strategy_id=sv.strategy_id
               WHERE m.symbol=%s AND m.enabled=1 AND s.strategy_name='Conservative FX Demo'
                 AND sv.version='1.0'""", (symbol,),
        )
        market = cursor.fetchone()
        if not market:
            raise ValueError("Enabled market and strategy version are required")
        market_id, strategy_version_id, strategy_version, feature_version = market
        frame = _market_frame(cursor, str(market_id))
        cursor.execute(
            """SELECT TOP (1) c.version,b.p75_spread
               FROM app.cost_model_versions c JOIN app.cost_model_buckets b
                 ON b.cost_model_version_id=c.cost_model_version_id
               WHERE c.market_id=%s AND c.status='CURRENT' AND b.bucket_type='OVERALL'
               ORDER BY c.created_at_utc DESC""", (str(market_id),),
        )
        cost = cursor.fetchone()
        cursor.execute(
            """SELECT TOP (1) research_lineage_id,development_start_utc,development_end_utc,
                      holdout_start_utc,holdout_end_utc,configuration_hash,
                      research_protocol_version,research_target_spec_id
               FROM app.research_lineages
               WHERE tenant_id=%s AND market_id=%s AND status='RESERVED'
               ORDER BY created_at_utc DESC""", (tenant_id, str(market_id)),
        )
        lineage = cursor.fetchone()
    if not cost:
        raise ValueError("A current empirical cost model is required before freezing")
    if not lineage:
        raise ValueError("Reserve an immutable research lineage and holdout before freezing a candidate")
    if len(lineage) > 6 and str(lineage[6] or "") == PROTOCOL_VERSION:
        return _freeze_selective_candidate(settings, tenant_id, request)
    cost_version, fallback_spread = str(cost[0]), float(cost[1])
    lineage_id = str(lineage[0])
    development_raw = frame.loc[
        (frame.index >= _utc_timestamp(lineage[1])) & (frame.index <= _utc_timestamp(lineage[2]))
    ].copy()
    holdout_raw = frame.loc[
        (frame.index >= _utc_timestamp(lineage[3])) & (frame.index <= _utc_timestamp(lineage[4]))
    ].copy()
    if development_raw.empty or holdout_raw.empty or development_raw.index.max() >= holdout_raw.index.min():
        raise ValueError("Reserved research lineage no longer maps to immutable chronological data")
    availability = add_features(
        _effective_costs(frame, fallback_spread, settings.model_round_trip_cost_bps),
        labelled=True,
    )
    available_development_rows = int((availability.index < holdout_raw.index.min()).sum())
    available_holdout_rows = int((availability.index >= holdout_raw.index.min()).sum())
    if (available_development_rows < settings.model_minimum_rows or
            available_holdout_rows < settings.holdout_minimum_rows):
        development_digest = _frame_digest(development_raw)
        holdout_digest = _frame_digest(holdout_raw)
        blocked_configuration = {
            "policy_version": HOLDOUT_POLICY_VERSION, "symbol": symbol,
            "holdout_fraction": fraction, "minimum_development_rows": settings.model_minimum_rows,
            "minimum_holdout_rows": settings.holdout_minimum_rows,
            "available_development_rows": available_development_rows,
            "available_holdout_rows": available_holdout_rows,
            "feature_version": feature_version or FEATURE_VERSION_FALLBACK,
            "label_version": LABEL_VERSION, "regime_version": REGIME_VERSION,
            "cost_model_version": cost_version,
            "development_digest": development_digest, "holdout_digest": holdout_digest,
        }
        configuration_hash = hashlib.sha256(
            json.dumps(blocked_configuration, sort_keys=True).encode(),
        ).hexdigest()
        outcome = {
            "status": "DATA_BLOCKED", "reason": "INSUFFICIENT_INDEPENDENT_FEATURE_ROWS",
            "available_development_rows": available_development_rows,
            "required_development_rows": settings.model_minimum_rows,
            "available_holdout_rows": available_holdout_rows,
            "required_holdout_rows": settings.holdout_minimum_rows,
            "holdout_consumed": False,
        }
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """SELECT TOP (1) experiment_id FROM app.research_experiments
                   WHERE tenant_id=%s AND market_id=%s AND retrain_type='HOLDOUT_CANDIDATE'
                     AND configuration_hash=%s""", (tenant_id, str(market_id), configuration_hash),
            )
            existing = cursor.fetchone()
            experiment_id = str(existing[0]) if existing else str(uuid4())
            if not existing:
                cursor.execute(
                    """INSERT app.research_experiments
                         (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                          model_version,regime_version,cost_model_version,retrain_type,training_start_utc,
                          training_end_utc,holdout_start_utc,holdout_end_utc,configuration_hash,status,
                          notes,outcome_json,completed_at_utc)
                       VALUES(%s,%s,%s,%s,%s,%s,NULL,%s,%s,'HOLDOUT_CANDIDATE',%s,%s,%s,%s,%s,
                              'REJECTED',%s,%s,SYSUTCDATETIME())""",
                    (experiment_id, tenant_id, str(market_id), str(strategy_version),
                     str(feature_version or FEATURE_VERSION_FALLBACK), LABEL_VERSION, REGIME_VERSION,
                     cost_version, development_raw.index.min().to_pydatetime(),
                     development_raw.index.max().to_pydatetime(), holdout_raw.index.min().to_pydatetime(),
                     holdout_raw.index.max().to_pydatetime(), configuration_hash, request.notes,
                     json.dumps(outcome)),
                )
                connection.commit()
        return {"experiment_id": experiment_id, "market": symbol, **outcome,
                "promotable": False, "forward_shadow_enabled": False,
                "execution_enabled": False}
    evaluation = chronological_evaluate(
        _effective_costs(development_raw, fallback_spread, settings.model_round_trip_cost_bps),
        minimum_rows=settings.model_minimum_rows,
        walk_forward_windows=settings.model_walk_forward_windows,
        round_trip_cost_bps=settings.model_round_trip_cost_bps,
    )
    validation, validation_gates = _validation_evidence(settings, evaluation)
    validation_passed = all(validation_gates.values())

    combined_features = add_features(_effective_costs(frame, fallback_spread, settings.model_round_trip_cost_bps), labelled=True)
    development_features = combined_features.loc[combined_features.index < holdout_raw.index.min()].iloc[:-HORIZON]
    holdout_features = combined_features.loc[
        (combined_features.index >= holdout_raw.index.min()) &
        (combined_features.index <= holdout_raw.index.max())
    ]
    if len(development_features) < settings.model_minimum_rows:
        raise ValueError("Feature-complete development rows are below the configured floor")
    if len(holdout_features) < settings.holdout_minimum_rows:
        raise ValueError("Feature-complete holdout rows are below the configured floor")

    configuration = {
        "policy_version": HOLDOUT_POLICY_VERSION, "symbol": symbol,
        "holdout_fraction": fraction, "minimum_development_rows": settings.model_minimum_rows,
        "minimum_holdout_rows": settings.holdout_minimum_rows,
        "buy_threshold": 0.70, "sell_threshold": 0.30, "horizon": HORIZON,
        "features": FEATURES, "feature_version": feature_version or FEATURE_VERSION_FALLBACK,
        "label_version": LABEL_VERSION, "regime_version": REGIME_VERSION,
        "cost_model_version": cost_version,
        "label_horizon_minutes": LABEL_HORIZON_MINUTES,
        "label_definition_hash": LABEL_DEFINITION_HASH,
        "purge_gap_rows": purge_rows_for_horizon(HORIZON),
        "validation_policy_version": VALIDATION_POLICY_VERSION,
        "source_identity": source_identity(),
        "research_lineage_id": lineage_id,
    }
    development_digest = _frame_digest(development_raw)
    holdout_digest = _frame_digest(holdout_raw)
    configuration_hash = hashlib.sha256(
        json.dumps({**configuration, "development_digest": development_digest,
                    "holdout_digest": holdout_digest}, sort_keys=True).encode(),
    ).hexdigest()
    candidate_id, experiment_id = str(uuid4()), str(uuid4())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate_version = f"holdout-{symbol.lower()}-{stamp}-{candidate_id[:6]}"
    artifact_path: Path | None = None
    artifact_digest: str | None = None
    if validation_passed:
        model = HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200,
            l2_regularization=1, random_state=42,
        )
        model.fit(development_features[FEATURES], development_features["target"].astype(int))
        artifact_root = MODEL_ROOT / "holdout"
        artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_root / f"{candidate_version}.joblib"
        joblib.dump({
            "model": model, "features": FEATURES, "horizon": HORIZON,
            "configuration": configuration, "fallback_spread": fallback_spread,
            "validation_policy_version": VALIDATION_POLICY_VERSION,
            "development_data_sha256": development_digest,
            "holdout_data_sha256": holdout_digest,
        }, artifact_path)
        artifact_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    status = "FROZEN" if validation_passed else "VALIDATION_REJECTED"
    experiment_status = "REGISTERED" if validation_passed else "REJECTED"
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT TOP (1) c.holdout_candidate_id,c.status,c.candidate_version
               FROM app.holdout_candidates c
               WHERE c.tenant_id=%s AND c.market_id=%s AND c.configuration_hash=%s
                 AND c.holdout_start_utc=%s AND c.holdout_end_utc=%s""",
            (tenant_id, str(market_id), configuration_hash, holdout_raw.index.min().to_pydatetime(),
             holdout_raw.index.max().to_pydatetime()),
        )
        existing = cursor.fetchone()
        if existing:
            if artifact_path:
                artifact_path.unlink(missing_ok=True)
            return {"status": "CURRENT", "candidate_id": str(existing[0]),
                    "candidate_status": existing[1], "candidate_version": existing[2],
                    "execution_enabled": False}
        try:
            cursor.execute(
                """INSERT app.research_experiments
                     (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                      model_version,regime_version,cost_model_version,retrain_type,training_start_utc,
                      training_end_utc,validation_start_utc,validation_end_utc,holdout_start_utc,
                      holdout_end_utc,configuration_hash,status,notes,outcome_json,completed_at_utc)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'HOLDOUT_CANDIDATE',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          CASE WHEN %s='REJECTED' THEN SYSUTCDATETIME() ELSE NULL END)""",
                (experiment_id, tenant_id, str(market_id), str(strategy_version),
                 str(feature_version or FEATURE_VERSION_FALLBACK), LABEL_VERSION, candidate_version,
                 REGIME_VERSION, cost_version, development_features.index.min().to_pydatetime(),
                 development_features.index.max().to_pydatetime(), evaluation.validation_start,
                 evaluation.validation_end, holdout_features.index.min().to_pydatetime(),
                 holdout_features.index.max().to_pydatetime(), configuration_hash, experiment_status,
                 request.notes, json.dumps({"validation": validation, "validation_passed": validation_passed}, default=_serial),
                 experiment_status),
            )
            cursor.execute(
                """INSERT app.holdout_candidates
                     (holdout_candidate_id,experiment_id,tenant_id,market_id,strategy_version_id,
                      candidate_version,feature_version,label_version,regime_version,cost_model_version,
                      artifact_path,artifact_sha256,configuration_hash,development_data_sha256,
                      holdout_data_sha256,development_start_utc,development_end_utc,holdout_start_utc,
                      holdout_end_utc,development_rows,holdout_rows,validation_json,validation_passed,
                      status,notes,research_lineage_id,validation_policy_version,label_horizon_bars,
                      label_definition_hash)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          %s,%s,%s,%s)""",
                (candidate_id, experiment_id, tenant_id, str(market_id), str(strategy_version_id),
                 candidate_version, str(feature_version or FEATURE_VERSION_FALLBACK), LABEL_VERSION,
                 REGIME_VERSION, cost_version, str(artifact_path.resolve()) if artifact_path else None,
                 artifact_digest, configuration_hash, development_digest, holdout_digest,
                 development_raw.index.min().to_pydatetime(), development_raw.index.max().to_pydatetime(),
                 holdout_raw.index.min().to_pydatetime(), holdout_raw.index.max().to_pydatetime(),
                 len(development_features), len(holdout_features),
                 json.dumps(validation, default=_serial), int(validation_passed), status, request.notes,
                 lineage_id, VALIDATION_POLICY_VERSION, HORIZON, LABEL_DEFINITION_HASH),
            )
            if validation_passed:
                cursor.execute(
                    """UPDATE app.research_lineages SET status='CANDIDATE_FROZEN'
                       WHERE research_lineage_id=%s AND status='RESERVED'""", (lineage_id,),
                )
                lifecycle_evidence = {
                    "validation_policy_version": VALIDATION_POLICY_VERSION,
                    "artifact_sha256": artifact_digest, "development_gates": validation_gates,
                    "holdout_consumed": False, "execution_enabled": False,
                }
                insert_lifecycle_event(
                    cursor, tenant_id=tenant_id, market_id=str(market_id),
                    research_lineage_id=lineage_id, holdout_candidate_id=candidate_id,
                    from_state="RESEARCH", to_state="ELIGIBLE_TO_FREEZE",
                    reason="All predeclared development gates passed", evidence=lifecycle_evidence,
                )
                insert_lifecycle_event(
                    cursor, tenant_id=tenant_id, market_id=str(market_id),
                    research_lineage_id=lineage_id, holdout_candidate_id=candidate_id,
                    from_state="ELIGIBLE_TO_FREEZE", to_state="FROZEN",
                    reason="Artifact and development/holdout checksums frozen", evidence=lifecycle_evidence,
                )
            else:
                insert_lifecycle_event(
                    cursor, tenant_id=tenant_id, market_id=str(market_id),
                    research_lineage_id=lineage_id, holdout_candidate_id=candidate_id,
                    from_state="RESEARCH", to_state="REJECTED",
                    reason="One or more development gates failed",
                    evidence={"development_gates": validation_gates, "execution_enabled": False},
                )
            connection.commit()
        except Exception:
            connection.rollback()
            if artifact_path:
                artifact_path.unlink(missing_ok=True)
            raise
    return {
        "status": status, "candidate_id": candidate_id, "candidate_version": candidate_version,
        "market": symbol, "development_rows": len(development_features),
        "holdout_rows": len(holdout_features), "holdout_start_utc": holdout_raw.index.min().isoformat(),
        "holdout_end_utc": holdout_raw.index.max().isoformat(),
        "validation_passed": validation_passed, "validation": validation,
        "holdout_consumed": False, "promotable": False, "execution_enabled": False,
    }


def evaluate_holdout(
    settings: Settings, tenant_id: str, request: EvaluateHoldoutRequest,
) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT c.*,m.symbol FROM app.holdout_candidates c
               JOIN app.markets m ON m.market_id=c.market_id
               WHERE c.holdout_candidate_id=%s AND c.tenant_id=%s""",
            (request.candidate_id, tenant_id),
        )
        candidate = cursor.fetchone()
        if not candidate:
            raise ValueError("Frozen candidate was not found")
        if candidate["status"] != "FROZEN" or not candidate["validation_passed"]:
            raise ValueError(f"Holdout cannot be consumed from status {candidate['status']}")
        cursor.execute(
            """UPDATE app.holdout_candidates SET status='EVALUATING',
                      holdout_consumed_at_utc=SYSUTCDATETIME()
               WHERE holdout_candidate_id=%s AND status='FROZEN'""",
            (request.candidate_id,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("Holdout was already claimed by another evaluation")
        insert_lifecycle_event(
            cursor, tenant_id=tenant_id, market_id=str(candidate["market_id"]),
            research_lineage_id=str(candidate["research_lineage_id"]) if candidate.get("research_lineage_id") else None,
            holdout_candidate_id=request.candidate_id, from_state="FROZEN", to_state="HOLDOUT_REVIEW",
            reason="Explicit single-use holdout acknowledgement accepted",
            evidence={"acknowledgement": request.acknowledgement, "holdout_consumed": True,
                      "execution_enabled": False},
        )
        connection.commit()

    try:
        artifact_path = Path(str(candidate["artifact_path"]))
        if not artifact_path.is_file():
            raise ValueError("Frozen candidate artifact is unavailable")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != candidate["artifact_sha256"]:
            raise ValueError("Frozen candidate artifact checksum changed")
        bundle = joblib.load(artifact_path)
        with open_database(settings) as connection:
            cursor = connection.cursor()
            frame = _market_frame(cursor, str(candidate["market_id"]))
        development_raw = frame.loc[
            (frame.index >= _utc_timestamp(candidate["development_start_utc"])) &
            (frame.index <= _utc_timestamp(candidate["development_end_utc"]))
        ]
        holdout_raw = frame.loc[
            (frame.index >= _utc_timestamp(candidate["holdout_start_utc"])) &
            (frame.index <= _utc_timestamp(candidate["holdout_end_utc"]))
        ]
        if _frame_digest(development_raw) != candidate["development_data_sha256"]:
            raise ValueError("Frozen development data checksum changed")
        if _frame_digest(holdout_raw) != candidate["holdout_data_sha256"]:
            raise ValueError("Reserved holdout data checksum changed")
        prepared = _effective_costs(
            frame.loc[frame.index <= holdout_raw.index.max()], float(bundle["fallback_spread"]),
            settings.model_round_trip_cost_bps,
        )
        if str(bundle.get("research_protocol_version") or "") == PROTOCOL_VERSION:
            specification_payload = dict(bundle.get("target_specification") or {})
            specification = _target_specification(
                str(candidate["symbol"]), str(specification_payload.get("sha256") or ""),
            )
            if (str(candidate.get("research_protocol_version") or "") != PROTOCOL_VERSION or
                    str(candidate.get("label_definition_hash") or "") != specification.digest):
                raise ValueError("Frozen selective candidate metadata does not match its artifact")
            development = build_selective_target(
                _effective_costs(development_raw, float(bundle["fallback_spread"]),
                                 settings.model_round_trip_cost_bps),
                specification, configured_cost_bps=settings.model_round_trip_cost_bps,
            )
            holdout = build_selective_target(
                _effective_costs(holdout_raw, float(bundle["fallback_spread"]),
                                 settings.model_round_trip_cost_bps),
                specification, configured_cost_bps=settings.model_round_trip_cost_bps,
            )
            if len(holdout) != int(candidate["holdout_rows"]):
                raise ValueError("Reserved selective holdout observation count changed")
            model = bundle["model"]
            probabilities = model.predict_proba(holdout[FEATURES])
            edges = dict(bundle.get("edge_parameters") or {})
            directions, explanations = selective_directions_from_edges(
                probabilities, model.classes_, holdout, specification,
                buy_move_bps=float(edges["buy_move_bps"]),
                sell_move_bps=float(edges["sell_move_bps"]),
            )
            directions = apply_ensemble_disagreement(model, holdout, directions)
            targets = holdout["target"].to_numpy(int)
            metrics = trading_metrics(
                holdout["future_return"].to_numpy(float), directions,
                round_trip_cost_bps=holdout["effective_cost_bps"].to_numpy(float),
            )
            baselines = _baseline_results(
                [holdout], round_trip_cost_bps=settings.model_round_trip_cost_bps,
            )
            regimes = regime_slices(holdout, directions, str(candidate["symbol"]))
            auc = _selective_multiclass_auc(targets, probabilities, model.classes_)
            one_hot = np.column_stack([(targets == int(value)).astype(float)
                                       for value in model.classes_])
            brier = float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))
            calibration = _multiclass_calibration_error(targets, probabilities, model.classes_)
            drift = _feature_drift(development, holdout)
            regime_coverage = float(np.mean([
                int(item["observation_count"]) >= 100 for item in regimes
            ])) if regimes else 0.0
            best_baseline = max(float(item["expectancy"] or 0) for item in baselines)
            gates = evidence_gates(
                settings, auc=auc, metrics=metrics, calibration_error=calibration,
                feature_drift_score=drift, regime_coverage=regime_coverage,
                baseline_expectancy=best_baseline,
            )
            gates["buy_sell_hold_class_coverage"] = (
                set(int(value) for value in np.unique(targets)) == {0, 1, 2}
                and set(int(value) for value in model.classes_) == {0, 1, 2}
            )
            bootstrap = block_bootstrap_expectancy(
                holdout["future_return"].to_numpy(float), directions,
                holdout["effective_cost_bps"].to_numpy(float),
            )
            stresses = cost_stress_evidence(holdout, directions)
            p90 = next(item for item in stresses if item["scenario"] == "SPREAD_P90")
            gates["bootstrap_lower_bound_positive"] = float(bootstrap["lower_95"]) > 0
            gates["p90_spread_stress_positive"] = float(p90["expectancy"] or 0) > 0
            passed = all(gates.values())
            evaluation_id = str(uuid4())
            reason_counts: dict[str, int] = {}
            for explanation in explanations:
                reason = str(explanation["reason"])
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            outcome = {
                "research_protocol_version": PROTOCOL_VERSION,
                "target_sha256": specification.digest,
                "challenger_key": bundle.get("challenger_key"),
                "auc": auc, "brier_score": brier, "calibration_error": calibration,
                "feature_drift_score": drift, "regime_coverage": regime_coverage,
                "hold_fraction": float(np.mean(directions == 0)),
                "decision_reason_counts": reason_counts,
                "metrics": metrics, "baselines": baselines, "regimes": regimes,
                "bootstrap_expectancy": bootstrap, "cost_stress": stresses,
                "gates": gates, "passed": passed,
            }
            with open_database(settings) as connection:
                cursor = connection.cursor()
                cursor.execute(
                    """INSERT app.holdout_evaluations
                         (holdout_evaluation_id,holdout_candidate_id,result,observation_count,trade_count,
                          validation_auc,brier_score,calibration_error,feature_drift_score,regime_coverage,
                          win_rate,profit_factor,expectancy,max_drawdown,baseline_outperformed,
                          metrics_json,baselines_json,regimes_json,gates_json)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (evaluation_id, request.candidate_id, "PASSED" if passed else "REJECTED",
                     len(holdout), metrics["trade_count"], auc, brier, calibration, drift,
                     regime_coverage, metrics["win_rate"], metrics["profit_factor"],
                     metrics["expectancy"], metrics["max_drawdown"],
                     int(gates["baseline_outperformance"]), json.dumps(metrics, default=_serial),
                     json.dumps(baselines, default=_serial), json.dumps(regimes, default=_serial),
                     json.dumps(gates)),
                )
                cursor.execute(
                    "UPDATE app.holdout_candidates SET status=%s,evaluated_at_utc=SYSUTCDATETIME() WHERE holdout_candidate_id=%s AND status='EVALUATING'",
                    ("OWNER_REVIEW_REQUIRED" if passed else "HOLDOUT_REJECTED", request.candidate_id),
                )
                cursor.execute(
                    "UPDATE app.research_lineages SET status=%s WHERE research_lineage_id=%s AND status='CANDIDATE_FROZEN'",
                    ("OWNER_REVIEW_REQUIRED" if passed else "REJECTED", str(candidate["research_lineage_id"])),
                )
                cursor.execute(
                    "UPDATE app.research_experiments SET status=%s,outcome_json=%s,completed_at_utc=SYSUTCDATETIME() WHERE experiment_id=%s",
                    ("COMPLETED" if passed else "REJECTED", json.dumps(outcome, default=_serial),
                     str(candidate["experiment_id"])),
                )
                if not passed:
                    insert_lifecycle_event(cursor, tenant_id=tenant_id,
                        market_id=str(candidate["market_id"]),
                        research_lineage_id=str(candidate["research_lineage_id"]),
                        holdout_candidate_id=request.candidate_id,
                        from_state="HOLDOUT_REVIEW", to_state="REJECTED",
                        reason="Selective untouched holdout rejected the frozen candidate",
                        evidence={"evaluation": outcome, "execution_enabled": False})
                connection.commit()
            return {"status": "OWNER_REVIEW_REQUIRED" if passed else "HOLDOUT_REJECTED",
                    "candidate_id": request.candidate_id, "market": candidate["symbol"],
                    "holdout_consumed": True, "evaluation": outcome, "promotable": False,
                    "forward_shadow_enabled": False, "execution_enabled": False}
        featured = add_features(prepared, labelled=True)
        development = featured.loc[
            (featured.index >= development_raw.index.min()) &
            (featured.index <= development_raw.index.max())
        ]
        holdout = featured.loc[
            (featured.index >= holdout_raw.index.min()) &
            (featured.index <= holdout_raw.index.max())
        ]
        if len(holdout) != int(candidate["holdout_rows"]):
            raise ValueError("Reserved holdout observation count changed")
        probabilities = bundle["model"].predict_proba(holdout[FEATURES])[:, 1]
        directions = np.where(probabilities >= 0.70, 1, np.where(probabilities <= 0.30, -1, 0))
        targets = holdout["target"].to_numpy(int)
        metrics = trading_metrics(
            holdout["future_return"].to_numpy(float), directions,
            round_trip_cost_bps=holdout["effective_cost_bps"].to_numpy(float),
        )
        baselines = _baseline_results([holdout], round_trip_cost_bps=settings.model_round_trip_cost_bps)
        regimes = _regime_results(holdout, directions, round_trip_cost_bps=settings.model_round_trip_cost_bps)
        auc = _safe_auc(targets, probabilities)
        brier = float(np.mean((probabilities - targets) ** 2))
        calibration = _calibration_error(targets, probabilities)
        drift = _feature_drift(development, holdout)
        regime_coverage = float(np.mean([int(item["observation_count"]) >= 100 for item in regimes]))
        best_baseline = max(float(item["expectancy"]) for item in baselines)
        gates = evidence_gates(
            settings, auc=auc, metrics=metrics, calibration_error=calibration,
            feature_drift_score=drift, regime_coverage=regime_coverage,
            baseline_expectancy=best_baseline,
        )
        passed = all(gates.values())
        evaluation_id = str(uuid4())
        outcome = {
            "auc": auc, "brier_score": brier, "calibration_error": calibration,
            "feature_drift_score": drift, "regime_coverage": regime_coverage,
            "metrics": metrics, "baselines": baselines, "regimes": regimes,
            "gates": gates, "passed": passed,
        }
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """INSERT app.holdout_evaluations
                     (holdout_evaluation_id,holdout_candidate_id,result,observation_count,trade_count,
                      validation_auc,brier_score,calibration_error,feature_drift_score,regime_coverage,
                      win_rate,profit_factor,expectancy,max_drawdown,baseline_outperformed,
                      metrics_json,baselines_json,regimes_json,gates_json)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (evaluation_id, request.candidate_id, "PASSED" if passed else "REJECTED", len(holdout),
                 metrics["trade_count"], auc, brier, calibration, drift, regime_coverage,
                 metrics["win_rate"], metrics["profit_factor"], metrics["expectancy"],
                 metrics["max_drawdown"], int(gates["baseline_outperformance"]),
                 json.dumps(metrics, default=_serial), json.dumps(baselines, default=_serial),
                 json.dumps(regimes, default=_serial), json.dumps(gates)),
            )
            cursor.execute(
                """UPDATE app.holdout_candidates SET status=%s,evaluated_at_utc=SYSUTCDATETIME()
                   WHERE holdout_candidate_id=%s AND status='EVALUATING'""",
                ("OWNER_REVIEW_REQUIRED" if passed else "HOLDOUT_REJECTED", request.candidate_id),
            )
            if candidate.get("research_lineage_id"):
                cursor.execute(
                    """UPDATE app.research_lineages SET status=%s
                       WHERE research_lineage_id=%s AND status='CANDIDATE_FROZEN'""",
                    ("OWNER_REVIEW_REQUIRED" if passed else "REJECTED",
                     str(candidate["research_lineage_id"])),
                )
            cursor.execute(
                """UPDATE app.research_experiments SET status=%s,outcome_json=%s,
                          completed_at_utc=SYSUTCDATETIME() WHERE experiment_id=%s""",
                ("COMPLETED" if passed else "REJECTED", json.dumps(outcome, default=_serial),
                 str(candidate["experiment_id"])),
            )
            if not passed:
                insert_lifecycle_event(
                    cursor, tenant_id=tenant_id, market_id=str(candidate["market_id"]),
                    research_lineage_id=str(candidate["research_lineage_id"]) if candidate.get("research_lineage_id") else None,
                    holdout_candidate_id=request.candidate_id,
                    from_state="HOLDOUT_REVIEW", to_state="REJECTED",
                    reason="Untouched holdout gates rejected the frozen candidate",
                    evidence={"evaluation": outcome, "execution_enabled": False},
                )
            connection.commit()
        return {
            "status": "OWNER_REVIEW_REQUIRED" if passed else "HOLDOUT_REJECTED",
            "candidate_id": request.candidate_id, "market": candidate["symbol"],
            "holdout_consumed": True, "evaluation": outcome,
            "promotable": False, "forward_shadow_enabled": False, "execution_enabled": False,
        }
    except Exception:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """UPDATE app.holdout_candidates SET status='EVALUATION_FAILED',
                          evaluated_at_utc=SYSUTCDATETIME()
                   WHERE holdout_candidate_id=%s AND status='EVALUATING'""",
                (request.candidate_id,),
            )
            cursor.execute(
                """UPDATE app.research_experiments SET status='FAILED',completed_at_utc=SYSUTCDATETIME()
                   WHERE experiment_id=%s""", (str(candidate["experiment_id"]),),
            )
            connection.commit()
        raise


def approve_holdout_candidate(
    settings: Settings, tenant_id: str, user_id: str, user_role: str,
    request: ApproveHoldoutRequest,
) -> dict[str, object]:
    if user_role.lower() not in {"owner", "administrator", "admin"}:
        raise PermissionError("Owner role is required")
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT c.*,m.symbol FROM app.holdout_candidates c
               JOIN app.markets m ON m.market_id=c.market_id
               JOIN app.holdout_evaluations e ON e.holdout_candidate_id=c.holdout_candidate_id
               WHERE c.holdout_candidate_id=%s AND c.tenant_id=%s
                 AND c.status='OWNER_REVIEW_REQUIRED' AND e.result='PASSED'""",
            (request.candidate_id, tenant_id),
        )
        candidate = cursor.fetchone()
        if not candidate:
            raise ValueError("An exact single-use holdout-passed candidate is required")
        artifact = Path(str(candidate["artifact_path"]))
        if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest() != candidate["artifact_sha256"]:
            raise ValueError("Frozen candidate artifact integrity failed")
        identity = source_identity()
        model_id = str(uuid4())
        version = f"approved-{str(candidate['symbol']).lower()}-{request.candidate_id[:8]}"[:30]
        try:
            cursor.execute(
                """INSERT app.model_versions
                     (model_version_id,strategy_version_id,market_id,model_name,version,artifact_path,
                      artifact_sha256,validation_auc,training_rows,status,holdout_candidate_id,
                      research_lineage_id,validation_policy_version,feature_version,label_version,
                      cost_model_version,source_identity,dirty_worktree,research_target_spec_id,
                      research_protocol_version,challenger_key)
                   SELECT %s,c.strategy_version_id,c.market_id,%s,%s,c.artifact_path,c.artifact_sha256,
                          e.validation_auc,c.development_rows,'VALIDATED',c.holdout_candidate_id,
                          c.research_lineage_id,c.validation_policy_version,c.feature_version,
                          c.label_version,c.cost_model_version,%s,%s,c.research_target_spec_id,
                          c.research_protocol_version,c.challenger_key
                   FROM app.holdout_candidates c JOIN app.holdout_evaluations e
                     ON e.holdout_candidate_id=c.holdout_candidate_id
                   WHERE c.holdout_candidate_id=%s AND c.status='OWNER_REVIEW_REQUIRED'""",
                (model_id, f"{candidate['symbol']} governed model", version,
                 str(identity["source_identity"]), int(bool(identity["dirty_worktree"])), request.candidate_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Candidate changed during owner approval")
            cursor.execute(
                """UPDATE app.holdout_candidates SET status='OWNER_APPROVED',
                          owner_reviewed_by_user_id=%s,owner_reviewed_at_utc=SYSUTCDATETIME(),
                          owner_acknowledgement=%s
                   WHERE holdout_candidate_id=%s AND status='OWNER_REVIEW_REQUIRED'""",
                (user_id, request.acknowledgement, request.candidate_id),
            )
            if candidate.get("research_lineage_id"):
                cursor.execute(
                    """UPDATE app.research_lineages SET status='OWNER_APPROVED',closed_at_utc=SYSUTCDATETIME()
                       WHERE research_lineage_id=%s AND status='OWNER_REVIEW_REQUIRED'""",
                    (str(candidate["research_lineage_id"]),),
                )
            cursor.execute(
                """INSERT app.audit_logs
                     (tenant_id,user_id,action_code,entity_type,entity_id,correlation_id,metadata_json)
                   VALUES(%s,%s,'model.holdout.owner_approved','holdout_candidate',%s,NEWID(),%s)""",
                (tenant_id, user_id, request.candidate_id, json.dumps({
                    "model_version_id": model_id, "artifact_sha256": candidate["artifact_sha256"],
                    "forward_shadow_only": True, "execution_enabled": False,
                })),
            )
            approval_evidence = {
                "model_version_id": model_id, "artifact_sha256": candidate["artifact_sha256"],
                "owner_acknowledgement": request.acknowledgement,
                "forward_shadow_only": True, "execution_enabled": False,
            }
            insert_lifecycle_event(
                cursor, tenant_id=tenant_id, market_id=str(candidate["market_id"]),
                research_lineage_id=str(candidate["research_lineage_id"]) if candidate.get("research_lineage_id") else None,
                holdout_candidate_id=request.candidate_id, model_version_id=model_id,
                changed_by_user_id=user_id, from_state="HOLDOUT_REVIEW", to_state="OWNER_APPROVED",
                reason="Owner approved the exact checksum-bound holdout-passed artifact",
                evidence=approval_evidence,
            )
            insert_lifecycle_event(
                cursor, tenant_id=tenant_id, market_id=str(candidate["market_id"]),
                research_lineage_id=str(candidate["research_lineage_id"]) if candidate.get("research_lineage_id") else None,
                holdout_candidate_id=request.candidate_id, model_version_id=model_id,
                changed_by_user_id=user_id, from_state="OWNER_APPROVED", to_state="FORWARD_SHADOW",
                reason="Approved artifact admitted to isolated forward shadow only",
                evidence=approval_evidence,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "status": "OWNER_APPROVED", "candidate_id": request.candidate_id,
        "model_version_id": model_id, "market": candidate["symbol"],
        "forward_shadow_only": True, "execution_enabled": False,
    }


def read_holdout_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT c.holdout_candidate_id,m.symbol,c.candidate_version,c.feature_version,
                      c.label_version,c.regime_version,c.cost_model_version,c.development_start_utc,
                      c.development_end_utc,c.holdout_start_utc,c.holdout_end_utc,c.development_rows,
                      c.holdout_rows,c.validation_passed,c.status,c.notes,c.frozen_at_utc,
                      c.holdout_consumed_at_utc,c.evaluated_at_utc,c.validation_json,
                      e.result,e.observation_count,e.trade_count,e.validation_auc,e.brier_score,
                      e.calibration_error,e.feature_drift_score,e.regime_coverage,e.win_rate,
                      e.profit_factor,e.expectancy,e.max_drawdown,e.baseline_outperformed,
                      e.metrics_json,e.baselines_json,e.regimes_json,e.gates_json
               FROM app.holdout_candidates c JOIN app.markets m ON m.market_id=c.market_id
               LEFT JOIN app.holdout_evaluations e ON e.holdout_candidate_id=c.holdout_candidate_id
               WHERE c.tenant_id=%s ORDER BY c.frozen_at_utc DESC""", (tenant_id,),
        )
        candidates = []
        for row in cursor.fetchall():
            item = {key: _serial(value) for key, value in row.items()
                    if key not in ("validation_json", "metrics_json", "baselines_json", "regimes_json", "gates_json")}
            item["validation"] = json.loads(row["validation_json"])
            item["metrics"] = json.loads(row["metrics_json"]) if row.get("metrics_json") else None
            item["baselines"] = json.loads(row["baselines_json"]) if row.get("baselines_json") else None
            item["regimes"] = json.loads(row["regimes_json"]) if row.get("regimes_json") else None
            item["gates"] = json.loads(row["gates_json"]) if row.get("gates_json") else None
            candidates.append(item)
        cursor.execute(
            """WITH ranked AS (
                   SELECT e.*,ROW_NUMBER() OVER(
                       PARTITION BY e.market_id ORDER BY e.started_at_utc DESC,e.experiment_id DESC
                   ) attempt_rank
                   FROM app.research_experiments e
                   WHERE e.tenant_id=%s AND e.retrain_type='HOLDOUT_CANDIDATE'
                     AND NOT EXISTS(SELECT 1 FROM app.holdout_candidates c WHERE c.experiment_id=e.experiment_id)
               )
               SELECT e.experiment_id,m.symbol,e.configuration_hash,e.status,e.notes,
                      e.outcome_json,e.started_at_utc,e.completed_at_utc,e.holdout_start_utc,
                      e.holdout_end_utc
               FROM ranked e JOIN app.markets m ON m.market_id=e.market_id
               WHERE e.attempt_rank=1 ORDER BY e.started_at_utc DESC""", (tenant_id,),
        )
        blocked_attempts = []
        for row in cursor.fetchall():
            item = {key: _serial(value) for key, value in row.items() if key != "outcome_json"}
            item["outcome"] = json.loads(row["outcome_json"]) if row.get("outcome_json") else None
            blocked_attempts.append(item)
    return {
        "status": "HOLDOUT_ENFORCED", "policy_version": HOLDOUT_POLICY_VERSION,
        "single_use": True, "candidates": candidates, "blocked_attempts": blocked_attempts,
        "promotable": False, "forward_shadow_enabled": False, "execution_enabled": False,
    }
