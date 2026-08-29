import { Component, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe, KeyValuePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { DashboardApi, ResearchExperiment, ResearchStatusData } from './dashboard-api';
import { AuthApi } from './auth-api';

@Component({
  selector: 'aurex-research',
  imports: [DatePipe, DecimalPipe, KeyValuePipe, RouterLink],
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
  protected readonly logoutBusy = signal(false);
  protected readonly selectedExperiment = signal<ResearchExperiment | null>(null);
  protected readonly selectedDimension = signal('direction');
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

  protected freezeGermanyCandidate(): void {
    this.busy.set('holdout-freeze'); this.message.set('');
    this.api.freezeHoldoutCandidate().pipe(finalize(() => this.busy.set(''))).subscribe({
      next: (result: any) => {
        this.message.set(result.status === 'DATA_BLOCKED'
          ? `Holdout remains blocked: ${result.available_holdout_rows}/${result.required_holdout_rows} independent rows. No holdout was consumed.`
          : `Germany 40 candidate status: ${result.status}.`);
        this.load();
      },
      error: () => this.message.set('Candidate freeze failed safely; no holdout or execution state changed.'),
    });
  }

  protected consumeHoldout(candidateId: string): void {
    this.busy.set(candidateId); this.message.set('');
    this.api.evaluateHoldoutCandidate(candidateId).pipe(finalize(() => this.busy.set(''))).subscribe({
      next: (result: any) => { this.message.set(`Single-use evaluation completed: ${result.status}.`); this.load(); },
      error: () => this.message.set('Holdout evaluation was blocked; it was not retried.'),
    });
  }

  protected chooseExperiment(experiment: ResearchExperiment): void {
    this.selectedExperiment.set(experiment);
  }
}
