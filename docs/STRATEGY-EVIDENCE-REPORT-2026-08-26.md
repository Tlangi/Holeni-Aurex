# Aurex strategy-evidence report — 26 August 2026

## Safety boundary

This report contains offline diagnostics of the latest **rejected** model for
each market. Every run used `TECHNICAL_DIAGNOSTIC`, is non-promotable, and has
no broker execution authority. It is not forward-shadow evidence and does not
change any market execution mode.

## Method

- Chronological M15 replay from 1 January 2024 through the latest available
  completed candle (26 August 2026).
- Continuous-segment boundary handling: positions never cross a missing-data,
  provider or session boundary without an explicit `END_OF_SEGMENT` close.
- Latest account equity (approximately R319,600) and current IG demo market
  rules determine position size; sub-minimum positions are rejected.
- Risk per trade: 0.25%; reward/risk: 1.5; maximum holding: 32 M15 candles.
- Costs: current empirical IG spread model, 0.5 bps slippage and configured
  funding. Normal, optimistic and stressed cost variants were registered.
- Model outputs are evaluated diagnostically even though the models remain
  rejected. The result cannot promote a model.

## Full available-history result — normal costs

| Market | Candles | Trades | Net P/L | Profit factor | Cost-aware expectancy | Max drawdown | Min-size rejects | Finding |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| EURUSD | 64,193 | 60 | -R7,288.73 | 0.66 | -R121.48 | 3.00% | 85 | Rejected: negative edge and sparse executable sizing |
| GBPUSD | 53,199 | 411 | R39,345.86 | 1.29 | R95.73 | 3.74% | 0 | Research candidate only; drawdown exceeds 3% ceiling |
| USDJPY | 11,520 | 527 | R12,131.13 | 1.07 | R23.02 | 5.11% | 145 | Rejected: weak margin over costs and excessive drawdown |
| GERMANY40 | 4,770 | 249 | R25,949.04 | 1.45 | R104.21 | 1.95% | 7 | Strongest diagnostic candidate; validation still absent |

The different candle totals are truthful provider/market-session availability,
not imputed rows. Data volume must not be confused with independent evidence:
trades share regimes and time periods.

## Cost sensitivity (10,000-candle ceiling)

Germany 40 remained positive under the stressed empirical spread model:
249 trades, R16,903.11 net P/L, 1.28 profit factor, R67.88 expectancy and
2.05% drawdown. In the same stressed pass, GBPUSD fell to a 0.54 profit factor
and USDJPY to 0.77. EURUSD had only two executable trades in that bounded
sample and is statistically unusable.

This sensitivity evidence supports further research on Germany 40 and possibly
GBPUSD. It does not establish an out-of-sample edge. No threshold, label,
feature or model may be selected using the final holdout.

## Required next evidence

1. Freeze a candidate feature, label, regime and cost configuration using only
   train/validation periods.
2. Evaluate it once on a later untouched holdout.
3. Require calibration, baseline outperformance, regime stability and drift
   evidence in addition to aggregate P/L.
4. Start market-specific forward shadow only after offline validation passes.
5. Apply the existing sustained forward-shadow policy before `DEMO_TEST_READY`.

Current execution conclusion: **all markets remain blocked**. No IG order was
submitted, demo automatic execution remains disabled, and no live-trading path
exists.

## Holdout enforcement update

`FROZEN_HOLDOUT_V1` is now enforced. The Germany 40 reservation attempt retained
2,006 feature-complete development rows but found only 234 independent holdout
rows versus the required 500. It was recorded as `DATA_BLOCKED`; no model outcome
was calculated on the holdout, no candidate artifact was created and the holdout
remains unconsumed.
