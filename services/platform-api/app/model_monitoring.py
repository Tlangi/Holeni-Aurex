from __future__ import annotations

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd

from app.config import Settings
from app.database import open_database
from app.holdout_service import _target_specification
from app.model_pipeline import FEATURES, _feature_drift, _market_frame, add_features
from app.research_protocol import (
    PROTOCOL_VERSION,
    _multiclass_calibration_error,
    build_selective_target,
)


def capture_model_monitoring(settings: Settings, tenant_id: str) -> list[dict[str, object]]:
    """Persist hourly feature/calibration/cost drift evidence for every market."""
    outcomes: list[dict[str, object]] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id,symbol FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
        for market in markets:
            market_id, symbol = str(market["market_id"]), str(market["symbol"])
            cursor.execute(
                """SELECT TOP (1) evaluated_at_utc FROM app.model_monitoring_snapshots
                   WHERE tenant_id=%s AND market_id=%s
                     AND evaluated_at_utc>=DATEADD(hour,-1,SYSUTCDATETIME())""",
                (tenant_id, market_id),
            )
            if cursor.fetchone():
                outcomes.append({"symbol": symbol, "status": "CURRENT"})
                continue
            cursor.execute(
                """SELECT TOP (1) mv.model_version_id,mv.artifact_path,mv.artifact_sha256,
                          c.development_start_utc,c.development_end_utc,c.holdout_end_utc
                   FROM app.model_versions mv LEFT JOIN app.holdout_candidates c
                     ON c.holdout_candidate_id=mv.holdout_candidate_id
                   WHERE mv.market_id=%s AND mv.status='VALIDATED'
                   ORDER BY mv.registered_at_utc DESC""", (market_id,),
            )
            model_row = cursor.fetchone()
            if not model_row:
                details = {"reason": "NO_VALIDATED_MODEL", "alerts_enabled": True,
                           "execution_enabled": False}
                cursor.execute(
                    """INSERT app.model_monitoring_snapshots
                         (model_monitoring_snapshot_id,tenant_id,market_id,model_version_id,status,details_json)
                       VALUES(%s,%s,%s,NULL,'MODEL_UNAVAILABLE',%s)""",
                    (str(uuid4()), tenant_id, market_id, json.dumps(details)),
                )
                outcomes.append({"symbol": symbol, "status": "MODEL_UNAVAILABLE"})
                continue
            frame = _market_frame(cursor, market_id)
            artifact_path = Path(str(model_row["artifact_path"]))
            if (not artifact_path.is_file() or
                    hashlib.sha256(artifact_path.read_bytes()).hexdigest() != str(model_row["artifact_sha256"])):
                raise ValueError(f"Validated model artifact integrity failed for {symbol}")
            artifact = joblib.load(artifact_path)
            development = frame.loc[
                (frame.index >= _utc(model_row["development_start_utc"])) &
                (frame.index <= _utc(model_row["development_end_utc"]))
            ].copy()
            recent_raw = frame.loc[frame.index > _utc(model_row["holdout_end_utc"])].tail(750).copy()
            if len(recent_raw) < 120:
                status, feature_drift, calibration_drift, cost_drift = "WARN", None, None, None
                details = {"reason": "INSUFFICIENT_POST_APPROVAL_OBSERVATIONS",
                           "recent_rows": len(recent_raw), "required_rows": 120}
            else:
                fallback = float(artifact.get("fallback_spread") or settings.model_round_trip_cost_bps)
                development["effective_cost_bps"] = _costs(development, fallback)
                recent_raw["effective_cost_bps"] = _costs(recent_raw, fallback)
                if str(artifact.get("research_protocol_version") or "") == PROTOCOL_VERSION:
                    payload = dict(artifact.get("target_specification") or {})
                    specification = _target_specification(symbol, str(payload.get("sha256") or ""))
                    development_features = build_selective_target(
                        development, specification, configured_cost_bps=settings.model_round_trip_cost_bps,
                    )
                    recent = build_selective_target(
                        recent_raw, specification, configured_cost_bps=settings.model_round_trip_cost_bps,
                    )
                    probabilities = artifact["model"].predict_proba(recent[FEATURES])
                    calibration_drift = _multiclass_calibration_error(
                        recent["target"].to_numpy(int), probabilities, artifact["model"].classes_,
                    )
                else:
                    development_features = add_features(development, labelled=True)
                    recent = add_features(recent_raw, labelled=True)
                    probabilities = artifact["model"].predict_proba(recent[FEATURES])[:, 1]
                    calibration_drift = float(np.mean(np.abs(
                        probabilities - recent["target"].to_numpy(float)
                    )))
                feature_drift = _feature_drift(development_features, recent)
                observed = recent["effective_cost_bps"].to_numpy(float)
                cost_drift = abs(float(np.median(observed)) - fallback) / max(fallback, 1e-9)
                status = "FAIL" if (feature_drift > 1.5 or calibration_drift > 0.25 or cost_drift > 0.75) \
                    else "WARN" if (feature_drift > 1.0 or calibration_drift > 0.20 or cost_drift > 0.50) \
                    else "CURRENT"
                details = {"baseline_rows": len(development_features), "recent_rows": len(recent),
                           "thresholds": {"feature_warn": 1.0, "feature_fail": 1.5,
                                          "calibration_warn": 0.20, "calibration_fail": 0.25,
                                          "cost_warn": 0.50, "cost_fail": 0.75},
                           "execution_enabled": False}
            cursor.execute(
                """INSERT app.model_monitoring_snapshots
                     (model_monitoring_snapshot_id,tenant_id,market_id,model_version_id,
                      feature_drift_score,calibration_drift_score,cost_drift_score,regime_coverage,
                      status,details_json)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s)""",
                (str(uuid4()), tenant_id, market_id, str(model_row["model_version_id"]),
                 feature_drift, calibration_drift, cost_drift, status, json.dumps(details)),
            )
            outcomes.append({"symbol": symbol, "status": status,
                             "feature_drift": feature_drift,
                             "calibration_drift": calibration_drift,
                             "cost_drift": cost_drift})
        connection.commit()
    return outcomes


def read_model_monitoring(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """WITH latest AS (
                 SELECT s.*,ROW_NUMBER() OVER(PARTITION BY s.market_id ORDER BY s.evaluated_at_utc DESC) rn
                 FROM app.model_monitoring_snapshots s WHERE s.tenant_id=%s)
               SELECT m.symbol,l.model_version_id,l.feature_drift_score,l.calibration_drift_score,
                      l.cost_drift_score,l.regime_coverage,l.status,l.details_json,l.evaluated_at_utc
               FROM app.markets m LEFT JOIN latest l ON l.market_id=m.market_id AND l.rn=1
               WHERE m.enabled=1 ORDER BY m.symbol""", (tenant_id,),
        )
        rows = []
        for row in cursor.fetchall():
            rows.append({"symbol": row["symbol"], "model_version_id": str(row["model_version_id"])
                         if row.get("model_version_id") else None,
                         "feature_drift_score": _number(row.get("feature_drift_score")),
                         "calibration_drift_score": _number(row.get("calibration_drift_score")),
                         "cost_drift_score": _number(row.get("cost_drift_score")),
                         "regime_coverage": _number(row.get("regime_coverage")),
                         "status": row.get("status") or "PENDING",
                         "details": json.loads(row["details_json"]) if row.get("details_json") else {},
                         "evaluated_at_utc": row["evaluated_at_utc"].replace(tzinfo=timezone.utc).isoformat()
                         if row.get("evaluated_at_utc") else None})
    return {"markets": rows, "execution_enabled": False}


def _costs(frame, fallback: float) -> np.ndarray:
    observed = frame.get("observed_spread_bps")
    return np.maximum(observed.fillna(fallback).clip(lower=0).to_numpy(float), fallback)


def _utc(value: object):
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _number(value: object) -> float | None:
    return float(value) if value is not None else None
