# Aurex multi-timeframe model implementation — 2026-09-12

## Status

**Partial implementation; not trading-ready.** This sprint's first research primitives are implemented and unit-tested. No experiment has been run against current SQL data, no model has been promoted or enabled, no Shadow state was changed, and no order was sent. This report deliberately does not claim the full 70-section command is complete.

## Implementation and schema changes

- Added `app.multi_timeframe_research.ResearchArchitecture`: explicit signal/context/execution timeframes, forecast and holding horizons, feature/label/strategy/cost versions, and a stable metadata digest. M1 is execution-only in this contract; M5 and M15 remain candidates.
- Added a completed-bar context join. An M5 signal at 08:05 UTC cannot consume the M15 candle opened at 08:00 UTC until that M15 candle completes at 08:15 UTC. Duplicate and timezone-naive indexes fail closed.
- Added a strict one-to-one prediction/outcome bridge keyed by prediction timestamp, fold and dataset row, with experiment/market/dataset identity. Missing or duplicated rows fail closed. It is an in-memory research primitive, **not** yet immutable SQL evidence storage.
- Added experimental `CFD_NET_OPPORTUNITY_V1` fixed-horizon label using entry ask/future bid for longs and entry bid/future ask for shorts, explicit slippage/funding/required-edge parameters, and a NO_TRADE abstain state. Any missing M1 interval or quote gives UNKNOWN. This is not yet a stop/target path-aware label; it must not be used for model promotion.
- No migration, data update, execution configuration, broker call or model artifact change was made.

## Data and baselines

The pre-change audit recorded 90-day completed PASS M5 counts of GBPUSD 4,458 and USDJPY 4,451, with M15 counts 1,478 and 1,475. Those are not frozen dataset manifests or current quality percentages. The requested immutable GBPUSD/USDJPY baseline freeze remains outstanding. Historical AUC/PF figures (~0.573/0.642 for GBPUSD and ~0.538/0.424 for USDJPY) are prior evidence, **not** results of this implementation.

## Research comparison

| Architecture | Label | AUC/ranking | Trades | Net expectancy | PF | Drawdown | Stability |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| GBPUSD M15 | Direction | Not rerun | — | — | — | — | — |
| GBPUSD M5 | Direction | Not run | — | — | — | — | — |
| GBPUSD M5+M15 | Direction | Not run | — | — | — | — | — |
| Best GBPUSD | CFD Net Opportunity | Not run | — | — | — | — | — |
| USDJPY M15 | Direction | Not rerun | — | — | — | — | — |
| USDJPY M5 | Direction | Not run | — | — | — | — | — |
| USDJPY M5+M15 | Direction | Not run | — | — | — | — | — |
| Best USDJPY | CFD Net Opportunity | Not run | — | — | — | — | — |

No signal timeframe, context timeframe, model, label or Demo market is selected. `CURRENT_MODEL_FAMILY_ADEQUATE`, `MODEL_SIGNAL_PRESENT` and `TRADING_CONVERSION_DESTROYS_EDGE` remain UNCERTAIN pending matched out-of-fold economic results. The existing direction label remains untouched for comparison.

## Safety and readiness

The new code is non-executing and disconnected from production training, Shadow and Demo. The M1 layer is sufficient for *fixed-horizon label construction* only when a complete executable quote path exists; stop/target ordering, MFE/MAE and slippage evidence are not yet integrated. Therefore `M1_EXECUTION_LAYER_READY=NO`, `M5_RESEARCH_LAYER_READY=PARTIAL`, `M15_CONTEXT_LAYER_READY=PARTIAL`, `MULTI_TIMEFRAME_JOIN_SAFE=YES` for the tested helper, `POINT_IN_TIME_LEAKAGE=NO` for that join only, and `SAME_COHORT_DIAGNOSTIC_READY=PARTIAL` (join contract exists, persisted matched replay does not).

`DEMO_EXPERIMENT_MODEL_AVAILABLE=NO`; `SHADOW_ACTIVE=NO` was not established by a fresh SQL status query; `BROKER_RULES_READY=NO` on current verified authority; `RISK_READY=NOT_VERIFIED`; `HUMAN_APPROVED_DEMO_BACKEND_READY=NO`. Demo execution was not armed by this work. Live was not enabled by this work; runtime flags should be checked before any canary.

## Tests

Focused test module: five passed. It covers completed context timing, bid/ask economics, M1 gap rejection, bridge cardinality and timeframe metadata validation. Full backend suite and live-data experiments have not yet run.

## Five remaining blockers, in dependency order

1. **Research/data:** Freeze current GBPUSD/USDJPY dataset hashes and model baselines, with holdout boundaries and provider lineage. Blocks reproducible comparison; not Demo execution directly.
2. **Research/wiring:** Persist immutable experiment and prediction-to-trade evidence, then connect out-of-fold predictions to the actual broker-aware replay on identical row IDs. Blocks a defensible model decision and Shadow.
3. **Label/execution:** Resolve stop/target event order from complete M1 bid/ask paths; mark ambiguous cases conservatively. Test 30/60-minute economic labels without future-context leakage. Blocks aligned-label claim.
4. **Model:** Run predeclared GBPUSD M15, M5 and M5+M15 development comparisons, then selected-label and USDJPY replication with holdout isolation and per-window gates. Blocks candidate/Shadow.
5. **Demo safety:** After a candidate earns forward Shadow evidence, verify current IG dealing rules, minimum-size risk, authenticated owner approval, atomic submission and reconciliation. Blocks Human-Approved Demo. Demo and Live must remain unarmed.

## Next action

Implement immutable baseline/experiment storage and a read-only SQL-backed same-cohort extraction, then run the existing GBPUSD M15 baseline without touching holdout or trading state.

## Continuation — baseline boundary and snapshot

Added [read-only baseline extraction](../../services/platform-api/app/research_baselines.py) and a command that prints current reserved-lineage snapshots. The extraction filters `app.candles` in SQL to `open_time_utc < holdout_start_utc`, and rejects any requested range that crosses that boundary before querying. A concrete [GBPUSD/USDJPY data snapshot](AUREX_BASELINE_DATASET_SNAPSHOT_2026-09-12.json) records hashes, counts, provider mix, lineage IDs and boundaries. GBPUSD has 43,012 selected development M15 bars, all `DUKASCOPY_BID_M15`, ending 2025-10-06 01:30 UTC; USDJPY has 9,984, also all Dukascopy, ending 2024-05-28 14:45 UTC. These are immutable *file evidence* for the read-only extraction, not an applied SQL registry or a model rerun. `6/6` focused tests pass across the baseline and timeframe modules.

The existing reserved holdouts begin 2025-10-06 01:45 UTC (GBPUSD) and 2024-05-28 15:00 UTC (USDJPY), extending through much of 2026. Consequently the requested recent-2026 M5/M15 comparisons cannot be described as development-only under these existing lineages. Before running them, research governance must establish a **new, explicitly versioned cohort and holdout boundary**, and document whether 2026 data previously inspected has already been used for model selection. Reusing a viewed period as an untouched holdout would be invalid. No holdout rows were fetched by the new extractor.

The lineage metadata names `COST_VOLATILITY_TERNARY_V1`, not the old `FUTURE_CLOSE_DIRECTION_4_M15_V2` baseline. Its model family and thresholds were not attested by this snapshot; no numerical M15 baseline result is claimed. Migration `055_multi_timeframe_research_evidence.sql` prepares append-only experiment and same-cohort prediction/trade tables with uniqueness, period, JSON and probability checks. It has **not been applied** to SQL Server, and no result rows have been written. Its `outcome_json` must be populated by the real M1 broker-aware replay and verified before model comparison can count as durable economic evidence. The next step is to apply/verify the migration, wire a transactional writer with readback, and establish a new 2026 development/validation/holdout protocol before model comparisons.
