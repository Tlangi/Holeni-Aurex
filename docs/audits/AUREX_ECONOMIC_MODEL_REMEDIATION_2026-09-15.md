# Aurex economic-model remediation — implementation increment 1, 15 September 2026

## Scope and outcome

This is the **first completed implementation increment** against `AUREX_ECONOMIC_MODEL_IMPLEMENTATION_PLAN_2026-09-15.md`, not a declaration that every audit blocker is resolved. The outcome sought is scientific validity: a future positive PF/expectancy must come from executable broker-native bid/ask paths, declared CFD costs, fixed policy and chronological validation. **No profitable model was sought or identified. No model was trained, promoted, or connected to execution. Trading remains fail-closed.** The registered M15 directional label remains historical evidence and is not overwritten.

## 1. Files changed

Added `services/platform-api/app/executable_trade_outcome.py`, `app/broker_m1_quality.py`, `app/point_in_time_features.py`, `scripts/report_broker_m1_quality.py`, and targeted tests `test_executable_trade_outcome.py`, `test_broker_m1_quality.py`, `test_point_in_time_features.py`. Extended `tests/test_broker_rules.py` to assert that IG's price `minStepDistance` is never interpreted as an authoritative *deal-size* increment. Added the implementation plan and this report. No existing trading, settings, model registry, broker persistence or frontend source was edited. The comprehensive 15 September audit remains preserved.

## 2. Migrations applied

**Zero.** This increment is research-only and read-only against SQL. No new cohort or outcome was persisted. Immutable research persistence/schema design remains a subsequent step, after the source/path contract is exercised and reviewed. Latest applied schema observed in the preceding audit was migration 058; it was not changed here.

## 3. Tests

Targeted new/related suites: **28 passed**; point-in-time feature suite: **4 passed**. Complete backend: **357 passed, 2 upstream joblib/NumPy deprecation warnings**, no failures/skips. Frontend: **40 passed in 5 files**. Angular production browser/server build passed with no reported budget warnings. Unit tests cover LONG ask→bid, SHORT bid→ask, stop adverse open gaps, first-hit, ambiguous same M1, missing/crossed/non-broker paths, missing declared costs, financing, policy-sensitive identity, no-trade, source separation, calendar gaps, future feature exclusion and expired programme behavior retained from the prior suite. These do not prove real IG fill behavior or a model edge.

## 4. Safety-state verification

Before: local settings `trading_mode=demo`, Demo capability configured true, Live false, Experimental Demo feature true; SQL engine `SHADOW`, `new_orders_enabled=false`; one EUR/USD programme ARMED but expired 11 September 07:06 UTC with REJECTED model; 0 experimental attempts, 0 order intents, 0 unresolved intents, 0 authoritative broker size increments. After implementation/test/build, preopen check at approximately 06:58 UTC returned engine `SHADOW`, orders false, Live false, unresolved intents 0, authoritative increments 0. SQL still had 0 experimental attempts, order intents, Shadow candidates and trades. Feature capability flags are not order authority. The research evaluator imports no DB or IG client and performs no side effect. No order, programme arming, model promotion or service restart occurred.

## 5. New label architecture

`EXECUTABLE_TRADE_OUTCOME_M1_V1_RESEARCH` identifies an outcome by market, decision UTC, feature cutoff UTC, feature/research/dataset hash, direction, execution policy and cost policy. `prediction_id()` is a canonical SHA-256 of all declared assumptions, so policy changes produce a new identity rather than silently updating a past result. LONG, SHORT and NO_TRADE are distinct. A complete path produces `PROFITABLE_LONG`, `PROFITABLE_SHORT` or `NONPROFITABLE_TRADE` from **net executable** return. Missing IG M1, invalid quote/source, unknown cost, intrabar ambiguity or insufficient path returns `UNVERIFIABLE` without a net label. No existing registered `FUTURE_CLOSE_DIRECTION_4_M15_V2` model uses this label yet; its model-design blocker is only **partially resolved**.

## 6. Execution policy

Declared `ExecutionPolicy` uses the first IG Lightstreamer M1 open at or after the decision timestamp, never the M15 close. The feature cutoff cannot exceed decision time. Stop/target distances and maximum holding are fixed, versioned research parameters. LONG enters ask and exits bid; SHORT enters bid and exits ask. M1 rows are evaluated chronologically for STOP, TARGET, TIME_EXIT or SESSION_EXIT using an optional market-specific session callback. When both barriers occur in the same M1 OHLC candle, ordering is unknown and the outcome is `AMBIGUOUS`/unverifiable; it never selects the favorable side. Missing/crossed/incomplete/non-IG rows fail. A stop touched after an adverse opening gap uses the adverse open, not an optimistic stop-level price. Full policy-family preregistration and market-specific ATR distances remain to do.

## 7. CFD cost model

Versioned `CostPolicy` requires explicitly declared per-side slippage, round-trip commission and daily financing rates; `None` is unknown and blocks the net label. The evaluator reports gross **executable pre-fee** return separately from net return, slippage, commission, prorated financing, entry spread and R/MFE/MAE. Spread is intrinsically reflected by ask/bid entry/exit. An exact separate round-trip midpoint spread decomposition is available only for TIME/SESSION close where both exit close quotes are known; stop/target OHLC does not reveal the opposite quote at the first hit, so that component remains `null` rather than fabricated. Market-specific authoritative CFD commission/financing schedules, broker minimum size, margin, leverage and stop rule verification are **not yet connected**. Therefore this is a research-evaluation primitive, not a broker-qualified profitability claim.

## 8. Multi-timeframe architecture

`M1_M5_M15_EXECUTABLE_POINT_IN_TIME_V1_RESEARCH` forms a versioned/hased snapshot from contiguous completed M1/M5/M15 windows. Each bar's completion time must be <= decision UTC. M1 must be a single IG Lightstreamer source and supplies spread, short return and volatility; M5/M15 supply local/broader return and volatility. Source transitions, incomplete bars, trailing gaps, invalid close or invalid spread yield an unverifiable snapshot. Editing a candle that completes after the decision leaves the hash/features unchanged in tests. The new snapshots are not yet used in a frozen cohort or model tournament.

## 9. Data-quality results by market

The read-only `scripts/report_broker_m1_quality.py` gives permanently separated RAW_IG, HYBRID_RESEARCH and CURRENT_IG_EXECUTION M1 views; it does not persist or repair data. It reports latest 2,000 selected M1 rows per view, expected-session gaps, source duplicates, bid/ask availability, invalid/crossed OHLC, nonpositive spread, >10× median spread diagnostic and in-session staleness. The table is the **current IG execution** view at the run around 06:50 UTC. Percentages for separate M5 views are in the comprehensive audit; this increment does not silently merge them into an M1 score. All nine M1 execution windows remain BLOCKED by gaps; extreme spread is a diagnostic threshold, not a trade veto by itself.

| Market | Selected IG M1 | Session M1 gaps | Missing bid/ask | Crossed | Extreme spread >10× median | M1 execution status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| AUD/JPY | 2,000 | 6 | 0 | 0 | 0 | BLOCKED |
| EUR/JPY | 2,000 | 18 | 0 | 0 | 47 | BLOCKED |
| EUR/USD | 2,000 | 17 | 0 | 0 | 52 | BLOCKED |
| GBP/JPY | 2,000 | 11 | 0 | 0 | 53 | BLOCKED |
| GBP/USD | 2,000 | 25 | 0 | 0 | 49 | BLOCKED |
| Germany 40 | 2,000 | 483 | 0 | 0 | 0 | BLOCKED |
| USD/JPY | 2,000 | 19 | 0 | 0 | 46 | BLOCKED |
| USD/ZAR | 2,000 | 13 | 0 | 0 | 0 | BLOCKED |
| Gold | 2,000 | 64 | 0 | 0 | 0 | BLOCKED |

The quality report is provisional and source-aware; it does not assert that all gaps are broker faults. Germany 40's session calendar and market status need separate reconciliation before treating 483 missing expected intervals as a root cause. This report has no per-prediction complete M1 inventory for all nine markets yet.

**Root-cause evidence for flagged diagnostics:** GBP/USD's earliest completed PASS IG Lightstreamer M1 in current SQL is 7 September 18:11 UTC, which explains the frozen 7 September 03:45 missing entry. On 8 September there were only 394 PASS IG M1 rows between 00:00 and 19:45 UTC; several frozen missing-entry decisions occurred inside this date and cannot be explained by the earliest-row cutoff. The 10 missing entries and two later path gaps reflect a sparse broker M1 history, but the original capture failure/worker outage cause is **not yet established**. USD/JPY's 471 hybrid duplicate *source* rows are an overlap across stores: 471 timestamps in `app.market_candles_m5` Dukascopy recovery join corresponding `app.candles` M5 timestamps since 1 September. `app.candles` had 809 `DERIVED_M1` M5 rows and the recovery store 570 `DUKASCOPY_M1_DERIVED`; the hybrid view combines them before canonical precedence. These are overlapping lineage rows, not proof of 471 duplicate canonical candle keys. Whether each overlap is economically identical and why it was written to both stores remain to investigate; no row was rewritten.

## 10. IG size-increment findings

An authorized read-only IG Demo session/market-detail query retrieved the field names for **all nine** currently enabled epics. Every `dealingRules` object had `minDealSize` and `minStepDistance`, but no `dealSizeIncrement`, `sizeStep` or other size-increment field. `minStepDistance` had unit `POINTS` with values 1–400 and represents a price/dealing level step, not deal size. Instrument objects had `lotSize` and `contractSize`, not a dealing-size step. `app/ig_demo.py:480-540` therefore derives a conservative minimum-size fallback and keeps `size_increment_authoritative=false`; `broker_rules.py` persists source/authority/raw payload hash; `demo_execution.py:92` and `experimental_demo.py:729-730` reject non-authority before submission. The new test prevents a tempting but invalid `minStepDistance` reinterpretation. **B01 remains open**: no authoritative increment was observed in these market-detail responses, and an independently governed pre-submission validation/contract source must be designed before execution. No fallback was marked authoritative and no IG order was submitted.

## 11. New research cohort

**None created.** Current frozen GBP/USD diagnostic remains 13 predictions with only 1 broker-evaluable path and is expressly non-promotable. Cohort persistence, policy preregistration, broker-native path eligibility, costs and immutable manifests are next. A missing path must remain UNVERIFIABLE rather than become a losing trade.

## 12. Tournament results

**None run in this increment.** Logistic Regression, Random Forest and HGB remain code-available challengers, but the old HGB registry was not retrained. Running a tournament before the new outcome/feature cohort is frozen would produce another directional-proxy result, not the desired scientific experiment.

## 13. Market-by-market economics

No new executable economic-label cohort, same-cohort tournament, positive PF, net expectancy or untouched holdout exists yet. The old rejected HGB rows in the comprehensive audit are historical comparison only. No market is claimed profitable. **NO PROFITABLE MODEL IDENTIFIED.**

| Market | IG M1 Path Ready | Economic Labels | Best Model | AUC | PF | Net Expectancy | Max DD | Holdout | Shadow Eligible | Remaining blocker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AUD/JPY | NO | Engine only; no cohort | None | — | — | — | — | None | NO | Data/rules/no model |
| EUR/JPY | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Data/rules/old loss |
| EUR/USD | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Data/rules/expired programme |
| GBP/JPY | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Data/rules/old loss |
| GBP/USD | NO; frozen 1/13 | Engine only; no cohort | None governed | — | — | — | — | None | NO | IG prediction paths |
| Germany 40 | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Session path/rules |
| USD/JPY | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Data/lineage/rules |
| USD/ZAR | NO | Engine only; no cohort | None | — | — | — | — | None | NO | Data/rules/no model |
| Gold | NO | Engine only; no cohort | None governed | — | — | — | — | None | NO | Data/rules/old loss |

## 14. Shadow readiness

The evaluator can provide a future Shadow trade's decision/policy/hash and prospective executable path outcome, but it is not wired to `shadow_candidates`, `shadow_trades` or a daily zero-trade ledger. SQL still shows 0 candidates and 0 trades. Backtest evidence must never be inserted as forward evidence. No market is Shadow-eligible from this increment.

## 15. Remaining blockers

B03 is **partially implemented** as a research-only executable label and feature primitive; integration with immutable cohorts and governed net-target training remains. B04 has a three-view M1 quality report and partial flagged-root-cause evidence; calendar-aware M5/M15 integration, all-market prediction path inventory and actual feed-gap causes remain. B01 is **evidence-confirmed unresolved** because nine IG market responses lack a size increment; fallback remains blocked. B02 (scientifically governed frozen tournament), B05 (prospective Shadow), B07 (loaded deployment fingerprint) and B06 (stale expired-programme display) remain. No P0 unsafe active trade path was observed. The P1 gates stay in force.

## 16. Regression findings

No existing trading or model source was modified. Existing suites passed and the before/after trading authority remained unchanged. The new M1 quality diagnostic reports additional detail rather than a newly created data regression. No historical rejected models, frozen outcomes or prior audit artifacts were deleted. Loaded production service versions were not attested; source passing tests do not establish deployment parity.

## 17. Recommended next action

**Next implementation increment:** connect `feature_snapshot` and `evaluate_trade` to a read-only per-prediction IG M1 coverage inventory for all nine markets; specify bounded pre-registered ATR/risk execution and market-specific cost families; then design append-only frozen outcome/cohort persistence without using the untouched holdout to choose policy. In parallel, investigate IG dealing-size authority via another authoritative contract or a fail-closed validation design, and attest running service versions. Do not run a model tournament until enough complete broker-native paths exist on one immutable cohort. After that, run the three-family chronological/purged development and untouched-holdout evaluation, then prepare prospective Shadow. The implementation plan tracks every remaining workstream; the next increment should update this report rather than call an available primitive a validated profitable model.

### Continuation on 16 September 2026

The all-M15 development universe and its independent verifier are now complete. The frozen artifact contains 4,340 opportunities and 471 rows where both the point-in-time feature snapshot and full 120-minute IG M1 path are complete: AUDJPY 6, EURJPY 5, EURUSD 66, GBPJPY 84, GBPUSD 59, Germany40 2, USDJPY 46, USDZAR 103 and XAUUSD 100. These counts are data readiness only.

`AUREX_CFD_COST_EVIDENCE_GAPS_V1` records the current evidence boundary: observed bid/ask spreads are present in the frozen paths and slippage is a preregistered sensitivity, while instrument/account commission and financing terms remain unverified for all nine markets. `AUREX_FROZEN_RESEARCH_COHORT_ELIGIBILITY_2026-09-16.json` therefore reports zero net-label-eligible opportunities. Its verifier reproduces the source-universe hash, cost-evidence hash and every gate result. No unknown fee was treated as zero, no economic outcome was calculated, no validation or holdout partition was accessed and no model was trained.

**Next implementation increment:** obtain and freeze authoritative IG account/instrument commission and rollover evidence, or a governed conservative upper bound that the protocol explicitly permits. Then regenerate a new versioned eligibility register and freeze LONG/SHORT outcomes for the three preregistered execution families on development data only. Germany40, AUDJPY and EURJPY also remain below the 30-path cohort minimum and cannot enter a governed market tournament even after cost authority is resolved.

### Cost authority and development outcomes — 16 September 2026

Official IG South Africa terms support zero separate commission for the platform's non-share FX, cash-index and spot-metal CFDs because their direct execution charge is the executable spread already present in bid/ask paths. They also establish a 22:00 UK-time overnight funding boundary, while the applicable funding amount varies. Aurex therefore does not assign a made-up funding rate: `IG_ZA_SPREAD_ONLY_NO_ROLLOVER_COHORT_V1` excludes any opportunity whose full 120-minute horizon crosses 22:00 Europe/London, including daylight-saving changes.

The original protocol did not define the ATR formula behind its three ATR-multiple families. Before calculating outcomes, `AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1_ATR14_SMA_AMENDMENT` fixed ATR as the simple mean of 14 M15 true ranges from 15 contiguous, completed, point-in-time-available candles with one source. This stricter gate exposed extensive M15 source transitions.

`AUREX_FROZEN_EXECUTABLE_DEVELOPMENT_OUTCOMES_2026-09-16.json` contains 792 evaluated outcomes for 66 distinct development opportunities. The counts surviving both ATR and no-rollover gates are EURUSD 8, GBPJPY 10, USDJPY 11, USDZAR 11 and XAUUSD 26; all other markets have zero. Each opportunity has three execution families, LONG and SHORT counterfactuals, and normal/stressed preregistered slippage sensitivity. No market reaches the required 30 observations. No tournament, validation evaluation, holdout access, model training, promotion or broker submission occurred.

**Next implementation increment:** repair prospective M15 source continuity and availability at ingestion rather than rewriting frozen history, then accumulate a new protocol-versioned development window until at least one market has 30 complete ATR/path/no-rollover opportunities. Only then run the development tournament. The untouched validation and holdout partitions remain closed.

### Prospective M15 continuity activation — 16 September 2026

The source-transition defect was a live writer race. A completed M5 event could create an M15 row as `IG_LIGHTSTREAMER` without `ingested_at_utc`, while completed M1 events independently tried to create the same row as `DERIVED_M1`. Unique-key first-writer behavior produced alternating M15 lineage. The direct M5-to-M15 writer has been removed. New live M15 rows now require exactly fifteen completed PASS broker-native M1 rows and use the sole versioned source `IG_LIGHTSTREAMER_M1_AGG_M15_V1`, with close time and ingestion time persisted at creation.

`AUREX_PROSPECTIVE_M15_CONTINUITY_PROTOCOL_V1` governs the new accumulation window. It counts ATR-warmed opportunities within separate contiguous regular-session segments, requires later complete 120-minute IG M1 paths, retains the no-rollover rule and targets at least 30 opportunities per market. Historical source rows are not renamed or rewritten. The immutable activation snapshot contains zero new-authority rows because it was captured before the tested worker version was activated. The Aurex market-stream service was then restarted and returned to RUNNING. Read-only control verification remained SHADOW with new orders disabled.

**Next implementation increment:** allow the prospective source to accumulate naturally, capture subsequent immutable snapshots, and join each warmed M15 opportunity to its later 120-minute IG path and rollover gate. Do not train until one market reaches 30 joined opportunities. Validation and holdout remain closed.

### Prospective opportunity joining — 16 September 2026

`PROSPECTIVE_EXECUTABLE_OPPORTUNITY_JOIN_V1` now joins four independent gates for every new-authority M15 candle: ATR(14) evidence, point-in-time M1/M5/M15 feature evidence, the no-rollover rule and the later complete 120-minute IG M1 path. Each row retains the three evidence hashes and a stable opportunity identity. Gate ordering prevents an incomplete warm-up from being reported as a path loss or economic result.

The first immutable joined snapshot contains three `IG_LIGHTSTREAMER_M1_AGG_M15_V1` candles for each of the nine markets. All 27 are `ACCUMULATING` with `ATR:INSUFFICIENT_COMPLETED_BARS`, so joined counts and target counts remain zero. No historical data was rewritten, and no validation, holdout, economic-label, training, promotion or broker action occurred. Subsequent snapshots accept a new explicit filename under `docs/audits` and refuse overwrite.

**Next implementation increment:** after at least fifteen continuous regular-session M15 candles exist, capture the next immutable join snapshot and inspect feature and later-path gates. Continue accumulating until one market reaches 30 `JOINED` opportunities; only then may the development tournament start.

### Second prospective join snapshot and M5 lineage — 16 September 2026

The verified snapshot at 13:34 SAST contains 17 authoritative M15 candles per market. Each market has fourteen ATR warm-up rows and three post-warm-up candidates. EURUSD, GBPJPY and USDJPY have three paths whose 120-minute horizon was not yet complete. The remaining markets also exposed M5 feature source transitions. Joined counts remain zero.

The M5 failures revealed a second first-writer race between direct `IG_LIGHTSTREAMER_M5` candles and `IG_LIGHTSTREAMER_M1_AGG_M5_V1`. Canonical live persistence now accepts only M1 directly; M5, M15, M30 and H1 are all constructed from complete PASS M1 buckets. This change is prospective and does not rename existing rows. Once four consecutive new-authority M5 bars replace the mixed trailing feature window and 120 minutes elapse, later snapshots can pass those gates.

The historical backfill job ledger currently reports 44 `COMPLETE`, 41 `FAILED` and 89 `SUPERSEDED` rows, which differs from the earlier page count of 34 completed. The queue has finished processing, but the 41 failed partitions remain non-eligible until separately validated or recovered.

### Durable prospective accumulation ledger — 16 September 2026

The append-only ledger is deployed through migration `059_prospective_opportunity_ledger.sql`. Every semantic gate transition has a stable idempotency key and retains its ATR, feature, path and complete evidence hashes. Database triggers reject UPDATE and DELETE operations. Milestone records link joined-count changes to no-overwrite JSON artifacts, and `app.vw_prospective_training_gate` opens only at 30 distinct `JOINED` opportunities for one market.

The first cycle inserted 153 events: 126 `ATR_PENDING`, 12 `FEATURE_PENDING` and 15 `PATH_PENDING`. It emitted `AUREX_PROSPECTIVE_ACCUMULATION_MILESTONE_20260916T114701Z_ecc5679cbd08.json`. Repeating the same cycle inserted zero events and emitted no duplicate milestone. The `AurexProspectiveAccumulation` Windows service is RUNNING and reevaluates pending opportunities every five minutes. A direct EURUSD tournament invocation was rejected with `PROSPECTIVE_TRAINING_GATE_BLOCKED:EURUSD:0/30`; no model code ran.

**Next implementation increment:** allow the ledger to accumulate and verify real transitions from pending states into `JOINED`. When the first joined count changes, verify the automatically emitted milestone and investigate any `PATH_BLOCKED` rows without converting them to losses. At 30 joined rows for a market, freeze its preregistered executable outcomes and run the development-only tournament; validation and holdout remain closed.

## Terminal summary

TRADING STATE: SHADOW; local Demo capability configured, order authority blocked
ORDERS ENABLED: false
EXPERIMENTAL DEMO: not armed here; only stored programme expired/REJECTED
DEMO AUTO: disabled by SHADOW engine and unmet gates
LIVE: false
AUTHORITATIVE IG RULES: 0/9 size increments
ECONOMIC LABEL VERSION: EXECUTABLE_TRADE_OUTCOME_M1_V1_RESEARCH (research primitive only)
BEST POSITIVE MODEL: NO PROFITABLE MODEL IDENTIFIED
MARKETS WITH POSITIVE HOLDOUT ECONOMICS: 0 established
SHADOW-ELIGIBLE MARKETS: 0
REMAINING P0/P1 BLOCKERS: B01, B02, B03 integration, B04, B05, B06, B07, B08
REPORT PATH: `docs/audits/AUREX_ECONOMIC_MODEL_REMEDIATION_2026-09-15.md`
