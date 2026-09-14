# EXECUTIVE CONCLUSION

Aurex is operational for market collection, historical import, candle recovery, diagnostics, and cost modelling. It is not ready for Shadow or HUMAN_APPROVED_DEMO because no recent candidate has passed experimental model gates, the hybrid research quality view is not wired as a canonical authority, and the execution chain still requires authoritative IG rules and final revalidation. The M5 stream is fresh and has zero invalid-OHLC/duplicate evidence. Dukascopy recovery is additive and provenance-preserving, but current qualification remains primarily IG-window based. Germany 40 is independently blocked and does not block FX. Live execution remains disabled.

# CURRENT OPERATIONAL STATE

The dependency chain is:

```text
RAW DATA → SESSION CLASSIFICATION → DATA REPAIR → RESEARCH DATASET
→ FEATURES → MODEL → EXPERIMENTAL ELIGIBILITY → SHADOW
→ IG BROKER RULES → RISK → HUMAN APPROVAL → IG DEMO ORDER
```

| Transition | State | Evidence |
|---|---|---|
| Raw data → session classification | CONFLICTING | Operational and qualification services disagree |
| Session classification → repair | PASS/PARTIAL | Calendar-aware recovery exists; closure policy remains incomplete |
| Repair → research dataset | PARTIAL | Separate M1/M5 evidence exists; hybrid quality is not canonical |
| Research dataset → features | PARTIAL | Recent windows lose rows during feature warmup/completeness |
| Features → model | PASS | Training pipeline runs |
| Model → experimental eligibility | FAIL | Recent candidates fail cost-aware gates |
| Model → shadow | FAIL | No eligible candidate |
| Broker rules → Demo | PARTIAL/FAIL | Size increment authority remains conservative/fallback in qualification |
| Approval → IG Demo | NOT READY | Must remain fail-closed until upstream gates pass |

# DATA READINESS

| Market | Recent IG M5 | Historical quality | Recent-window result |
|---|---:|---:|---|
| AUDJPY | 90.950% | 94.330% | Recent gaps |
| EURJPY | 90.909% | 98.290% | Recent gaps |
| EURUSD | 90.992% | 98.884% | Recent gaps |
| GBPJPY | 90.950% | 98.580% | Recent gaps |
| GBPUSD | 90.992% | 99.759% | Recent gaps |
| GERMANY40 | 3.453% | 38.425% | Old discontinuity / insufficient recent rows |
| USDJPY | 90.992% | 99.431% | Recent gaps |
| USDZAR | 90.950% | 91.597% | Recent gaps |
| XAUUSD | 86.919% | 97.805% | Session and recent gaps |

Common reported intervals are 7 September `05:20–07:30 UTC`, 8 September `13:40/13:50–15:55 UTC`, 8 September `17:40–17:50 UTC`, 8–9 September `19:40–07:30 UTC`, 9 September `07:30–08:10 UTC`, and 11 September `03:30–03:40 UTC`. Gold also reports daily `20:55–22:00 UTC` breaks that require explicit session classification.

Dukascopy tick → M1 → complete M5 recovery is implemented. Complete partitions generated derived M5 evidence; incomplete partitions were quarantined. IG precedence and provenance are preserved. The remaining defect is that `RAW_IG_COMPLETENESS`, `HYBRID_RESEARCH_COMPLETENESS`, and `EXECUTION_WINDOW_IG_COMPLETENESS` are not yet exposed through one canonical service.

# MODEL READINESS

Recent-window experimental runs used the 1 July–11 September 2026 window and the separated 500-row experimental floor.

| Market | Feature-complete rows | Result | Main failures |
|---|---:|---|---|
| USDJPY | 1,259 effective evaluation rows | Rejected | Negative expectancy, PF 0.424, calibration, drawdown, stability, baseline |
| GBPUSD | 1,250 effective evaluation rows | Rejected | Negative expectancy, PF 0.642, baseline, stability |
| EURUSD | 5,452 effective evaluation rows | Rejected | AUC 0.512, negative expectancy, PF 0.307, baseline, stability |
| AUDJPY | 360 | Blocked | Insufficient feature-complete rows |
| EURJPY | 341 | Blocked | Insufficient feature-complete rows |
| GBPJPY | 391 | Blocked | Insufficient feature-complete rows |
| USDZAR | 357 | Blocked | Insufficient feature-complete rows |
| Gold | 298 | Blocked | Insufficient feature-complete rows |
| Germany40 | 476 M15 rows | Blocked | July-to-date sample below training capacity |

The model artifact and chronological split work. The current candidates do not demonstrate a deployable cost-aware edge. No candidate is `DEMO_EXPERIMENT_ELIGIBLE`.

# SHADOW READINESS

Shadow infrastructure exists, but active database states referencing rejected models must be reconciled. `SHADOW_INFRASTRUCTURE_READY` is distinct from `SHADOW_MODEL_ELIGIBLE` and `SHADOW_ACTIVE`; current evidence supports infrastructure readiness only. No valid model is active.

# BROKER READINESS

M5/M15 freshness, bid, ask, spread, session, and cost-model evidence are present. Qualification still reports `size_increment_authoritative=false` with `CONSERVATIVE_MINIMUM_FALLBACK`. This blocks actual order submission only; it must not block research or shadow.

# HUMAN-APPROVED DEMO READINESS

`HUMAN_APPROVED_DEMO_READY = NO`. The human approval and execution path must remain fail-closed because there is no eligible model/shadow candidate and the authoritative broker-rule chain is not complete. IG must remain the only source for current bid, ask, spread, margin, account state, and dealing rules.

# RUNTIME/SERVICE READINESS

Database evidence shows current M5/M15 streams and recent cost-model updates. Historical recovery, reconciliation, risk, and Demo components exist. Recent operational alerts were resolved. Runtime readiness is therefore `PARTIAL`: collection is operating, but the model/shadow/approval chain is not producing an eligible candidate.

# DATABASE DEFECTS

- Multiple tables/services expose overlapping readiness concepts without one canonical authority.
- Reprocessing can produce negative fallback counters; this is a reporting defect, not candle corruption.
- Shadow state can outlive the eligibility of the referenced model and needs an integrity query/cleanup policy.
- Dataset manifest schema is applied and training writes manifests, but hybrid quality statistics are not yet fully populated.

# CONFIGURATION/POLICY DEFECTS

- The former 2,000-row rule was applied to M15 despite the original target being 2,000 M5 candles; this is now separated for research, while production gates remain unchanged.
- Broker rule authority is still mixed with readiness reporting and must be scoped to Demo submission.
- Germany 40 full-history quality remains visible as a blocker even though a recent-window experiment should be independent.

# BLOCKER MATRIX

| ID | Blocker | Market/System | Type | Actual cause | Is it real? | Fix | Blocks Shadow | Blocks Demo |
|---|---|---|---|---|---|---|---|---|
| B1 | No experimental candidate | USDJPY/GBPUSD/EURUSD | MODEL | Negative cost-aware results and stability failures | YES | Improve/retest signal conversion on hybrid recent data | YES | YES |
| B2 | Hybrid quality not canonical | All | DATA/BUG | Repairs stored separately; qualification remains IG-window based | YES | One readiness service with three quality views | YES | YES |
| B3 | Quality authorities conflict | All | BUG | Different queries/windows/session rules | YES | Canonical readiness API and shared policy | YES | YES |
| B4 | Insufficient feature rows | Smaller markets | DATA/FEATURE | Warmup/session/missing-row losses | YES | Quantify losses; use qualified M5/M15 window | YES | YES |
| B5 | Germany 40 recent sample | Germany40 | DATA/POLICY | July window has 476 M15 rows | YES, independent | Expand backward by month and test capacity | NO | NO |
| B6 | Size increment fallback | Demo path | BROKER | Authoritative rule not represented in qualification | YES | Fix IG rule retrieval/mapping and freshness | NO | YES |
| B7 | Stale shadow references | Shadow | BUG | Rejected model can still have shadow state | YES | Enforce model-status join in worker/UI | YES | NO |
| B8 | Negative recovery counter | Recovery reporting | BUG | Idempotent reprocessing uses rowcount incorrectly | YES | Make counters monotonic/idempotent | NO | NO |

# FALSE OR STALE BLOCKERS

- Germany 40’s poor 2024 history is not an FX blocker.
- All nine markets passing is not required for the first Demo experiment.
- 100% IG historical purity is not required for research.
- Production model validation is not conceptually required for research eligibility, although current model-quality failures are real.
- Broker size increment authority should not block training or shadow.

# MUST FIX BEFORE SHADOW

1. Make hybrid research quality the canonical research view while retaining raw IG and execution IG views.
2. Reconcile shadow state so only eligible model artifacts can run.
3. Produce at least one candidate that passes experimental data, leakage, artifact, and cost-aware signal gates.

# MUST FIX BEFORE HUMAN-APPROVED DEMO

1. Have an eligible model with active shadow evidence.
2. Resolve authoritative IG size increment and broker-rule evidence.
3. Verify approval token/authentication, TTL, atomic submission, final revalidation, and reconciliation end to end.
4. Keep IG current market/account state authoritative at submission.

# SHORTEST PATH TO SHADOW

1. Canonicalize the three quality views.
2. Repair/classify the USDJPY and GBPUSD model windows.
3. Re-run threshold/exit/cost experiments.
4. Mark only a passing candidate experimental-eligible.
5. Start shadow with a status-integrity check.

# SHORTEST PATH TO HUMAN-APPROVED DEMO

1. Complete the eligible shadow candidate.
2. Resolve authoritative IG broker rules for the selected market.
3. Verify risk/margin/exposure checks.
4. Verify secure single-use owner approval.
5. Verify atomic `OWNER_APPROVED → SUBMITTING`.
6. Revalidate market, risk, margin, exposure, and broker rules immediately before submission.
7. Test timeout/retry/restart reconciliation.
8. Run one owner-approved minimum-risk IG Demo canary; Live remains disabled.

# FIXES IMPLEMENTED DURING AUDIT

- Applied migration 054.
- Added authority fields and immutable dataset-manifest schema.
- Added `FULL_HISTORY`, `RECENT_CONSECUTIVE`, and `ROLLING_WINDOW` selection.
- Added separate 500-row experimental research floor versus the 2,000-row production floor.
- Added per-market training failure isolation.
- Corrected qualification to recompute session membership from the calendar.
- Executed bounded Dukascopy recovery and retained provenance.
- Regression tests passed during the implementation sequence.

# FINAL OWNER DECISION

```text
ENOUGH_DATA_FOR_EXPERIMENTAL_RESEARCH = YES for selected recent FX windows; NO for current Germany40 July window and smaller feature windows
CURRENT_HUMAN_DEMO_GATE_REQUIRES_PRODUCTION_VALIDATION = NO in policy; current candidates still fail independent experimental gates
CAN_START_SHADOW_NOW = NO
CAN_START_HUMAN_APPROVED_DEMO_NOW = NO
LIVE_ENABLED = NO
```

The next implementation action is to finish the canonical hybrid research-quality service, then run a focused USDJPY/GBPUSD strategy-conversion experiment. Do not enable a rejected model or submit an order.
