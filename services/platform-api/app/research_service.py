from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.database import open_database
from app.holdout_service import read_holdout_status
from app.market_intelligence import model_readiness
from app.model_pipeline import FEATURES, add_features
from app.model_governance import LABEL_VERSION
from app.replay_engine import ReplayRequest, run_replay
from app.research_evidence import read_research_evidence, sync_cost_models, sync_quality_evidence
from app.research_regimes import REGIME_VERSION, confidence_bucket, market_session, trend_regime, volatility_regimes


DIAGNOSTIC_VERSION = "STRATEGY_DIAGNOSTICS_V1"


class ResearchReplayRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    market: str
    from_utc: datetime | None = Field(default=None, alias="from")
    to_utc: datetime | None = Field(default=None, alias="to")
    timeframe: str = Field(default="M15", pattern="^M15$")
    cost_model: str = Field(default="NORMAL", pattern="^(OPTIMISTIC|NORMAL|STRESSED)$")
    segment_mode: str = Field(default="CONTINUOUS_ONLY", pattern="^CONTINUOUS_ONLY$")
    max_candles: int = Field(default=100000, ge=60, le=100000)
    notes: str = Field(default="Diagnostic replay of the current rejected model", max_length=1000)


def _serial(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    pnl = [float(row.get("realized_pnl_zar") or 0) for row in rows]
    gross_pnl = [float(row.get("gross_pnl_zar") or 0) for row in rows]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)
    costs = [float(row.get("total_cost_zar") or 0) for row in rows]
    consecutive = current = 0
    equity = peak = drawdown = 0.0
    for value in pnl:
        current = current + 1 if value < 0 else 0
        consecutive = max(consecutive, current)
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trade_count": len(rows), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else 0.0,
        "loss_rate": len(losses) / len(rows) if rows else 0.0,
        "gross_profit_zar": gross_profit, "gross_loss_zar": gross_loss,
        "net_pnl_zar": sum(pnl), "average_winner_zar": float(np.mean(wins)) if wins else 0.0,
        "average_loser_zar": float(np.mean(losses)) if losses else 0.0,
        "median_winner_zar": median(wins) if wins else 0.0,
        "median_loser_zar": median(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0),
        "cost_aware_expectancy_zar": float(np.mean(pnl)) if pnl else 0.0,
        "gross_expectancy_zar": float(np.mean(gross_pnl)) if gross_pnl else 0.0,
        "maximum_drawdown_zar": drawdown,
        "total_transaction_cost_zar": sum(costs),
        "average_spread_cost_zar": float(np.mean([float(row.get("spread_cost_zar") or 0) for row in rows])) if rows else 0.0,
        "total_spread_cost_zar": sum(float(row.get("spread_cost_zar") or 0) for row in rows),
        "total_slippage_cost_zar": sum(float(row.get("slippage_cost_zar") or 0) for row in rows),
        "maximum_consecutive_losses": consecutive,
        "average_holding_minutes": float(np.mean([int(row.get("holding_minutes") or 0) for row in rows])) if rows else 0.0,
        "median_holding_minutes": median([int(row.get("holding_minutes") or 0) for row in rows]) if rows else 0.0,
        "average_mae_points": float(np.mean([float(row.get("mae_points") or 0) for row in rows])) if rows else 0.0,
        "average_mfe_points": float(np.mean([float(row.get("mfe_points") or 0) for row in rows])) if rows else 0.0,
        "mae_p50": float(np.percentile([float(row.get("mae_points") or 0) for row in rows], 50)) if rows else 0.0,
        "mae_p90": float(np.percentile([float(row.get("mae_points") or 0) for row in rows], 90)) if rows else 0.0,
        "mfe_p50": float(np.percentile([float(row.get("mfe_points") or 0) for row in rows], 50)) if rows else 0.0,
        "mfe_p90": float(np.percentile([float(row.get("mfe_points") or 0) for row in rows], 90)) if rows else 0.0,
        "average_r_multiple": float(np.mean([float(row.get("r_multiple") or 0) for row in rows])) if rows else 0.0,
    }


def _quantile_buckets(rows: list[dict[str, object]], source: str, target: str) -> None:
    values = np.asarray([float(row.get(source) or 0) for row in rows], dtype=float)
    if not len(values):
        return
    q25, q50, q75 = np.percentile(values, [25, 50, 75])
    for row, value in zip(rows, values, strict=True):
        row[target] = (
            "Q1_LOW" if value <= q25 else
            "Q2" if value <= q50 else
            "Q3" if value <= q75 else
            "Q4_HIGH"
        )


def _decompose(rows: list[dict[str, object]], field: str) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = str(row.get(field) if row.get(field) is not None else "UNKNOWN")
        groups.setdefault(key, []).append(row)
    return [{"bucket": key, **_metrics(values)} for key, values in sorted(groups.items())]


def _enrich_replay(settings: Settings, replay_run_id: str, symbol: str) -> tuple[dict[str, object], dict[str, object]]:
    boundaries = tuple(float(value.strip()) for value in settings.research_confidence_buckets.split(","))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT r.start_time_utc,r.end_time_utc,r.max_drawdown_pct,r.model_version_id,
                      mv.artifact_path,b.value_per_price_point_zar
               FROM app.replay_runs r JOIN app.broker_market_rules b ON b.market_id=r.market_id
               LEFT JOIN app.model_versions mv ON mv.model_version_id=r.model_version_id
               WHERE r.replay_run_id=%s ORDER BY b.observed_at_utc DESC""", (replay_run_id,),
        )
        run = cursor.fetchone()
        if not run:
            raise ValueError("Persisted replay run was not found")
        model = None
        if run.get("artifact_path"):
            model = joblib.load(str(run["artifact_path"]))["model"]
        cursor.execute(
            """SELECT candle_id,open_time_utc,[open],high,low,[close],tick_count
               FROM app.candles WHERE market_id=(SELECT market_id FROM app.replay_runs WHERE replay_run_id=%s)
                 AND timeframe='M15' AND open_time_utc BETWEEN %s AND %s ORDER BY open_time_utc""",
            (replay_run_id, run["start_time_utc"], run["end_time_utc"]),
        )
        candle_rows = cursor.fetchall()
        frame = pd.DataFrame(candle_rows)
        feature_map: dict[int, pd.Series] = {}
        path_frame = pd.DataFrame()
        if not frame.empty:
            frame["time"] = pd.to_datetime(frame["open_time_utc"], utc=True)
            frame["tick_volume"] = pd.to_numeric(frame["tick_count"], errors="coerce").fillna(0)
            for column in ("open", "high", "low", "close"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            source = frame.set_index("time")[["open", "high", "low", "close", "tick_volume"]]
            path_frame = source[["high", "low"]]
            featured = add_features(source, labelled=False)
            featured["volatility_regime"] = volatility_regimes(featured["atr_pct"])
            if model is not None:
                featured["prediction_probability"] = model.predict_proba(featured[FEATURES])[:, 1]
            candle_lookup = frame.set_index("time")["candle_id"]
            for opened, row in featured.iterrows():
                candle_id = candle_lookup.get(opened)
                if candle_id is not None:
                    feature_map[int(candle_id)] = row
        cursor.execute(
            """SELECT t.*,ec.open_time_utc entry_time,xc.open_time_utc exit_time
               FROM app.replay_trades t JOIN app.candles ec ON ec.candle_id=t.entry_candle_id
               LEFT JOIN app.candles xc ON xc.candle_id=t.exit_candle_id
               WHERE t.replay_run_id=%s ORDER BY t.opened_at_utc""", (replay_run_id,),
        )
        trades = cursor.fetchall()
        cursor.execute(
            """SELECT event_type,COUNT(1) event_count FROM app.replay_events
               WHERE replay_run_id=%s GROUP BY event_type""", (replay_run_id,),
        )
        event_counts = {
            str(row["event_type"]): int(row["event_count"])
            for row in cursor.fetchall()
        }
        enriched: list[dict[str, object]] = []
        value_per_point = Decimal(str(run["value_per_price_point_zar"]))
        for trade in trades:
            entry_time = pd.Timestamp(trade["entry_time"])
            exit_time = pd.Timestamp(trade["exit_time"] or trade["entry_time"])
            if entry_time.tzinfo is None:
                entry_time = entry_time.tz_localize("UTC")
            if exit_time.tzinfo is None:
                exit_time = exit_time.tz_localize("UTC")
            path = path_frame.loc[entry_time:exit_time]
            entry = Decimal(str(trade["entry_price"]))
            low = Decimal(str(path["low"].min())) if not path.empty else entry
            high = Decimal(str(path["high"].max())) if not path.empty else entry
            mae = max(Decimal("0"), entry-low) if trade["direction"] == "BUY" else max(Decimal("0"), high-entry)
            mfe = max(Decimal("0"), high-entry) if trade["direction"] == "BUY" else max(Decimal("0"), entry-low)
            risk = abs(entry-Decimal(str(trade["stop_price"]))) * Decimal(str(trade["size"])) * value_per_point
            r_multiple = Decimal(str(trade["realized_pnl_zar"] or 0)) / risk if risk else Decimal("0")
            holding = max(0, int(((trade["closed_at_utc"] or trade["opened_at_utc"])-trade["opened_at_utc"]).total_seconds() // 60))
            feature = feature_map.get(int(trade["entry_candle_id"]))
            confidence = Decimal("0.5")
            trend = "UNKNOWN"
            volatility = "UNKNOWN"
            if feature is not None:
                trend = trend_regime(float(feature["ema_gap"]), float(feature["atr_pct"]))
                volatility = str(feature["volatility_regime"])
                if model is not None and "prediction_probability" in feature:
                    probability = float(feature["prediction_probability"])
                    confidence = Decimal(str(max(probability, 1-probability)))
            session = market_session(symbol, trade["entry_time"])
            cost = sum(Decimal(str(trade.get(name) or 0)) for name in
                       ("explicit_transaction_cost_zar", "slippage_cost_zar", "funding_cost_zar"))
            cursor.execute(
                """UPDATE app.replay_trades SET mae_points=%s,mfe_points=%s,r_multiple=%s,
                          holding_minutes=%s,prediction_confidence=%s,session_name=%s,
                          trend_regime=%s,volatility_regime=%s,entry_reason=%s
                   WHERE replay_trade_id=%s""",
                (mae, mfe, r_multiple, holding, confidence, session, trend, volatility,
                 "LATEST_MODEL_SIGNAL", str(trade["replay_trade_id"])),
            )
            record = dict(trade)
            record.update({"mae_points": mae, "mfe_points": mfe, "r_multiple": r_multiple,
                           "holding_minutes": holding, "prediction_confidence": confidence,
                           "confidence_bucket": confidence_bucket(float(confidence), boundaries),
                           "session_name": session, "trend_regime": trend,
                           "volatility_regime": volatility, "entry_reason": "LATEST_MODEL_SIGNAL",
                           "entry_hour": trade["entry_time"].hour,
                           "entry_quarter": trade["entry_time"].hour*4+trade["entry_time"].minute//15,
                           "weekday": trade["entry_time"].weekday(), "total_cost_zar": cost})
            enriched.append(record)
        _quantile_buckets(enriched, "spread_cost_zar", "spread_cost_bucket")
        _quantile_buckets(enriched, "mae_points", "mae_bucket")
        _quantile_buckets(enriched, "mfe_points", "mfe_bucket")
        connection.commit()
    summary = {**_metrics(enriched), "long_count": sum(row["direction"] == "BUY" for row in enriched),
               "short_count": sum(row["direction"] == "SELL" for row in enriched),
               "opened_signal_count": event_counts.get("OPENED", 0),
               "minimum_size_rejection_count": event_counts.get("RISK_REJECTED_MINIMUM_SIZE", 0),
               "segment_boundary_exit_count": sum(
                   row.get("exit_reason") == "END_OF_SEGMENT" for row in enriched
               ),
               "maximum_drawdown_pct": str(run["max_drawdown_pct"] or 0),
               "diagnostic_version": DIAGNOSTIC_VERSION}
    decomposition = {field: _decompose(enriched, field) for field in (
        "direction", "session_name", "entry_hour", "entry_quarter", "weekday",
        "trend_regime", "volatility_regime", "confidence_bucket", "entry_reason", "exit_reason",
        "spread_cost_bucket", "mae_bucket", "mfe_bucket",
    )}
    return summary, decomposition


def run_research_replay(
    settings: Settings, tenant_id: str, request: ResearchReplayRequest,
) -> dict[str, object]:
    symbol = request.market.upper()
    sync_cost_models(settings)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1", (symbol,))
        market = cursor.fetchone()
        if not market:
            raise ValueError("Unsupported or disabled research market")
        cursor.execute(
            """SELECT TOP (1) mv.version model_version,sv.version strategy_version,sv.features_version
               FROM app.model_versions mv JOIN app.strategy_versions sv ON sv.strategy_version_id=mv.strategy_version_id
               WHERE mv.market_id=%s ORDER BY mv.registered_at_utc DESC""", (str(market["market_id"]),),
        )
        versions = cursor.fetchone() or {}
        cursor.execute(
            """SELECT TOP (1) version,cost_model_version_id FROM app.cost_model_versions
               WHERE market_id=%s AND status='CURRENT' ORDER BY created_at_utc DESC""", (str(market["market_id"]),),
        )
        cost = cursor.fetchone() or {}
        cursor.execute(
            """SELECT TOP (1) s.equity FROM app.account_snapshots s
               JOIN app.trading_accounts a ON a.trading_account_id=s.trading_account_id
               WHERE a.tenant_id=%s AND s.equity>0 ORDER BY s.observed_at_utc DESC""",
            (tenant_id,),
        )
        equity_row = cursor.fetchone()
        initial_equity = Decimal(str(equity_row["equity"])) if equity_row else Decimal("100000")
    configuration = request.model_dump(mode="json", by_alias=True)
    configuration.update({"model_version": versions.get("model_version"), "label_version": LABEL_VERSION,
                          "regime_version": REGIME_VERSION, "cost_model_version": cost.get("version"),
                          "initial_equity_zar": str(initial_equity)})
    config_hash = hashlib.sha256(json.dumps(configuration, sort_keys=True, default=str).encode()).hexdigest()
    experiment_id = str(uuid4())
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """INSERT app.research_experiments
                 (experiment_id,tenant_id,market_id,strategy_version,feature_version,label_version,
                  model_version,regime_version,cost_model_version,retrain_type,configuration_hash,
                  status,notes)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'DIAGNOSTIC_REPLAY',%s,'RUNNING',%s)""",
            (experiment_id, tenant_id, str(market["market_id"]), versions.get("strategy_version") or "UNKNOWN",
             versions.get("features_version") or "UNKNOWN", LABEL_VERSION,
             versions.get("model_version"), REGIME_VERSION, cost.get("version") or "CONFIGURED_BPS_FALLBACK",
             config_hash, request.notes),
        )
        connection.commit()
    try:
        replay = run_replay(settings, tenant_id, ReplayRequest(
            symbol=symbol, mode="TECHNICAL_DIAGNOSTIC", initial_equity_zar=initial_equity,
            max_candles=request.max_candles, from_utc=request.from_utc, to_utc=request.to_utc,
            segment_mode=request.segment_mode, cost_mode=request.cost_model, use_latest_model=True,
        ))
        replay_id = str(replay["replay_run_id"])
        summary, decomposition = _enrich_replay(settings, replay_id, symbol)
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE app.replay_runs SET experiment_id=%s,cost_model_version_id=%s WHERE replay_run_id=%s",
                           (experiment_id, cost.get("cost_model_version_id"), replay_id))
            cursor.execute(
                """INSERT app.research_diagnostics
                     (research_diagnostic_id,experiment_id,replay_run_id,diagnostic_version,summary_json,decomposition_json)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), experiment_id, replay_id, DIAGNOSTIC_VERSION,
                 json.dumps(summary, default=_serial), json.dumps(decomposition, default=_serial)),
            )
            cursor.execute(
                """UPDATE app.research_experiments SET status='COMPLETED',outcome_json=%s,
                          completed_at_utc=SYSUTCDATETIME() WHERE experiment_id=%s""",
                (json.dumps(summary, default=_serial), experiment_id),
            )
            connection.commit()
        return {"status": "COMPLETED", "experiment_id": experiment_id, **replay,
                "summary": summary, "decomposition": decomposition, "promotable": False,
                "execution_enabled": False}
    except Exception:
        with open_database(settings) as connection:
            cursor = connection.cursor()
            cursor.execute("UPDATE app.research_experiments SET status='FAILED',completed_at_utc=SYSUTCDATETIME() WHERE experiment_id=%s", (experiment_id,))
            connection.commit()
        raise


def read_research_status(settings: Settings, tenant_id: str, limit: int = 20) -> dict[str, object]:
    readiness = model_readiness(settings, tenant_id)
    evidence = read_research_evidence(settings)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) e.experiment_id,m.symbol,e.strategy_version,e.feature_version,
                      e.label_version,e.model_version,e.regime_version,e.cost_model_version,
                      e.retrain_type,e.configuration_hash,e.status,e.notes,e.started_at_utc,
                      e.completed_at_utc,d.summary_json,d.decomposition_json
               FROM app.research_experiments e JOIN app.markets m ON m.market_id=e.market_id
               LEFT JOIN app.research_diagnostics d ON d.experiment_id=e.experiment_id
               WHERE e.tenant_id=%s ORDER BY e.started_at_utc DESC""", (max(1, min(limit, 100)), tenant_id),
        )
        experiments = []
        for row in cursor.fetchall():
            item = {key: _serial(value) for key, value in row.items()
                    if key not in ("summary_json", "decomposition_json")}
            item["summary"] = json.loads(row["summary_json"]) if row.get("summary_json") else None
            item["decomposition"] = json.loads(row["decomposition_json"]) if row.get("decomposition_json") else None
            experiments.append(item)
    return {"status": "RESEARCH_READY", "execution_enabled": False,
            "required_feature_rows": readiness["required_feature_rows"], "markets": readiness["markets"],
            **evidence, "experiments": experiments, "holdout": read_holdout_status(settings, tenant_id),
            "holdout_policy": {"train": "model fitting", "validation": "configuration selection",
                               "holdout": "single final offline assessment; never tune against it",
                               "forward_shadow": "unseen real-time evidence after validation"}}
