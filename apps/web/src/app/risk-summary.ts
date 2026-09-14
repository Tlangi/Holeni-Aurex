import { Component, input } from '@angular/core';
import { RiskStatusData } from './dashboard-api';

@Component({
  selector: 'aurex-risk-summary',
  templateUrl: './risk-summary.html',
  styleUrl: './risk-summary.scss'
})
export class RiskSummaryComponent {
  readonly risk = input<RiskStatusData | null>(null);

  protected money(value?: string): string {
    return new Intl.NumberFormat('en-ZA', { style: 'currency', currency: 'ZAR', minimumFractionDigits: 2 }).format(Number(value ?? 0));
  }
}
