import { describe, expect, it } from 'vitest';
import { clampWindow, isAtLatest, latestWindow, mergeStreamCandle, normalizeCandles, recommendedCandleCount, visiblePriceBounds } from './chart-utils';
import { MarketCandle } from './dashboard-api';

function candle(time: string, open: number, high: number, low: number, close: number): MarketCandle {
  return { open_time_utc: time, open_time_sast: time.replace('Z', ''), open: String(open), high: String(high),
    low: String(low), close: String(close), bid_close: null, ask_close: null, spread_close: null,
    is_regular_session: true, tick_count: 1, source: 'TEST' };
}

describe('candlestick viewport utilities', () => {
  it('selects the most recent recommended candles', () => {
    expect(recommendedCandleCount('M5')).toBe(100);
    expect(recommendedCandleCount('H4')).toBe(64);
    expect(latestWindow(1000, 100)).toEqual({ start: 900, count: 100 });
  });

  it('calculates padded bounds from only the supplied visible candles', () => {
    const bounds = visiblePriceBounds([
      candle('2026-09-01T00:00:00Z', 1.1, 1.12, 1.09, 1.11),
      candle('2026-09-01T00:05:00Z', 1.11, 1.13, 1.1, 1.12),
    ], 0.00001);
    expect(bounds.minimum).toBeLessThan(1.09);
    expect(bounds.maximum).toBeGreaterThan(1.13);
    expect(bounds.minimum).toBeGreaterThan(1.08);
  });

  it('handles flat and one-candle markets without a zero range', () => {
    const bounds = visiblePriceBounds([candle('2026-09-01T00:00:00Z', 200, 200, 200, 200)], 0.1);
    expect(bounds.maximum).toBeGreaterThan(bounds.minimum);
  });

  it('sorts candles and merges duplicate timestamps using the latest value', () => {
    const earlier = candle('2026-09-01T00:00:00Z', 1, 2, 0.5, 1.5);
    const replacement = candle('2026-09-01T00:00:00Z', 1, 3, 0.5, 2.5);
    const later = candle('2026-09-01T00:05:00Z', 2.5, 3, 2, 2.8);
    const result = normalizeCandles([later, earlier, replacement]);
    expect(result).toHaveLength(2);
    expect(result[0].close).toBe('2.5');
    expect(result[1].open_time_utc).toBe(later.open_time_utc);
  });

  it('clamps historical navigation and recognises the latest edge', () => {
    expect(clampWindow(1000, 850, 100)).toEqual({ start: 850, count: 100 });
    expect(clampWindow(1000, 990, 100)).toEqual({ start: 900, count: 100 });
    expect(isAtLatest(1000, 900, 100)).toBe(true);
    expect(isAtLatest(1000, 700, 100)).toBe(false);
  });

  it('mutates the active streamed candle without rebuilding the series', () => {
    const first = candle('2026-09-01T00:00:00Z', 1, 2, .5, 1.5);
    const active = candle('2026-09-01T00:05:00Z', 1.5, 2, 1, 1.8);
    const updated = candle('2026-09-01T00:05:00Z', 1.5, 2.2, .9, 2.1);
    const result = mergeStreamCandle([first, active], updated);
    expect(result).toHaveLength(2);
    expect(result[0]).toBe(first);
    expect(result[1]).toBe(updated);
  });

  it('appends one new candle and rejects stale or duplicate stream events', () => {
    const first = candle('2026-09-01T00:00:00Z', 1, 2, .5, 1.5);
    const second = candle('2026-09-01T00:05:00Z', 1.5, 2, 1, 1.8);
    const next = candle('2026-09-01T00:10:00Z', 1.8, 2.1, 1.7, 2);
    const appended = mergeStreamCandle([first, second], next);
    expect(appended).toHaveLength(3);
    expect(mergeStreamCandle(appended, first)).toBe(appended);
    expect(mergeStreamCandle(appended, next)).toBe(appended);
  });
});
