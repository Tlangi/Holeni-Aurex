# Aurex Open-Source Model Lab Report — 27 August 2026

## Scope and safety

Six CPU candidates were trained independently for EUR/USD, GBP/USD, USD/JPY and
Germany 40. Every candidate used the same M15 features, four-row label purge,
three expanding chronological windows, BUY/SELL/HOLD thresholds, transaction
costs, regimes and baselines. Research used development data only. No reserved
holdout was consumed, no artifact was promoted, trading stayed disabled and no
IG order was submitted.

The tournament is market-wide but not a pooled global model. Each market retains
its own evidence, candidate choice, eventual holdout and readiness state.

## Fixed-threshold results

| Market | Informative candidate | ROC AUC | PR AUC | PF | Net expectancy | Max DD | Trades | Profitable windows | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| EURUSD | CatBoost | 0.522 | 0.505 | 0.075 | -0.0132% | 1.93% | 142 | 2/3 | Rejected |
| GBPUSD | Random forest (best AUC) | 0.518 | 0.511 | 0.029 | -0.0138% | 1.75% | 126 | 0/3 | Rejected |
| USDJPY | Aurex HGB | 0.508 | 0.550 | 1.126 | +0.0078% | 4.33% | 176 | 2/3 | Rejected |
| GERMANY40 | XGBoost | 0.482 | 0.519 | 0.836 | -0.0101% | 2.31% | 117 | 2/3 | Rejected |

The rows are representative research comparisons, not universal winners. GBP/USD
logistic regression and Germany 40 random forest each showed superficially large
profit factors at the fixed 0.70 threshold, but generated only one trade and are
therefore invalid evidence.

## Selective BUY/SELL/HOLD research

Four predeclared threshold pairs were evaluated on development validation only:
0.55/0.45, 0.60/0.40, 0.65/0.35 and 0.70/0.30.

| Market | Exploratory selective leader | Threshold | PF | Net expectancy | Max DD | Trades | Profitable windows | Why it still fails |
|---|---|---:|---:|---:|---:|---:|---:|---|
| EURUSD | Logistic regression | 0.55 | 1.008 | +0.0005% | 2.16% | 58 | 2/3 | Negligible edge; worst window negative |
| GBPUSD | Logistic regression | 0.55 | 1.001 | +0.0001% | 3.48% | 201 | 2/3 | Below PF requirement and above 3% DD |
| USDJPY | Logistic regression | 0.65 | 1.103 | +0.0103% | 4.22% | 121 | 2/3 | AUC, drawdown and worst-window failures |
| GERMANY40 | Logistic regression | 0.60 | 1.025 | +0.0016% | 1.58% | 31 | 2/3 | AUC and PF failures; worst window negative |

Threshold selection is exploratory configuration research. These results cannot
be applied to the holdout or execution unless the exact configuration is frozen.

## Trust findings

- No model works reliably across all four markets under the current seven-feature
  directional formulation.
- USD/JPY remains the strongest economic research market, but its apparent edge
  comes with unacceptable drawdown and weak discrimination.
- Brier scores remain close to 0.25 and log loss close to 0.693 for most FX
  candidates. That is near an uninformative balanced binary forecast. Germany 40
  boosting calibration is worse, with calibration error from roughly 0.10 to 0.16.
- Volatility and regime variables (`atr_pct`, `range_pct`, `ema_gap`, `rsi`) dominate
  tree importance across markets. Importance is associative, not causal evidence.
- New boosting libraries did not create a durable edge. More model complexity is
  therefore not the immediate answer.

## Implementation record

- Added LightGBM 4.7.0, XGBoost 3.4.1 and CatBoost 1.2.10 to the existing Python
  environment and dependency file.
- `MODEL_TOURNAMENT_V3_OPEN_SOURCE_STRICT` records exact model parameters, CPU
  limits, gate values, ROC AUC, PR AUC, Brier score, log loss, calibration buckets,
  feature importance, selective thresholds and window evidence.
- Freeze eligibility uses the stricter 3% final-holdout drawdown ceiling even
  though scheduled diagnostic training retains a wider 10% tolerance.
- Research runs sequentially and each native model is limited to two CPU threads.

Latest strict experiment IDs:

- EURUSD: `533d3338-1f46-4254-9772-979cbba62881`
- GBPUSD: `214ae9c5-be5f-45d5-9b66-7374080f0923`
- USDJPY: `570f0749-3823-48e7-af1f-1b149955337c`
- GERMANY40: `c9fef900-e4a0-46e6-9a4c-9dda04774eda`

## Next experiment

Do not add Qlib or deep learning yet. Pre-register one simple, explainable primary
setup that can operate on every market while retaining market-specific parameters
and validation. Then test a leakage-safe `TAKE`/`SKIP` meta-label on the proposed
direction. That directly tests whether ML can remove bad setups without asking it
to predict every future candle. Run the same meta-label tournament independently
for all four markets and keep `NO MODEL QUALIFIED` as an acceptable outcome.
