import { MarketCandle } from './dashboard-api';

export interface PriceBounds {
  minimum: number;
  maximum: number;
}

export function recommendedCandleCount(timeframe: string): number {
  return ({ M5: 100, M15: 100, M30: 80, H1: 80, H4: 64, D1: 60 } as Record<string, number>)[timeframe] ?? 80;
}

export function normalizeCandles(candles: MarketCandle[]): MarketCandle[] {
  const byTimestamp = new Map<number, MarketCandle>();
  for (const candle of candles) {
    const timestamp = Date.parse(candle.open_time_utc);
    const prices = [candle.open, candle.high, candle.low, candle.close].map(Number);
    if (!Number.isFinite(timestamp) || prices.some((price) => !Number.isFinite(price))) continue;
    const [open, high, low, close] = prices;
    if (high < Math.max(open, close, low) || low > Math.min(open, close, high)) continue;
    byTimestamp.set(timestamp, candle);
  }
  return [...byTimestamp.entries()].sort(([left], [right]) => left - right).map(([, candle]) => candle);
}

export function latestWindow(total: number, requested: number): { start: number; count: number } {
  const count = Math.max(1, Math.min(total || 1, Math.round(requested)));
  return { start: Math.max(0, total - count), count };
}

export function clampWindow(total: number, start: number, count: number): { start: number; count: number } {
  const safeCount = Math.max(1, Math.min(total || 1, Math.round(count)));
  return { start: Math.max(0, Math.min(Math.round(start), Math.max(0, total - safeCount))), count: safeCount };
}

export function visiblePriceBounds(candles: MarketCandle[], minimumTick: number): PriceBounds {
  const values = candles.flatMap((candle) => [candle.open, candle.high, candle.low, candle.close].map(Number))
    .filter(Number.isFinite);
  if (!values.length) return { minimum: 0, maximum: Math.max(minimumTick, 1) };
  const low = Math.min(...values);
  const high = Math.max(...values);
  const rawRange = high - low;
  const reference = Math.max(Math.abs(low), Math.abs(high), minimumTick);
  const padding = Math.max(rawRange * 0.08, minimumTick * 4, reference * 0.00005);
  return { minimum: low - padding, maximum: high + padding };
}

export function isAtLatest(total: number, start: number, count: number, tolerance = 2): boolean {
  return start + count >= total - tolerance;
}

export function mergeStreamCandle(candles: MarketCandle[], incoming: MarketCandle): MarketCandle[] {
  const valid = normalizeCandles([incoming]);
  if (!valid.length) return candles;
  const timestamp = Date.parse(incoming.open_time_utc);
  const latestTimestamp = candles.length ? Date.parse(candles.at(-1)!.open_time_utc) : -Infinity;
  if (timestamp < latestTimestamp) return candles;
  const existing = candles.findIndex((item) => item.open_time_utc === incoming.open_time_utc);
  if (existing >= 0) {
    if (JSON.stringify(candles[existing]) === JSON.stringify(incoming)) return candles;
    const result = candles.slice();
    result[existing] = incoming;
    return result;
  }
  return [...candles, incoming];
}
