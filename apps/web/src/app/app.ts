import { afterNextRender, Component, computed, DestroyRef, ElementRef, inject, signal, ViewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { DashboardApi, DashboardData, ForwardEvidenceData, MacroStatusData, MarketCandle, MarketCandlesData, MarketInventoryData, ModelReadinessData, ModelValidationData, OperationsStatusData, OrderIntentsData, ReconciliationData, ReplayRunsData, RiskStatusData, ShadowPerformanceData, ShadowTradesData, StrategiesData, TradeHistoryData, TradingReadinessData, TradingStatusData } from './dashboard-api';
import { AuthApi } from './auth-api';
import { Router } from '@angular/router';
import { catchError, finalize, map, of, Subject, switchMap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { clampWindow, isAtLatest, latestWindow, normalizeCandles, recommendedCandleCount, visiblePriceBounds } from './chart-utils';

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
  private readonly destroyRef = inject(DestroyRef);
  private chartViewport?: ElementRef<HTMLDivElement>;
  @ViewChild('chartViewport') set chartViewportRef(value: ElementRef<HTMLDivElement> | undefined) {
    this.chartViewport = value;
    this.observeChartViewport(value?.nativeElement);
  }

  protected readonly sidebarOpen = signal(false);
  protected readonly dashboardTab = signal<'overview' | 'research' | 'markets' | 'trading' | 'operations'>('overview');
  protected readonly dashboardTabs = [
    ['overview', 'Overview'], ['research', 'Models & evidence'], ['markets', 'Markets & charts'],
    ['trading', 'Trading activity'], ['operations', 'Operations'],
  ] as const;
  protected readonly dashboardData = signal<DashboardData | null>(null);
  protected readonly marketData = signal<MarketCandlesData | null>(null);
  protected readonly marketInventory = signal<MarketInventoryData | null>(null);
  protected readonly selectedMarket = signal('EURUSD');
  protected readonly selectedTimeframe = signal('M5');
  protected readonly selectedPeriod = signal('7D');
  protected readonly marketLoading = signal(true);
  protected readonly marketError = signal('');
  protected readonly marketLastUpdated = signal<Date | null>(null);
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
  protected readonly shadowPerformance = signal<ShadowPerformanceData | null>(null);
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
  protected readonly chartVisibleStart = signal(0);
  protected readonly chartVisibleCount = signal(100);
  protected readonly chartViewportWidth = signal(1200);
  protected readonly chartViewportHeight = signal(360);
  protected readonly chartZoom = signal(1);
  protected readonly autoFollowLatest = signal(true);
  protected readonly hoveredCandleIndex = signal<number | null>(null);
  protected readonly crosshairX = signal<number | null>(null);
  protected readonly crosshairY = signal<number | null>(null);
  private readonly marketRequests = new Subject<{ symbol: string; timeframe: string; period: string }>();
  private chartResizeObserver?: ResizeObserver;
  private resizeFrame: number | null = null;
  private marketRefreshTimer: number | null = null;
  private chartPointerId: number | null = null;
  private readonly chartPointers = new Map<number, { x: number; y: number }>();
  private chartPinchDistance: number | null = null;
  private chartDragStartX = 0;
  private chartDragStartVisibleStart = 0;
  private chartDragMoved = false;
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
        instrumentType: instrument?.asset_class === 'INDEX' ? 'Index CFD'
          : instrument?.asset_class === 'METAL' ? 'Metal CFD' : 'Forex CFD',
        marker: instrument?.asset_class === 'INDEX' ? '40'
          : instrument?.asset_class === 'METAL' ? 'AU' : instrument?.base_currency ?? 'FX',
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
  protected readonly visiblePriceTicks = computed(() => this.candleChart().priceTicks);
  protected readonly visibleTimeTicks = computed(() => this.candleChart().timeTicks);
  protected readonly hoveredCandle = computed(() => {
    const index = this.hoveredCandleIndex();
    return index === null ? null : this.marketData()?.candles[index] ?? null;
  });
  protected readonly chartIsStale = computed(() => {
    const latest = this.marketData()?.candles.at(-1);
    if (!latest) return false;
    const intervalMinutes = ({ M5: 5, M15: 15, M30: 30, H1: 60, H4: 240, D1: 1440 } as Record<string, number>)[this.selectedTimeframe()] ?? 5;
    return Date.now() - Date.parse(latest.open_time_utc) > intervalMinutes * 3 * 60_000;
  });

  constructor() {
    this.marketRequests.pipe(
      switchMap((request) => {
        this.marketLoading.set(true);
        this.marketError.set('');
        return this.dashboardApi.candles(request.symbol, request.timeframe, request.period).pipe(
          map((data) => ({ data, request, error: '' })),
          catchError(() => of({ data: null, request, error: 'Candle data is temporarily unavailable.' })),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(({ data, error }) => {
      this.marketLoading.set(false);
      if (error || !data) {
        this.marketError.set(error);
        return;
      }
      const candles = normalizeCandles(data.candles);
      const previous = this.marketData();
      const sameSeries = !!previous && previous.symbol === data.symbol && previous.timeframe === data.timeframe && previous.period === data.period;
      this.marketData.set({ ...data, candles });
      this.marketLastUpdated.set(new Date());
      if (!sameSeries) this.fitChart();
      else if (this.autoFollowLatest()) this.goToLatest();
      else {
        const window = clampWindow(candles.length, this.chartVisibleStart(), this.chartVisibleCount());
        this.chartVisibleStart.set(window.start);
        this.chartVisibleCount.set(window.count);
      }
    });
    this.destroyRef.onDestroy(() => {
      this.chartResizeObserver?.disconnect();
      if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
      if (this.marketRefreshTimer !== null) window.clearInterval(this.marketRefreshTimer);
    });
    afterNextRender(() => {
      this.loadDashboard(false);
      this.loadMarketInventory();
      this.loadMarket();
      this.loadTradeHistory();
      this.loadTradingReadiness();
      this.loadTradingOperations();
      this.marketRefreshTimer = window.setInterval(() => {
        if (this.dashboardTab() === 'markets' && !this.marketLoading()) this.loadMarket();
      }, 30_000);
    });
  }

  protected selectMarket(symbol: string): void {
    if (symbol === this.selectedMarket()) return;
    this.selectedMarket.set(symbol);
    this.loadMarket();
  }

  protected selectTimeframe(timeframe: string): void {
    if (timeframe === this.selectedTimeframe()) return;
    this.selectedTimeframe.set(timeframe);
    this.loadMarket();
  }

  protected selectPeriod(period: string): void {
    if (period === this.selectedPeriod()) return;
    this.selectedPeriod.set(period);
    this.loadMarket();
  }

  protected toggleSidebar(): void {
    this.sidebarOpen.update((value) => !value);
  }

  protected selectDashboardTab(tab: 'overview' | 'research' | 'markets' | 'trading' | 'operations'): void {
    this.dashboardTab.set(tab);
    this.sidebarOpen.set(false);
    requestAnimationFrame(() => {
      const tabs = document.querySelector<HTMLElement>('.dashboard-tabs');
      if (typeof tabs?.scrollIntoView === 'function') tabs.scrollIntoView({ behavior: 'smooth' });
      if (tab === 'markets') this.refreshChartDimensions(true);
    });
  }

  protected navigateTo(target: string, event: Event): void {
    event.preventDefault();
    const tab = target === 'dashboard-top' ? 'overview'
      : ['model-validation', 'model-readiness', 'forward-evidence', 'replay-laboratory', 'macro-intelligence'].includes(target) ? 'research'
      : target === 'market-data' ? 'markets'
      : ['open-positions', 'strategies', 'orders', 'shadow-trades', 'trade-history'].includes(target) ? 'trading'
      : 'operations';
    this.dashboardTab.set(tab);
    this.sidebarOpen.set(false);
    requestAnimationFrame(() => {
      const element = document.getElementById(target);
      if (typeof element?.scrollIntoView === 'function') {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      if (tab === 'markets') this.refreshChartDimensions(true);
    });
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
    this.chartPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this.chartPointers.size === 2) {
      const [first, second] = [...this.chartPointers.values()];
      this.chartPinchDistance = Math.hypot(second.x - first.x, second.y - first.y);
      this.chartPointerId = null;
      this.chartDragging.set(false);
      event.preventDefault();
      return;
    }
    this.chartPointerId = event.pointerId;
    this.chartDragStartX = event.clientX;
    this.chartDragStartVisibleStart = this.chartVisibleStart();
    this.chartDragMoved = false;
    viewport.setPointerCapture(event.pointerId);
    this.chartDragging.set(true);
    event.preventDefault();
  }

  protected moveChartDrag(event: PointerEvent): void {
    const viewport = this.chartViewport?.nativeElement;
    if (!viewport) return;
    if (this.chartPointers.has(event.pointerId)) this.chartPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (this.chartPointers.size === 2 && this.chartPinchDistance) {
      const [first, second] = [...this.chartPointers.values()];
      const distance = Math.hypot(second.x - first.x, second.y - first.y);
      if (distance > this.chartPinchDistance * 1.12) {
        this.zoomChart(0.25);
        this.chartPinchDistance = distance;
      } else if (distance < this.chartPinchDistance * .88) {
        this.zoomChart(-0.25);
        this.chartPinchDistance = distance;
      }
      event.preventDefault();
      return;
    }
    if (this.chartPointerId !== event.pointerId) {
      this.updateCrosshair(event);
      return;
    }
    const candleWidth = Math.max((viewport.clientWidth - 96) / Math.max(this.chartVisibleCount(), 1), 1);
    const delta = event.clientX - this.chartDragStartX;
    const shift = Math.round(-delta / candleWidth);
    const total = this.marketData()?.candles.length ?? 0;
    const window = clampWindow(total, this.chartDragStartVisibleStart + shift, this.chartVisibleCount());
    this.chartVisibleStart.set(window.start);
    if (Math.abs(delta) > 3) {
      this.chartDragMoved = true;
      this.autoFollowLatest.set(isAtLatest(total, window.start, window.count));
    }
    this.updateCrosshair(event);
    event.preventDefault();
  }

  protected endChartDrag(event: PointerEvent): void {
    this.chartPointers.delete(event.pointerId);
    if (this.chartPointers.size < 2) this.chartPinchDistance = null;
    if (this.chartPointerId !== event.pointerId) return;
    const viewport = this.chartViewport?.nativeElement;
    if (viewport?.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    this.chartPointerId = null;
    this.chartDragging.set(false);
  }

  protected clearCrosshair(): void {
    if (this.chartDragging()) return;
    this.hoveredCandleIndex.set(null);
    this.crosshairX.set(null);
    this.crosshairY.set(null);
  }

  protected zoomChart(change: number): void {
    const total = this.marketData()?.candles.length ?? 0;
    if (!total) return;
    const currentCount = this.chartVisibleCount();
    const factor = change > 0 ? 0.8 : 1.25;
    const nextCount = Math.max(20, Math.min(total, Math.round(currentCount * factor)));
    if (nextCount === currentCount) return;
    const wasLatest = this.autoFollowLatest() && isAtLatest(total, this.chartVisibleStart(), currentCount);
    const center = this.chartVisibleStart() + currentCount / 2;
    const window = wasLatest ? latestWindow(total, nextCount) : clampWindow(total, center - nextCount / 2, nextCount);
    this.chartVisibleStart.set(window.start);
    this.chartVisibleCount.set(window.count);
    this.chartZoom.set(Math.max(0.5, Math.min(2.5, recommendedCandleCount(this.selectedTimeframe()) / window.count)));
    this.autoFollowLatest.set(wasLatest);
  }

  protected resetChartZoom(): void {
    this.fitChart();
  }

  protected fitChart(): void {
    const total = this.marketData()?.candles.length ?? 0;
    if (!total) return;
    const window = latestWindow(total, recommendedCandleCount(this.selectedTimeframe()));
    this.chartVisibleStart.set(window.start);
    this.chartVisibleCount.set(window.count);
    this.chartZoom.set(1);
    this.autoFollowLatest.set(true);
    this.scheduleChartDimensions();
  }

  protected goToLatest(): void {
    const total = this.marketData()?.candles.length ?? 0;
    if (!total) return;
    const window = latestWindow(total, this.chartVisibleCount());
    this.chartVisibleStart.set(window.start);
    this.chartVisibleCount.set(window.count);
    this.autoFollowLatest.set(true);
  }

  protected chartWheel(event: WheelEvent): void {
    if (Math.abs(event.deltaY) < 1) return;
    event.preventDefault();
    this.zoomChart(event.deltaY < 0 ? 0.25 : -0.25);
  }

  protected chartKeydown(event: KeyboardEvent): void {
    if (event.key === '+' || event.key === '=') this.zoomChart(0.25);
    else if (event.key === '-') this.zoomChart(-0.25);
    else if (event.key === 'End') this.goToLatest();
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const total = this.marketData()?.candles.length ?? 0;
      const direction = event.key === 'ArrowLeft' ? -1 : 1;
      const window = clampWindow(total, this.chartVisibleStart() + direction * Math.max(1, Math.round(this.chartVisibleCount() * .1)), this.chartVisibleCount());
      this.chartVisibleStart.set(window.start);
      this.autoFollowLatest.set(isAtLatest(total, window.start, window.count));
    } else return;
    event.preventDefault();
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

  protected loadMarket(): void {
    this.marketRequests.next({
      symbol: this.selectedMarket(), timeframe: this.selectedTimeframe(), period: this.selectedPeriod(),
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
    this.dashboardApi.shadowPerformance().subscribe({
      next: (data) => this.shadowPerformance.set(data),
      error: () => this.shadowPerformance.set({ days: 30, zero_trade_days_included: true,
        execution_enabled: false, daily: [] }),
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
    candles: Array<{ sourceIndex: number; x: number; wickTop: number; wickBottom: number; bodyY: number; bodyHeight: number; width: number; rising: boolean }>;
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
      latestPrice: '—', change: '—', positive: true, openPrice: '—', highPrice: '—', lowPrice: '—', priceTicks: [], timeTicks: [], chartWidth: 900, chartHeight: 360,
      minValue: 0, maxValue: 0, priceDigits: 5, plotLeft: 76, plotRight: 24, plotTop: 24, plotBottom: 68 };
    const window = clampWindow(source.length, this.chartVisibleStart(), this.chartVisibleCount());
    const visible = source.slice(window.start, window.start + window.count);
    const width = Math.max(320, this.chartViewportWidth());
    const height = Math.max(280, this.chartViewportHeight());
    const left = width < 520 ? 64 : 76, right = width < 520 ? 12 : 20, top = 18, bottom = width < 520 ? 58 : 62;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const digits = this.marketInventory()?.markets.find((market) => market.symbol === this.selectedMarket())?.price_digits
      ?? (this.selectedMarket() === 'GERMANY40' ? 1 : this.selectedMarket() === 'USDJPY' ? 3 : 5);
    const tick = 10 ** -digits;
    const bounds = visiblePriceBounds(visible, tick);
    const min = bounds.minimum, max = bounds.maximum, spread = max - min;
    const y = (value: number) => top + ((max - value) / spread) * plotHeight;
    const step = plotWidth / Math.max(visible.length * 1.08, 1);
    const candles = visible.map((candle, index) => {
      const open = Number(candle.open), close = Number(candle.close);
      const bodyTop = y(Math.max(open, close)), bodyBottom = y(Math.min(open, close));
      return { sourceIndex: window.start + index, x: left + step * index + step / 2, wickTop: y(Number(candle.high)), wickBottom: y(Number(candle.low)),
        bodyY: bodyTop, bodyHeight: Math.max(bodyBottom - bodyTop, 2), width: Math.max(Math.min(step * 0.56, 12), 2), rising: close >= open };
    });
    const firstOpen = Number(source[0].open), latestClose = Number(source[source.length - 1].close);
    const periodHigh = Math.max(...source.map((candle) => Number(candle.high)));
    const periodLow = Math.min(...source.map((candle) => Number(candle.low)));
    const changePct = firstOpen ? ((latestClose - firstOpen) / firstOpen) * 100 : 0;
    const priceTicks = Array.from({ length: 5 }, (_, index) => {
      const value = max - (spread * index) / 4;
      return { y: top + (plotHeight * index) / 4, label: value.toFixed(digits) };
    });
    const tickCount = Math.min(Math.max(3, Math.floor(plotWidth / 170)), visible.length);
    const timeTicks = Array.from({ length: tickCount }, (_, tickIndex) => {
      const visibleIndex = tickCount === 1 ? 0 : Math.round((tickIndex * (visible.length - 1)) / (tickCount - 1));
      const sourceIndex = window.start + visibleIndex;
      const stamp = new Date(source[sourceIndex].open_time_sast + '+02:00');
      const includeDate = this.selectedPeriod() !== 'TODAY';
      return {
        x: left + step * visibleIndex + step / 2,
        label: stamp.toLocaleString('en-ZA', includeDate
          ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }
          : { hour: '2-digit', minute: '2-digit' }),
      };
    });
    return { candles, minLabel: min.toFixed(digits), maxLabel: max.toFixed(digits),
      latestLabel: new Date(source[source.length - 1].open_time_sast + '+02:00').toLocaleString('en-ZA', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short' }),
      latestPrice: latestClose.toFixed(digits), change: `${changePct >= 0 ? '+' : ''}${changePct.toFixed(3)}%`, positive: changePct >= 0,
      openPrice: firstOpen.toFixed(digits), highPrice: periodHigh.toFixed(digits), lowPrice: periodLow.toFixed(digits), priceTicks, timeTicks,
      chartWidth: width, chartHeight: height, minValue: min, maxValue: max, priceDigits: digits,
      plotLeft: left, plotRight: right, plotTop: top, plotBottom: bottom };
  }

  private observeChartViewport(viewport?: HTMLDivElement): void {
    this.chartResizeObserver?.disconnect();
    if (!viewport) return;
    if (typeof ResizeObserver !== 'undefined') {
      this.chartResizeObserver = new ResizeObserver(() => this.scheduleChartDimensions());
      this.chartResizeObserver.observe(viewport);
    }
    this.scheduleChartDimensions();
  }

  private scheduleChartDimensions(): void {
    if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
    this.resizeFrame = requestAnimationFrame(() => {
      this.resizeFrame = null;
      this.refreshChartDimensions(false);
    });
  }

  private refreshChartDimensions(refit: boolean): void {
    const viewport = this.chartViewport?.nativeElement;
    if (!viewport) return;
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (width <= 0 || height <= 0) return;
    this.chartViewportWidth.set(width);
    this.chartViewportHeight.set(height);
    if (refit && this.autoFollowLatest()) this.goToLatest();
  }

  private updateCrosshair(event: PointerEvent): void {
    const viewport = this.chartViewport?.nativeElement;
    const chart = this.candleChart();
    if (!viewport || !chart.candles.length) return;
    const rect = viewport.getBoundingClientRect();
    const x = Math.max(chart.plotLeft, Math.min(event.clientX - rect.left, chart.chartWidth - chart.plotRight));
    const y = Math.max(chart.plotTop, Math.min(event.clientY - rect.top, chart.chartHeight - chart.plotBottom));
    const candle = chart.candles.reduce((closest, item) =>
      Math.abs(item.x - x) < Math.abs(closest.x - x) ? item : closest, chart.candles[0]);
    this.hoveredCandleIndex.set(candle.sourceIndex);
    this.crosshairX.set(candle.x);
    this.crosshairY.set(y);
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
