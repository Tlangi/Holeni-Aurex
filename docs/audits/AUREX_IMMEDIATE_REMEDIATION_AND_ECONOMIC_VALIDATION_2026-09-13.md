# Aurex immediate remediation and economic validation — 2026-09-13

## Status

**Partial implementation, not a completed trading-readiness cycle.** No IG order was submitted, no programme was armed, and no Demo Auto/Live gate was changed. The meaningful progress is an explicit read-only three-view data diagnostic, exact GBP/USD cohort reconciliation at the available manifest level, effective expired-programme presentation, and a research-only executable M1 first-hit primitive. It is **not** a measured GBP/USD prediction-to-R result or a validated profitable model.

## Implementation completed

1. Added `economic_outcomes.py`: versioned research-only labels/outputs for net executable return, M1 first-hit barrier status and realised R. It uses ask entry/bid exit for longs, bid entry/ask exit for shorts; requires UTC indexed M1 bid/ask OHLC; rejects missing, gapped or invalid paths; marks both barriers in the same minute `AMBIGUOUS`; applies per-side slippage/funding deductions; treats adverse stop gaps conservatively. Its deterministic prediction identity is a hash of market, dataset hash, decision time, signal resolution and direction. It is not wired to trading, model promotion or live inference.
2. Added `effective_programme_status` to preserve historical `ARMED` records while displaying expired active-like records as `EXPIRED`. New `ARM`/`RESUME` control requests reject expired records. The existing submission gate already requires `starts <= now < expires`; it remains unchanged. No historical programme row was deleted or rewritten.
3. Tightened `completed_context_join`: incomplete signal candles are rejected; incomplete higher-timeframe context bars are excluded before as-of joining. No incomplete M15 can become context for a completed M5 decision.
4. Added a read-only `report_three_view_quality.py` diagnostic. It selects separately RAW IG, HYBRID RESEARCH and IG Lightstreamer execution rows; IG wins same-time research-source ties; it applies configured calendar/holiday exclusions and reports gap intervals, source mix, bid/ask and M1-support counts. Germany 40 is bounded to 2026 to avoid hiding its recent deficit behind 2024 data. Its output declares `PROVISIONAL_CALENDAR_DIAGNOSTIC`, not production execution authority.
5. Added targeted tests for direction-specific fills, slippage, ambiguity, missing/gapped M1, deterministic identity, expiry projection, temporal joins and source separation.

## Database changes and migrations

**None applied by this cycle.** The quality diagnostic is stdout-only and was not persisted in SQL. Dataset manifests and training artefacts were not modified. Read-only `OBJECT_ID` checks found `app.model_dataset_manifests` (migration 054), but **did not find `app.research_prediction_trade_results`** (migration 055). Thus the intended immutable same-prediction/trade evidence table is not yet available in this database; migration 055 must be validated and applied through a separate governed database change before persisting the bridge. This is an explicit outstanding deliverable.

## Runtime/release attestation

**Not implemented.** The source checkout is dirty, and no signed/versioned runtime manifest or deployed backend/worker/frontend hash was produced. The running binary may differ from this checkout. No services were restarted. The effective expiry display will only take effect when the relevant API is safely deployed; the database still retains its historical `ARMED` value.

## Broker authority — all enabled markets

Read-only SQL showed rows refreshed around 13 Sep 12:50 UTC, but `size_increment_authoritative=false` for **all nine**: AUD/JPY, EUR/JPY, EUR/USD, GBP/JPY, GBP/USD, Germany 40, USD/JPY, USD/ZAR and Gold. The current `ig_demo.parse_broker_market_rule` explicitly sets size increment to a conservative minimum-size fallback and `size_increment_authoritative=False`. **No market is cleared for execution on this basis.** An authoritative IG increment field was not found or established during this cycle. `BROKER_SIZE_INCREMENT_NOT_AUTHORITATIVE` remains a P0 blocker. A refreshed fallback is not an authoritative rule.

Follow-up live **read-only IG Demo GBP/USD market-details** inspection on 13 Sep listed `minDealSize` (value 0.04) but no separately identified dealing-size increment field in the returned `dealingRules`. Instrument fields included `contractSize`, `lotSize`, margin factors and pip values, none of which by itself establishes an increment. This reinforces fail-closed status; no fallback was promoted to authoritative. Other eight live payloads were not individually inspected in that call.

## Operational alert follow-up — 13 September

The owner reported emails saying `CRITICAL · SYSTEM HEALTH` for `ig_demo` and `market_feed` even though both rows said `CURRENT`. SQL showed their `checked_at_utc` timestamps frozen around 12:57 UTC during Sunday's market closure, while the monitor's 20-minute generic heartbeat rule continued treating them as incidents. The stream's own `stalled()` logic correctly exempts closed sessions; the alert monitor did not. `health_monitor.py` now uses the configured market-session assessment before interpreting a stale `CURRENT` feed/IG row. Explicit `DEGRADED`/offline states, unknown calendars, open-session feed staleness, and other components' stale heartbeats still alert. The health monitor alone was restarted after tests; the two persisted alerts became `RESOLVED` at 14:26:54 UTC. API, market stream and trading worker were not restarted. This is an operational alert fix, **not** evidence that current broker rules or execution data are trade-ready.

## Data quality — three views, all markets

Read-only 13 Sep diagnostic on the latest *up to* 2,000 completed PASS, regular-session M5 rows per view. Figures are **provisional calendar-diagnostic percentages**, `observed/(observed + counted in-session missing)` for each independently selected view window, rounded to two decimals. They are **not interchangeable**: IG-only windows may span a longer interval than hybrid windows; no historical research row is promoted to current IG authority. All views were `BLOCKED` by the existing recent-window no-gap/2,000-row criteria. These figures should not be used to arm trading. Non-PASS/incomplete row totals and quantitative spread distributions were not yet added; exact ongoing IG market-session outages require calendar/market-rule confirmation.

| Market | Raw IG % | Hybrid research % | IG execution % | Hybrid observed/required | Hybrid missing | Broker increment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| AUD/JPY | 72.91 | 90.95 | 62.56 | 2,000/2,000 | 199 | Non-authoritative |
| EUR/JPY | 72.29 | 90.91 | 61.86 | 2,000/2,000 | 200 | Non-authoritative |
| EUR/USD | 70.17 | 90.99 | 64.45 | 2,000/2,000 | 198 | Non-authoritative |
| GBP/JPY | 63.92 | 90.95 | 53.49 | 2,000/2,000 | 199 | Non-authoritative |
| GBP/USD | 69.93 | 90.99 | 64.23 | 2,000/2,000 | 198 | Non-authoritative |
| Germany 40 | 92.50 | 97.25 | 81.96 | 1,309/2,000 | 37 | Non-authoritative |
| USD/JPY | 71.33 | 90.99 | 65.40 | 2,000/2,000 | 198 | Non-authoritative |
| USD/ZAR | 63.01 | 90.95 | 52.59 | 2,000/2,000 | 199 | Non-authoritative |
| Gold | 61.09 | 86.92 | 50.56 | 2,000/2,000 | 301 | Non-authoritative |

GBP/USD's hybrid gap boundaries are 7 Sep **05:20–07:30 UTC** (25 missing M5 timestamps), 8 Sep **13:50–15:55** (24), 8–9 Sep **19:40–07:30** (141), 9 Sep **07:30–08:10** (7), and 11 Sep **03:30–03:40** (1). The existing output deliberately includes exact boundaries and counts for every market, but no immutable snapshot was persisted. M1 support rows exist over the diagnostic intervals; their counts do not prove every missing M5 interval has complete M1 support or broker-executable bid/ask. Germany 40's 2026-only hybrid window has only 1,309 regular-session rows; 2024 is not used to fake its recent readiness.

## GBP/USD cohort reconciliation

The two 11 September SQL records are **different training datasets**, not repeated scores for the same immutable cohort:

| Item | Earlier recent-window run (19:14 UTC) | Later full-history run (20:24 UTC) |
| --- | --- | --- |
| Model version | `trained-20260911191444-7f0828` | `trained-20260911202401-b33683` |
| Dataset hash | `508158b7e03e4082a29af7c67426721f3e838082e85c6e3a103fdf81cd6911aa` | `5d91e4b899d38c63605e195658e33f0967374f16849a61d4ab5bd0b10bf88b5a` |
| Canonical dataset rows | 1,441 | 54,271 |
| Training rows / validation rows | 854 / 396 | 44,777 / 20,669 |
| Training start | 20 Aug 2026 22:45 UTC | 1 Jan 2024 03:30 UTC |
| Latest dataset bar | 11 Sep 2026 18:45 UTC | 11 Sep 2026 20:00 UTC |
| Feature / label / validation policy | `FEATURES_V1` / `FUTURE_CLOSE_DIRECTION_4_M15_V2` / `MODEL_VALIDATION_POLICY_V2` | Same |
| Configured cost | 1.0 bps | 1.0 bps |
| AUC / PF / trades | .573 / .642 / 156 | .516 / .164 / 139 |

The dataset/window change is proven by hash, row count and dates. It is **not** proven which individual prediction IDs, provider transitions, selected thresholds or exact fills account for each metric difference: those rows were not persisted in an identical comparison table. The earlier record has a `RESEARCH_RETRAIN` experiment note about a recent-window research floor; the later version had no matching `research_experiments` record in the bounded query. Both evaluations lost money under their own recorded cost assumptions. Do not call the earlier AUC evidence of a profitable edge.

## Economic bridge and label comparison

| Stage | Current implementation/evidence |
| --- | --- |
| Prediction ID → directional outcome | Deterministic ID primitive implemented; no historical out-of-fold prediction ledger was materialised this cycle. |
| Gross → spread-adjusted → net return | Research-only M1 outcome primitive computes these for supplied immutable decisions and quotes; unit-tested. |
| First-hit target/stop/time/ambiguous → net R | Research-only primitive implemented and unit-tested; real GBP/USD cohort **not run**. |
| Full same-ID GBP/USD `Prediction → Net Return → First-Hit Outcome → R` | **NOT YET MEASURED.** This is the next decisive output, not AUC. |

The existing directional production label remains `future M15 close > current close after four bars`. The new experimental outputs instead distinguish positive *executable* M1 net return, barrier-first result and realised net R. They are **not** production labels, have not trained a new model, and do not justify promotion. In one M1 candle that touches both barriers, the outcome is `AMBIGUOUS`, never a favourable first-hit guess. CFD financing and market-specific broker-size/margin rejection are not yet integrated into the full historical cohort pipeline; the primitive accepts a declared funding cost but does not infer one.

## Bounded model experiment, holdout, Shadow and Demo

No controlled GBP/USD retrain/tournament was run because the same-cohort prediction-to-M1 evidence does not yet exist and recent quality remains blocked. There is no new AUC or profit factor. **Untouched holdout: NOT ACCESSED.** Shadow recommendation: **NO-GO for a newly promoted GBP/USD candidate**. The existing Shadow worker/settings were not changed; historical Shadow records must not be relabelled as forward evidence. Experimental Demo recommendation: **NO-GO** because broker rule authority, current IG execution quality and a valid in-window programme remain unresolved. Demo Auto and Live: **NO-GO**, gates unchanged.

## Remaining blockers

| Priority | Blocker |
| --- | --- |
| P0 | All enabled market size increments non-authoritative; no proposal-to-IG Human-Approved Demo submission architecture completed; no same-ID GBP/USD executable economic result or validated edge. |
| P1 | Three-view quality is diagnostic only, not persisted/canonical API; recent gaps and M1 support need interval-level resolution; deployed release/config not attested; expired `ARMED` row remains in SQL until governed lifecycle migration/deployment. |
| P1 | GBP/USD prediction IDs/trade outcomes from both cohorts not reconstructively compared; migration 055 prediction/outcome table absent; economic label not wired into bounded development research or protected holdout protocol. |
| P2 | Owner UI has not been updated with exact new blockers and release metadata; real mobile approval remains unverified with zero proposals. |
| P3 | Further UX terminology/technical-panel consolidation. |

## Tests and files changed

Targeted tests added: `test_economic_outcomes.py`, `test_three_view_quality.py`, `test_health_monitor_session_alerts.py`. Backend suite after the alert fix: **310 passed, 0 failed**, two existing joblib/NumPy deprecation warnings. Frontend suite: **37 passed, 0 failed**. Angular production build: **PASS** (frontend unchanged in the alert follow-up). Files changed by this cycle: `app/economic_outcomes.py` (new), `app/experimental_demo.py`, `app/multi_timeframe_research.py`, `app/health_monitor.py`, `scripts/report_three_view_quality.py` (new), the three new test files, and this report. No migration. Pre-existing dirty changes in other files were preserved.

## Owner action required

**No authorization to trade is requested now.** Do not arm another programme or interpret the old stored `ARMED` status as active. A later owner decision is required only after authoritative IG rules, the complete same-ID economic bridge, qualified Shadow evidence and the separate proposal-to-order safety workflow are demonstrated. A future tightly bounded Experimental Demo canary can have a different research-evidence threshold from Demo Auto, but both remain blocked today.

## Continuation — later 13 September

**Research schema:** Migration `055_multi_timeframe_research_evidence.sql` was applied through the existing checksum-verified migration runner; SQL readback found the migration checksum and both `app.multi_timeframe_research_experiments` and `app.research_prediction_trade_results`. No trading table or setting changed. The new tables are append-only, but no experiment rows were inserted: GBP/USD has an existing open lineage with a 2025 holdout. Attaching a new 2026 experiment to it or silently closing it would falsify holdout governance. A valid new lineage is required before SQL persistence of this diagnostic.

**Read-only broker check:** Live IG Demo GBP/USD market details expose `minDealSize=0.04` but no separately identified increment. No size increment was promoted to authoritative. Other markets remain non-authoritative. This is a broker-information blocker, not a coding test failure.

**Frozen GBP/USD development diagnostic:** Added `scripts/diagnose_gbpusd_economic_bridge.py` with fixed HGB configuration, 0.70/0.30 selection thresholds, 1.5×M15 ATR stop, 2R target, 60-minute holding limit, 0.5 bps per-side slippage and IG M1 bid/ask only. SQL now bounds `_market_frame` itself to 20 Aug–before 10 Sep 2026, and M1 is queried only before 10 Sep; this corrects an earlier read-before-filter holdout-boundary mistake. The rerun produced dataset hash `bf08345e4972dd612017b0aa7ce9e1ded418d341f323b58981e5022aa01f68ac`, 938 training rows, 48 validation rows, 1,636 IG M1 rows, and diagnostic directional AUC **0.6052**. Of 13 threshold-selected decisions, **10 lacked the next IG M1 entry, one had an M1 gap, one had an incomplete path, and only one had a valid time-exit outcome**. That single valid R was positive, but **one trade is not profitability evidence**; PF and strategy readiness are not estimable. No model was promoted and no Shadow state changed. The decisive same-ID economic bridge remains blocked by missing executable M1 paths, even though the diagnostic now assigns deterministic IDs and preserves gross four-bar outcomes for invalid rows.

**Expired programme UI:** The static Experimental Lab now computes effective expiry client-side as a fallback for the still-running older API, displays `EXPIRED`, disables inappropriate arm/pause/resume controls, and rechecks expiry immediately before sending arm/resume. Frontend tests **39/39 PASS** and Angular production build **PASS**. The tested static release `C:\sites\aurex\releases\20260913-180901` was activated for the Aurex IIS site; its Experimental Lab bundle SHA-256 matched the build. The platform API and trading worker were **not restarted**, so the backend expiry read-model change is not yet deployed there. Browser-level visual verification of this new UI is still outstanding.

**Remaining priority:** Broker increment authority, interval-level IG M1 recovery, legitimate new GBP/USD research lineage and immutable prediction/outcome persistence, release metadata, canonical persisted quality, and the separate authenticated Human-Approved Demo submission workflow. Experimental Demo and Demo Auto both remain NO-GO, for different reasons. No IG order was submitted.

**Regression and evidence check:** Full backend suite after the bounded SQL query change: **311 passed, 0 failed** (two third-party NumPy/joblib deprecation warnings). The selected prediction timestamps are 7 Sep 05:45 UTC and 8 Sep 04:15–14:30 UTC. The only evaluable first-hit path was the 8 Sep 09:00 UTC short, ending in a time exit. Missing IG M1 paths are an evidence-coverage failure; the apparent positive R on one path cannot be extrapolated to the other twelve. The first diagnostic implementation fetched a broader M15 range before filtering, though it did not use holdout rows for fitting or selection. The corrected rerun enforces the pre-10-Sep holdout boundary in SQL; the earlier transient read means the historical claim of a never-accessed holdout is not literally true for this cycle.

## Owner-authorized continuation — three-view M1 support

Migration `056_three_view_research_quality_snapshots.sql` was applied and the bounded diagnostic appended **27 snapshots (three views for nine enabled markets)**. Each snapshot includes policy/evidence SHA-256, source-specific provider counts, exact M5 gap boundaries, and M1 support classified per missing M5 interval as complete (all five M1 minutes), partial, or absent. An initial Germany 40 run revealed that counting closed-session M1 intervals disagreed with the M5 gap denominator; the support checker was corrected to use the same calendar predicate. The corrected support totals equal missing M5 counts for all 27 views. This is append-only **research diagnostic** persistence, not a canonical execution-ready quality gate; the percentages remain provisional and all 27 views are blocked.

GBP/USD: raw IG **69.93%**, 860 missing M5 intervals (660 complete M1 support, 12 partial, 188 absent); hybrid research **90.99%**, 198 missing (0 complete, 12 partial, 186 absent); current IG execution **64.23%**, 1,114 missing (704 complete, 19 partial, 391 absent). These views have independently selected windows and should not be subtracted as if they shared one denominator. Complete M1 support allows future research reconstruction only after provenance/quality validation; it does **not** create an IG M5 execution candle or certify an executable trade. All 27 snapshot statuses remain `BLOCKED`. Backend suite after this change: **313 passed, 0 failed**, two existing third-party deprecation warnings.

IG's published `/markets/{epic}` schema identifies `minDealSize` and `minStepDistance` (a stop-distance rule), but no distinct deal-size increment. Neither field was promoted to authoritative increment. [IG market-details reference](https://labs.ig.com/reference/markets-epic.html). Broker authority remains a P0 external-information dependency.

The backend API was **not restarted**: this checkout contains unrelated in-progress trading code, and restart would activate more than the tested expired-programme read-model fix. The existing frontend static expiry guard remains active. The Human-Approved Demo proposal-to-order path remains unimplemented; no approval token was issued and no IG order was sent. Forward Shadow, Experimental Demo, Demo Auto and Live remain disabled/not qualified as previously described.

**Bounded recovery-source check:** The existing `recover_local_dukascopy_gaps.py --dry-run` selected 25 nonempty local files on the four requested dates, including GBP/USD 7–9 Sep. The GBP/USD 8 Sep tick file has 78,317 rows and contained vendor quotes at sample IG-M1-missing next-entry timestamps (04:30, 07:45, 08:00, 08:15, 11:45, 12:15, 13:15, 14:30 and 14:45 UTC). This demonstrates candidate *research* recovery, not complete five-minute support at every interval or executable IG quotes. The existing importer/recovery path writes `app.market_candles_m1/m5`, while this three-view report reads `app.candles`; that store/provenance integration remains to be implemented and verified before these snapshots can improve. No vendor file was imported in this continuation.
