from __future__ import annotations

from datetime import timezone

from app.config import Settings
from app.database import open_database


def read_model_validation(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.symbol,mv.version,mv.status,me.model_evaluation_id,me.validation_auc,
                      me.training_rows,me.validation_rows,me.walk_forward_windows,me.trade_count,
                      me.win_rate,me.profit_factor,me.expectancy,me.max_drawdown,me.sharpe_ratio,
                      me.sortino_ratio,me.precision_buy,me.precision_sell,me.baseline_outperformed,
                      me.cost_assumption_bps,me.result,me.failure_reason,me.evaluated_at_utc,
                      me.brier_score,me.calibration_error,me.feature_drift_score,me.regime_coverage
               FROM app.markets m OUTER APPLY
                 (SELECT TOP 1 * FROM app.model_versions x WHERE x.market_id=m.market_id
                  ORDER BY x.registered_at_utc DESC) mv
               LEFT JOIN app.model_evaluations me ON me.model_version_id=mv.model_version_id
               WHERE m.enabled=1 ORDER BY m.symbol"""
        )
        models = []
        for row in cursor.fetchall():
            windows: list[dict[str, object]] = []
            baselines: list[dict[str, object]] = []
            regimes: list[dict[str, object]] = []
            if row["model_evaluation_id"]:
                cursor.execute(
                    """SELECT window_number,training_rows,validation_rows,auc,trade_count,win_rate,
                              profit_factor,expectancy,max_drawdown,validation_start_utc,validation_end_utc
                       FROM app.model_walk_forward_windows WHERE model_evaluation_id=%s ORDER BY window_number""",
                    (str(row["model_evaluation_id"]),),
                )
                windows = [{name: (value.isoformat() + "Z" if hasattr(value, "isoformat") else str(value)
                                    if value is not None else None)
                            for name, value in item.items()} for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT baseline_name,trade_count,win_rate,profit_factor,expectancy,max_drawdown
                       FROM app.model_baseline_results WHERE model_evaluation_id=%s ORDER BY baseline_name""",
                    (str(row["model_evaluation_id"]),),
                )
                baselines = [{name: str(value) if value is not None else None for name, value in item.items()}
                             for item in cursor.fetchall()]
                cursor.execute(
                    """SELECT regime_name,observation_count,trade_count,win_rate,expectancy
                       FROM app.model_regime_results WHERE model_evaluation_id=%s ORDER BY regime_name""",
                    (str(row["model_evaluation_id"]),),
                )
                regimes = [{name: str(value) if value is not None else None for name, value in item.items()}
                           for item in cursor.fetchall()]
            models.append({
                "market": row["symbol"], "version": row["version"], "status": row["status"],
                "evaluation_result": row["result"], "training_rows": row["training_rows"],
                "validation_rows": row["validation_rows"], "walk_forward_windows": row["walk_forward_windows"],
                "auc": str(row["validation_auc"]) if row["validation_auc"] is not None else None,
                "trade_count": row["trade_count"], "win_rate": str(row["win_rate"]) if row["win_rate"] is not None else None,
                "profit_factor": str(row["profit_factor"]) if row["profit_factor"] is not None else None,
                "expectancy": str(row["expectancy"]) if row["expectancy"] is not None else None,
                "max_drawdown": str(row["max_drawdown"]) if row["max_drawdown"] is not None else None,
                "sharpe_ratio": str(row["sharpe_ratio"]) if row["sharpe_ratio"] is not None else None,
                "sortino_ratio": str(row["sortino_ratio"]) if row["sortino_ratio"] is not None else None,
                "baseline_outperformed": bool(row["baseline_outperformed"]) if row["baseline_outperformed"] is not None else None,
                "cost_assumption_bps": str(row["cost_assumption_bps"]) if row["cost_assumption_bps"] is not None else None,
                "failure_reason": row["failure_reason"],
                "brier_score": str(row["brier_score"]) if row["brier_score"] is not None else None,
                "calibration_error": str(row["calibration_error"]) if row["calibration_error"] is not None else None,
                "feature_drift_score": str(row["feature_drift_score"]) if row["feature_drift_score"] is not None else None,
                "regime_coverage": str(row["regime_coverage"]) if row["regime_coverage"] is not None else None,
                "windows": windows, "baselines": baselines, "regimes": regimes,
            })
    return {"models": models, "promotion_policy": "AUC_AND_POSITIVE_COST_AWARE_EXPECTANCY_AND_BASELINE_OUTPERFORMANCE"}


def read_shadow_trades(settings: Settings, tenant_id: str, *, limit: int = 50) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) st.shadow_trade_id,m.symbol,st.direction,st.size,st.entry_price,
                      st.stop_price,st.target_price,st.current_price,st.unrealized_pnl_zar,
                      st.exit_price,st.realized_pnl_zar,st.exit_reason,st.status,st.opened_at_utc,
                      st.closed_at_utc,st.estimated_entry_cost_zar
               FROM app.shadow_trades st JOIN app.markets m ON m.market_id=st.market_id
               WHERE st.tenant_id=%s ORDER BY st.opened_at_utc DESC""", (max(1, min(limit, 200)), tenant_id),
        )
        trades = [{name: (value.replace(tzinfo=timezone.utc).isoformat() if hasattr(value, "tzinfo")
                            else str(value) if value is not None else None) for name, value in row.items()}
                  for row in cursor.fetchall()]
    return {"count": len(trades), "environment": "SHADOW", "trades": trades}


def read_order_intents(settings: Settings, tenant_id: str, *, limit: int = 50) -> dict[str, object]:
    limit = max(1, min(limit, 200))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) oi.order_intent_id,m.symbol,oi.direction,oi.calculated_size,
                      oi.stop_level,oi.take_profit_level,oi.risk_amount_zar,oi.status,
                      oi.client_reference,oi.created_at_utc,oi.updated_at_utc,
                      s.confidence,rd.reason_code
               FROM app.order_intents oi
               JOIN app.markets m ON m.market_id=oi.market_id
               JOIN app.signals s ON s.signal_id=oi.signal_id
               JOIN app.risk_decisions rd ON rd.risk_decision_id=oi.risk_decision_id
               WHERE oi.tenant_id=%s ORDER BY oi.created_at_utc DESC""",
            (limit, tenant_id),
        )
        rows = cursor.fetchall()
    return {
        "count": len(rows),
        "orders": [
            {
                "order_intent_id": str(row["order_intent_id"]),
                "market": str(row["symbol"]),
                "direction": str(row["direction"]),
                "size": str(row["calculated_size"]),
                "stop": str(row["stop_level"]),
                "take_profit": str(row["take_profit_level"]),
                "risk_zar": str(row["risk_amount_zar"]),
                "status": str(row["status"]),
                "client_reference": str(row["client_reference"]),
                "confidence": str(row["confidence"]),
                "risk_reason": str(row["reason_code"]),
                "created_at_utc": row["created_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
                "updated_at_utc": row["updated_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
                "broker_submission": False if row["status"] == "WOULD_SUBMIT" else None,
            }
            for row in rows
        ],
    }


def read_risk_status(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (1) rv.risk_per_trade_pct,rv.daily_loss_limit_pct,
                      rv.max_open_positions,rv.max_positions_per_market,rv.max_consecutive_losses,
                      rv.preferred_daily_return_pct,rv.profit_protection_pct,
                      rv.daily_profit_lock_pct,rv.max_portfolio_risk_pct,
                      rv.max_intraday_drawdown_pct,rv.profit_giveback_limit_pct,
                      rv.max_trades_per_day,rv.min_reward_risk_ratio,
                      l.ledger_date_sast,l.opening_equity_zar,l.current_equity_zar,
                      l.realized_pnl_zar,l.unrealized_pnl_zar,l.reserved_risk_zar,
                      l.daily_drawdown_pct,l.consecutive_losses,l.peak_equity_zar,
                      l.intraday_drawdown_pct,l.daily_return_pct,l.peak_daily_return_pct,
                      l.profit_protection_state,l.status,l.status_reason,
                      l.last_reconciled_at_utc
               FROM app.risk_versions rv
               LEFT JOIN app.trading_accounts ta ON ta.tenant_id=rv.tenant_id
               LEFT JOIN app.daily_risk_ledger l ON l.trading_account_id=ta.trading_account_id
                 AND l.ledger_date_sast=CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time' AS date)
               WHERE rv.tenant_id=%s AND rv.active=1 ORDER BY ta.created_at_utc""",
            (tenant_id,),
        )
        row = cursor.fetchone()
    if not row:
        return {"status": "BLOCKED", "reason": "NO_ACTIVE_RISK_POLICY", "policy": None, "ledger": None}
    ledger = None
    if row["ledger_date_sast"]:
        ledger = {
            "date_sast": row["ledger_date_sast"].isoformat(),
            "opening_equity_zar": str(row["opening_equity_zar"]),
            "current_equity_zar": str(row["current_equity_zar"]),
            "realized_pnl_zar": str(row["realized_pnl_zar"]),
            "unrealized_pnl_zar": str(row["unrealized_pnl_zar"]),
            "reserved_risk_zar": str(row["reserved_risk_zar"]),
            "daily_drawdown_pct": str(row["daily_drawdown_pct"]),
            "peak_equity_zar": str(row["peak_equity_zar"] or row["current_equity_zar"]),
            "intraday_drawdown_pct": str(row["intraday_drawdown_pct"]),
            "daily_return_pct": str(row["daily_return_pct"]),
            "peak_daily_return_pct": str(row["peak_daily_return_pct"]),
            "profit_protection_state": str(row["profit_protection_state"]),
            "consecutive_losses": int(row["consecutive_losses"]),
            "status": str(row["status"]),
            "reason": row["status_reason"],
            "last_reconciled_at_utc": row["last_reconciled_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
        }
    return {
        "status": str(row["status"]) if ledger else "BLOCKED",
        "reason": row["status_reason"] if ledger else "DAILY_RISK_LEDGER_MISSING",
        "policy": {
            "risk_per_trade_pct": str(row["risk_per_trade_pct"]),
            "daily_loss_limit_pct": str(row["daily_loss_limit_pct"]),
            "max_open_positions": int(row["max_open_positions"]),
            "max_positions_per_market": int(row["max_positions_per_market"]),
            "max_consecutive_losses": int(row["max_consecutive_losses"]),
            "preferred_daily_return_pct": str(row["preferred_daily_return_pct"]),
            "profit_protection_pct": str(row["profit_protection_pct"]),
            "daily_profit_lock_pct": str(row["daily_profit_lock_pct"]),
            "max_portfolio_risk_pct": str(row["max_portfolio_risk_pct"]),
            "max_intraday_drawdown_pct": str(row["max_intraday_drawdown_pct"]),
            "profit_giveback_limit_pct": str(row["profit_giveback_limit_pct"]),
            "max_trades_per_day": int(row["max_trades_per_day"]),
            "min_reward_risk_ratio": str(row["min_reward_risk_ratio"]),
            "profit_objective_authority": "INFORMATIONAL_ONLY",
        },
        "ledger": ledger,
    }


def read_reconciliation_status(settings: Settings, tenant_id: str, *, limit: int = 50) -> dict[str, object]:
    limit = max(1, min(limit, 200))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (%s) reconciliation_issue_id,issue_type,status,
                      broker_reference_masked,detail,first_seen_at_utc,last_seen_at_utc,resolved_at_utc
               FROM app.reconciliation_issues WHERE tenant_id=%s
               ORDER BY CASE WHEN status='RESOLVED' THEN 1 ELSE 0 END,last_seen_at_utc DESC""",
            (limit, tenant_id),
        )
        rows = cursor.fetchall()
    issues = [
        {
            "id": str(row["reconciliation_issue_id"]),
            "type": str(row["issue_type"]),
            "status": str(row["status"]),
            "broker_reference": row["broker_reference_masked"],
            "detail": str(row["detail"]),
            "first_seen_at_utc": row["first_seen_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
            "last_seen_at_utc": row["last_seen_at_utc"].replace(tzinfo=timezone.utc).isoformat(),
            "resolved_at_utc": row["resolved_at_utc"].replace(tzinfo=timezone.utc).isoformat()
                if row["resolved_at_utc"] else None,
        }
        for row in rows
    ]
    unresolved = sum(1 for item in issues if item["status"] != "RESOLVED")
    return {"status": "CLEAR" if unresolved == 0 else "BLOCKED", "unresolved": unresolved, "issues": issues}
