from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402


def main() -> None:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.symbol,MIN(CASE WHEN c.timeframe='M5' THEN c.open_time_utc END) earliest_m5,
                      MAX(CASE WHEN c.timeframe='M5' THEN c.open_time_utc END) latest_m5,
                      SUM(CASE WHEN c.timeframe='M5' AND c.spread_close IS NOT NULL THEN 1 ELSE 0 END) spread_rows,
                      MIN(CASE WHEN c.timeframe='M15' THEN c.open_time_utc END) earliest_m15,
                      MAX(CASE WHEN c.timeframe='M15' THEN c.open_time_utc END) latest_m15,
                      SUM(CASE WHEN c.timeframe='M15' AND c.spread_close IS NOT NULL THEN 1 ELSE 0 END) m15_spread_rows,
                      (SELECT TOP (1) q.status FROM app.market_data_quality_runs q
                       WHERE q.market_id=m.market_id AND q.timeframe='M15'
                       ORDER BY q.evaluated_at_utc DESC) quality_status
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
               WHERE m.enabled=1 GROUP BY m.market_id,m.symbol ORDER BY m.symbol"""
        )
        print("MARKETS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT m.symbol,COUNT(DISTINCT CASE WHEN c.timeframe='M15' AND c.completed=1
                                                    AND c.quality_status='PASS' THEN c.candle_id END) m15_rows,
                      (SELECT TOP (1) mv.status FROM app.model_versions mv
                       WHERE mv.market_id=m.market_id ORDER BY mv.registered_at_utc DESC) model_status,
                      (SELECT TOP (1) es.mode FROM app.market_execution_states es
                       WHERE es.market_id=m.market_id ORDER BY es.changed_at_utc DESC) execution_mode,
                      COUNT(DISTINCT r.broker_market_rule_id) broker_rule_rows
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
               LEFT JOIN app.broker_market_rules r ON r.market_id=m.market_id
               WHERE m.enabled=1 GROUP BY m.market_id,m.symbol ORDER BY m.symbol"""
        )
        print("READINESS_EVIDENCE")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """WITH latest AS (
                   SELECT q.*,ROW_NUMBER() OVER (
                       PARTITION BY q.market_id ORDER BY q.evaluated_at_utc DESC
                   ) evidence_rank
                   FROM app.execution_quality_snapshots q
               )
               SELECT m.symbol,q.historical_research_quality,q.training_quality,
                      q.recent_ig_continuity,q.cross_provider_continuity,
                      q.execution_price_freshness,q.overall_execution_quality,
                      q.recent_unexpected_gap_count,q.m5_fresh,q.m15_fresh,
                      q.bid_fresh,q.ask_fresh,q.spread_fresh,q.broker_rules_fresh,
                      q.market_session_valid,q.evaluated_at_utc
               FROM latest q JOIN app.markets m ON m.market_id=q.market_id
               WHERE q.evidence_rank=1 ORDER BY m.symbol"""
        )
        print("RESEARCH_QUALITY")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT m.symbol,c.version,c.observation_count,c.status,c.created_at_utc
               FROM app.cost_model_versions c JOIN app.markets m ON m.market_id=c.market_id
               WHERE c.status='CURRENT' ORDER BY m.symbol"""
        )
        print("COST_MODELS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) m.symbol,h.provider,h.file_name,h.price_side,
                      h.source_start_utc,h.source_end_utc,h.rows_read,h.accepted_m5,
                      h.accepted_m15,h.invalid_rows,h.persisted_m5,h.persisted_m15,
                      h.status,h.imported_at_utc
               FROM app.historical_import_runs h
               JOIN app.markets m ON m.market_id=h.market_id
               ORDER BY h.imported_at_utc DESC"""
        )
        print("HISTORICAL_IMPORTS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (12) m.symbol,c.timeframe,c.open_time_utc,c.bid_close,c.ask_close,
                      c.spread_close,c.is_regular_session
               FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id
               WHERE c.spread_close IS NOT NULL ORDER BY c.open_time_utc DESC,m.symbol"""
        )
        print("LATEST_SPREAD_EVIDENCE")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT alert_key,severity,status,summary,last_notified_at_utc
               FROM app.operational_alerts ORDER BY last_seen_at_utc DESC"""
        )
        print("ALERTS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (5) status,backup_file,backup_size_bytes,restore_verified_at_utc
               FROM app.backup_verifications ORDER BY created_at_utc DESC"""
        )
        print("BACKUPS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (5) r.replay_run_id,m.symbol,r.mode,r.candle_count,r.trade_count,
                      r.realized_pnl_zar,r.max_drawdown_pct,r.promotable,r.non_promotable_reason
               FROM app.replay_runs r JOIN app.markets m ON m.market_id=r.market_id
               ORDER BY r.started_at_utc DESC"""
        )
        print("REPLAY_RUNS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (20) e.experiment_id,m.symbol,e.retrain_type,e.model_version,
                      e.cost_model_version,e.status,e.started_at_utc,e.completed_at_utc
               FROM app.research_experiments e JOIN app.markets m ON m.market_id=e.market_id
               ORDER BY e.started_at_utc DESC"""
        )
        print("RESEARCH_EXPERIMENTS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) c.holdout_candidate_id,m.symbol,c.candidate_version,
                      c.development_rows,c.holdout_rows,c.validation_passed,c.status,
                      c.holdout_consumed_at_utc,c.evaluated_at_utc,e.result,e.trade_count,
                      e.profit_factor,e.expectancy,e.max_drawdown
               FROM app.holdout_candidates c JOIN app.markets m ON m.market_id=c.market_id
               LEFT JOIN app.holdout_evaluations e ON e.holdout_candidate_id=c.holdout_candidate_id
               ORDER BY c.frozen_at_utc DESC"""
        )
        print("HOLDOUT_CANDIDATES")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) replay_run_id,direction,spread_cost_zar,spread_cost_in_price,
                      explicit_transaction_cost_zar,slippage_cost_zar,funding_cost_zar,
                      realized_pnl_zar,exit_reason
               FROM app.replay_trades ORDER BY opened_at_utc DESC"""
        )
        print("REPLAY_COST_EVIDENCE")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """WITH ranked AS (
                   SELECT f.*,
                          ROW_NUMBER() OVER (
                              PARTITION BY f.tenant_id,f.market_id
                              ORDER BY f.captured_at_utc DESC,f.forward_evidence_snapshot_id DESC
                          ) AS evidence_rank
                   FROM app.forward_evidence_snapshots f
               )
               SELECT m.symbol,f.evidence_state,f.feature_complete_rows,
                      f.required_feature_rows,f.quality_status,f.model_status,f.market_decision,
                      f.decision_blocker,f.risk_status,f.reconciliation_clear,f.shadow_open_count,
                      f.shadow_closed_count,f.shadow_realized_pnl_zar,f.blockers_json,f.latest_m15_utc,
                      f.captured_at_utc
               FROM ranked f JOIN app.markets m ON m.market_id=f.market_id
               WHERE f.evidence_rank=1
               ORDER BY m.symbol"""
        )
        print("FORWARD_EVIDENCE")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT p.policy_version,p.minimum_closed_trades,p.minimum_trading_days,
                      p.minimum_profit_factor,p.minimum_expectancy_zar,p.maximum_drawdown_pct,
                      p.maximum_consecutive_losses,p.require_cost_evidence,p.active
               FROM app.forward_shadow_policies p WHERE p.active=1 ORDER BY p.tenant_id"""
        )
        print("FORWARD_SHADOW_POLICY")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) m.symbol,e.closed_trades,e.trading_days,e.profit_factor,
                      e.expectancy_zar,e.maximum_drawdown_pct,e.maximum_consecutive_losses,
                      e.cost_evidence_coverage,e.passed,e.blockers_json,e.evaluated_at_utc
               FROM app.forward_shadow_evaluations e
               JOIN app.markets m ON m.market_id=e.market_id
               ORDER BY e.evaluated_at_utc DESC"""
        )
        print("FORWARD_SHADOW_EVALUATIONS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) m.symbol,a.status,a.submission_count,a.failure_code,
                      a.started_at_utc,a.completed_at_utc
               FROM app.demo_execution_attempts a JOIN app.markets m ON m.market_id=a.market_id
               ORDER BY a.started_at_utc DESC"""
        )
        print("DEMO_EXECUTION_ATTEMPTS")
        for row in cursor.fetchall():
            print(row)
        cursor.execute(
            """SELECT TOP (10) report_date_sast,recipient_email,status,claimed_at_utc,
                      sent_at_utc,failed_at_utc,failure_code
               FROM app.daily_progress_reports
               ORDER BY report_date_sast DESC,claimed_at_utc DESC"""
        )
        print("DAILY_PROGRESS_REPORTS")
        for row in cursor.fetchall():
            print(row)


if __name__ == "__main__":
    main()
