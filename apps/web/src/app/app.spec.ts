import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { ElementRef, signal } from '@angular/core';
import { vi } from 'vitest';
import { DashboardComponent } from './app';
import { DashboardApi } from './dashboard-api';
import { AuthApi } from './auth-api';
import { provideRouter, Router } from '@angular/router';
import { routes } from './app.routes';

function chartCandles(count: number, start = 1.1) {
  return Array.from({ length: count }, (_, index) => {
    const close = start + index * 0.0001;
    return {
      open_time_utc: new Date(Date.UTC(2026, 7, 25, 8, index * 5)).toISOString(),
      open_time_sast: new Date(Date.UTC(2026, 7, 25, 10, index * 5)).toISOString().replace('Z', ''),
      open: (close - 0.00005).toFixed(5), high: (close + 0.0001).toFixed(5),
      low: (close - 0.0001).toFixed(5), close: close.toFixed(5), bid_close: null,
      ask_close: null, spread_close: null, is_regular_session: true, tick_count: 10, source: 'TEST',
    };
  });
}

class DashboardApiMock {
  private readonly dashboard = {
    locale: 'en-ZA', timezone: 'Africa/Johannesburg', reporting_currency: 'ZAR',
    data_status: 'current', portfolio: { currency: 'ZAR', equity: '322620.40', balance: '322620.40',
      available_funds: '322620.40', margin_used: '0', profit_loss: '0', observed_at_utc: null,
      source_equity: '20000.00', source_balance: '20000.00', source_available_funds: '20000.00',
      source_margin_used: '0', source_profit_loss: '0',
      conversion: { source_currency: 'USD', rate: '16.13102', source: 'configured', observed_at_utc: '2026-08-20T18:00:00Z' } },
    account: null, open_positions: 0, positions: [], performance: [], components: [],
    safety: { trading_mode: 'disabled', broker_environment: 'demo', live_trading_allowed: false },
  };
  load = vi.fn(() => of(this.dashboard));
  sync = vi.fn(() => of(this.dashboard));
  candles = vi.fn((_symbol?: string, _timeframe?: string, _period?: string) => of({ candles: [] }));
  marketInventory = vi.fn(() => of({
    markets: [
      { symbol: 'EURUSD', display_name: 'EUR/USD', asset_class: 'FX', tier: 1, ig_epic: 'EUR', base_currency: 'EUR', quote_currency: 'USD', price_digits: 5, calendar_code: 'FX_24X5', market_timezone: 'UTC' },
      { symbol: 'GERMANY40', display_name: 'Germany 40 Cash (E1)', asset_class: 'INDEX', tier: 1, ig_epic: 'DAX', base_currency: 'EUR', quote_currency: 'EUR', price_digits: 1, calendar_code: 'XETRA_REGULAR', market_timezone: 'Europe/Berlin' },
    ],
    timeframes: ['M5', 'M15'], periods: ['TODAY', '7D', 'ALL'], execution_enabled: false,
  }));
  ownerReadiness = vi.fn(() => of({ overall_health: 'HEALTHY', trading_mode: 'SHADOW',
    broker_environment: 'IG_DEMO', live_status: 'DISABLED', data_status: 'SEE_MARKET_SUMMARY',
    model_status: 'SEE_MARKET_SUMMARY', shadow_status: 'RUNNING', broker_status: 'NOT_ATTESTED_BY_THIS_PAYLOAD',
    risk_status: 'NOT_ATTESTED_BY_THIS_PAYLOAD', demo_auto_status: 'NOT_READY',
    human_approved_demo_status: 'NOT_ATTESTED_BY_THIS_PAYLOAD', pending_approvals: 0,
    reconciliation_unresolved: 0, blocking_reasons: [{ code: 'SHADOW_ONLY',
      message: 'Shadow evaluation is running. Shadow trades are simulated and cannot send IG orders.', action: 'View shadow activity' }] }));
  ownerMarkets = vi.fn(() => of({ generated_at_utc: '2026-09-12T00:00:00Z', environment: 'IG_DEMO',
    markets: [{ symbol: 'EURUSD', display_name: 'EUR/USD', bid: null, ask: null, spread: null,
      quote_observed_at_utc: null, quote_age_seconds: null, quote_status: 'STALE_OR_UNAVAILABLE',
      quote_source: null, model_status: 'REJECTED', demo_configured: false, trading_eligibility: 'UNVERIFIED' }] }));
  tradeHistory = vi.fn(() => of({ count: 0, trades: [], pnl_note: '' }));
  tradingReadiness = vi.fn(() => of({ status: 'NOT_READY', blockers: [] }));
  modelReadiness = vi.fn(() => of({ required_feature_rows: 2000, markets: [] }));
  modelValidation = vi.fn(() => of({ promotion_policy: 'STRICT', models: [] }));
  researchJobs = vi.fn(() => of({ active_job: null, latest_successful_job: null, jobs: [],
    system_status: 'IDLE', stale_after_seconds: 120, execution_enabled: false,
    governance_notice: 'Training completion does not validate a model or enable trading.' }));
  replayRuns = vi.fn(() => of({ runs: [] }));
  forwardEvidence = vi.fn(() => of({ policy: 'FORWARD_EVIDENCE_NEVER_OVERRIDES_VALIDATION_OR_RISK_GATES', latest: [], snapshots: [] }));
  runReplay = vi.fn(() => of({ status: 'COMPLETED' }));
  macroStatus = vi.fn(() => of({ status: 'STALE', execution_authority: 'DETERMINISTIC_RISK_ENGINE', sources: [], currencies: [], decisions: [] }));
  syncMacro = vi.fn(() => of({ status: 'CURRENT' }));
  shadowTrades = vi.fn(() => of({ count: 0, environment: 'SHADOW', trades: [] }));
  shadowPerformance = vi.fn(() => of({ days: 30, zero_trade_days_included: true,
    execution_enabled: false, daily: [] }));
  orderIntents = vi.fn(() => of({ count: 0, orders: [] }));
  tradeProposals = vi.fn(() => of({ status: 'OWNER_REVIEW', execution_authority: 'NONE', count: 0, proposals: [] }));
  decideTradeProposal = vi.fn(() => of({ status: 'OWNER_APPROVED_FOR_RISK', broker_order_submitted: false }));
  riskStatus = vi.fn(() => of({ status: 'CURRENT', policy: null, ledger: null }));
  reconciliation = vi.fn(() => of({ status: 'CLEAR', unresolved: 0, issues: [] }));
  operationsStatus = vi.fn(() => of({
    status: 'HEALTHY', open_alert_count: 0, component_summary: { healthy: 5, total: 5 },
    latest_backup: { backup_file: 'ForexSaas.bak', status: 'BACKED_UP', backup_size_bytes: 1024,
      backup_completed_at_utc: '2026-08-27T02:15:00Z', restore_verified_at_utc: null, detail: 'Checksum verified' },
    latest_verified_restore: { backup_file: 'ForexSaas.bak', status: 'RESTORE_VERIFIED',
      backup_completed_at_utc: '2026-08-23T02:15:00Z', restore_verified_at_utc: '2026-08-23T03:00:00Z', detail: 'DBCC CHECKDB passed' },
    latest_daily_report: { report_date_sast: '2026-08-26', recipient_email: 'owner@example.com',
      subject: 'Aurex daily progress', status: 'SENT', claimed_at_utc: '2026-08-26T17:22:00Z',
      sent_at_utc: '2026-08-26T17:22:03Z', failed_at_utc: null, failure_code: null },
    components: [], alerts: [], backups: [], daily_reports: [],
    safety: { trading_mode: 'disabled', live_trading_allowed: false, reporting_has_execution_authority: false },
  }));
  tradingStatus = vi.fn(() => of({ environment: 'DEMO', mode: 'SHADOW', new_orders_enabled: false, pause_reason: null, shadow_evaluations: [] }));
  strategies = vi.fn(() => of({ strategies: [] }));
  changeControl = vi.fn(() => of({ environment: 'DEMO', mode: 'PAUSED', new_orders_enabled: false, pause_reason: null }));
  changeStrategy = vi.fn(() => of({ status: 'PAUSED' }));
}

describe('DashboardComponent', () => {
  let api: DashboardApiMock;
  const auth = {
    user: signal({ id: 'owner-1', tenant_id: 'tenant-1', email: 'owner@example.com', display_name: 'Tlangelani Maswanganye', role: 'owner' }),
    logout: vi.fn(() => of({ status: 'logged_out' })),
  };

  beforeEach(async () => {
    api = new DashboardApiMock();
    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [{ provide: DashboardApi, useValue: api }, { provide: AuthApi, useValue: auth }, provideRouter(routes)],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render the dashboard heading', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toMatch(/Good (morning|afternoon|evening)/);
  });

  it('exposes exactly six owner areas with dedicated guarded routes', () => {
    const ownerPaths = ['dashboard', 'markets', 'trading', 'research', 'risk', 'system'];
    for (const path of ownerPaths) {
      const route = routes.find((candidate) => candidate.path === path);
      expect(route?.component).toBe(DashboardComponent);
      expect(route?.canActivate?.length).toBeGreaterThan(0);
    }
    expect(routes.find((candidate) => candidate.path === 'markets/:market')).toBeTruthy();
    expect(routes.find((candidate) => candidate.path === 'research/advanced')).toBeTruthy();
  });

  it('shows the owner summary and six primary links without technical sidebar clutter', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.querySelectorAll('.owner-summary article')).toHaveLength(6);
    const links = Array.from(page.querySelectorAll<HTMLAnchorElement>('.nav-item'));
    expect(links.map((link) => link.textContent?.trim())).toEqual(['Dashboard', 'Markets', 'Trading', 'Research', 'Risk', 'System']);
    expect(page.querySelector('#operational-assurance')?.hasAttribute('hidden')).toBe(true);
  });

  it('does not fetch chart or deep research data for the initial dashboard route', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    expect(api.ownerReadiness).toHaveBeenCalledOnce();
    expect(api.candles).not.toHaveBeenCalled();
    expect(api.researchJobs).not.toHaveBeenCalled();
    expect(api.modelValidation).not.toHaveBeenCalled();
  });

  it('uses existing read-only status endpoints when new owner summaries are unavailable', () => {
    api.ownerReadiness.mockReturnValueOnce(throwError(() => new Error('Not deployed')) as any);
    api.ownerMarkets.mockReturnValueOnce(throwError(() => new Error('Not deployed')) as any);
    api.modelReadiness.mockReturnValueOnce(of({ markets: [{ symbol: 'EURUSD', model_status: 'REJECTED', latest_candle_utc: null }] }) as any);
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['loadOwnerReadiness']();
    component['loadOwnerMarkets']();
    expect(api.tradingStatus).toHaveBeenCalledOnce();
    expect(api.modelReadiness).toHaveBeenCalledOnce();
    expect(component['tradingStatus']()?.mode).toBe('SHADOW');
    expect(component['ownerMarkets']()).toBeNull();
    expect(component['marketModelStatus']('EURUSD')).toBe('REJECTED');
  });

  it('prevents decisions on expired proposals before calling the backend', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['tradeProposals'].set({ status: 'OWNER_REVIEW', execution_authority: 'NONE', count: 1,
      proposals: [{ trade_proposal_id: 'expired', status: 'PENDING_OWNER', expires_at_utc: '2020-01-01T00:00:00Z' }] } as any);
    component['decideProposal']('expired', 'APPROVE');
    expect(api.decideTradeProposal).not.toHaveBeenCalled();
    expect(component['proposalMessage']()).toContain('expired');
    expect(component['proposalRemaining']('2020-01-01T00:00:00Z')).toBe('00:00');
  });

  it('keeps the Demo boundary and gives an owner action for the current mode', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.querySelector('.environment-banner')?.textContent).toContain('NO LIVE CAPITAL');
    expect(page.querySelector('.environment-banner')?.textContent).toContain('LIVE DISABLED');
    expect(page.querySelector('.attention-panel')?.textContent).toContain('Shadow evaluation is running');
    expect(page.querySelector<HTMLAnchorElement>('.attention-panel a')?.getAttribute('href')).toBe('#shadow-trades');
  });

  it('shows the source-dollar balance and USD to ZAR exchange rate', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const sourceBalance = (fixture.nativeElement as HTMLElement).querySelector('.source-balance')?.textContent ?? '';
    expect(sourceBalance).toContain('20');
    expect(sourceBalance).toContain('1 USD = R');
  });

  it('shows audited report and recovery assurance', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    fixture.componentInstance['dashboardTab'].set('system');
    fixture.componentInstance['loadSystemEvidence']();
    fixture.detectChanges();
    const assurance = (fixture.nativeElement as HTMLElement).querySelector('#operational-assurance')?.textContent ?? '';
    expect(assurance).toContain('SENT');
    expect(assurance).toContain('RESTORE_VERIFIED');
    expect(assurance).toContain('0 OPEN');
  });

  it('pauses and resumes only shadow execution after confirmation', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'SHADOW', new_orders_enabled: false, pause_reason: null, shadow_evaluations: [] });
    component['changeExecutionControl']();
    expect(api.changeControl).toHaveBeenCalledWith('PAUSE', expect.any(String));
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'PAUSED', new_orders_enabled: false, pause_reason: 'test', shadow_evaluations: [] });
    component['changeExecutionControl']();
    expect(api.changeControl).toHaveBeenCalledWith('RESUME_SHADOW', expect.any(String));
  });

  it('toggles a demo strategy only after confirmation', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fixture = TestBed.createComponent(DashboardComponent);
    fixture.componentInstance['changeStrategy']('strategy-1', 'ACTIVE');
    expect(api.changeStrategy).toHaveBeenCalledWith('strategy-1', 'PAUSED', expect.any(String));
  });

  it('starts only shadow testing from a paused state', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'PAUSED', new_orders_enabled: false, pause_reason: 'test', shadow_evaluations: [] });
    component['startShadowTesting']();
    expect(api.changeControl).toHaveBeenCalledWith('RESUME_SHADOW', expect.any(String));
  });

  it('does not render a trendline over the candlesticks', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    const candles = Array.from({ length: 100 }, (_, index) => {
      const close = index < 50 ? 1.10 + index * 0.0002 : 1.13 - index * 0.0002;
      return {
        open_time_utc: new Date(Date.UTC(2026, 7, 25, 8, index * 5)).toISOString(),
        open_time_sast: new Date(Date.UTC(2026, 7, 25, 10, index * 5)).toISOString().replace('Z', ''),
        open: (close - 0.00005).toFixed(5), high: (close + 0.0001).toFixed(5),
        low: (close - 0.0001).toFixed(5), close: close.toFixed(5), bid_close: null,
        ask_close: null, spread_close: null, is_regular_session: true, tick_count: 10, source: 'TEST',
      };
    });
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: '2026-08-25', period: '7D', candles });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.trend-line')).toBeNull();
  });

  it('zooms the candle canvas in and out within safe limits', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: '2026-08-25', period: '7D', candles: chartCandles(200) });
    component['fitChart']();
    component['zoomChart'](0.25);
    expect(component['chartVisibleCount']()).toBe(80);
    expect(component['chartZoom']()).toBe(1.25);
    component['resetChartZoom']();
    expect(component['chartZoom']()).toBe(1);
    for (let index = 0; index < 10; index += 1) component['zoomChart'](-0.25);
    expect(component['chartZoom']()).toBe(0.5);
  });

  it('fits the initial viewport to the latest 100 M5 candles and their prices', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    const candles = chartCandles(200);
    candles[0] = { ...candles[0], high: '9.00000', low: '0.10000' };
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: '2026-08-25', period: '7D', candles });
    component['fitChart']();
    const chart = component['candleChart']();
    expect(component['chartVisibleStart']()).toBe(100);
    expect(chart.candles).toHaveLength(100);
    expect(chart.maxValue).toBeLessThan(2);
    expect(chart.minValue).toBeGreaterThan(1);
    expect(component['autoFollowLatest']()).toBe(true);
  });

  it('renders chart axis and latest candle time in SAST independent of browser timezone', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: '2026-08-25', period: 'TODAY', candles: chartCandles(3) });
    const chart = component['candleChart']();
    expect(chart.timeTicks[0].label).toContain('10:00');
    expect(chart.latestLabel).toContain('10:10');
  });

  it('go to latest restores automatic following after historical navigation', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: '2026-08-25', period: 'ALL', candles: chartCandles(300) });
    component['chartVisibleStart'].set(40);
    component['chartVisibleCount'].set(100);
    component['autoFollowLatest'].set(false);
    component['goToLatest']();
    expect(component['chartVisibleStart']()).toBe(200);
    expect(component['autoFollowLatest']()).toBe(true);
  });

  it('cancels an older candle request so it cannot overwrite the latest market', async () => {
    const first = new Subject<any>();
    const second = new Subject<any>();
    api.candles.mockImplementation((symbol?: string) => symbol === 'EURUSD' ? first : second);
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    fixture.componentInstance['loadMarket']();
    fixture.componentInstance['selectMarket']('GERMANY40');
    second.next({ symbol: 'GERMANY40', timeframe: 'M5', timezone: 'Africa/Johannesburg', session_date: null, period: '7D', candles: chartCandles(40, 18000) });
    first.next({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg', session_date: null, period: '7D', candles: chartCandles(40) });
    expect(fixture.componentInstance['marketData']()?.symbol).toBe('GERMANY40');
    expect(fixture.componentInstance['marketLoading']()).toBe(false);
  });

  it('chart interactions never call trading mutation endpoints', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: null, period: '7D', candles: chartCandles(150) });
    component['fitChart']();
    component['zoomChart'](0.25);
    component['goToLatest']();
    expect(api.changeControl).not.toHaveBeenCalled();
    expect(api.changeStrategy).not.toHaveBeenCalled();
  });

  it('preserves historical viewport when a new live candle arrives', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    const candles = chartCandles(150);
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg',
      session_date: null, period: '7D', candles });
    component['chartVisibleStart'].set(10);
    component['chartVisibleCount'].set(50);
    component['autoFollowLatest'].set(false);
    component['applyStreamCandle'](chartCandles(151).at(-1)!);
    expect(component['marketData']()?.candles).toHaveLength(151);
    expect(component['chartVisibleStart']()).toBe(10);
    expect(component['autoFollowLatest']()).toBe(false);
  });

  it('renders honest unverified quality and persisted training state', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const component = fixture.componentInstance;
    component['dashboardTab'].set('research');
    component['researchJobs'].set({ active_job: null, latest_successful_job: null, jobs: [], system_status: 'IDLE',
      stale_after_seconds: 120, execution_enabled: false,
      governance_notice: 'Training completion does not validate a model or enable trading.' });
    component['marketData'].set({ symbol: 'EURUSD', timeframe: 'M5', timezone: 'Africa/Johannesburg', session_date: null,
      period: '7D', candles: chartCandles(10), quality: { requested_start_utc: null, requested_end_utc: '2026-09-04T18:00:00Z',
        actual_start_utc: '2026-09-04T17:00:00Z', actual_end_utc: '2026-09-04T18:00:00Z', returned_candle_count: 10,
        expected_candle_count: null, completeness_percentage: null, gap_count: 0, missing_candle_count: null,
        period_not_retained_count: null, delayed_candle_count: null, largest_unexplained_gap_seconds: 0,
        is_complete: null, quality_status: 'UNVERIFIED', calculation_method: 'OBSERVED', calendar_source: 'UNKNOWN',
        limitation: 'Completeness unverified because an authoritative calendar is unavailable.', generated_at_utc: '2026-09-04T18:00:00Z', gaps: [] } });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#training-progress')?.textContent).toContain('No training job is running');
    component['dashboardTab'].set('markets');
    component['marketDetail'].set(true);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('.data-quality')?.textContent).toContain('UNVERIFIED');
  });

  it('updates chart dimensions only from a non-zero container', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    const element = document.createElement('div');
    Object.defineProperties(element, { clientWidth: { value: 840 }, clientHeight: { value: 420 } });
    component['chartViewport'] = new ElementRef(element);
    component['refreshChartDimensions'](false);
    expect(component['chartViewportWidth']()).toBe(840);
    expect(component['chartViewportHeight']()).toBe(420);
  });

  it('disposes the chart resize observer with the component', () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    const disconnect = vi.fn();
    fixture.componentInstance['chartResizeObserver'] = { disconnect } as unknown as ResizeObserver;
    fixture.destroy();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it('offers Germany 40 from the backend market inventory', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    fixture.componentInstance['dashboardTab'].set('markets');
    fixture.componentInstance['loadMarketInventory']();
    fixture.detectChanges();
    const links = Array.from(fixture.nativeElement.querySelectorAll('.owner-market-row')) as HTMLAnchorElement[];
    expect(links.some((link) => link.textContent?.includes('Germany 40 Cash (E1)'))).toBe(true);
    expect(api.marketInventory).toHaveBeenCalled();
  });

  it('keeps unrelated long sections hidden by operational area', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    expect(fixture.componentInstance['dashboardTab']()).toBe('overview');
    fixture.componentInstance['dashboardTab'].set('system');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('#operational-assurance')?.hasAttribute('hidden')).toBe(false);
    expect((fixture.nativeElement as HTMLElement).querySelector('#market-data')?.hasAttribute('hidden')).toBe(true);
  });

  it('shows the authenticated owner identity', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const profile = (fixture.nativeElement as HTMLElement).querySelector('.profile-button')?.textContent ?? '';
    expect(profile).toContain('Tlangelani Maswanganye');
    expect(profile).toContain('Owner');
  });

  it('logs out explicitly and returns to the login page', async () => {
    const router = TestBed.inject(Router);
    const navigate = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.logout-button');
    button?.click();
    expect(auth.logout).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('/login');
  });
});
