# Aurex data, research and model audit — 2026-09-12

## Executive conclusion

The dominant GBP/USD problem is **label/strategy mismatch, with cost and execution conversion unproven**, not proof that the classifier is useless. The recorded recent-window AUC (~0.573) and net profit factor (0.642) are compatible with modest directional ranking but losing trading economics. They do **not** establish that conversion alone destroys a real edge: the AUC can be noisy, the model's selected trades may differ from the population used for AUC, and the simulated return is not the replayed CFD outcome. No model should be promoted from this audit. Status: `VERIFIED_CURRENT` for code and live SQL inventory; `STALE` for the 11 September performance figures until rerun; `NOT_VERIFIABLE` for current IG dealing-rule authority and external service health.

## Current data state

Read-only SQL connection succeeded on 12 September. All nine configured markets are enabled for training. Completed, quality-passed M5 rows in the last 90 days: AUDJPY 2,283; EURJPY 2,281; EURUSD 21,058; GBPJPY 2,284; GBPUSD 4,458; GERMANY40 3,581; USDJPY 4,451; USDZAR 2,285; XAUUSD 2,162. Corresponding M15 rows: 756, 753, 7,008, 757, 1,478, 1,187, 1,475, 757, 714. These are **row counts, not decision-window quality percentages**; duplicates, session gaps, source mix and feature completeness still need the canonical quality query. Latest completed M5 timestamps were 11 September 20:55 UTC for all nine; weekend closure must not be reported as a stream outage.

## Hybrid data status

`model_pipeline._market_frame` selects one completed PASS regular-session M15 bar per timestamp, preferring IG Lightstreamer, then IG Demo historical, then Dukascopy. `add_features` breaks sequences at provider transitions. Thus repaired Dukascopy rows may enter research, but do not become IG execution authority. The three quality views (raw IG, repaired research, current IG execution) must be reported separately. The live inventory above cannot establish that the selected recent feature window is canonical; status `PARTIAL`.

## Data loss through pipeline

M5 is not directly the training input. The model reads M15; `add_features` discards warm-up rows (13 per continuous segment), the four unobservable end labels, and rows around missing intervals/provider transitions. A 2,000-M5 target must not be conflated with 2,000 feature-complete M15 rows. GBP/USD has 1,478 PASS M15 rows in the 90-day SQL inventory, while the earlier training audit reported 1,250 effective evaluation rows; exact cohort matching and per-loss attribution must be rerun before calling the difference data corruption. Germany 40's 1,187 recent M15 rows make a recent experiment plausible but do not prove adequate chronological train/validation/holdout coverage.

## Feature audit

Current features are ret1, ret4, EMA gap, RSI, ATR percent, range percent and tick-volume z-score. They are backward-looking in `_add_features_segment`; no direct future feature was found. This is a code-level finding, not an end-to-end leakage proof. Provider switches and discontinuities segment feature construction. The published GBP/USD AUC suggests possible ranking signal; feature importance and ablation are still needed before declaring any feature useful.

## Label audit

`FUTURE_CLOSE_DIRECTION_4_M15_V2` labels 1 when `close[t+4] > close[t]`, otherwise 0. It ignores bid/ask, spread, slippage, funding, stop distance, target and intrabar path. A tiny up move is a positive label even if a long loses after costs. This label answers “higher close one hour later?”, **not** “would the CFD trade earn positive risk-adjusted net P&L?”. `research_labels.economic_path_labels` exists as experimental work, but uses future extrema and does not settle event order when both barriers are touched in one candle; it is not production-authoritative. The label is therefore `NO` for exact alignment with the traded decision.

## Training pipeline

`chronological_evaluate` uses expanding chronological windows and purges four rows before validation. It predicts probabilities, applies fixed 0.70/0.30 cutoffs, and scores the close-to-close four-bar return after an effective cost equal to max(observed M15 spread bps, configured round-trip bps). The cost is a floor, not a full broker-aware fill model. The normal training path still defaults to full history; recent/rolling selection is opt-in. A trained final artifact is the final window's model, while summary metrics aggregate multiple validation windows. Evaluation data selection and final model fit lineage should be explicit in every manifest.

## Model tournament

Tournament code tests model families and selective threshold grids on development data and excludes reserved holdout. Ranking a threshold after viewing development results is exploratory; it is not independent validation. Previously reported GBP/USD CatBoost selective PF 2.152 on only 57 trades, AUC 0.516 and 2/3 positive windows did not satisfy stability/sample gates. Do not promote that result or tune more thresholds against the same holdout.

## GBPUSD analysis

Previous 11 September recent-window result: AUC about 0.573, PF 0.642, negative expectancy, rejected. This is a **diagnostic clue**, not a verified current edge. Compare the same frozen out-of-sample prediction rows under (a) direction-label AUC, (b) gross signed four-bar return, (c) net four-bar return, and (d) executable replay P&L with bid/ask and stop/target. Break each down by long/short, session, spread bucket and confidence, with trade counts and uncertainty. Only then can “conversion destroys edge” be answered YES rather than UNCERTAIN. The code currently does not provide that matched-prediction-to-execution bridge.

## USDJPY analysis

Previous recent-window PF 0.424 and AUC about 0.538; both need current rerun. The same label/conversion mismatch applies. Its 4,451 recent PASS M5 and 1,475 M15 rows show that an experimental recent study is possible, not that a profitable model exists.

## EURUSD analysis

Previous AUC about 0.512 and PF 0.307. Its much larger M15 inventory (7,008 recent PASS rows) rules out a simple absolute-row shortage, but not source/segment/cohort defects. Prioritize the GBP/USD matched-outcome experiment before changing EUR/USD architecture.

## Cost and spread analysis

Research `trading_metrics` subtracts per-row bps from signed close return. Replay instead uses bid/ask entry/exit where available, slippage, funding and broker-size rules. These are different economic estimands. Report gross PF, net PF, average cost drag and spread stress on identical trade IDs; do not compare aggregate AUC to a replay PF from another cohort.

## Stop/target analysis

Training assumes a four-M15-bar close exit. Replay configuration shows risk per trade 0.25%, reward:risk 1.5 and maximum holding 32 candles, with actual stop/target handling. Those horizons and payoff distributions differ substantially. Predeclare one baseline replay policy and one alternative; if both stop and target are crossed in one candle, use the conservative outcome or mark ambiguous rather than infer favourable sequence.

## MFE/MAE analysis

Research replay already calculates MFE/MAE and holding metrics. They must be joined to the **same** out-of-sample prediction/trade cohort for label-versus-exit inference. No current matched-cohort MFE/MAE result was verified here.

## Research process

Freeze dataset hash, provider proportions, feature/label/cost versions, train/validation boundaries, candidate thresholds and replay policy before the next run. Keep the reserved holdout untouched. Compare confidence intervals and per-window trade floors; avoid making a profit claim from 57 selected trades.

## Experimental eligibility

Live SQL model inventory: GBPUSD 15 REJECTED and one REGISTERED; USDJPY 14 REJECTED and one REGISTERED; EURUSD 16 REJECTED and one REGISTERED; EURJPY has one CANDIDATE and eight REJECTED; no `VALIDATED` row appeared in the grouped inventory. `CANDIDATE` is not evidence of enabled Shadow. Research experimentation and shadow eligibility must remain distinct from Demo Auto/Live validation.

## Shadow readiness

Shadow worker and candidate-recording code exist. No eligible, active shadow model was established by this audit. Read live shadow state and verify model-status joins before claiming Shadow active. A rejected model's stale shadow reference is a governance defect, not forward evidence.

## Broker readiness

Replay loads latest IG Demo broker rule, but a row's presence is not proof of current authoritative size increment, minimum stop, margin or permitted dealing state. The 11 September audit flagged `size_increment_authoritative=false`. Refresh and attest rules **only for the selected canary market** before any Demo order. Broker rules do not block research-only training.

## Risk readiness

Risk and ledger modules exist and replay uses 0.25% per-trade risk. This is not proof that a 0.25% maximum loss is guaranteed: stop fills can slip and adverse gaps can exceed the planned loss. Verify current risk decision, exposure, margin, daily loss and reconciliation at proposal and again immediately before submission.

## Human-approved Demo backend readiness

Not ready on this evidence. Proposal approval, single-use authentication, atomic submission, final IG/risk checks, monitoring and reconciliation require separate end-to-end verification. No trading flags or orders were changed by this audit. Live remains disabled by policy; current runtime flag was not queried.

## False blockers

Old 2024 Germany 40 history does not have to block GBP/USD research. A 2,000-M15 production floor is not the original 2,000-M5 evidence target. Lack of authoritative broker size increment does not block offline model research or non-executing diagnostics. A losing experimental trade is not automatically a system failure. A rejected model is a legitimate research outcome, not an infrastructure outage.

## Real blockers

No demonstrated positive, stable cost-aware experimental candidate; no matched label-to-realized-trade diagnostic; no active governed Shadow evidence; current broker-rule authority unresolved for a Demo canary; and end-to-end approval/submission/reconciliation safety unverified.

## Blocker matrix

| ID | Severity | Layer | Root cause | True blocker? | Fix | Shadow | Demo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B1 | P1 | LABEL/STRATEGY | Four-bar direction target differs from stop/target CFD P&L | Yes for promotion | Matched prediction/trade diagnostic and predeclared cost-aware target trial | Yes | Yes |
| B2 | P1 | MODEL | No stable positive net candidate verified | Yes | One bounded GBP/USD experiment, independent validation | Yes | Yes |
| B3 | P1 | SHADOW | No eligible active frozen candidate/evidence | Yes | Status-integrity check, then forward observation | Yes | Yes |
| B4 | P1 | BROKER | Selected-market size increment/dealing-rule authority unverified | No for research | Fresh IG rule attestation | No | Yes |
| B5 | P1 | EXECUTION | Approval-to-reconciliation path not end-to-end verified | No for research | Safe recovery tests; owner canary only afterwards | No | Yes |
| B6 | P2 | DATA | Recent M15 cohorts fragmented by gaps/provider switches | Conditional | Canonical three-view quality report and per-segment row-loss ledger | Conditional | Conditional |
| B7 | P2 | COST | Research cost floor differs from executable fill cost | Yes for economic claim | Same-cohort bid/ask replay and stress | Yes | Yes |

## Next two experiments

1. **GBP/USD, predeclared conversion test.** Freeze existing out-of-sample probabilities and dataset. Compare fixed 0.70/0.30 baseline with a *single* long-only London/NY, 0.65 threshold, current-spread-at-entry filter and unchanged baseline stop/target replay. Report gross/net PF, expectancy, trade count and each walk-forward segment under normal and stressed costs. Pass only with positive stressed net expectancy, PF ≥1.10, adequate per-window trades and no holdout use. Failure means threshold/session filtering alone is insufficient; test cost-aware labels next. This is a hypothesis, not a recommendation to trade.
2. **USD/JPY, label alignment test.** On frozen development folds, compare current four-bar direction label against an explicitly versioned cost-aware net four-bar opportunity label, using identical features, splits and HGB family. Keep an abstain zone for outcomes smaller than observed-plus-stressed costs. Score out-of-fold executable replay on one frozen policy, not only AUC. Pass only on stable net replay expectancy/PF and independent holdout later. Failure points to features or exit policy rather than automatically demanding more M5 history.

## Implementation priority

1. Build a read-only, same-cohort out-of-fold prediction-to-trade diagnostic with dataset/label/cost hashes and bid/ask availability.
2. Produce canonical raw-IG, repaired-research and IG-execution quality reports, plus M15 row-loss ledger.
3. Run the predeclared GBP/USD conversion experiment; inspect long/short, session, spread, calibration and MFE/MAE.
4. If conversion fails, test the cost-aware label on the same frozen folds; use unambiguous stop/target ordering.
5. Verify shadow model-status integrity, freeze a qualified experimental artifact and collect forward evidence.
6. Attest selected-market IG dealing rules and exercise approval/rejection, atomic submission, unknown-state recovery and reconciliation without sending an order.
7. Only after evidence and owner approval, consider one minimum-size Demo canary; never infer Live readiness.

## Final readiness

`ENOUGH_DATA_FOR_PRIORITY_RESEARCH=YES` (raw counts, conditional on cohort quality); `HYBRID_RESEARCH_DATA_CANONICAL=NOT_VERIFIED`; `DATA_PIPELINE_HEALTH=PARTIAL`; `FEATURE_PIPELINE_HEALTH=PARTIAL`; `FEATURE_LEAKAGE=NOT_DEMONSTRATED`; `LABEL_ALIGNED_TO_TRADING=NO`; `CURRENT_MODEL_FAMILY_ADEQUATE=UNCERTAIN`; `MODEL_SIGNAL_PRESENT=UNCERTAIN`; `TRADING_CONVERSION_DESTROYS_EDGE=UNCERTAIN`; `CURRENT_STRONGEST_MARKET=GBPUSD` (provisional); `DEMO_EXPERIMENT_MODEL_AVAILABLE=NO`; `SHADOW_INFRASTRUCTURE_READY=PARTIAL`; `SHADOW_MODEL_READY=NO`; `SHADOW_ACTIVE=NOT_VERIFIED`; `BROKER_RULES_READY_FOR_SELECTED_MARKET=NO`; `RISK_ENGINE_READY=NOT_VERIFIED_END_TO_END`; `HUMAN_APPROVED_DEMO_BACKEND_READY=NO`; `LIVE_ENABLED=NOT_VERIFIED_RUNTIME` (must remain NO).

Dominant path: **GBP/USD C/E (label and strategy conversion)**; **USD/JPY C/E uncertain**; **EUR/USD B/C/E uncertain**. Do not select model-family replacement (D) until identical-cohort diagnostics disprove a simpler explanation.
