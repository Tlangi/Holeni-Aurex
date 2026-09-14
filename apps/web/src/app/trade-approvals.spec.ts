import { TestBed } from '@angular/core/testing';
import { describe, expect, it, vi } from 'vitest';
import { TradeApprovalsComponent } from './trade-approvals';
import { TradeProposalsData } from './dashboard-api';

function proposal(expires: string): TradeProposalsData {
  return { status: 'OWNER_REVIEW', execution_authority: 'NONE', count: 1, proposals: [{
    trade_proposal_id: 'p-1', market: 'GBP/USD', direction: 'BUY', confidence: '0.57',
    proposed_size: '1', entry_price: '1.2500', stop_price: '1.2400', target_price: '1.2700',
    risk_zar: '25', horizon_minutes: 15, decision_time_utc: '2026-09-13T08:00:00Z',
    data_cutoff_utc: '2026-09-13T08:00:00Z', expires_at_utc: expires,
    status: 'PENDING_OWNER', rationale_summary: 'Test', notification_status: 'SENT',
    decided_at_utc: null, decision_reason: null, created_at_utc: '2026-09-13T08:00:00Z',
    evidence: { risk_acceptable: 'PASS', tradeability: {} },
  }] };
}

describe('TradeApprovalsComponent', () => {
  it('shows a countdown and emits an owner decision without submitting an order', async () => {
    await TestBed.configureTestingModule({ imports: [TradeApprovalsComponent] }).compileComponents();
    const fixture = TestBed.createComponent(TradeApprovalsComponent);
    fixture.componentRef.setInput('proposals', proposal('2026-09-13T08:01:30Z'));
    fixture.componentRef.setInput('now', Date.parse('2026-09-13T08:00:00Z'));
    fixture.detectChanges();
    const emitted = vi.fn();
    fixture.componentInstance.decision.subscribe(emitted);
    expect(fixture.nativeElement.textContent).toContain('01:30');
    expect(fixture.nativeElement.textContent).toContain('Approval does not submit an IG order');
    (fixture.nativeElement.querySelector('.proposal-actions button') as HTMLButtonElement).click();
    expect(emitted).toHaveBeenCalledWith({ id: 'p-1', action: 'APPROVE' });
  });

  it('disables both actions after expiry or while a decision is recording', async () => {
    await TestBed.configureTestingModule({ imports: [TradeApprovalsComponent] }).compileComponents();
    const fixture = TestBed.createComponent(TradeApprovalsComponent);
    fixture.componentRef.setInput('proposals', proposal('2026-09-13T08:00:00Z'));
    fixture.componentRef.setInput('now', Date.parse('2026-09-13T08:00:01Z'));
    fixture.detectChanges();
    const buttons = () => Array.from(fixture.nativeElement.querySelectorAll('.proposal-actions button')) as HTMLButtonElement[];
    expect(buttons().every((button) => button.disabled)).toBe(true);
    fixture.componentRef.setInput('proposals', proposal('2026-09-13T08:01:30Z'));
    fixture.componentRef.setInput('busyId', 'p-1');
    fixture.detectChanges();
    expect(buttons().every((button) => button.disabled)).toBe(true);
    expect(buttons()[0].textContent).toContain('Recording');
  });
});
