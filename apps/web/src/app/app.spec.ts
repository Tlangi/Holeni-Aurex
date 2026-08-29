import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { signal } from '@angular/core';
import { vi } from 'vitest';
import { DashboardComponent } from './app';
import { DashboardApi } from './dashboard-api';
import { AuthApi } from './auth-api';
import { provideRouter, Router } from '@angular/router';

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
  candles = vi.fn(() => of({ candles: [] }));
  marketInventory = vi.fn(() => of({
    markets: [
      { symbol: 'EURUSD', display_name: 'EUR/USD', asset_class: 'FX', ig_epic: 'EUR', base_currency: 'EUR', quote_currency: 'USD', price_digits: 5, calendar_code: 'FX_24X5', market_timezone: 'UTC' },
      { symbol: 'GERMANY40', display_name: 'Germany 40 Cash (E1)', asset_class: 'INDEX', ig_epic: 'DAX', base_currency: 'EUR', quote_currency: 'EUR', price_digits: 1, calendar_code: 'XETRA_REGULAR', market_timezone: 'Europe/Berlin' },
    ],
    timeframes: ['M5', 'M15'], periods: ['TODAY', '7D', 'ALL'], execution_enabled: false,
  }));
  tradeHistory = vi.fn(() => of({ count: 0, trades: [], pnl_note: '' }));
  tradingReadiness = vi.fn(() => of({ status: 'NOT_READY', blockers: [] }));
  modelReadiness = vi.fn(() => of({ required_feature_rows: 2000, markets: [] }));
  modelValidation = vi.fn(() => of({ promotion_policy: 'STRICT', models: [] }));
  replayRuns = vi.fn(() => of({ runs: [] }));
  forwardEvidence = vi.fn(() => of({ policy: 'FORWARD_EVIDENCE_NEVER_OVERRIDES_VALIDATION_OR_RISK_GATES', latest: [], snapshots: [] }));
  runReplay = vi.fn(() => of({ status: 'COMPLETED' }));
  macroStatus = vi.fn(() => of({ status: 'STALE', execution_authority: 'DETERMINISTIC_RISK_ENGINE', sources: [], currencies: [], decisions: [] }));
  syncMacro = vi.fn(() => of({ status: 'CURRENT' }));
  shadowTrades = vi.fn(() => of({ count: 0, environment: 'SHADOW', trades: [] }));
  orderIntents = vi.fn(() => of({ count: 0, orders: [] }));
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
  tradingStatus = vi.fn(() => of({ environment: 'DEMO', mode: 'SHADOW', new_orders_enabled: false, pause_reason: null }));
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
      providers: [{ provide: DashboardApi, useValue: api }, { provide: AuthApi, useValue: auth }, provideRouter([])],
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
    const assurance = (fixture.nativeElement as HTMLElement).querySelector('#operational-assurance')?.textContent ?? '';
    expect(assurance).toContain('SENT');
    expect(assurance).toContain('RESTORE_VERIFIED');
    expect(assurance).toContain('0 OPEN');
  });

  it('pauses and resumes only shadow execution after confirmation', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const fixture = TestBed.createComponent(DashboardComponent);
    const component = fixture.componentInstance;
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'SHADOW', new_orders_enabled: false, pause_reason: null });
    component['changeExecutionControl']();
    expect(api.changeControl).toHaveBeenCalledWith('PAUSE', expect.any(String));
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'PAUSED', new_orders_enabled: false, pause_reason: 'test' });
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
    component['tradingStatus'].set({ environment: 'DEMO', mode: 'PAUSED', new_orders_enabled: false, pause_reason: 'test' });
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
    component['zoomChart'](0.25);
    expect(component['chartZoom']()).toBe(1.25);
    component['resetChartZoom']();
    expect(component['chartZoom']()).toBe(1);
    for (let index = 0; index < 10; index += 1) component['zoomChart'](-0.25);
    expect(component['chartZoom']()).toBe(0.5);
  });

  it('offers Germany 40 from the backend market inventory', async () => {
    const fixture = TestBed.createComponent(DashboardComponent);
    await fixture.whenStable();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    expect(buttons.some((button) => button.textContent?.trim() === 'Germany 40 Cash (E1)')).toBe(true);
    expect(api.marketInventory).toHaveBeenCalled();
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
