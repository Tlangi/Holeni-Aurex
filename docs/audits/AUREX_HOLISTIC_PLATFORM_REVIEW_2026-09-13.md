# Aurex holistic platform review — 13 September 2026

## Scope and evidence standard

This is a read-only review of the current checkout, a local SQL Server read-only query, local configuration flags (never credentials), Windows service status, and test/build runs. The checkout has extensive uncommitted work; a running service may use a different release. SQL rows prove stored state, not that the deployed worker executes the same code. No order, proposal, model promotion, service restart, or migration was initiated. `UNKNOWN` means evidence was not obtained, not that a control failed. Historical audit figures are cited only as context and are not silently promoted to current runtime facts.

# Part A — Executive summary

## A1. Overall status

**RESEARCH READY, conditionally Shadow-capable; not Experimental Demo ready, Demo Auto ready, or Live ready.** The codebase has a real data/research/risk/broker architecture, but no currently validated profitable model was found and broker size increments are non-authoritative for every enabled market. An experimental programme row remains `ARMED` even though its configured expiry passed on 11 September; that is a stale administrative state, not evidence of a currently executable trade.

An overall completion or readiness percentage would imply a defined denominator and weighting that this project does not have. **Overall readiness score: not defensibly quantifiable.** Technical maturity is moderate; data, ML profitability, execution evidence, operational assurance, and UI maturity are partial. Security has concrete controls but has not received a complete adversarial or penetration assessment in this review. Deployment maturity is partial: IIS and API/worker services exist, but the `AurexWeb` Windows service is `Stopped/Disabled`, and the exact deployed binaries were not fingerprinted against this checkout.

## A2–A3. What works and what the chain does

IG Lightstreamer and historical/Dukascopy paths persist candles with provenance; M1/M5/M15 research, features, chronological evaluation, model registry, shadow evaluation, risk ledgers, broker-rule capture, a separate experimental Demo submit path, reconciliation, owner APIs, and a six-area Angular UI all exist. The strongest architectural properties are Demo/Live separation, explicit provenance, owner session/CSRF controls, fail-closed broker gates, a non-forced-profit policy, and 295 passing backend tests.

The end-to-end chain loses authority at **model/economic validation**: current registered models are rejected, the principal training target predicts a four-M15-bar close direction rather than a broker-executable stop/target outcome, and available dealing-size increments are non-authoritative. Owner trade-proposal approval is deliberately **not** an IG submission: it records `OWNER_APPROVED_FOR_RISK` and returns `broker_order_submitted: false`. Experimental Demo is a different, guarded path, not proof that the proposed Human-Approved Demo workflow is complete.

## A4. Critical blockers by area

| Priority | Area | Blocker and consequence |
| --- | --- | --- |
| P0 | Trading/broker | All nine current broker-rule rows have `size_increment_authoritative=false`; experimental submission checks and rejects that state. Do not submit against inferred increments. |
| P0 | ML/research | No latest registered evaluation has positive expectancy and passing validation; none demonstrates a credible post-cost edge. |
| P0 | Execution/governance | Proposal approval does not atomically become a revalidated IG submission. Do not present it as an operational Human-Approved Demo path. |
| P1 | Operations | One EUR/USD experimental programme is still stored as `ARMED` after 11 September expiry; verify UI/worker expiry semantics and reconcile the stale display. No attempt rows were present. |
| P1 | Data | Recent row counts do not prove calendar-aware 2,000-M5 continuity, M1 support, or IG-only execution freshness. Germany 40 session logic needs independent confirmation. |
| P1 | Research | The latest GBP/USD registered evaluation differs materially from the earlier promising diagnostic; selected cohort/window/manifest differences must be reconciled before tuning. |
| P1 | Security/deployment | Dirty checkout versus running release and inaccessible service command details prevent code-to-runtime attestation. |
| P2 | UX | Shared Angular operational component and button inventory remain incomplete; phone-width real-proposal approval is unverified because there were no proposals. |

## A5. Can Aurex trade today?

| Question | Answer | Basis |
| --- | --- | --- |
| Collect market data | CONDITIONAL | Market-stream service reports Running; last stored completed PASS M5 is Friday 11 Sep 20:55 UTC, consistent with weekend closure on Sunday 13 Sep. A live in-session update was not observed. |
| Generate signals | CONDITIONAL | Shadow inference code exists; latest registered models are `REJECTED`, so a qualifying model signal is not established. |
| Shadow trade | CONDITIONAL | Worker and ledger code exist, but active eligible model/forward-cycle state was not attested by these checks. |
| Place controlled Experimental IG Demo order | NO, on current evidence | Separate code path exists, but current rules are non-authoritative; the only programme has expired and no attempts exist. |
| Autonomous Demo | NO | No validated edge or end-to-end unattended execution/recovery evidence. |
| Live | NO | Live flag is false and there is no Demo/forward profitability record. |

Local settings currently load `trading_mode=demo`, `ig_environment=demo`, `allow_demo_trading=true`, `experimental_demo_enabled=true`, `allow_live_trading=false`, and `daily_profit_target_enabled=false`. These are *capability flags*, not readiness or proof of an executable opportunity. The stale `ARMED` row was EUR/USD, 0.10% per-trade risk, 0.50% daily loss limit, 1.00% programme drawdown limit, expired 11 Sep 07:06 UTC; no experimental attempts were recorded.

## A6. Profitability

**No demonstrated edge.** Latest registered evaluations queried from SQL are rejected and have negative expectancy. GBP/USD's earlier recent-window result (AUC 0.573, PF 0.642, 156 trades) is a useful diagnostic, not a profit result. A later registered GBP/USD row is AUC 0.516, PF 0.164, 139 trades. Neither shows economic profitability; comparing them without an identical frozen prediction/trade cohort would be invalid. AUC measures ranking on a directional target, not a broker-executable return. No untouched-holdout/forward/Demo evidence observed here warrants a higher label.

## A7. Top ten actions, dependency order

1. Attest the deployed code, runtime flags, and current DB state; make an expired programme display expired and stay fail-closed.
2. Recover authoritative IG dealing rules, especially size increment and stop/margin details, with source/time/hash evidence.
3. Produce the canonical three-view market quality report (raw IG, hybrid research, current IG execution) with calendar-aware gaps and M1 support.
4. Freeze one comparable GBP/USD development cohort, manifests, and untouched holdout; explain the two registered evaluation results.
5. Bridge identical prediction IDs through direction AUC, gross return, cost-adjusted return, and actual stop/target executable replay.
6. Introduce/test an economic label and first-hit path policy on M1 bid/ask without contaminating feature time or holdout.
7. Re-evaluate a bounded set of model/threshold/exit hypotheses; require net expectancy and stability, not AUC alone.
8. Run genuine forward Shadow with immutable proposal, rejection, spread, fill and outcome evidence.
9. Complete Human-Approved Demo's single-use authenticated confirmation, atomic transition, final revalidation and reconciled IG Demo submission, separately from the existing proposal decision.
10. Simplify/attest owner UI, alerts and service release process; only then consider an owner-authorized minimum-risk canary.

# Part B — Detailed technical review

## 1–3. Repository architecture and end-to-end path

`services/platform-api/app` is a FastAPI/SQL Server monolith with scheduled and worker modules; `apps/web/src/app` is Angular 21; `database/scripts` contains migrations through 055; `infrastructure/iis/Aurex/web.config` proxies `/api` and two owner-summary GETs to a separate localhost service. `integrations/tradingagents` is a bounded local-model research adapter. The observed service names are `AurexPlatformAPI`, `AurexOwnerOverviewAPI`, `AurexMarketStream`, `AurexTradingWorker`, `AurexHealthMonitor` (all Running) and `AurexWeb` (Stopped/Disabled). The IIS static site can operate without the old Web service; a service's Running state does not prove healthy work. CIM command-line inspection was denied, so exact executable paths/recovery settings are UNKNOWN.

| Stage | Code location | State and audit observation |
| --- | --- | --- |
| IG market capture, M1/M5 | `streaming.py`, `market_data.py`, `ig_demo.py` | PARTIAL: persisted rows and worker existence verified; live Sunday continuity not testable. |
| M15/provider selection | `model_pipeline._market_frame`, `multi_timeframe_research.py`, `recent_window.py` | PARTIAL: IG preference and Dukascopy research lineage coded; cohort completeness not proven. |
| Features/labels | `model_pipeline.add_features`, `research_labels.py` | PARTIAL: backward-looking features; production label economically misaligned. |
| Training/selection | `model_pipeline.py`, `model_tournament.py`, `holdout_service.py` | PARTIAL: chronological/purged paths exist, latest rows rejected; holdout integrity not independently reconstructed. |
| Shadow/risk | `shadow_engine.py`, `shadow_trades.py`, `risk_ledger.py` | PARTIAL: candidate/ledger logic exists; no current qualifying forward edge verified. |
| Owner proposal | `trade_proposals.py`, `main.py` | PASS for decision recording; FAIL as a submission workflow by design. |
| Experimental submit | `experimental_demo.py`, `ig_execution.py` | PARTIAL: guarded IG Demo path exists, blocked by current rule authority and expired programme. |
| Broker sync/reconciliation | `ig_sync.py`, `order_lifecycle.py` | PARTIAL: uncertain and mismatch states implemented; unattended reliability not observed over real orders. |
| Monitoring/UI | `health_monitor.py`, `owner_overview.py`, Angular routes | PARTIAL: owner summaries and alerts exist; release attestation and UX cleanup remain. |

Research `trading_metrics` subtracts bps from signed close-to-close future return. The operational path must use current bid/ask, broker rules, stop/target, position size, margin, state transitions, confirmation, and reconciliation. These are materially different estimands; a research PF cannot be treated as Demo-order PF. No order/position was submitted or closed as part of this audit.

## 4. Market data, calendars and provenance

Read-only SQL on 13 September found the following **completed PASS rows in the last 90 days**. These are stored-row counts, **not quality percentages or proven consecutive windows**. All nine latest PASS M5 timestamps were 11 Sep 20:55 UTC. M1 latest timestamps were 11 Sep 20:58–20:59 UTC. Sunday closure should not be counted as a missing weekday candle.

| Market | M1 | M5 | M15 | Latest model blocker |
| --- | ---: | ---: | ---: | --- |
| AUD/JPY | 4,356 | 2,283 | 756 | No registered latest model |
| EUR/JPY | 4,352 | 2,281 | 753 | Rejected, negative expectancy/PF |
| EUR/USD | 4,307 | 20,864 | 6,943 | Rejected, negative expectancy/PF |
| GBP/JPY | 4,340 | 2,284 | 757 | Rejected, negative expectancy/PF |
| GBP/USD | 4,329 | 4,458 | 1,478 | Rejected, cohort-dependent result |
| Germany 40 | 4,206 | 3,581 | 1,187 | Rejected; independent session/calendar policy needed |
| USD/JPY | 4,336 | 4,451 | 1,475 | Rejected, negative expectancy/PF |
| USD/ZAR | 4,363 | 2,285 | 757 | No registered latest model |
| Gold | 4,047 | 2,162 | 714 | Rejected, negative expectancy/PF |

M5 dates in this query start 15 June (EUR/USD), 20 August (GBP/USD and USD/JPY), 25 August (Germany 40), and around 1 September for the other five. M1 PASS rows predominantly start 7 September. Larger M5 than M1 counts reflect imported history; do not infer M1 completeness for older M5. The exact dates of residual in-session gaps, duplicate rate, mid/bid/ask outliers, last 2,000 quality percentages, and raw-IG versus Dukascopy shares were **not recomputed** in this review. Older gap dates from prior audits remain hypotheses until the calendar-aware, source-aware query is rerun. Germany 40 must use its own exchange/IG session calendar in UTC, with South African times only for display. Dukascopy repair remains research-only; IG precedence must not be overwritten.

## 5–8. Timeframes, features, models and economics

`model_pipeline.py` uses M15 training bars, seven features (`ret1`, `ret4`, EMA gap, RSI, ATR%, range%, tick-volume z-score), and a four-bar future-close direction label. Its trailing indicators are backward-looking and its chronological evaluation purges four boundary rows. This is good hygiene but **not** full point-in-time/leakage proof across every source transition, revised candle or macro join. Incomplete candles must remain excluded from live inference. `research_labels.py` contains an experimental high/low path label; high/low extrema alone cannot determine first-hit order when stop and target occur within one bar. `multi_timeframe_research.py` has a fixed-horizon CFD-net prototype, not an authoritative stop/target outcome.

The model family seen in the primary production training path is histogram gradient boosting. Tournament/research modules add competing families and selective thresholds; their comparability and untouched holdout were not independently re-executed in this review. Run a frozen same-cohort table for every candidate (window, feature/label version, costs, trade IDs, holdout lock, model hash). Threshold selection on the development set must not be reported as fresh validation. Model selection must optimise *cost-adjusted utility subject to stability and risk*, with AUC only as a diagnostic. Replay has bid/ask/stop-target abstractions but a complete real-CFD audit of financing, slippage, market-open gaps, min size/increment, partial fills and MFE/MAE first-hit logic remains open. Treat current historical PF as potentially optimistic or simply non-comparable until the bridge is run.

### Latest registered model evaluations (SQL, not a fresh retrain)

All figures are from the most recently registered model version per market. Expectancy/drawdown are return units, not ZAR. Holdout and forward status: **not attested** by this query.

| Market | AUC | PF | Expectancy | Max drawdown | Trades | Registry status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| AUD/JPY | — | — | — | — | — | No version |
| EUR/JPY | .525 | .591 | -.000151 | .0548 | 252 | REJECTED |
| EUR/USD | .525 | .014 | -.000127 | .0183 | 144 | REJECTED |
| GBP/JPY | .492 | .513 | -.000216 | .0541 | 186 | REJECTED |
| GBP/USD | .516 | .164 | -.000112 | .0166 | 139 | REJECTED |
| Germany 40 | .487 | .797 | -.000135 | .0261 | 87 | REJECTED |
| USD/JPY | .496 | .989 | -.00000764 | .0467 | 182 | REJECTED |
| USD/ZAR | — | — | — | — | — | No version |
| Gold | .493 | .544 | -.000393 | .0606 | 132 | REJECTED |

The prior GBP/USD .573 AUC/.642 PF row was registered at 19:14 UTC on 11 Sep; the .516/.164 row at 20:24 UTC. The dataset/window/threshold differences must be diffed, not explained by speculation. Both are losing after the recorded cost assumptions. AUC, PF and expectancy here are validation metrics; they do not establish untouched holdout, forward Shadow, or Demo performance.

## 9–13. Risk, broker, reconciliation, Shadow and Experimental Demo

`config.py` prohibits enabling a daily profit target at startup. Risk modules implement per-trade/daily loss, reserved exposure and other constraints; no evidence of forced daily-return chasing was found in inspected paths. This is a code-level observation, not a complete numerical stress test. The separate experimental programme has explicit owner control, expiry, loss and drawdown limits. Its `submit_experimental_attempt` checks evaluated/single submission state, authoritative size increment, unknown submissions and programme/risk/broker state before IG submission. `ig_execution.py` separates normal, experimental and close gates; `ig_demo.py` itself is read-only. Direct owner proposal `APPROVE` only advances to risk review and never submits.

Broker rules were refreshed around 13 Sep 12:50 UTC, but **all nine `size_increment_authoritative` flags are false**. Refreshed is not authoritative. The programme row is expired and there are **zero** experimental attempts and **zero** owner proposal rows. A safe canary therefore requires a *new* governed, in-window programme and owner decision after rule authority and the research/Shadow gates pass. This audit does not authorize one.

`ig_sync.py` explicitly covers `UNKNOWN_WORKING_ORDER`, `STALE_LOCAL_SUBMISSION`, `DUPLICATE_DEAL_REFERENCE`, `SUBMISSION_UNKNOWN`; experimental reconciliation uses `UNKNOWN_SUBMISSION` and `RECONCILIATION_MISMATCH`. Unknown outcomes block further action rather than blind retry in inspected paths. Actual sustained reconciliation reliability, position-close recovery, broker-side stop/target handling and unattended alert delivery are **not proven** by zero experimental attempts. Shadow records candidate decisions and hypothetical outcomes; it cannot validate real slippage/fills until matched against controlled Demo evidence.

## 14–15. Research agents and macro intelligence

`intelligence.py`, `macro_intelligence.py`, `market_intelligence.py`, `tradingagents_adapter.py`, `llm_runtime.py` and `integrations/tradingagents/aurex_worker.py` provide bounded research/agent paths. Configuration restricts locally configured LLM endpoints when local-only mode is requested. A complete point-in-time replay of each source's publication timestamp, revision, validation and decision cutoff was **not** run. No stale-macro exemption or agent opinion should override model, price, risk or broker gates. Per-currency live macro source/score/freshness was **not retrieved**, so no current currency score is asserted. Missing/unverified evidence should remain neutral or reject, never fabricated conviction.

## 16–17. Database and API

Migrations exist through `055_multi_timeframe_research_evidence.sql`; actual applied-version parity, index coverage, growth, foreign-key/orphan checks and backup-restore health were not queried here. The database was reachable through the configured read-only inspection path. Schema names were checked from current code (`app.candles`, `app.model_versions`, `app.model_evaluations`, `app.broker_market_rules`, `app.experimental_programmes`, `app.experimental_attempts`). Migration reproducibility requires a clean-database rehearsal, not mere file presence. FastAPI has owner-session dependencies, typed requests, CSRF enforcement on mutating requests, and a separate GET-only overview API behind IIS. Response-size and high-load race profiling remain open.

## 18–21. Frontend, security, deployment and observability

Angular routes expose Dashboard, Markets, Trading, Research, Risk and System; the recent Risk summary extraction and advanced disclosures reduce some clutter. The shared operational component is still large. A real authenticated phone-width Approve/Decline check remains unperformed because no live proposal exists. Chart auto-positioning/polling-fallback code and tests exist but a live in-session chart observation was not part of this review. A complete button-handler inventory and duplicate-readiness audit remain P2. Treat owner-summary trading eligibility `UNVERIFIED` as a safety statement, not a UI bug.

Auth stores hashed session tokens, uses `HttpOnly`, `Secure` (production config requirement), `SameSite=Strict`, CSRF token/header matching and owner-role checks in inspected paths. The main risk is not a proven exploit but incomplete deployment attestation, secret-history scan, HTTP-header/TLS verification and adversarial auth testing. No secret values are reproduced. IIS proxy routes two owner GETs to localhost 8011 and other API traffic to 8010. Running services were observed; exact service executable/recovery configuration was inaccessible (`Get-CimInstance Win32_Service`: Access denied). Observability includes health/decision/reconciliation modules, but no end-to-end sampled trace from signal to confirmed close or measured alert latency was obtained.

## 22. Tests and evidence limits

Backend `services/platform-api/.venv/Scripts/python.exe -m pytest -q`: **295 passed, 0 failed, 0 skipped**, two NumPy/joblib deprecation warnings. Frontend `npm test -- --watch=false`: **37 passed, 0 failed**; production `npm run build`: **PASS**. Tests are evidence of code behaviour, not live broker correctness. Gaps requiring explicit tests: first-hit path with both barriers in one M1 candle; identical-cohort label/replay bridge; programme expiry state presentation; broker-rule authority ingestion; concurrent owner approval/submit idempotency; uncertain IG response and recovery; real phone-width pending approval; deployed-release hash parity.

## 23–24. Debt and blocker register

| ID | Priority | Component | Evidence | Operational/trading impact | Resolution / dependency |
| --- | --- | --- | --- | --- | --- |
| B01 | P0 | Broker rules | 9/9 size increments non-authoritative | Current experimental submit must reject | Obtain/persist verified IG rule authority; test fail-closed |
| B02 | P0 | Models | Latest 7 versions rejected, 2 absent | No demonstrated edge | Frozen same-cohort cost/label experiment after data qualification |
| B03 | P0 | Owner Demo | Proposal approval returns no order | Approval UX cannot imply submission | Authenticated token, atomic transition, final checks, IG adapter, recovery |
| B04 | P1 | Programme lifecycle | Expired EUR/USD row still `ARMED` | Misleading UI/state | Derive effective status from expiry; test guard/display |
| B05 | P1 | Data quality | Counts only; no 2,000-window percentage | Research/execution authority unclear | Three-view calendar-aware report + M1 lineage |
| B06 | P1 | Research cohort | Two GBP/USD results differ | Invalid tuning decisions | Manifest/diff prediction cohort and cost assumptions |
| B07 | P1 | Runtime attestation | Dirty tree, service path inaccessible | Code/runtime mismatch possible | Hash deployed artifacts and collect authorized service metadata |
| B08 | P2 | Frontend | Large shared component; no live proposal | Operator clarity/mobile approval unverified | Route split/button inventory and genuine proposal walkthrough |
| B09 | P2 | Observability | No sampled end-to-end trace | Unattended reliability unproven | Correlation IDs/alerts and recovery drill |
| B10 | P3 | Legacy UX | Old technical labels still appear | Clutter, no direct trading risk | Progressive disclosure after P0/P1 work |

## 25. Readiness matrix

No numeric domain score is given: the evidence does not define comparable denominators. `PARTIAL` means implemented capability with unverified operational or economic acceptance.

| Domain | Status | Required next step |
| --- | --- | --- |
| Infrastructure/deployment | PARTIAL | Release hash, service recovery and IIS verification |
| Database/migrations | PARTIAL | Applied migration/index/restore rehearsal |
| Market data/historical data | PARTIAL | Three-view quality and gap report |
| Data quality | PARTIAL | Qualified 2,000-M5 per market and M1 support |
| Features | PARTIAL | Full point-in-time parity and ablation |
| Research/ML | PARTIAL | Same-cohort economic label/replay and protected holdout |
| Macro intelligence | PARTIAL | Live source/freshness inventory and historical publication audit |
| Backtesting | PARTIAL | Broker-executable M1 path/financing/slippage checks |
| Shadow | PARTIAL | Current model eligibility plus forward evidence |
| Risk | PARTIAL | End-to-end stress and race tests |
| Broker rules | FAIL | Authoritative size increments for chosen market |
| IG integration/reconciliation | PARTIAL | Controlled canary and uncertain-response recovery |
| Experimental Demo | FAIL | B01/B02, new valid programme, owner go/no-go |
| Autonomous Demo/Live | FAIL | Longitudinal forward/Demo economics and operational gates |
| API/security/observability | PARTIAL | Deployed attestation, adversarial tests, alert drill |
| Frontend | PARTIAL | Component split, button audit, real mobile proposal check |

## 26–27. Market and model readiness

The market data/model table above is the current evidence. None is trading-ready. AUD/JPY and USD/ZAR have no latest version; the other seven have negative validation expectancy and rejected status. All nine have non-authoritative broker size increments. Germany 40 needs an independent session calendar and rolling 2026 research window; its old 2024 coverage should not block *research*, but absence of a valid model/rules still blocks execution. Model family/version/holdout/Shadow cannot be honestly listed per market from the latest-evaluation query alone; export each immutable manifest in the next work package.

## 28–31. Target architecture, roadmap and definitions of done

Keep a single broker/risk authority and immutable evidence ledger. Keep three distinct data views: raw IG, repaired research, IG execution. Consolidate owner readiness into one read-only API; retire duplicate local UI inference after parity tests. Do **not** rewrite the platform or invent an unrestricted LLM trader. Extract Angular route-owned components incrementally. Keep the experimental submit path isolated while implementing a *separate*, explicit Human-Approved Demo transition; do not conflate proposal approval with broker submission.

| Phase | Scope and dependency | Acceptance and tests |
| --- | --- | --- |
| 0 Correctness | Attest live release/config, expire stale programme state, authoritative rules | Expired programmes cannot submit; no unknown rule can size; deployment parity recorded |
| 1 Data/labels | Three-view 2,000-M5 quality; M1 first-hit economic labels and same-cohort replay | Calendar exclusions, IG precedence, no lookahead; identical trade IDs through every metric |
| 2 Profitability | Bounded GBP/USD thresholds/long-short/session/spread/exit study | Frozen development cohort, untouched holdout, positive net expectancy/PF with uncertainty and stability |
| 3 Shadow | Qualified one-model/one-market forward collection | Immutable signal/rejection/trade records, drift/latency and risk controls observed |
| 4 Experimental Demo | Governed human-approved one-off path and owner canary | Demo-only credentials; single-use approval; atomic submit; final quote/spread/risk/margin/rule check; reconciliation and recovery; minimum-risk owner signoff |
| 5 Demo Auto | Separate promotion/arming and unattended validation | Production gates unchanged; sustained profitable Demo sample and alert/recovery evidence |
| 6 Live | New explicit governance decision | Statistically credible forward/Demo sample, drift/risk/drawdown tolerance, broker/reconciliation reliability, emergency stop and security review |

Experimental Demo must have an in-window owner-armed programme, Demo-only account, known-authoritative rule and size/stop/margin evidence, current IG execution data, bounded risk/trade/loss limits, clear reconciliation, no unknown submissions, owner confirmation, and recovery-tested monitoring. It need not require *production* model validation for a controlled learning canary, but its specific experimental hypothesis, dataset/Shadow evidence and owner loss tolerance must be explicit. **Current evidence fails this definition.** Demo Auto additionally requires the existing model promotion/holdout/forward profitability gates, broker/risk stability, and unattended incident response. Live additionally needs a materially larger independent trade sample, stable net edge under stress, safe drift handling, broker and reconciliation track record, approved capital/risk limits, and a separate security and operational authorization. No arbitrary daily-profit quota should be introduced.

# Owner Decision Summary

1. **Stage:** Research ready, Shadow-capable only conditionally; not Demo-ready.
2. **Top five blockers:** Non-authoritative broker increments; no validated profitable model; incomplete proposal-to-order workflow; unproven 2,000-M5 calendar-aware quality; unaligned production label/replay economics.
3. **Architecture fundamentally sound?** Broadly yes for separated research/risk/broker authority, but execution and provenance joins remain incomplete.
4. **Market data trustworthy?** Partially; stored PASS counts exist, but source-aware recent continuity and execution freshness are unproven.
5. **Labels aligned with profitability?** No. Four-M15-close direction is not net executable stop/target outcome.
6. **Credible model edge?** No demonstrated post-cost edge.
7. **Experimental Demo safe now?** No.
8. **Autonomous Demo safe now?** No.
9. **Live acceptable?** No.
10. **Implement next:** The immediate package below.
11. **Stop doing:** Treating AUC or row count as profitability/readiness; treating proposal approval as submission; tuning on shifting cohorts; using research repair as IG broker truth.
12. **Single most important technical priority:** A frozen same-decision, broker-executable label-to-strategy outcome bridge, while retaining fail-closed broker-rule authority.

## Recommended Immediate Work Package — for the next implementation session, **not implemented here**

Build one bounded GBP/USD research-and-safety slice. First capture deployed release/config and expire the stale programme display without arming or submitting. Produce per-market raw IG, hybrid research and current IG execution quality for the latest 2,000 completed M5 candles, with calendar-aware gap dates, provider lineage and M1 support. Freeze GBP/USD prediction IDs, data/feature/label/cost versions, development/validation/untouched holdout and the two 11 September evaluation cohorts. On identical IDs compute directional AUC, signed four-bar gross/net returns, and M1 bid/ask first-hit stop/target replay with spread, slippage, sizing and broker-rule constraints; report long/short, session, spread and confidence slices with counts/uncertainty. Do not tune on holdout or enable a model. Independently establish authoritative GBP/USD IG rule evidence. Add tests for provider transitions, temporal joins, both-barrier ambiguity, cohort equality, rule failure, programme expiry, approval idempotency, and unknown submission. Update owner readiness to say exactly which gate fails. Deliver a go/no-go for genuine forward Shadow and, separately, a later owner-approved Experimental Demo canary. Do not change Live or Demo Auto gates or submit any order in this package.
