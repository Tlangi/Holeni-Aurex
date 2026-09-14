import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { RiskSummaryComponent } from './risk-summary';

describe('RiskSummaryComponent', () => {
  it('keeps technical ledger fields behind advanced disclosure', async () => {
    await TestBed.configureTestingModule({ imports: [RiskSummaryComponent] }).compileComponents();
    const fixture = TestBed.createComponent(RiskSummaryComponent);
    fixture.detectChanges();
    const details = fixture.nativeElement.querySelector('details') as HTMLDetailsElement;
    expect(fixture.nativeElement.textContent).toContain('Daily loss limit');
    expect(details.open).toBe(false);
    expect(details.textContent).toContain('Consecutive losses');
    expect(fixture.nativeElement.textContent).toContain('UNKNOWN');
  });
});
