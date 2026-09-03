import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, switchMap } from 'rxjs';

export interface PortfolioData {
  currency: 'ZAR';
  equity: string;
  balance: string;
  available_funds: string;
  margin_used: string;
  profit_loss: string;
  observed_at_utc: string | null;
  source_equity: string;
  source_balance: string;
  source_available_funds: string;
  source_margin_used: string;
  source_profit_loss: string;
  conversion: null | {
    source_currency: string;
    rate: string;
    source: string;
    observed_at_utc: string;
  };
}

export interface DashboardData {
  locale: string;
  timezone: string;
  reporting_currency: 'ZAR';
  data_status: 'current' | 'awaiting_ig_sync';
  portfolio: PortfolioData;
  account: null | {
    name: string;
    masked_id: string;
    source_currency: string;
    environment: 'demo';
  };
  open_positions: number;
  positions: Array<{
    market: string;
    direction: 'BUY' | 'SELL';
    entry_price: string;
    current_price: string | null;
    profit_loss: string;
    currency: string;
    status: string;
  }>;
  performance: Array<{ equity: string; observed_at_utc: string }>;
  components: Array<{ code: string; name: string; status: string; detail: string }>;
  safety: { trading_mode: string; broker_environment: string; live_trading_allowed: false };
}

export interface MarketCandle {
  open_time_utc: string;
  open_time_sast: string;
  open: string;
  high: string;
  low: string;
  close: string;
  bid_close: string | null;
  ask_close: string | null;
  spread_close: string | null;
  is_regular_session: boolean;
  tick_count: number;
  source: string;
}

export interface MarketCandlesData {
  symbol: string;
  timeframe: 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1';
  timezone: 'Africa/Johannesburg';
  session_date: string | null;
  period: 'TODAY' | '7D' | 'ALL';
  candles: MarketCandle[];
}

export interface MarketInventoryData {
  markets: Array<{
    symbol: string;
    display_name: string;
    asset_class: 'FX' | 'INDEX' | 'METAL';
    ig_epic: string;
    base_currency: string;
    quote_currency: string;
    price_digits: number;
    calendar_code: string;
    market_timezone: string;
    tier: 1 | 2 | 3;
    research_enabled: boolean;
    training_enabled: boolean;
    signal_enabled: boolean;
    demo_trading_enabled: boolean;
    live_trading_enabled: boolean;
    reporting_currency: string;
    pip_size: string | null;
    tick_size: string | null;
    max_spread_bps: string | null;
    slippage_assumption_bps: string | null;
    default_timeframe: string;
    confirmation_timeframe: string;
    risk_profile: string;
    eligibility: string;
    execution_promotion_required: boolean;
    broker_instrument_type: string;
    broker_resolved_at_utc: string | null;
  }>;
  timeframes: Array<'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D1'>;
  periods: Array<'TODAY' | '7D' | 'ALL'>;
  execution_enabled: false;
}

export interface TradeHistoryData {
  count: number;
  pnl_note: string;
  trades: Array<{
    position_id: string;
    market: string;
    direction: 'BUY' | 'SELL';
    size: string;
    entry_price: string;
    exit_price: string | null;
    last_recorded_pnl: string;
    pnl_currency: string;
    opened_at_utc: string;
    closed_at_utc: string | null;
    status: string;
  }>;
}

export interface TradingReadinessData {
  status: 'READY' | 'NOT_READY';
  execution_mode: 'DEMO_AUTO' | 'SHADOW_OR_PAUSED';
  evaluated_at_utc: string;
  checks: Record<string, { ready: boolean; status: string; detail: string }>;
  blockers: string[];
}

export interface ModelReadinessData {
  required_feature_rows: number;
  markets: Array<{
    symbol: string;
    display_name: string;
    required_rows: number;
    raw_m15_rows: number;
    feature_complete_rows: number;
    progress_pct: number;
    earliest_candle_utc: string | null;
    latest_candle_utc: string | null;
    quality_status: string;
    training_status: string;
    historical_research_quality: string;
    training_quality: string;
    cross_provider_continuity: string;
    model_status: string;
    model_version: string | null;
    execution_mode: string;
    demo_auto_ready: boolean;
    validation_evidence: {
      result: string | null;
      auc: string | null;
      expectancy: string | null;
      profit_factor: string | null;
      baseline_outperformed: boolean;
    };
    forward_shadow: {
      status: string;
      passed: boolean;
      closed_trades: number;
      trading_days: number;
      profit_factor: string;
      expectancy_zar: string;
      maximum_drawdown_pct: string;
      maximum_consecutive_losses: number;
      cost_evidence_coverage: string;
      blockers: string[];
      policy: null | {
        minimum_closed_trades: number;
        minimum_trading_days: number;
        minimum_profit_factor: string;
        minimum_expectancy_zar: string;
        maximum_drawdown_pct: string;
        maximum_consecutive_losses: number;
        require_cost_evidence: boolean;
      };
    };
    checks: Record<string, boolean | string | null>;
  }>;
}

export interface ModelValidationData {
  promotion_policy: string;
  models: Array<{
    market: string;
    version: string | null;
    status: string | null;
    evaluation_result: string | null;
    training_rows: number | null;
    validation_rows: number | null;
    walk_forward_windows: number | null;
    auc: string | null;
    trade_count: number | null;
    win_rate: string | null;
    profit_factor: string | null;
    expectancy: string | null;
    max_drawdown: string | null;
    sharpe_ratio: string | null;
    sortino_ratio: string | null;
    baseline_outperformed: boolean | null;
    cost_assumption_bps: string | null;
    failure_reason: string | null;
    brier_score: string | null;
    calibration_error: string | null;
    feature_drift_score: string | null;
    regime_coverage: string | null;
    windows: Array<Record<string, string | null>>;
    baselines: Array<Record<string, string | null>>;
    regimes: Array<Record<string, string | null>>;
  }>;
}

export interface ReplayRunsData {
  runs: Array<{
    replay_run_id: string;
    symbol: string;
    mode: string;
    status: string;
    candle_count: string;
    trade_count: string;
    initial_equity_zar: string;
    final_equity_zar: string;
    realized_pnl_zar: string;
    max_drawdown_pct: string;
    promotable: string;
    non_promotable_reason: string | null;
    started_at_utc: string;
    completed_at_utc: string | null;
  }>;
}

export interface ForwardEvidenceData {
  policy: 'FORWARD_EVIDENCE_NEVER_OVERRIDES_VALIDATION_OR_RISK_GATES';
  latest: ForwardEvidenceSnapshot[];
  snapshots: ForwardEvidenceSnapshot[];
}

export interface ForwardEvidenceSnapshot {
  forward_evidence_snapshot_id: string;
  symbol: string;
  evidence_date_sast: string;
  first_m15_utc: string | null;
  latest_m15_utc: string;
  raw_m15_rows: number;
  feature_complete_rows: number;
  required_feature_rows: number;
  spread_evidence_rows: number;
  quality_status: string;
  model_status: string;
  market_decision: 'BUY' | 'SELL' | 'HOLD' | 'NONE';
  decision_executable: boolean;
  decision_blocker: string | null;
  execution_mode: string;
  risk_status: string;
  reconciliation_clear: boolean;
  shadow_open_count: number;
  shadow_closed_count: number;
  shadow_win_count: number;
  shadow_loss_count: number;
  shadow_realized_pnl_zar: string;
  shadow_unrealized_pnl_zar: string;
  evidence_state: 'ACCUMULATING' | 'BLOCKED' | 'FORWARD_SHADOW' | 'DEMO_TEST_READY';
  blockers: string[];
  captured_at_utc: string;
}

export interface ShadowTradesData {
  count: number;
  environment: 'SHADOW';
  trades: Array<{
    shadow_trade_id: string;
    symbol: string;
    direction: string;
    size: string;
    entry_price: string;
    stop_price: string;
    target_price: string;
    current_price: string;
    unrealized_pnl_zar: string;
    exit_price: string | null;
    realized_pnl_zar: string | null;
    exit_reason: string | null;
    status: string;
    opened_at_utc: string;
    closed_at_utc: string | null;
    estimated_entry_cost_zar: string;
  }>;
}

export interface ShadowPerformanceData {
  days: number;
  zero_trade_days_included: boolean;
  execution_enabled: false;
  daily: Array<{ evidence_date: string; symbol: string; candidate_count: number;
    rejected_count: number; opened_count: number; closed_count: number; wins: number;
    losses: number; net_pnl: string; average_net_r: string | null;
    maximum_mfe: string; maximum_mae: string }>;
}

export interface OrderIntentsData {
  count: number;
  orders: Array<{
    order_intent_id: string;
    market: string;
    direction: 'BUY' | 'SELL';
    size: string;
    stop: string;
    take_profit: string;
    risk_zar: string;
    status: string;
    client_reference: string;
    confidence: string;
    risk_reason: string;
    created_at_utc: string;
    updated_at_utc: string;
    broker_submission: boolean | null;
  }>;
}

export interface RiskStatusData {
  status: string;
  reason: string | null;
  policy: null | {
    risk_per_trade_pct: string;
    daily_loss_limit_pct: string;
    max_open_positions: number;
    max_positions_per_market: number;
    max_consecutive_losses: number;
    preferred_daily_return_pct: null;
    profit_protection_pct: string;
    daily_profit_lock_pct: string;
    max_portfolio_risk_pct: string;
    max_intraday_drawdown_pct: string;
    profit_giveback_limit_pct: string;
    max_trades_per_day: number;
    min_reward_risk_ratio: string;
    profit_objective_authority: 'NONE_NO_FORCED_TRADING';
  };
  ledger: null | {
    date_sast: string;
    opening_equity_zar: string;
    current_equity_zar: string;
    realized_pnl_zar: string;
    unrealized_pnl_zar: string;
    reserved_risk_zar: string;
    daily_drawdown_pct: string;
    peak_equity_zar: string;
    intraday_drawdown_pct: string;
    daily_return_pct: string;
    peak_daily_return_pct: string;
    profit_protection_state: string;
    source_currency: string | null;
    risk_return_basis: string;
    opening_equity_source: string | null;
    current_equity_source: string | null;
    peak_equity_source: string | null;
    consecutive_losses: number;
    status: string;
    reason: string | null;
    last_reconciled_at_utc: string;
  };
}

export interface ReconciliationData {
  status: 'CLEAR' | 'BLOCKED';
  unresolved: number;
  issues: Array<{
    id: string;
    type: string;
    status: string;
    broker_reference: string | null;
    detail: string;
    first_seen_at_utc: string;
    last_seen_at_utc: string;
    resolved_at_utc: string | null;
  }>;
}

export interface OperationsStatusData {
  status: 'HEALTHY' | 'ATTENTION';
  open_alert_count: number;
  component_summary: { healthy: number; total: number };
  latest_backup: null | {
    backup_file: string;
    status: string;
    backup_size_bytes: number | null;
    backup_completed_at_utc: string | null;
    restore_verified_at_utc: string | null;
    detail: string | null;
  };
  latest_verified_restore: null | {
    backup_file: string;
    status: string;
    backup_completed_at_utc: string | null;
    restore_verified_at_utc: string | null;
    detail: string | null;
  };
  latest_daily_report: null | {
    report_date_sast: string;
    recipient_email: string;
    subject: string;
    status: string;
    claimed_at_utc: string;
    sent_at_utc: string | null;
    failed_at_utc: string | null;
    failure_code: string | null;
  };
  components: Array<{
    component_code: string;
    display_name: string;
    status: string;
    status_detail: string;
    checked_at_utc: string;
  }>;
  alerts: Array<{
    alert_key: string;
    severity: string;
    status: string;
    summary: string;
    detail: string | null;
    last_seen_at_utc: string;
    occurrence_count: number;
  }>;
  backups: Array<{
    backup_file: string;
    status: string;
    backup_completed_at_utc: string | null;
    restore_verified_at_utc: string | null;
  }>;
  daily_reports: Array<{
    report_date_sast: string;
    recipient_email: string;
    status: string;
    sent_at_utc: string | null;
    failure_code: string | null;
  }>;
  safety: {
    trading_mode: string;
    live_trading_allowed: false;
    reporting_has_execution_authority: false;
  };
}

export interface TradingStatusData {
  environment: 'DEMO';
  mode: 'READ_ONLY' | 'SHADOW' | 'DEMO_AUTO' | 'PAUSED';
  new_orders_enabled: boolean;
  pause_reason: string | null;
}

export interface StrategiesData {
  strategies: Array<{
    id: string;
    name: string;
    environment: 'DEMO';
    status: 'ACTIVE' | 'PAUSED';
    version: string;
    timeframe: string;
    buy_threshold: string;
    sell_threshold: string;
    features_version: string;
    validated_models: number;
    enabled_markets: number;
  }>;
}

export interface MacroStatusData {
  status: 'CURRENT' | 'STALE';
  execution_authority: 'DETERMINISTIC_RISK_ENGINE';
  sources: Array<{
    source_code: string;
    institution: string;
    currency: string;
    evidence_type: string;
    source_url: string;
    enabled: boolean;
    last_attempt_at_utc: string | null;
    last_success_at_utc: string | null;
    last_http_status: number | null;
    last_error_code: string | null;
  }>;
  currencies: Array<{
    currency: string;
    as_of_utc: string;
    policy_score: string;
    inflation_score: string;
    event_risk_score: string;
    composite_score: string;
    evidence_count: number;
    valid_until_utc: string;
    evidence: Array<{ id: string; title: string; url: string; classification: string }>;
  }>;
  decisions: Array<{
    symbol: string;
    decision: 'BUY' | 'SELL' | 'HOLD';
    technical_score: string;
    model_score: string | null;
    macro_score: string;
    event_risk_score: string;
    combined_score: string;
    confidence: string;
    executable: boolean;
    blocker: string | null;
    generated_at_utc: string;
    evidence: Record<string, unknown>;
  }>;
}

export interface ResearchMarket {
  symbol: string;
  display_name: string;
  feature_complete_rows: number;
  required_rows: number;
  historical_research_quality: string;
  training_quality: string;
  cross_provider_continuity: string;
  quality_status: string;
  model_status: string;
  model_version: string | null;
  training_status: string;
  execution_mode: string;
  demo_auto_ready: boolean;
  tier: 1 | 2 | 3;
  asset_class: string;
  research_enabled: boolean;
  training_enabled: boolean;
  signal_enabled: boolean;
  demo_trading_enabled: boolean;
  live_trading_enabled: boolean;
  risk_profile: string;
  eligibility: string;
  execution_promotion_required: boolean;
  checks: Record<string, unknown>;
}

export interface ResearchExperiment {
  experiment_id: string;
  symbol: string;
  strategy_version: string;
  feature_version: string;
  label_version: string;
  model_version: string | null;
  regime_version: string;
  cost_model_version: string;
  retrain_type: string;
  status: string;
  notes: string | null;
  started_at_utc: string;
  completed_at_utc: string | null;
  summary: Record<string, number | string> | null;
  decomposition: Record<string, Array<Record<string, number | string>>> | null;
}

export interface HoldoutCandidate {
  holdout_candidate_id: string;
  symbol: string;
  candidate_version: string;
  development_rows: number;
  holdout_rows: number;
  validation_passed: boolean;
  status: string;
  holdout_start_utc: string;
  holdout_end_utc: string;
  holdout_consumed_at_utc: string | null;
  evaluated_at_utc: string | null;
  validation: Record<string, unknown>;
  metrics: Record<string, number | string> | null;
  gates: Record<string, boolean> | null;
}

export interface HoldoutStatusData {
  status: 'HOLDOUT_ENFORCED';
  policy_version: string;
  single_use: true;
  candidates: HoldoutCandidate[];
  blocked_attempts: Array<{
    experiment_id: string;
    symbol: string;
    status: string;
    started_at_utc: string;
    completed_at_utc: string | null;
    outcome: {
      status: string;
      reason: string;
      available_development_rows: number;
      required_development_rows: number;
      available_holdout_rows: number;
      required_holdout_rows: number;
      holdout_consumed: false;
    } | null;
  }>;
  promotable: false;
  forward_shadow_enabled: false;
  execution_enabled: false;
}

export interface ResearchStatusData {
  status: 'RESEARCH_READY';
  execution_enabled: false;
  required_feature_rows: number;
  markets: ResearchMarket[];
  execution_quality: Array<{
    symbol: string;
    historical_research_quality: string;
    training_quality: string;
    recent_ig_continuity: string;
    execution_price_freshness: string;
    cross_provider_continuity: string;
    overall_execution_quality: string;
    recent_unexpected_gap_count: number;
    evaluated_at_utc: string;
  }>;
  cost_models: Array<{
    symbol: string;
    version: string;
    observation_count: number;
    status: string;
    source_start_utc: string;
    source_end_utc: string;
  }>;
  experiments: ResearchExperiment[];
  holdout: HoldoutStatusData;
  selective_protocol: {
    protocol_version: string;
    execution_enabled: false;
    holdout_policy: string;
    target_specifications: Array<{
      symbol: string;
      target_mode: string;
      horizon_bars: number;
      target_version: string;
      target_sha256: string;
      passed: boolean | null;
      source_rows: number | null;
      feature_rows: number | null;
      gates: Record<string, boolean> | null;
      evaluated_at_utc: string | null;
    }>;
    lifecycle_events: Array<{
      candidate_lifecycle_event_id: string;
      symbol: string;
      from_state: string;
      to_state: string;
      transition_reason: string;
      evidence_sha256: string;
      changed_at_utc: string;
    }>;
    lineages: Array<{
      research_lineage_id: string;
      symbol: string;
      hypothesis: string;
      model_families: string[];
      status: string;
      development_start_utc: string;
      development_end_utc: string;
      holdout_start_utc: string;
      holdout_end_utc: string;
      created_at_utc: string;
      target_mode: string;
      horizon_bars: number;
      target_sha256: string;
    }>;
  };
  data_operations: {
    quarantine_summary: Record<string, number | undefined>;
    recovery_summary: Record<string, number | undefined>;
    quarantine: Array<{
      market_data_quarantine_id: string;
      symbol: string;
      provider: string;
      source_reference: string;
      source_row_number: number | null;
      rejection_code: string;
      rejection_detail: string;
      status: string;
      observed_at_utc: string;
    }>;
    recovery_jobs: Array<{
      market_data_recovery_job_id: string;
      symbol: string;
      timeframe: string;
      gap_start_utc: string;
      gap_end_utc: string;
      maximum_requested_rows: number;
      status: string;
      attempt_count: number;
      retry_after_utc: string | null;
      last_error_code: string | null;
      created_at_utc: string;
    }>;
    synthetic_fill_allowed: false;
    execution_enabled: false;
  };
  holdout_policy: Record<string, string>;
}

export interface ExperimentalLabData {
  programme: 'BROKER EVIDENCE PROGRAMME';
  warning: string;
  global_feature_flag: boolean;
  configured: boolean;
  normal_demo_auto_unchanged: true;
  promotion_authority: 'NONE';
  readiness: {
    status: 'READY' | 'NOT_READY';
    checks: Record<string, { ready: boolean; status: string; detail: string }>;
    blockers: string[];
    deferred: string[];
  };
  programmes: Array<{
    experimental_programme_id: string;
    symbol: string;
    market_tier: number;
    model_version: string;
    model_status: string;
    artifact_sha256: string;
    feature_version: string;
    target_version: string;
    programme_type: string;
    stage: string;
    status: string;
    starts_at_utc: string;
    expires_at_utc: string;
    max_attempts: number;
    max_holding_minutes: number;
    armed_at_utc: string | null;
    risk_per_trade_pct: string;
    hard_max_risk_per_trade_pct: string;
    daily_loss_limit_pct: string;
    programme_drawdown_limit_pct: string;
    max_daily_losing_trades: number;
    max_open_positions: number;
    attempt_count: number;
    observation_count: number;
    unknown_count: number;
  }>;
  attempts: Array<{
    experimental_attempt_id: string;
    experimental_programme_id: string;
    signal_timestamp_utc: string;
    decision_side: string;
    model_probability: string | null;
    decision_state: string;
    reason_code: string | null;
    requested_size: string | null;
    calculated_risk_zar: string | null;
    actual_fill: string | null;
    spread_zar: string | null;
    slippage_zar: string | null;
    net_pnl_zar: string | null;
    exit_reason: string | null;
  }>;
  tier_matrix: Array<{
    symbol: string;
    market_tier: number;
    research_enabled: boolean;
    demo_trading_enabled: boolean;
    experimental_eligibility: string;
  }>;
  candidates: Array<{
    model_version_id: string;
    symbol: string;
    market_tier: number;
    model_name: string;
    version: string;
    status: string;
    artifact_sha256: string;
    feature_version: string;
    target_version: string;
    artifact_valid: boolean;
  }>;
  canary_readiness: {
    execution_continuity_lookback_hours: number;
    account_equity_zar: string | null;
    account_observed_at_utc: string | null;
    unknown_submissions: number;
    open_experimental_positions: number;
    infrastructure_ready: boolean;
    global_flag_required_before_owner_arm: boolean;
    global_flag_enabled: boolean;
    owner_arm_enabled: boolean;
    recommended: ExperimentalCanaryMarket | null;
    markets: ExperimentalCanaryMarket[];
  };
}

export interface ExperimentalCanaryMarket {
  symbol: string;
  model_version_id: string | null;
  model_version: string | null;
  model_status: string | null;
  gates: Record<string, boolean>;
  blocker: string | null;
  eligible_without_global_flag: boolean;
  latest_m5_utc: string | null;
  unresolved_execution_gaps: number;
  market_status: string | null;
  bid: string;
  ask: string;
  spread_bps: string | null;
  minimum_size: string;
  minimum_stop_distance: string;
  canary_stop_distance: string;
  canary_target_distance: string;
  maximum_holding_minutes: number;
  minimum_size_risk_zar: string;
  minimum_size_risk_pct: string | null;
  default_risk_pct: string;
  hard_max_risk_pct: string;
  artifact: Record<string, unknown>;
}

@Injectable({ providedIn: 'root' })
export class DashboardApi {
  private readonly http = inject(HttpClient);

  load(): Observable<DashboardData> {
    return this.http.get<DashboardData>('/api/v1/dashboard');
  }

  sync(): Observable<DashboardData> {
    return this.http.post('/api/v1/integrations/ig/sync', {}).pipe(switchMap(() => this.load()));
  }

  candles(symbol: string, timeframe: string, period: string): Observable<MarketCandlesData> {
    const limit = period === 'ALL' ? 2000 : period === '7D' ? 1000 : 500;
    return this.http.get<MarketCandlesData>('/api/v1/markets/candles', {
      params: { symbol, timeframe, period, limit },
    });
  }

  marketInventory(): Observable<MarketInventoryData> {
    return this.http.get<MarketInventoryData>('/api/v1/markets');
  }

  tradeHistory(): Observable<TradeHistoryData> {
    return this.http.get<TradeHistoryData>('/api/v1/trades/history', { params: { limit: 50 } });
  }

  tradingReadiness(): Observable<TradingReadinessData> {
    return this.http.get<TradingReadinessData>('/api/v1/trading/readiness');
  }

  modelReadiness(): Observable<ModelReadinessData> {
    return this.http.get<ModelReadinessData>('/api/v1/models/readiness');
  }

  modelValidation(): Observable<ModelValidationData> {
    return this.http.get<ModelValidationData>('/api/v1/models/validation');
  }

  replayRuns(): Observable<ReplayRunsData> {
    return this.http.get<ReplayRunsData>('/api/v1/replay/runs');
  }

  forwardEvidence(): Observable<ForwardEvidenceData> {
    return this.http.get<ForwardEvidenceData>('/api/v1/forward-evidence', {
      params: { limit: 200 },
    });
  }

  runReplay(
    symbol: string,
    mode: 'VALIDATED_MODEL' | 'TECHNICAL_DIAGNOSTIC',
    initialEquityZar: string,
  ): Observable<object> {
    return this.http.post('/api/v1/replay/runs', {
      symbol,
      mode,
      max_candles: 2000,
      initial_equity_zar: initialEquityZar,
    });
  }

  macroStatus(): Observable<MacroStatusData> {
    return this.http.get<MacroStatusData>('/api/v1/macro/status');
  }

  syncMacro(): Observable<object> {
    return this.http.post('/api/v1/macro/sync', {});
  }

  researchStatus(): Observable<ResearchStatusData> {
    return this.http.get<ResearchStatusData>('/api/v1/research/status');
  }

  experimentalLab(): Observable<ExperimentalLabData> {
    return this.http.get<ExperimentalLabData>('/api/v1/experimental-demo');
  }

  createExperimentalProgramme(body: {
    symbol: string;
    model_version_id: string;
    starts_at_utc: string;
    expires_at_utc: string;
    programme_type: 'INFRASTRUCTURE_CANARY' | 'BROKER_EVIDENCE';
    max_attempts: number;
    max_holding_minutes: number;
  }): Observable<object> {
    return this.http.post('/api/v1/experimental-demo/programmes', body);
  }

  controlExperimentalProgramme(
    programmeId: string,
    action: string,
    acknowledgement: string,
  ): Observable<object> {
    return this.http.post(`/api/v1/experimental-demo/programmes/${programmeId}/control`, {
      action,
      acknowledgement,
    });
  }

  reconcileExperimentalDemo(): Observable<object> {
    return this.http.post('/api/v1/experimental-demo/reconcile', {
      acknowledgement: 'RECONCILE_EXPERIMENTAL_IG_DEMO',
    });
  }

  submitExperimentalAttempt(attemptId: string): Observable<object> {
    return this.http.post(`/api/v1/experimental-demo/attempts/${attemptId}/submit`, {
      acknowledgement: 'SUBMIT_ONE_EXPERIMENTAL_IG_DEMO_ATTEMPT',
    });
  }

  closeExperimentalPosition(attemptId: string): Observable<object> {
    return this.http.post(`/api/v1/experimental-demo/attempts/${attemptId}/close`, {
      acknowledgement: 'CLOSE_OPEN_EXPERIMENTAL_POSITION',
      reason: 'OWNER_MANUAL_CLOSE',
    });
  }

  syncResearchEvidence(): Observable<object> {
    return this.http.post('/api/v1/research/evidence/sync', {});
  }

  runResearchProtocolAudit(): Observable<object> {
    return this.http.post('/api/v1/research/protocol/audit', {});
  }

  reserveResearchLineage(
    market: string,
    targetMode: string,
    targetHorizonBars: number,
    hypothesis: string,
  ): Observable<object> {
    return this.http.post('/api/v1/research/lineage/reserve', {
      market,
      hypothesis,
      target_mode: targetMode,
      target_horizon_bars: targetHorizonBars,
      model_families: [
        'LOGISTIC_REGRESSION',
        'RANDOM_FOREST',
        'AUREX_HIST_GRADIENT_BOOSTING',
        'LIGHTGBM',
        'XGBOOST',
        'CATBOOST',
        'CALIBRATED_DISAGREEMENT_ENSEMBLE',
      ],
    });
  }

  runSelectiveTournament(market: string): Observable<object> {
    return this.http.post('/api/v1/research/selective-tournament', {
      market,
      notes: 'Owner-requested target-bound development tournament; holdout untouched',
    });
  }

  freezeSelectiveCandidate(market: string): Observable<object> {
    return this.http.post('/api/v1/research/holdout/freeze', {
      market,
      notes: 'Freeze exact eligible V4 tournament leader; broker execution remains disabled',
    });
  }

  runResearchReplay(
    market: string,
    costModel: 'OPTIMISTIC' | 'NORMAL' | 'STRESSED' = 'NORMAL',
  ): Observable<object> {
    return this.http.post('/api/v1/research/replay', {
      market,
      timeframe: 'M15',
      cost_model: costModel,
      segment_mode: 'CONTINUOUS_ONLY',
      max_candles: 100000,
      notes: 'Owner-requested diagnostic replay of the current rejected model',
    });
  }

  evaluateHoldoutCandidate(candidateId: string): Observable<object> {
    return this.http.post('/api/v1/research/holdout/evaluate', {
      candidate_id: candidateId,
      acknowledgement: 'CONSUME HOLDOUT ONCE',
    });
  }

  approveHoldoutCandidate(candidateId: string): Observable<object> {
    return this.http.post('/api/v1/research/holdout/approve', {
      candidate_id: candidateId,
      acknowledgement: 'I APPROVE THIS EXACT HOLDOUT-PASSED ARTIFACT FOR FORWARD SHADOW ONLY',
    });
  }

  shadowTrades(): Observable<ShadowTradesData> {
    return this.http.get<ShadowTradesData>('/api/v1/shadow/trades', { params: { limit: 50 } });
  }

  shadowPerformance(): Observable<ShadowPerformanceData> {
    return this.http.get<ShadowPerformanceData>('/api/v1/shadow/performance/daily', { params: { days: 30 } });
  }

  orderIntents(): Observable<OrderIntentsData> {
    return this.http.get<OrderIntentsData>('/api/v1/orders', { params: { limit: 50 } });
  }

  riskStatus(): Observable<RiskStatusData> {
    return this.http.get<RiskStatusData>('/api/v1/risk/status');
  }

  reconciliation(): Observable<ReconciliationData> {
    return this.http.get<ReconciliationData>('/api/v1/reconciliation', { params: { limit: 50 } });
  }

  operationsStatus(): Observable<OperationsStatusData> {
    return this.http.get<OperationsStatusData>('/api/v1/operations/status', {
      params: { limit: 10 },
    });
  }

  tradingStatus(): Observable<TradingStatusData> {
    return this.http.get<TradingStatusData>('/api/v1/trading/status');
  }

  changeControl(action: 'PAUSE' | 'RESUME_SHADOW', reason: string): Observable<TradingStatusData> {
    return this.http.post<TradingStatusData>('/api/v1/trading/control', { action, reason });
  }

  strategies(): Observable<StrategiesData> {
    return this.http.get<StrategiesData>('/api/v1/strategies');
  }

  changeStrategy(id: string, status: 'ACTIVE' | 'PAUSED', reason: string): Observable<object> {
    return this.http.patch(`/api/v1/strategies/${id}`, { status, reason });
  }
}
