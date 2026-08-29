import { afterNextRender, Component, computed, ElementRef, inject, signal, ViewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { DashboardApi, DashboardData, ForwardEvidenceData, MacroStatusData, MarketCandlesData, MarketInventoryData, ModelReadinessData, ModelValidationData, OperationsStatusData, OrderIntentsData, ReconciliationData, ReplayRunsData, RiskStatusData, ShadowTradesData, StrategiesData, TradeHistoryData, TradingReadinessData, TradingStatusData } from './dashboard-api';
import { AuthApi } from './auth-api';
import { Router } from '@angular/router';
import { finalize } from 'rxjs';

interface NavigationItem {
  label: string;
  icon: string;
  target: string;
  active?: boolean;
}

interface NavigationSection {
  group: string;
  items: NavigationItem[];
}

@Component({
  selector: 'aurex-dashboard',
  imports: [DatePipe],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class DashboardComponent {
  private readonly dashboardApi = inject(DashboardApi);
  private readonly authApi = inject(AuthApi);
  private readonly router = inject(Router);
  @ViewChild('chartViewport') private chartViewport?: ElementRef<HTMLDivElement>;

  protected readonly sidebarOpen = signal(false);
  protected readonly dashboardData = signal<DashboardData | null>(null);
  protected readonly marketData = signal<MarketCandlesData | null>(null);
  protected readonly marketInventory = signal<MarketInventoryData | null>(null);
  protected readonly selectedMarket = signal('EURUSD');
  protected readonly selectedTimeframe = signal('M5');
  protected readonly selectedPeriod = signal('7D');
  protected readonly marketLoading = signal(true);
  protected readonly marketError = signal('');
  protected readonly tradeHistory = signal<TradeHistoryData | null>(null);
  protected readonly tradingReadiness = signal<TradingReadinessData | null>(null);
  protected readonly modelReadiness = signal<ModelReadinessData | null>(null);
  protected readonly modelValidation = signal<ModelValidationData | null>(null);
  protected readonly replayRuns = signal<ReplayRunsData | null>(null);
  protected readonly forwardEvidence = signal<ForwardEvidenceData | null>(null);
  protected readonly replayBusy = signal(false);
  protected readonly replayMessage = signal('');
  protected readonly macroStatus = signal<MacroStatusData | null>(null);
  protected readonly macroBusy = signal(false);
  protected readonly macroError = signal('');
  protected readonly shadowTrades = signal<ShadowTradesData | null>(null);
  protected readonly orderIntents = signal<OrderIntentsData | null>(null);
  protected readonly riskStatus = signal<RiskStatusData | null>(null);
  protected readonly reconciliation = signal<ReconciliationData | null>(null);
  protected readonly operationsStatus = signal<OperationsStatusData | null>(null);
  protected readonly tradingStatus = signal<TradingStatusData | null>(null);
  protected readonly strategies = signal<StrategiesData | null>(null);
  protected readonly controlBusy = signal(false);
  protected readonly controlError = signal('');
  protected readonly logoutBusy = signal(false);
  protected readonly logoutError = signal('');
  protected readonly testingMessage = signal('');
  protected readonly chartDragging = signal(false);
  protected readonly chartScrollLeft = signal(0);
  protected readonly chartScrollTop = signal(0);
  protected readonly chartViewportWidth = signal(1200);
  protected readonly chartViewportHeight = signal(360);
  protected readonly chartZoom = signal(1);
  private chartPointerId: number | null = null;
  private chartDragStartX = 0;
  private chartDragStartY = 0;
  private chartDragStartScrollLeft = 0;
  private chartDragStartScrollTop = 0;
  protected readonly todayLabel = new Intl.DateTimeFormat('en-ZA', {
    weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Africa/Johannesburg',
  }).format(new Date());
  protected readonly greetingLabel = this.southAfricanGreeting(new Date());
  protected readonly loading = signal(true);
  protected readonly ownerUser = this.authApi.user;
  protected readonly ownerInitials = computed(() => {
    const name = this.ownerUser()?.display_name?.trim() || this.ownerUser()?.email || 'Owner';
    return name.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('');
  });
  protected readonly ownerRole = computed(() => {
    const role = this.ownerUser()?.role || 'owner';
    return role.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
  });

  protected promotionFor(symbol: string) {
    return this.modelReadiness()?.markets.find((market) => market.symbol === symbol)?.forward_shadow ?? null;
  }
  protected readonly syncError = signal('');

  protected readonly navigation: NavigationSection[] = [
    { group: 'Overview', items: [{ label: 'Dashboard', icon: 'grid', target: 'dashboard-top', active: true }] },
    { group: 'Trading', items: [{ label: 'Market data', icon: 'chart', target: 'market-data' }, { label: 'Macro intelligence', icon: 'globe', target: 'macro-intelligence' }, { label: 'Model readiness', icon: 'gauge', target: 'model-readiness' }, { label: 'Forward evidence', icon: 'trend', target: 'forward-evidence' }, { label: 'Replay laboratory', icon: 'clock', target: 'replay-laboratory' }, { label: 'Shadow trades', icon: 'trend', target: 'shadow-trades' }, { label: 'Strategies', icon: 'gauge', target: 'strategies' }, { label: 'Orders', icon: 'grid', target: 'orders' }, { label: 'Open positions', icon: 'trend', target: 'open-positions' }, { label: 'Trade history', icon: 'clock', target: 'trade-history' }] },
    { group: 'Operations', items: [{ label: 'Assurance', icon: 'grid', target: 'operational-assurance' }, { label: 'Risk management', icon: 'gauge', target: 'risk-management' }, { label: 'Reconciliation', icon: 'clock', target: 'reconciliation' }, { label: 'System status', icon: 'gauge', target: 'system-status' }] },
  ];

  protected readonly metrics = computed(() => {
    const data = this.dashboardData();
    return [
      { label: 'Equity', value: this.money(data?.portfolio.equity), detail: 'Latest IG demo snapshot', tone: 'neutral' },
      { label: 'Open P/L', value: this.money(data?.portfolio.profit_loss), detail: 'Converted to ZAR', tone: Number(data?.portfolio.profit_loss ?? 0) >= 0 ? 'positive' : 'negative' },
      { label: 'Open positions', value: String(data?.open_positions ?? 0), detail: 'From IG demo', tone: 'neutral' },
    ];
  });

  protected readonly positions = computed(() =>
    (this.dashboardData()?.positions ?? []).map((position) => {
      const normalized = position.market.replace(/[^A-Z0-9]/gi, '').toUpperCase();
      const instrument = this.marketInventory()?.markets.find((market) =>
        market.symbol === normalized || (() => {
          const display = market.display_name.replace(/[^A-Z0-9]/gi, '').toUpperCase();
          return display === normalized || display.startsWith(normalized) || normalized.startsWith(display);
        })(),
      );
      return {
        market: instrument?.display_name ?? position.market,
        instrumentType: instrument?.asset_class === 'INDEX' ? 'Index CFD' : 'Forex CFD',
        marker: instrument?.asset_class === 'INDEX' ? '40' : instrument?.base_currency ?? 'FX',
        side: position.direction,
        entry: position.entry_price,
        current: position.current_price ?? '—',
        pnl: this.sourceMoney(position.profit_loss, position.currency),
        change: position.currency,
        status: position.status,
      };
    }),
  );

  protected readonly statuses = computed(() =>
    (this.dashboardData()?.components ?? []).map((component) => ({
      label: component.name,
      state: component.status,
      healthy: ['CURRENT', 'HEALTHY'].includes(component.status.toUpperCase()),
      detail: component.detail,
    })),
  );

  protected readonly chartLine = computed(() => this.chartPath(false));
  protected readonly chartArea = computed(() => this.chartPath(true));
  private readonly performanceBounds = computed(() => {
    const values = (this.dashboardData()?.performance ?? []).map((point) => Number(point.equity));
    if (values.length < 2) return null;
    const minimum = Math.min(...values), maximum = Math.max(...values);
    const rawSpread = maximum - minimum;
    const padding = rawSpread > 0 ? rawSpread * 0.08 : Math.max(Math.abs(maximum) * 0.005, 1);
    return { minimum: minimum - padding, maximum: maximum + padding };
  });
  protected readonly performanceAxisTicks = computed(() => {
    const bounds = this.performanceBounds();
    if (!bounds) return [];
    const spread = bounds.maximum - bounds.minimum;
    return Array.from({ length: 4 }, (_, index) => bounds.maximum - (spread * index) / 3).map((value) =>
      new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', notation: 'compact', maximumFractionDigits: 1 }).format(value),
    );
  });
  protected readonly performanceDateTicks = computed(() => {
    const points = this.dashboardData()?.performance ?? [];
    if (points.length < 2) return [];
    const count = Math.min(5, points.length);
    return Array.from({ length: count }, (_, index) => {
      const pointIndex = count === 1 ? 0 : Math.round((index * (points.length - 1)) / (count - 1));
      return new Intl.DateTimeFormat('en-ZA', {
        day: 'numeric', month: 'short', timeZone: 'Africa/Johannesburg',
      }).format(new Date(points[pointIndex].observed_at_utc));
    });
  });
  protected readonly candleChart = computed(() => this.buildCandleChart());
  protected readonly visiblePriceTicks = computed(() => {
    const chart = this.candleChart();
    const viewportHeight = this.chartViewportHeight();
    const axisBottom = Math.max(70, viewportHeight - 60);
    const plotHeight = chart.chartHeight - chart.plotTop - chart.plotBottom;
    return Array.from({ length: 5 }, (_, index) => {
      const y = chart.plotTop + ((axisBottom - chart.plotTop) * index) / 4;
      const worldY = this.chartScrollTop() + y;
      const ratio = (worldY - chart.plotTop) / Math.max(plotHeight, 1);
      const value = chart.maxValue - ratio * (chart.maxValue - chart.minValue);
      return { y, label: value.toFixed(chart.priceDigits) };
    });
  });
  protected readonly visibleTimeTicks = computed(() => {
    const source = this.marketData()?.candles ?? [];
    if (!source.length) return [];
    const chart = this.candleChart();
    const viewportWidth = this.chartViewportWidth();
    const usableWidth = Math.max(viewportWidth - chart.plotLeft - 20, 200);
    return Array.from({ length: 6 }, (_, index) => {
      const x = chart.plotLeft + (usableWidth * index) / 5;
      const worldX = this.chartScrollLeft() + x;
      const ratio = (worldX - chart.plotLeft) / Math.max(chart.chartWidth - chart.plotLeft - chart.plotRight, 1);
      const sourceIndex = Math.max(0, Math.min(source.length - 1, Math.round(ratio * (source.length - 1))));
      const stamp = new Date(source[sourceIndex].open_time_sast + '+02:00');
      return {
        x,
        label: stamp.toLocaleString('en-ZA', this.selectedPeriod() === 'TODAY'
          ? { hour: '2-digit', minute: '2-digit' }
          : { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
      };
    });
  });

  constructor() {
    afterNextRender(() => {
      this.loadDashboard(false);
      this.loadMarketInventory();
      this.loadMarket();
      this.loadTradeHistory();
      this.loadTradingReadiness();
      this.loadTradingOperations();
    });
  }

  protected selectMarket(symbol: string): void {
    this.selectedMarket.set(symbol);
    this.loadMarket();
  }

  protected selectTimeframe(timeframe: string): void {
    this.selectedTimeframe.set(timeframe);
    this.loadMarket();
  }

  protected selectPeriod(period: string): void {
    this.selectedPeriod.set(period);
    this.loadMarket();
  }

  protected toggleSidebar(): void {
    this.sidebarOpen.update((value) => !value);
  }

  protected refreshData(): void {
    this.loadDashboard(true);
  }

  protected logout(): void {
    if (this.logoutBusy()) return;
    this.logoutBusy.set(true);
    this.logoutError.set('');
    this.authApi.logout().pipe(finalize(() => this.logoutBusy.set(false))).subscribe({
      next: () => void this.router.navigateByUrl('/login'),
      error: () => this.logoutError.set('Logout failed. Please try again.'),
    });
  }

  protected changeExecutionControl(): void {
    const paused = this.tradingStatus()?.mode === 'PAUSED';
    const action = paused ? 'RESUME_SHADOW' : 'PAUSE';
    const message = paused
      ? 'Resume shadow evaluation? This still cannot submit orders.'
      : 'Pause signal evaluation and new shadow intents?';
    if (!window.confirm(message)) return;
    this.controlBusy.set(true);
    this.controlError.set('');
    const reason = paused ? 'Owner resumed shadow evaluation' : 'Owner paused shadow evaluation';
    this.dashboardApi.changeControl(action, reason).subscribe({
      next: () => { this.controlBusy.set(false); this.loadTradingOperations(); },
      error: () => { this.controlBusy.set(false); this.controlError.set('The execution control change was blocked.'); },
    });
  }

  protected startShadowTesting(): void {
    const mode = this.tradingStatus()?.mode;
    if (mode === 'SHADOW') {
      this.testingMessage.set('Shadow testing is already active. Aurex will evaluate each completed IG candle.');
      return;
    }
    if (mode !== 'PAUSED' && mode !== 'READ_ONLY') {
      this.testingMessage.set('Testing cannot start until the current engine state is available.');
      return;
    }
    if (!window.confirm('Start hypothetical shadow testing? No order will be sent to IG.')) return;
    this.controlBusy.set(true);
    this.controlError.set('');
    this.testingMessage.set('Starting shadow testing…');
    this.dashboardApi.changeControl('RESUME_SHADOW', 'Owner started hypothetical testing from the IG market graph').subscribe({
      next: () => {
        this.controlBusy.set(false);
        this.testingMessage.set('Shadow testing started. Model and risk gates still apply to every market.');
        this.loadTradingReadiness();
        this.loadTradingOperations();
      },
      error: () => {
        this.controlBusy.set(false);
        this.testingMessage.set('The platform blocked the testing request. Review the operational status.');
      },
    });
  }

  protected beginChartDrag(event: PointerEvent): void {
    if (event.button !== 0) return;
    const viewport = this.chartViewport?.nativeElement;
    if (!viewport) return;
    this.chartPointerId = event.pointerId;
    this.chartDragStartX = event.clientX;
    this.chartDragStartY = event.clientY;
    this.chartDragStartScrollLeft = viewport.scrollLeft;
    this.chartDragStartScrollTop = viewport.scrollTop;
    viewport.setPointerCapture(event.pointerId);
    this.chartDragging.set(true);
    event.preventDefault();
  }

  protected moveChartDrag(event: PointerEvent): void {
    if (this.chartPointerId !== event.pointerId) return;
    const viewport = this.chartViewport?.nativeElement;
    if (!viewport) return;
    viewport.scrollLeft = this.chartDragStartScrollLeft - (event.clientX - this.chartDragStartX);
    viewport.scrollTop = this.chartDragStartScrollTop - (event.clientY - this.chartDragStartY);
    this.syncChartViewport(viewport);
    event.preventDefault();
  }

  protected endChartDrag(event: PointerEvent): void {
    if (this.chartPointerId !== event.pointerId) return;
    const viewport = this.chartViewport?.nativeElement;
    if (viewport?.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    this.chartPointerId = null;
    this.chartDragging.set(false);
  }

  protected chartScrolled(): void {
    const viewport = this.chartViewport?.nativeElement;
    if (viewport) this.syncChartViewport(viewport);
  }

  protected zoomChart(change: number): void {
    const viewport = this.chartViewport?.nativeElement;
    const horizontalAnchor = viewport?.scrollWidth
      ? (viewport.scrollLeft + viewport.clientWidth / 2) / viewport.scrollWidth
      : 0.5;
    const verticalAnchor = viewport?.scrollHeight
      ? (viewport.scrollTop + viewport.clientHeight / 2) / viewport.scrollHeight
      : 0.5;
    const next = Math.max(0.5, Math.min(2.5, Math.round((this.chartZoom() + change) * 4) / 4));
    if (next === this.chartZoom()) return;
    this.chartZoom.set(next);
    requestAnimationFrame(() => {
      const current = this.chartViewport?.nativeElement;
      if (!current) return;
      current.scrollLeft = Math.max(0, horizontalAnchor * current.scrollWidth - current.clientWidth / 2);
      current.scrollTop = Math.max(0, verticalAnchor * current.scrollHeight - current.clientHeight / 2);
      this.syncChartViewport(current);
    });
  }

  protected resetChartZoom(): void {
    const change = 1 - this.chartZoom();
    if (change) this.zoomChart(change);
  }

  protected changeStrategy(id: string, current: 'ACTIVE' | 'PAUSED'): void {
    const next = current === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
    if (!window.confirm(`${next === 'ACTIVE' ? 'Enable' : 'Pause'} this demo strategy?`)) return;
    this.dashboardApi.changeStrategy(id, next, `Owner changed strategy status to ${next}`).subscribe({
      next: () => this.loadTradingOperations(),
      error: () => this.controlError.set('The strategy status change failed.'),
    });
  }

  protected refreshMacroIntelligence(): void {
    if (this.macroBusy()) return;
    this.macroBusy.set(true);
    this.macroError.set('');
    this.dashboardApi.syncMacro().subscribe({
      next: () => {
        this.macroBusy.set(false);
        this.loadMacroStatus();
      },
      error: () => {
        this.macroBusy.set(false);
        this.macroError.set('Official-source synchronization failed. Existing evidence remains unchanged.');
      },
    });
  }

  protected runDiagnosticReplay(): void {
    if (this.replayBusy()) return;
    if (!window.confirm(`Run an offline diagnostic replay for ${this.selectedMarket()}? It cannot place an order or validate a model.`)) return;
    this.replayBusy.set(true);
    this.replayMessage.set('Running deterministic diagnostic replay…');
    this.dashboardApi.runReplay(
      this.selectedMarket(), 'TECHNICAL_DIAGNOSTIC', this.dashboardData()?.portfolio.equity ?? '100000',
    ).subscribe({
      next: () => {
        this.replayBusy.set(false);
        this.replayMessage.set('Diagnostic replay completed. The result is non-promotable.');
        this.loadReplayRuns();
      },
      error: () => {
        this.replayBusy.set(false);
        this.replayMessage.set('Replay was blocked. Review market data and broker-rule readiness.');
      },
    });
  }

  protected money(value?: string): string {
    return new Intl.NumberFormat('en-ZA', {
      style: 'currency',
      currency: 'ZAR',
      minimumFractionDigits: 2,
    }).format(Number(value ?? 0));
  }

  protected sourceMoney(value: string, currency: string): string {
    return new Intl.NumberFormat('en-ZA', {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
    }).format(Number(value));
  }

  protected scorePercent(value?: string | null): string {
    const score = Number(value);
    if (!Number.isFinite(score)) return '—';
    return `${score >= 0 ? '+' : ''}${(score * 100).toFixed(0)}`;
  }

  protected exchangeRateLabel(): string {
    const conversion = this.dashboardData()?.portfolio.conversion;
    if (!conversion) return 'Exchange rate unavailable';
    return `1 ${conversion.source_currency} = ${this.money(conversion.rate)}`;
  }

  private southAfricanGreeting(value: Date): string {
    const hourPart = new Intl.DateTimeFormat('en-ZA', {
      hour: '2-digit', hourCycle: 'h23', timeZone: 'Africa/Johannesburg',
    }).formatToParts(value).find((part) => part.type === 'hour');
    const hour = Number(hourPart?.value ?? 12);
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  private loadDashboard(synchronise: boolean): void {
    this.loading.set(true);
    this.syncError.set('');
    const request = synchronise ? this.dashboardApi.sync() : this.dashboardApi.load();
    request.subscribe({
      next: (data) => {
        this.dashboardData.set(data);
        this.loading.set(false);
        this.loadTradingReadiness();
        this.loadTradingOperations();
      },
      error: () => {
        this.syncError.set(
          synchronise
            ? 'IG demo could not be synchronised. Your last successful snapshot remains available.'
            : 'The platform API is unavailable. Start the API and try again.',
        );
        this.loading.set(false);
      },
    });
  }

  private loadMarket(): void {
    this.marketLoading.set(true);
    this.marketError.set('');
    this.dashboardApi.candles(this.selectedMarket(), this.selectedTimeframe(), this.selectedPeriod()).subscribe({
      next: (data) => {
        this.marketData.set(data);
        this.marketLoading.set(false);
        requestAnimationFrame(() => this.scrollChartToLatest());
      },
      error: () => {
        this.marketError.set('Candle data is temporarily unavailable.');
        this.marketLoading.set(false);
      },
    });
  }

  private loadMarketInventory(): void {
    this.dashboardApi.marketInventory().subscribe({
      next: (data) => {
        this.marketInventory.set(data);
        if (!data.markets.some((market) => market.symbol === this.selectedMarket()) && data.markets[0]) {
          this.selectedMarket.set(data.markets[0].symbol);
          this.loadMarket();
        }
      },
      error: () => this.marketInventory.set(null),
    });
  }

  private loadTradeHistory(): void {
    this.dashboardApi.tradeHistory().subscribe({
      next: (data) => this.tradeHistory.set(data),
      error: () => this.tradeHistory.set({ count: 0, pnl_note: 'Trade history is unavailable.', trades: [] }),
    });
  }

  private loadTradingReadiness(): void {
    this.dashboardApi.tradingReadiness().subscribe({
      next: (data) => this.tradingReadiness.set(data),
      error: () => this.tradingReadiness.set(null),
    });
    this.dashboardApi.modelReadiness().subscribe({
      next: (data) => this.modelReadiness.set(data),
      error: () => this.modelReadiness.set(null),
    });
    this.dashboardApi.modelValidation().subscribe({
      next: (data) => this.modelValidation.set(data), error: () => this.modelValidation.set(null),
    });
    this.dashboardApi.forwardEvidence().subscribe({
      next: (data) => this.forwardEvidence.set(data),
      error: () => this.forwardEvidence.set({
        policy: 'FORWARD_EVIDENCE_NEVER_OVERRIDES_VALIDATION_OR_RISK_GATES', latest: [], snapshots: [],
      }),
    });
    this.loadReplayRuns();
    this.loadMacroStatus();
    this.dashboardApi.shadowTrades().subscribe({
      next: (data) => this.shadowTrades.set(data),
      error: () => this.shadowTrades.set({ count: 0, environment: 'SHADOW', trades: [] }),
    });
  }

  private loadTradingOperations(): void {
    this.dashboardApi.orderIntents().subscribe({
      next: (data) => this.orderIntents.set(data),
      error: () => this.orderIntents.set({ count: 0, orders: [] }),
    });
    this.dashboardApi.riskStatus().subscribe({
      next: (data) => this.riskStatus.set(data), error: () => this.riskStatus.set(null),
    });
    this.dashboardApi.reconciliation().subscribe({
      next: (data) => this.reconciliation.set(data), error: () => this.reconciliation.set(null),
    });
    this.dashboardApi.operationsStatus().subscribe({
      next: (data) => this.operationsStatus.set(data), error: () => this.operationsStatus.set(null),
    });
    this.dashboardApi.tradingStatus().subscribe({
      next: (data) => this.tradingStatus.set(data), error: () => this.tradingStatus.set(null),
    });
    this.dashboardApi.strategies().subscribe({
      next: (data) => this.strategies.set(data), error: () => this.strategies.set({ strategies: [] }),
    });
  }

  private loadMacroStatus(): void {
    this.dashboardApi.macroStatus().subscribe({
      next: (data) => this.macroStatus.set(data),
      error: () => this.macroStatus.set(null),
    });
  }

  private loadReplayRuns(): void {
    this.dashboardApi.replayRuns().subscribe({
      next: (data) => this.replayRuns.set(data),
      error: () => this.replayRuns.set({ runs: [] }),
    });
  }

  private buildCandleChart(): {
    candles: Array<{ x: number; wickTop: number; wickBottom: number; bodyY: number; bodyHeight: number; width: number; rising: boolean }>;
    minLabel: string;
    maxLabel: string;
    latestLabel: string;
    latestPrice: string;
    change: string;
    positive: boolean;
    openPrice: string;
    highPrice: string;
    lowPrice: string;
    priceTicks: Array<{ y: number; label: string }>;
    timeTicks: Array<{ x: number; label: string }>;
    chartWidth: number;
    chartHeight: number;
    minValue: number;
    maxValue: number;
    priceDigits: number;
    plotLeft: number;
    plotRight: number;
    plotTop: number;
    plotBottom: number;
  } {
    const source = this.marketData()?.candles ?? [];
    if (!source.length) return { candles: [], minLabel: '—', maxLabel: '—', latestLabel: '—',
      latestPrice: '—', change: '—', positive: true, openPrice: '—', highPrice: '—', lowPrice: '—', priceTicks: [], timeTicks: [], chartWidth: 900, chartHeight: 600,
      minValue: 0, maxValue: 0, priceDigits: 5, plotLeft: 76, plotRight: 24, plotTop: 24, plotBottom: 68 };
    const zoom = this.chartZoom();
    const width = Math.max(760, Math.round(Math.max(1200, 100 + source.length * 14) * zoom));
    const height = Math.max(420, Math.round(600 * zoom));
    const left = 76, right = 24, top = 24, bottom = 68;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const lows = source.map((c) => Number(c.low));
    const highs = source.map((c) => Number(c.high));
    const min = Math.min(...lows), max = Math.max(...highs), spread = Math.max(max - min, 0.00001);
    const y = (value: number) => top + ((max - value) / spread) * plotHeight;
    const step = plotWidth / source.length;
    const candles = source.map((candle, index) => {
      const open = Number(candle.open), close = Number(candle.close);
      const bodyTop = y(Math.max(open, close)), bodyBottom = y(Math.min(open, close));
      return { x: left + step * index + step / 2, wickTop: y(Number(candle.high)), wickBottom: y(Number(candle.low)),
        bodyY: bodyTop, bodyHeight: Math.max(bodyBottom - bodyTop, 2), width: Math.max(Math.min(step * 0.56, 12), 2), rising: close >= open };
    });
    const digits = this.selectedMarket() === 'GERMANY40' ? 1 : this.selectedMarket() === 'USDJPY' ? 3 : 5;
    const firstOpen = Number(source[0].open), latestClose = Number(source[source.length - 1].close);
    const changePct = firstOpen ? ((latestClose - firstOpen) / firstOpen) * 100 : 0;
    const priceTicks = Array.from({ length: 5 }, (_, index) => {
      const value = max - (spread * index) / 4;
      return { y: top + (plotHeight * index) / 4, label: value.toFixed(digits) };
    });
    const tickCount = Math.min(Math.max(5, Math.floor(plotWidth / 190)), source.length);
    const timeTicks = Array.from({ length: tickCount }, (_, tickIndex) => {
      const sourceIndex = tickCount === 1 ? 0 : Math.round((tickIndex * (source.length - 1)) / (tickCount - 1));
      const stamp = new Date(source[sourceIndex].open_time_sast + '+02:00');
      const includeDate = this.selectedPeriod() !== 'TODAY';
      return {
        x: left + step * sourceIndex + step / 2,
        label: stamp.toLocaleString('en-ZA', includeDate
          ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
          : { hour: '2-digit', minute: '2-digit' }),
      };
    });
    return { candles, minLabel: min.toFixed(digits), maxLabel: max.toFixed(digits),
      latestLabel: new Date(source[source.length - 1].open_time_sast + '+02:00').toLocaleString('en-ZA', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' }),
      latestPrice: latestClose.toFixed(digits), change: `${changePct >= 0 ? '+' : ''}${changePct.toFixed(3)}%`, positive: changePct >= 0,
      openPrice: firstOpen.toFixed(digits), highPrice: max.toFixed(digits), lowPrice: min.toFixed(digits), priceTicks, timeTicks,
      chartWidth: width, chartHeight: height, minValue: min, maxValue: max, priceDigits: digits,
      plotLeft: left, plotRight: right, plotTop: top, plotBottom: bottom };
  }

  private syncChartViewport(viewport: HTMLDivElement): void {
    this.chartScrollLeft.set(viewport.scrollLeft);
    this.chartScrollTop.set(viewport.scrollTop);
    this.chartViewportWidth.set(viewport.clientWidth);
    this.chartViewportHeight.set(viewport.clientHeight);
  }

  private scrollChartToLatest(): void {
    const viewport = this.chartViewport?.nativeElement;
    if (!viewport) return;
    viewport.scrollLeft = Math.max(0, viewport.scrollWidth - viewport.clientWidth);
    viewport.scrollTop = Math.max(0, (viewport.scrollHeight - viewport.clientHeight) / 2);
    this.syncChartViewport(viewport);
  }

  private chartPath(closeArea: boolean): string {
    const points = this.dashboardData()?.performance ?? [];
    const bounds = this.performanceBounds();
    if (points.length < 2 || !bounds) return '';
    const values = points.map((point) => Number(point.equity));
    const spread = bounds.maximum - bounds.minimum;
    const coordinates = values.map((value, index) => {
      const x = (index / (values.length - 1)) * 760;
      const y = 190 - ((value - bounds.minimum) / spread) * 155;
      return `${x.toFixed(1)} ${y.toFixed(1)}`;
    });
    const line = `M${coordinates.join(' L')}`;
    return closeArea ? `${line} L760 220 L0 220 Z` : line;
  }
}
