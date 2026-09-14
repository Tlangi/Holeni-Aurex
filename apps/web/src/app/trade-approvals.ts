import { DatePipe } from '@angular/common';
import { Component, input, output } from '@angular/core';
import { TradeProposalsData } from './dashboard-api';

@Component({
  selector: 'aurex-trade-approvals',
  imports: [DatePipe],
  templateUrl: './trade-approvals.html',
  styleUrl: './trade-approvals.scss',
})
export class TradeApprovalsComponent {
  readonly proposals = input<TradeProposalsData | null>(null);
  readonly busyId = input('');
  readonly message = input('');
  readonly now = input(Date.now());
  readonly decision = output<{ id: string; action: 'APPROVE' | 'DECLINE' }>();

  protected remaining(expiresAt: string): string {
    const seconds = Math.max(0, Math.ceil((Date.parse(expiresAt) - this.now()) / 1000));
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }

  protected expired(expiresAt: string): boolean {
    return !Number.isFinite(Date.parse(expiresAt)) || Date.parse(expiresAt) <= this.now();
  }

  protected money(value: string): string {
    return new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', minimumFractionDigits: 2 }).format(Number(value));
  }

  protected confidence(value: string): string {
    const score = Number(value);
    return Number.isFinite(score) ? `${(score * 100).toFixed(1)}%` : '—';
  }
}
