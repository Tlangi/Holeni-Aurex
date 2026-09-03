import { Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, KeyValuePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { DashboardApi, ResearchExperiment, ResearchStatusData } from './dashboard-api';
import { AuthApi } from './auth-api';

@Component({
  selector: 'aurex-research',
  imports: [DatePipe, DecimalPipe, KeyValuePipe, RouterLink, FormsModule],
  templateUrl: './research.html',
  styleUrl: './research.scss',
})
export class ResearchComponent {
  private readonly api = inject(DashboardApi);
  private readonly auth = inject(AuthApi);
  private readonly router = inject(Router);
  protected readonly data = signal<ResearchStatusData | null>(null);
  protected readonly loading = signal(true);
  protected readonly busy = signal('');
  protected readonly message = signal('');
  protected readonly researchTab = signal<'overview' | 'protocol' | 'data' | 'holdout' | 'experiments'>('overview');
  protected readonly researchTabs = [
    ['overview', 'Market overview'], ['protocol', 'Protocol & lineage'],
    ['data', 'Data operations'], ['holdout', 'Holdout governance'],
    ['experiments', 'Experiments'],
  ] as const;
  protected readonly logoutBusy = signal(false);
  protected readonly selectedExperiment = signal<ResearchExperiment | null>(null);
  protected readonly selectedDimension = signal('direction');
  protected readonly selectedTarget = signal<{ symbol: string; target_mode: string;
    horizon_bars: number; target_sha256: string } | null>(null);
  protected readonly hypothesis = signal('Cost-aware directional edge remains stable across chronological windows and realistic execution stresses.');
  protected readonly dimensions = [
    ['direction', 'Long vs Short'], ['session_name', 'Sessions'], ['entry_quarter', 'Time of Day'],
    ['weekday', 'Weekdays'], ['trend_regime', 'Trend Regimes'],
    ['volatility_regime', 'Volatility'], ['confidence_bucket', 'Confidence'],
    ['spread_cost_bucket', 'Costs'], ['mae_bucket', 'MAE'], ['mfe_bucket', 'MFE'],
    ['entry_reason', 'Entry Reasons'], ['exit_reason', 'Exit Reasons'],
  ] as const;

  protected readonly dimensionRows = computed(() => {
    const experiment = this.selectedExperiment();
    return experiment?.decomposition?.[this.selectedDimension()] ?? [];
  });

  protected readonly marketGroups = computed(() => {
    const markets = this.data()?.markets ?? [];
    return [1, 2, 3].map((tier) => ({
      tier,
      label: tier === 1 ? 'Core governed markets' : tier === 2 ? 'Expansion research' : 'Research only',
      markets: markets.filter((market) => market.tier === tier),
    })).filter((group) => group.markets.length > 0);
  });

  protected protocolPassed(research: ResearchStatusData): string {
    const rows = research.selective_protocol.target_specifications;
    return `${rows.filter((item) => item.passed === true).length}/${rows.length}`;
  }

  constructor() { this.load(); }

  protected load(): void {
    this.loading.set(true);
    this.api.researchStatus().pipe(finalize(() => this.loading.set(false))).subscribe({
      next: (data) => {
        this.data.set(data);
        const selected = this.selectedExperiment();
        this.selectedExperiment.set(data.experiments.find((item) => item.experiment_id === selected?.experiment_id)
          ?? data.experiments[0] ?? null);
      },
      error: () => this.message.set('Research evidence could not be loaded.'),
    });
  }

  protected quality(symbol: string) {
    return this.data()?.execution_quality.find((item) => item.symbol === symbol);
  }

  protected cost(symbol: string) {
    return this.data()?.cost_models.find((item) => item.symbol === symbol);
  }

  protected syncEvidence(): void {
    this.busy.set('sync'); this.message.set('');
    this.api.syncResearchEvidence().pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set('Evidence refresh started in the background. Latest stored evidence is shown.'); this.load(); },
      error: () => this.message.set('Evidence refresh failed; execution remains blocked.'),
    });
  }

  protected runProtocolAudit(): void {
    this.busy.set('protocol-audit'); this.message.set('');
    this.api.runResearchProtocolAudit().pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set('Leakage and provider-boundary audit queued. No holdout was accessed.'); this.load(); },
      error: () => this.message.set('Protocol audit could not be queued; execution remains blocked.'),
    });
  }

  protected chooseTarget(target: { symbol: string; target_mode: string;
    horizon_bars: number; target_sha256: string }): void {
    this.selectedTarget.set(target);
  }

  protected reserveLineage(): void {
    const target = this.selectedTarget();
    if (!target || this.hypothesis().trim().length < 20) {
      this.message.set('Select a target and enter a hypothesis of at least 20 characters.'); return;
    }
    this.busy.set('lineage'); this.message.set('');
    this.api.reserveResearchLineage(target.symbol, target.target_mode, target.horizon_bars,
      this.hypothesis().trim()).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set(`${target.symbol} lineage reserved. Run a new boundary audit before the tournament.`); this.load(); },
      error: (error) => this.message.set(error?.error?.message ?? 'Lineage reservation was blocked safely.'),
    });
  }

  protected queueTournament(symbol: string): void {
    this.busy.set(`tournament-${symbol}`); this.message.set('');
    this.api.runSelectiveTournament(symbol).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set(`${symbol} selective tournament queued; the holdout remains untouched.`); this.load(); },
      error: (error) => this.message.set(error?.error?.message ?? 'Tournament was blocked safely.'),
    });
  }

  protected freezeLeader(symbol: string): void {
    this.busy.set(`freeze-${symbol}`); this.message.set('');
    this.api.freezeSelectiveCandidate(symbol).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set(`${symbol} exact tournament leader frozen. No holdout was consumed.`); this.load(); },
      error: (error) => this.message.set(error?.error?.message ?? 'Candidate freeze was blocked safely.'),
    });
  }

  protected marketBlocker(market: ResearchStatusData['markets'][number]): string {
    if (market.model_status !== 'VALIDATED') return 'MODEL RESEARCH';
    if (market.quality_status === 'FAIL') return 'DATA QUALITY FAILURE';
    if (market.quality_status === 'CLOSED' || market.quality_status === 'OPEN_GRACE') return 'SESSION DEFERRED';
    return 'FORWARD SHADOW';
  }

  protected logout(): void {
    if (this.logoutBusy()) return;
    this.logoutBusy.set(true);
    this.auth.logout().pipe(finalize(() => this.logoutBusy.set(false))).subscribe({
      next: () => void this.router.navigateByUrl('/login'),
      error: () => this.message.set('Logout failed. Please try again.'),
    });
  }

  protected runReplay(symbol: string): void {
    this.busy.set(symbol); this.message.set('');
    this.api.runResearchReplay(symbol).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set(`${symbol} diagnostic replay completed.`); this.load(); },
      error: () => this.message.set(`${symbol} replay failed; no strategy or execution setting changed.`),
    });
  }

  protected consumeHoldout(candidateId: string): void {
    this.busy.set(candidateId); this.message.set('');
    this.api.evaluateHoldoutCandidate(candidateId).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: (result: any) => { this.message.set(`Single-use evaluation completed: ${result.status}.`); this.load(); },
      error: () => this.message.set('Holdout evaluation was blocked; it was not retried.'),
    });
  }

  protected approveHoldout(candidateId: string): void {
    this.busy.set(`approve-${candidateId}`); this.message.set('');
    this.api.approveHoldoutCandidate(candidateId).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: () => { this.message.set('Exact holdout-passed artifact approved for forward shadow only.'); this.load(); },
      error: (error) => this.message.set(error?.error?.message ?? 'Owner approval was blocked safely.'),
    });
  }

  protected chooseExperiment(experiment: ResearchExperiment): void {
    this.selectedExperiment.set(experiment);
  }
}
