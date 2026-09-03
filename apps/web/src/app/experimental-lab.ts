import { KeyValuePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import { DashboardApi, ExperimentalLabData } from './dashboard-api';

@Component({
  selector: 'app-experimental-lab',
  standalone: true,
  imports: [RouterLink, KeyValuePipe],
  templateUrl: './experimental-lab.html',
  styleUrl: './experimental-lab.scss',
})
export class ExperimentalLabComponent implements OnInit {
  private readonly api = inject(DashboardApi);
  protected readonly data = signal<ExperimentalLabData | null>(null);
  protected readonly busy = signal('');
  protected readonly message = signal('');
  protected readonly selectedCandidate = signal('');

  ngOnInit(): void {
    this.load();
  }

  protected load(): void {
    this.busy.set('refresh');
    this.api
      .experimentalLab()
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: (data) => {
          this.data.set(data);
          if (!this.selectedCandidate() && data.candidates[0])
            this.selectedCandidate.set(data.candidates[0].model_version_id);
        },
        error: () => this.message.set('Experimental Lab evidence could not be loaded.'),
      });
  }

  protected selectCandidate(event: Event): void {
    this.selectedCandidate.set((event.target as HTMLSelectElement).value);
  }

  protected createCanary(data: ExperimentalLabData): void {
    const candidate = data.candidates.find(
      (item) => item.model_version_id === this.selectedCandidate(),
    );
    if (!candidate) return;
    if (
      !window.confirm(
        `Create a DRAFT IG Demo evidence programme for ${candidate.symbol} model ${candidate.version}? This does not arm it or approve the model.`,
      )
    )
      return;
    const start = new Date();
    const expiry = new Date(start.getTime() + 24 * 60 * 60 * 1000);
    this.busy.set('create');
    this.api
      .createExperimentalProgramme({
        symbol: candidate.symbol,
        model_version_id: candidate.model_version_id,
        starts_at_utc: start.toISOString(),
        expires_at_utc: expiry.toISOString(),
        programme_type: 'INFRASTRUCTURE_CANARY',
        max_attempts: 1,
        max_holding_minutes: 240,
      })
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: () => {
          this.message.set('Draft canary created. No experiment was armed.');
          this.load();
        },
        error: (error) =>
          this.message.set(error?.error?.reason_code ?? 'Draft creation was blocked.'),
      });
  }

  protected control(
    programmeId: string,
    action: 'ARM' | 'PAUSE' | 'RESUME' | 'KILL' | 'COMPLETE',
  ): void {
    const ack =
      action === 'ARM'
        ? 'ARM_EXPERIMENTAL_IG_DEMO_EVIDENCE_PROGRAMME'
        : action === 'KILL'
          ? 'STOP_EXPERIMENTAL_PROGRAMME'
          : action;
    if (
      (action === 'ARM' || action === 'KILL') &&
      !window.confirm(
        `${action} this isolated IG Demo evidence programme? Model promotion remains impossible.`,
      )
    )
      return;
    this.busy.set(programmeId);
    this.api
      .controlExperimentalProgramme(programmeId, action, ack)
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: () => {
          this.message.set(`${action} recorded.`);
          this.load();
        },
        error: (error) => this.message.set(error?.error?.reason_code ?? `${action} was blocked.`),
      });
  }

  protected reconcile(): void {
    this.busy.set('reconcile');
    this.api
      .reconcileExperimentalDemo()
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: () => {
          this.message.set('Broker reconciliation completed.');
          this.load();
        },
        error: () =>
          this.message.set('Reconciliation failed; experimental submission remains blocked.'),
      });
  }

  protected submitAttempt(attemptId: string): void {
    if (
      !window.confirm(
        'Route this one pre-evaluated attempt to IG Demo? It cannot be retried automatically and does not approve the model.',
      )
    )
      return;
    this.busy.set(attemptId);
    this.api
      .submitExperimentalAttempt(attemptId)
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: () => {
          this.message.set('Experimental attempt processed and reconciled.');
          this.load();
        },
        error: (error) => {
          this.message.set(error?.error?.reason_code ?? 'Submission was blocked.');
          this.load();
        },
      });
  }

  protected closePosition(attemptId: string): void {
    if (!window.confirm('Close this exact open Experimental IG Demo position now?')) return;
    this.busy.set(attemptId);
    this.api
      .closeExperimentalPosition(attemptId)
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: () => {
          this.message.set('Experimental position close confirmed.');
          this.load();
        },
        error: (error) => {
          this.message.set(
            error?.error?.reason_code ?? 'Close was blocked pending reconciliation.',
          );
          this.load();
        },
      });
  }
}
