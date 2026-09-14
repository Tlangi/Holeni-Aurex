import { describe, expect, it } from 'vitest';
import { effectiveExperimentalStatus } from './experimental-lab';

describe('effectiveExperimentalStatus', () => {
  const now = Date.parse('2026-09-13T12:00:00Z');

  it('does not present a historically ARMED programme as active after expiry', () => {
    expect(effectiveExperimentalStatus('ARMED', '2026-09-11T07:06:00Z', now)).toBe('EXPIRED');
    expect(effectiveExperimentalStatus('KILLED', '2026-09-11T07:06:00Z', now)).toBe('KILLED');
  });

  it('keeps a valid programme state and fails closed on invalid expiry', () => {
    expect(effectiveExperimentalStatus('ARMED', '2026-09-14T00:00:00Z', now)).toBe('ARMED');
    expect(effectiveExperimentalStatus('ARMED', 'not-a-date', now)).toBe('UNVERIFIED');
  });
});
