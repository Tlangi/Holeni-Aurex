# Aurex comprehensive readiness audit — 15 September 2026

## 1. Executive Summary

**Decision: NO-GO for EXPERIMENTAL_DEMO, DEMO_AUTO and Live on every market.** Aurex is an operational research/data collection platform with functioning read-only IG Demo connectivity and a Shadow worker, but the current data→feature→label→model→risk→broker→execution→reconciliation→P&L chain has no qualifying model, no actual forward Shadow trades and no authoritative broker size increments. These are independent hard gates. Owner approval cannot cure them.

Evidence conventions throughout: **VF** = verified fact from this audit's source, local service/API, settings or read-only SQL; **IN** = inference from those facts; **NV** = not verified. SQL results are snapshots around 06:32–06:35 UTC, not a guarantee of later state. SQL was read through `app.database.open_database`; no SQL write, migration, trading-state change, order or service restart was made. `report_three_view_quality.py` was called without `--persist` and returned `persisted:false`. Tests/build wrote only their normal local generated artifacts. A running Python service pointing at a mutable checkout can have older modules loaded, so source and runtime are identified separately.

| Readiness dimension | State | Basis |
| --- | --- | --- |
| Platform | PARTIAL | Six services running, API liveness/readiness 200; active IIS release and public TLS page not attested. |
| Data | DEGRADED | Fresh IG M1; all nine latest-M5 three-view assessments BLOCKED. |
| Research | PARTIAL | Research tables, cohorts and jobs exist; canonical IG execution paths incomplete. |
| Model | BLOCKED | Seven latest HGB registry versions REJECTED, two markets have none; no positive net expectancy. |
| Risk | PARTIAL | Limits/locks coded and active policy stored; no actual order-cycle proof. |
| IG broker | BLOCKED | Read-only Demo component CURRENT; 0/9 authoritative size increments. |
| Shadow | BLOCKED | Worker running but 0 candidates, 0 trades, no forward trade outcomes. |
| Experimental Demo | BLOCKED | Expired ARMED programme, rejected model, 0 attempts, broker authority absent. |
| Demo Auto | BLOCKED | Engine SHADOW/new orders false; model/holdout/Shadow/economics absent. |
| Live | BLOCKED | `allow_live_trading=false`; no Demo proof. |

## 2. Current Stage

**IN:** Research and monitoring with limited Shadow infrastructure, not a trading-ready stage. Local settings load `trading_mode=demo`, `ig_environment=demo`, `allow_demo_trading=true`, `experimental_demo_enabled=true`, `allow_live_trading=false`; these grant capability only. **VF:** `app.engine_controls` is `SHADOW`, `new_orders_enabled=false`; the 15 September preopen check reports `broker submission unavailable`. The application therefore remains fail-closed at the observed control and broker gates. **NV:** effective imported settings and module versions inside every long-running service were not fingerprinted.

## 3. Changes Since Previous Audit

The 13 September review reported last PASS M1 on 11 September and around 4,047–4,363 M1 rows, versus 15 September 06:33 UTC M1 and 5,936–6,401 rows here: **IMPROVED row volume/freshness**, but not proven continuity. M5 and M15 stored row counts have grown; all current three-view continuity checks still fail. Macro component is CURRENT at 06:25 UTC with `12/12` official sources, versus unverified macro scores in the 13 September review: **IMPROVED observability**, not established point-in-time model utility. HGB latest versions remain REJECTED: **UNCHANGED blocker**. Nine rule rows refreshed at 06:24 UTC yet 0 authoritative increments: **UNCHANGED blocker**. The stale expired EUR/USD `ARMED` programme is **UNCHANGED**. Current XAU/USD latest model metrics differ from 13 September; the registry timestamp is 15 September, so it is a new evaluation, but still negative. `docs/audits/AUREX_SOURCE_VERSION_RECONCILIATION_2026-09-14.md` records 330 backend/40 frontend passing then; this audit finds 333/40 passing: **IMPROVED source test count**. Deployment attestation remains open. Audits dated 1, 2 and 7 September were not found in `docs/audits`; no comparison is claimed for them.

## 4. Platform Health

**VF:** `Get-Service -Name Aurex*` returned `AurexHealthMonitor`, `AurexHistoricalBackfill`, `AurexMarketStream`, `AurexOwnerOverviewAPI`, `AurexPlatformAPI`, `AurexTradingWorker` Running/Automatic and `AurexWeb` Stopped/Disabled. CIM path/exit-code inspection was unavailable for all, so last service failures and exact executable releases are **NV**. IIS static hosting can operate without `AurexWeb`; `infrastructure/iis/Aurex/web.config` routes `/api/*` to localhost:8010, two owner summaries to 8011 and `/health/*` to 8010. The local source config is not proof of the active IIS physical path.

**VF:** `http://127.0.0.1:8010/health/live` and `/health/ready` returned HTTP 200 (`ok`, `ready`). Unauthenticated `http://127.0.0.1:8011/api/v1/owner/readiness` returned 401. `https://holeniaurex.co.za/` could not be reached from this shell because TLS negotiation failed; public frontend accessibility, certificate state and active IIS release are **NV**, not declared failed. `/api/v1/auth/me` is protected in source (`app/main.py:208`); authenticated login/logout behavior against the deployed API was not exercised. SQL read-only connection succeeded. `app.schema_migrations` latest applied row is `058_proposal_approval_reservations_no_submission.sql`, 13 September 19:17 UTC, matching the highest local script; checksum parity, backup restore and active worker code-to-schema parity are **NV**. Latest backup row was `BACKED_UP` 15 September 00:17 UTC with `restore_verified_at_utc=null`.

**VF:** preopen component rows: IG Demo CURRENT/read-only authentication, market_feed CURRENT, risk_engine CURRENT, trading_engine CURRENT with `outcomes=4, blocked=4; broker submission unavailable`, macro CURRENT; zero open alerts. One research job FAILED and seven SUCCEEDED; latest three jobs are 10–11 September. The generic CURRENT status does not override the model, continuity or broker gates. **NV:** worker dependencies/recovery policy, repeated event-log failures, IIS release path, deployed UI/API compatibility and current scheduled-job timing were not independently attested.

## 5. Market Data

The following **VF** read-only SQL counts are completed `PASS` candles in the previous 90 days at approximately 06:33 UTC; row count is not calendar coverage. M1 entries are all `IG_LIGHTSTREAMER%`; M5/M15 include other IG/historical and research lineage. The three percentages are separate latest-window calendar-aware M5 views from `scripts/report_three_view_quality.py` without persistence: raw IG, hybrid research and Lightstreamer-only current execution. All statuses were `BLOCKED`. These are provisional diagnostics (`THREE_VIEW_M5_CALENDAR_M1_RECOVERY_V3`), not an execution-authority score.

| Market | M1 | M5 | M15 | Raw IG % | Hybrid % | Current IG execution % | Principal data issue |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| AUD/JPY | 6,343 | 2,683 | 888 | 71.43 | 90.91 | 62.43 | 800 raw / 1,052 execution missing expected M5 intervals |
| EUR/JPY | 6,344 | 2,684 | 885 | 71.36 | 90.87 | 62.29 | 802 / 1,056 gaps |
| EUR/USD | 6,294 | 20,770 | 6,910 | 63.73 | 90.95 | 58.98 | 1,138 / 1,391 gaps despite long historical M5 |
| GBP/JPY | 6,401 | 2,697 | 894 | 57.90 | 90.91 | 48.84 | 1,180 / 1,434 gaps |
| GBP/USD | 6,379 | 4,871 | 1,615 | 63.76 | 90.95 | 58.98 | 1,137 / 1,391 gaps; frozen IG M1 path 1/13 |
| Germany 40 | 6,136 | 3,970 | 1,316 | 92.27 | 97.44 | 82.48 | Session-aware gaps, including 252 execution intervals; session closed at check |
| USD/JPY | 6,310 | 4,853 | 1,606 | 67.02 | 95.19 | 61.77 | 984 / 1,238 gaps; hybrid duplicate source rows 471 |
| USD/ZAR | 6,352 | 2,691 | 891 | 56.71 | 90.91 | 47.65 | 1,213 / 1,467 gaps |
| Gold/XAU/USD | 5,936 | 2,539 | 839 | 54.75 | 87.34 | 45.62 | 1,266 / 1,520 gaps; weakest execution coverage |

In latest selected windows, raw IG had zero duplicate source timestamps; all selected raw rows had bid/ask and spread, except Germany 40 (1,316/1,336) and current execution (1,176/1,186). `historical_quality.py`, `recent_window.py` and `report_three_view_quality.py:44-110` implement session selection, bid/ask/spread and gap checks; this audit did **not** independently recompute crossed bid/ask, invalid OHLC, extreme spread, zero spreads, UTC duplicate-key collisions, slippage distributions, stale periods or M1 continuity for every market. The hybrid USD/JPY view reported 471 duplicate source rows and 1,901 spread rows in 2,000 selected candles; these need investigation. **IN:** repaired research data cannot validate IG-native fill paths. Current broker-native spread model rows range from 1,558 XAU/USD to 3,662 Germany 40 and are `CURRENT`, but stored observation count does not prove path continuity or slippage/financing calibration. `scripts/report_frozen_gbpusd_economic_bridge.py` verifies 13 prediction IDs with only one complete executable IG M1 path; 10 had no IG entry and two had path gaps. The 13 September approximate row counts increased, while a like-for-like 13 September three-view percentage baseline was unavailable: percentage trend **NV**.

## 6. Timeframe/Label Alignment

**VF:** `app/model_pipeline.py:137-163,331-363,434,559-560` trains on completed PASS M15, seven trailing features, four-bar (~60-minute) future-close direction and purges four boundary rows. The current registry rows for all seven HGB markets have `FUTURE_CLOSE_DIRECTION_4_M15_V2`. `app/model_tournament.py:16-17,89-103` also defines Logistic Regression and Random Forest challengers. `app/multi_timeframe_research.py:81-136` offers M5/M15 signal plus M1 fixed-horizon CFD-net prototype, explicitly not stop/target first-hit; `research_labels.py` has path-label research logic. No registry evidence shows an economically aligned label deployed. Source timeframe M15, feature timeframe M15, label timeframe M15, prediction horizon four M15 bars; intended position holding, stop, target and exit are execution-policy decisions rather than embedded in the classification target. **MODEL DESIGN BLOCKER:** `future_close > current_close` is not equivalent to executable bid/ask entry, spread, slippage, minimum-size, stop/target first hit and realized P&L. A stop may hit before a positive horizon close. Gross directional labels and trade economics must be joined by prediction ID with M1 IG path, fixed entry/exit policy and point-in-time features. The frozen GBP/USD bridge showed 12/13 path outcomes unavailable. Embargo beyond the four-row purge, revised-source point-in-time joins and full training/holdout contamination check are **NV**.

## 7. Model Tournament

The table is **VF** latest registered HGB evaluation per market from `app.model_versions` joined to `app.model_evaluations`. AUC measures prediction quality; PF/expectancy measure the stored trading-cost simulation, not broker-executable profitability. Expectancy and drawdown are return units. Current registry has no Logistic Regression or Random Forest promoted model evidence; family-specific MARKET×MODEL training/validation/holdout counts, precision/recall, win/loss amounts, gross/net P&L, fold stability and untouched holdout metrics are **NV**. Do not fill missing values with zero.

| Market | Train | Validate | AUC | Trades | PF | Net expectancy | Max DD | Registry |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| AUD/JPY | — | — | — | — | — | — | — | None |
| EUR/JPY | 3,171 | 1,466 | .525 | 252 | .591 | -.000151 | .0548 | REJECTED |
| EUR/USD | 53,830 | 24,848 | .525 | 144 | .014 | -.000127 | .0183 | REJECTED |
| GBP/JPY | 3,772 | 1,743 | .492 | 186 | .513 | -.000216 | .0541 | REJECTED |
| GBP/USD | 44,777 | 20,669 | .516 | 139 | .164 | -.000112 | .0166 | REJECTED |
| Germany 40 | 2,169 | 1,004 | .487 | 87 | .797 | -.000135 | .0261 | REJECTED |
| USD/JPY | 10,147 | 4,686 | .496 | 182 | .989 | -.00000764 | .0467 | REJECTED |
| USD/ZAR | — | — | — | — | — | — | — | None |
| Gold | 3,697 | 1,709 | .512 | 132 | .731 | -.000199 | .0457 | REJECTED |

`model_tournament.py:543-577` uses chronological/purged development partitions, but exact challenger matrices and untouched holdout were not extracted. Seven current HGB records cannot substitute for a complete three-family tournament. The strongest stored PF/expectancy is USD/JPY HGB, but PF <1 and expectancy <0: **no model has strongest positive after-cost evidence**. GBP/USD is closest for targeted economic-bridge research because a frozen cohort exists, not closest to trading by profit.

## 8. Trading Economics

**VF:** `app/config.py:185` rejects enabling a daily profit target; loaded `daily_profit_target_enabled=false`. `database/scripts/052_remove_daily_profit_quota_author.sql` removes the quota concept. No forced target/risk escalation was found in inspected policy code; end-to-end behavior under loss was not executed (**NV**). `model_evaluations` stores `cost_assumption_bps`, Sharpe/Sortino, PF, expectancy and drawdown; `economic_outcomes.py`, `execution_simulator.py` and `position_sizing.py` encode broker-executable paths. Yet gross vs net by immutable trade ID, actual bid/ask fills, commission, slippage, overnight financing, margin/leverage and broker-side stops/targets were not reconciled for the active models. Gross profitability is **NV**; stored after-cost performance is negative. No artificial 2% daily goal is evidence of a sensible policy, not an edge.

## 9. Market-by-Market Readiness

**VF** data percentages and HGB metrics are above; **NV** untouched holdout and actual forward trade PF for all. Below, `Data` means hybrid research / current IG execution readiness; `Research` means material exists, not that it passes; `Demo` is independent per market.

| Market | Data | Execution data | Research | Best registered model / AUC / PF / expectancy / DD | Holdout | Forward Shadow | Demo | Primary blocker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AUD/JPY | DEGRADED | BLOCKED | PARTIAL | none | NV | 0 trades | NO-GO | no model; IG gaps |
| EUR/JPY | DEGRADED | BLOCKED | PARTIAL | HGB / .525 / .591 / negative / .0548 | NV | 0 | NO-GO | negative economics |
| EUR/USD | DEGRADED | BLOCKED | PARTIAL | HGB / .525 / .014 / negative / .0183 | NV | 0 | NO-GO | negative economics; expired programme |
| GBP/JPY | DEGRADED | BLOCKED | PARTIAL | HGB / .492 / .513 / negative / .0541 | NV | 0 | NO-GO | negative economics |
| GBP/USD | DEGRADED | BLOCKED | PARTIAL | HGB / .516 / .164 / negative / .0166 | NV | 0 | NO-GO | IG M1 path 1/13; negative economics |
| Germany 40 | PARTIAL | BLOCKED | PARTIAL | HGB / .487 / .797 / negative / .0261 | NV | 0 | NO-GO | market calendar/path economics |
| USD/JPY | DEGRADED | BLOCKED | PARTIAL | HGB / .496 / .989 / negative / .0467 | NV | 0 | NO-GO | near-breakeven still loss; duplicate lineage |
| USD/ZAR | DEGRADED | BLOCKED | PARTIAL | none | NV | 0 | NO-GO | no model; weak IG continuity |
| Gold | DEGRADED | BLOCKED | PARTIAL | HGB / .512 / .731 / negative / .0457 | NV | 0 | NO-GO | weakest IG coverage |

**IN:** strongest research candidate by stored net expectancy is USD/JPY, weakest execution-data market is Gold, and GBP/USD has the most useful frozen economic diagnostic. None is close to Demo in an absolute sense. AUD/JPY and USD/ZAR remain research-only pending models; Gold/GBP-JPY/USD-ZAR need data work; every registered market needs economic redesign.

## 10. Forward Shadow

**VF:** `app/shadow_candidates`, `app/shadow_trades`, `app.order_intents` and `app.trade_proposals` each have zero rows; latest `app.forward_evidence_snapshots` per market (14–15 September) report zero closed/winning/losing Shadow trades. AUD/JPY and USD/ZAR are `RESEARCH_ONLY`; EUR/JPY, GBP/JPY and Gold `VALIDATING`; EUR/USD, GBP/USD, Germany 40 and USD/JPY `BLOCKED`. EUR/USD had a `SELL` decision with `MODEL_NOT_VALIDATED`, showing decision production does not imply approval. `shadow_trades.py:79-110` persists candidate decisions; `forward_evidence.py:91-155` snapshots Shadow counts and blockers. Observed forward trade days/opportunities/accepted/rejected hypothetical signals/wins/losses/PF/expectancy/drawdown are **0 trade evidence / NV metrics**, not backtest rows. Component `outcomes=4, blocked=4` is operational cycle evidence, not four trades. Rejected candidate persistence, feature snapshots, probabilities, executable MFE/MAE and zero-trade daily integrity were not independently confirmed from current rows; these require a future live ledger audit.

## 11. IG Broker Integration

**VF:** read-only IG Demo component CURRENT/authenticated at 06:31 UTC; recent Lightstreamer M1 in all nine markets. Latest nine `app.broker_market_rules` rows observed 06:23:59–06:24:02 UTC are `TRADEABLE`, carry min size, stop distance, margin factor and SHA-256 raw-rule provenance, yet all `size_increment_authoritative=false` with `size_increment_source=CONSERVATIVE_MINIMUM_FALLBACK`. `app/ig_execution.py:92-119` and `experimental_demo.py` gate submissions independently; broker-rule authority is a hard block even with fresh rules. IG account balance/positions, full subscribed epic map, controlled-risk rules, exact dealing hours, size-step source, margin affordability and a dry-run broker validation were **NV**. Stored margin factors (0.5% on eight; 5% USD/ZAR) are observations, not a universal leverage promise. The execution path cannot treat fallback increments as broker-native.

## 12. Risk

**VF:** active `app.experimental_risk_policies` version 1 has per-trade 0.10%, hard max 0.25%, daily loss 0.50%, programme drawdown 1.00%, one concurrent position, mandatory stop/target and no automatic resubmission. This matches the 13 September stated intended canary risk. `app/experimental_demo.py:706-866` reads risk policy, size, spread and daily-loss state; `risk_ledger.py:86` reads daily-loss/drawdown policy. Local config rejects Live and stale price threshold is 180 seconds. Current *effective execution risk* is zero because engine new orders are false and broker submission unavailable, while configured candidate risk is 0.10%. Actual margin, correlated exposure, gap/slippage, simultaneous order race and kill-switch recovery under real Demo execution are **NV**. The stored controls are necessary but cannot be marked fully ready without an end-to-end broker-cycle test.

## 13. Reconciliation

**VF:** zero `app.order_intents`, zero experimental attempts and preopen `unresolved_intents=0`: no currently unresolved local submission discrepancy was found in those tables. `ig_sync.py`/`order_lifecycle.py` implement `UNKNOWN_WORKING_ORDER`, `STALE_LOCAL_SUBMISSION`, `DUPLICATE_DEAL_REFERENCE` and `SUBMISSION_UNKNOWN` handling; `experimental_demo.py` tracks unknown/reconciliation mismatch. Code/test coverage for idempotency exists; no real order/position/partial fill was available to prove recovery, missing/unexpected broker positions, duplicate deal reference or actual P&L closure. **IN:** reconciliation is structurally partial, operational reliability **NV**.

## 14. Intelligence

**VF:** platform macro component reports CURRENT and `Official sources current:12/12; evidence inserted:0` at 06:25 UTC. Latest SQL `app.macro_currency_scores` for EUR, GBP, JPY and USD were as-of 06:25 UTC, valid through 06:55 UTC. Other required currency/asset scores, per-source publication/revision timing and a point-in-time feature join are **NV**. `intelligence.py`, `macro_intelligence.py`, `market_intelligence.py`, `tradingagents_adapter.py` and `llm_runtime.py` provide official-source and local/provider-independent research paths. AgentDecision validation and reject/neutral fallback have test coverage (`tests/test_intelligence.py`, `test_macro_intelligence.py`, `test_llm_runtime.py`); deployment-level veto behavior was not exercised. Intelligence appears to influence market decisions/filters (`forward_evidence` latest HOLD/SELL and `market_decisions`), but whether the current trained HGB feature vector incorporates it is answered **NO in source**: `model_pipeline.py` seven-feature list is price/volume only. Thus macro availability improved, but the prior economic/model blocker remains. No agent opinion can override risk, model or broker gates.

## 15. Experimental Demo

**VF:** capability settings are enabled for Demo, but engine is SHADOW/orders false. The only `app.experimental_programmes` row is EUR/USD CANARY `ARMED`, expiry 11 September 07:06 UTC, `model_status=REJECTED`, max one attempt; `app.experimental_attempts=0`. **IN:** if arming were requested today, expiry/model/risk/broker gates should stop it before submission, and no order should be allowed. Source `experimental_demo.py:118-155,556-883` checks programme, owner, model, market, price, risk, spread and sizing; `ig_execution.py:101-119` rechecks environment/feature locks. Order construction→IG submission→confirmation→reconciliation→monitoring→exit→recorded P&L cannot be demonstrated because there are zero attempts. The expired row remaining ARMED is stale administrative state and merits display/worker expiry verification, but was not automatically repaired. Do not arm.

## 16. Demo Auto Governance

**VF:** latest HGB models rejected; no registered AUD/JPY or USD/ZAR model; no approved untouched holdout found in this audit, zero forward Shadow trades, engine SHADOW/new orders false. `holdout_service.py`, `forward_promotion.py`, `readiness.py:207` and `trading_controls.py` provide governance stages. For each of nine markets, development economics and broker-rule gates fail; forward trade gate fails; holdout status is **NV**, never assumed pass; owner approval is not present. `main.py:498-529` explicitly records owner proposal intent/reservation without an IG submission. A model must be positive after costs on a frozen development policy, untouched holdout, baseline/stability gates and forward Shadow, then pass broker/risk validation before DEMO_AUTO. No approval can waive technical gates.

## 17. Frontend/UX

**VF source:** Angular has Dashboard, Markets, Trading, Research, Risk, System and Experimental Lab; `app/app.html:288-398` shows market chart, quality/model/trade panels, stale/stream state, zoom, latest-follow, failure notice and manual refresh. `app/app.ts:325-328,841-879` implements polling fallback and WebSocket market candle stream; `chart-utils.ts` merges incoming candles. Source therefore supports dynamic updates without manual chart adjustment when stream is connected. Research and execution modes have distinct source copy, and `owner_overview.py` reports Demo Auto not ready. The 12 September UI implementation document and 14 September source/version reconciliation show source simplification work, but **NV deployment:** public TLS page could not be inspected, active IIS bundle not attested, responsive behavior and actual WebSocket candle update on the deployed frontend not observed. The UI must not be declared accurate at runtime solely from source. Trading readiness labels need an authenticated deployed comparison to API readiness/model/Shadow rows.

## 18. Tests/Build

**VF:** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` returned **333 passed**, no failures or skips, two NumPy/joblib deprecation warnings (legacy artifact test). `npm test -- --watch=false` returned **40 passed in five files**; `npm run build` passed production browser/server bundles with no reported budget warnings. These verify source safety units including auth, economic outcomes, model, holdout, execution, duplicate/unknown order, risk, Shadow and proposal paths; they do not simulate real IG Demo placement/reconciliation, deployed IIS, broker-fill slippage or model profitability. One persisted research job FAILED is an operational issue, separate from current tests. No flakiness was observed in this single run; repeatability **NV**.

## 19. Security

**VF source:** `auth.py:169-227,246-301` hashes session/CSRF tokens, sets secure SameSite cookies, validates header/cookie/session/tenant and revokes session on logout. Loaded `session_cookie_secure=true`; unauthenticated owner overview returned 401. `config.py:266-273` rejects non-Demo IG and Live permission; `web.config` blocks `.env`, `.key`, `.pem`, `.sql`, sets security headers, no-store API and HTTPS rewrite. Tests `test_auth_security.py`, `test_security_configuration.py`, `test_ig_session_policy.py` passed. No secret value is printed here. **NV:** active IIS config parity, public TLS/certificate, real logout invalidation, CSRF against deployed mutation routes, tenant/owner authorization across every API, secret storage/rotation, sensitive logging, DB account privilege, debug mode and adversarial penetration review. There is no evidence from this audit to declare security fully PASS or to claim a new exploitable vulnerability. Deployment attestation is a security and reliability dependency.

## 20. Regression Analysis

| Item | Classification | Evidence and limit |
| --- | --- | --- |
| Live M1 freshness/row volume | IMPROVED | 13 Sep review vs current 90-day PASS SQL; continuity still BLOCKED. |
| Research/IG M5 continuity | UNCHANGED blocker | All 27 current three-view assessments BLOCKED; no identical prior score series. |
| Broker size-step authority | UNCHANGED | Current 0/9 authoritative. |
| HGB model economics | UNCHANGED | Seven current REJECTED with negative expectancy. |
| Macro freshness visibility | IMPROVED | Current component/score rows; feature/decision correctness NV. |
| Expired ARMED programme | UNCHANGED | EUR/USD row still ARMED after 11 Sep expiry. |
| Shadow trade evidence | UNCHANGED | Zero candidates/trades. |
| Backend source suite | IMPROVED | 330/330 14 Sep → 333/333 current; no deployment implication. |
| Public site / version assurance | UNCHANGED unknown | 14 Sep active path unverified; current TLS probe failed locally. |
| New P0 trading regression | NOT VERIFIED | No current order or control mutation; no evidence of a newly active unsafe order path. |

## 21. Consolidated Blocker Register

| ID | Severity | Area / markets | Evidence | Why it blocks / required fix | Dependency; complexity; parallel? | Exp Demo | Demo Auto |
| --- | --- | --- | --- | --- | --- | --- | --- |
| B01 | P1 | Broker / all | 0/9 authoritative increments, latest rules 06:24 UTC | Unsafe order sizing; obtain broker-native authoritative size step/provenance and verify rejection | IG dealing rule access; medium; yes | Yes | Yes |
| B02 | P1 | Model economics / seven; no models two | Registry latest seven REJECTED, all expectancy negative; AUD/JPY/USD-ZAR none | No demonstrated edge; frozen same-cohort after-cost economic redesign/validation | B03/B04; high; per market parallel | Yes | Yes |
| B03 | P1 | Labels / all trained | `model_pipeline.py:159-160`, four-M15 close target | Target not executable stop/target P&L; define/test point-in-time M1 bid/ask first-hit policy | B04; high; yes | Yes | Yes |
| B04 | P1 | Data / all | All three-view M5 statuses BLOCKED; GBP/USD IG path 1/13 | Gaps prevent valid execution evidence; preserve raw IG vs repair and obtain complete path | feed/recovery diagnosis; high; per market parallel | Yes | Yes |
| B05 | P1 | Forward Shadow / all | 0 candidates/trades, zero closed outcomes | No prospective after-cost behavior; run immutable qualifying signals/rejections and outcomes | B02/B03/B04; medium; later | Yes | Yes |
| B06 | P1 | Programme/governance / EUR/USD | Expired 11 Sep but status ARMED; model REJECTED; 0 attempts | Current owner window invalid; expiry display/fail-closed check then new governed programme only after gates | B01–B05; low; yes | Yes | No |
| B07 | P1 | Deployment / all | service paths unavailable, active IIS path NV, mutable checkout caveat | Loaded code/config not attested; versioned manifest and runtime probes before canary | release tooling; medium; yes | Yes | Yes |
| B08 | P1 | Execution/reconciliation / all | 0 intents, 0 attempts; path unit tested only | Actual fill, uncertain order, close and P&L recovery unproved; controlled Demo canary only after prior gates | B01–B07; high; later | Yes | Yes |
| B09 | P2 | Holdout/tournament / all | Challenger and untouched-holdout matrix NV | Prevents governed model promotion; extract immutable same-cohort family/market table and lock untouched holdout | B02–B04; medium; yes | Conditional | Yes |
| B10 | P2 | UI/public deployment / all | public TLS probe failed; active release NV | Owner may see stale readiness; compare deployed pages and API on authenticated session | B07; medium; yes | Operational | Operational |
| B11 | P2 | USD/JPY source quality | hybrid duplicate rows 471, spread 1,901/2,000 | Research provenance/quality uncertain; investigate source-level duplication without overwrite | B04; low; yes | Conditional | Yes |
| B12 | P2 | Backup/ops / all | latest restore verification null; one FAILED research job | Recovery/job reliability unproved; verify restore in disposable environment and job failure | operations; medium; yes | Operational | Operational |

No P0 is asserted without evidence of an active unintended order or loss path. B01–B05 are hard readiness blockers despite source gates reducing immediate hazard. Complexity estimates are relative, not delivery dates.

## 22. Prioritised Remediation Roadmap

Phase 0 **Safety/regressions:** attest loaded release/config, expired-programme behavior, zero new-order authority, unknown intents and backup restore; investigate research-job failure. Phase 1 **Data:** freeze three-view source-aware per-market quality and IG M1 path continuity; diagnose/fix gaps and USD/JPY duplicate lineage without blending repaired research into execution data. Phase 2 **Alignment:** specify M1 bid/ask entry/stop/target/first-hit/holding/financing label and point-in-time feature cutoff; test exact prediction-ID trade bridges. Phase 3 **Economics:** pre-register same-cohort three-family tournament per market, gross/net decomposition, fold/regime tests, baseline and untouched holdout; promote only positive durable after-cost candidates. Phase 4 **Shadow:** accumulate immutable opportunities, accepted/rejected signals, zero-trade days and prospective outcomes with bid/ask MFE/MAE. Phase 5 **Broker/execution:** obtain authoritative IG size increments and full dealing rules, validate margin/stops/market sessions, idempotency/reconciliation and worst-case order handling. Phase 6 **Experimental Demo:** after phases 0–5, a new limited owner-approved in-window programme and minimum-risk canary with full reconciliation/P&L review. Phase 7 **Demo Auto:** require holdout, forward stability, risk and broker proof and Demo canary recovery before unattended activation. Phase 8 **UI/operations:** attest public frontend/TLS/API parity, chart WebSocket/live state, responsive mode labels and incident alerts.

Parallel work now: per-market raw/hybrid/IG quality analysis; broker-rule source authority investigation; point-in-time economic label specification; release attestation; frontend deployed validation; backup/job review. No trade gate should be removed merely to accelerate a demo order. Research-source repair need not be required for a market that independently has a complete IG-native execution cohort; for current nine, no such complete market passed the three-view check. A missing gate is frozen prediction-ID-to-executable-outcome comparability including first-hit order, real CFD costs and sufficient IG path coverage.

## 23. GO/NO-GO Matrix

`CONDITIONAL` here means useful work can continue but a gate is not proven; it is **not** order authorization. Broker is NO-GO for every market because authority is absent. Holdout and true Shadow trade evidence are NO-GO for promotion because none was established.

| Market | Research | Model | Holdout | Shadow | Risk | Broker | Exp Demo | Demo Auto | Decision / reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AUD/JPY | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: no model, IG gaps, broker rules |
| EUR/JPY | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: losing model, gaps, broker rules |
| EUR/USD | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: losing model, expired programme |
| GBP/JPY | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: losing model, gaps |
| GBP/USD | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: IG path 1/13, losing model |
| Germany 40 | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: session data/economics |
| USD/JPY | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: PF <1, source duplicates |
| USD/ZAR | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: no model, weak continuity |
| Gold | CONDITIONAL | NO-GO | NO-GO | NO-GO | CONDITIONAL | NO-GO | NO-GO | NO-GO | NO-GO: weakest IG continuity |

## 24. Final Recommendation and direct answers

1. **Stage:** operational research/monitoring; limited Shadow infrastructure, no trade-ready market.
2. **Improved since 13 September:** live M1 freshness/row volume, macro-score observability and backend source test count.
3. **Regressed:** no verified new trading regression. Continued stale ARMED state, broker-rule non-authority and M5 gaps are unchanged; public TLS/deployed frontend remains unverified from this shell.
4. **Top five blockers:** broker increment authority (B01), negative/no models (B02), economically mismatched label (B03), IG continuity/paths (B04), absent forward Shadow outcomes (B05).
5. **Closest market:** no safely tradable market. USD/JPY has the least negative registered expectancy but fails economics/data; GBP/USD has the strongest frozen path diagnostic but only 1/13 executable outcomes.
6. **Strongest after-cost model:** none profitable; USD/JPY HGB is closest to break-even (PF .989, expectancy -.00000764).
7. **Alignment:** no; active M15 future-close label is a model-design blocker.
8. **Forward Shadow sufficient:** no, zero candidate/trade rows and zero closed outcomes.
9. **IG Demo technically ready:** read-only access/feed yes; order readiness no, 0/9 authoritative increments and no executed canary.
10. **Risk ready:** policy/locks partial; actual order safety and effective size not validated.
11. **Reconciliation ready:** code/unit tests partial; real broker mismatch/fill/recovery unproved.
12. **Frontend accurate:** source has readiness/streaming cues; deployed public UI/API parity NV.
13. **Experimental Demo now:** NO-GO; do not arm. Expired programme, rejected model, gaps, rules and Shadow evidence block.
14. **Demo Auto now:** NO-GO; engine SHADOW/orders false, economics/holdout/Shadow/broker gates unmet.
15. **Before first governed demo order:** attest deployed release and fail-closed state; obtain authoritative IG rules; build continuous broker-native path and aligned cost-aware same-ID labels; validate a positive stable model and untouched holdout; collect forward Shadow; revalidate risk/account/market and create a fresh narrowly capped owner-approved programme; then one canary with confirmation, reconciliation, exit and P&L review. Owner approval is last governance authority, never a failed-gate override.
16. **Parallel now:** source-aware data, IG rule authority, label design, release/UX attestation and backup/job review.
17. **Unnecessary gates:** none proven to be needlessly delaying a safe demo trade; a complete IG-native cohort could make hybrid repair irrelevant for that market, but no current market passes.
18. **Missing gates:** explicit frozen bid/ask first-hit economically aligned label-to-outcome bridge, IG path sufficiency, actual broker-rule authority, real-order reconciliation/recovery and deployed-version attestation.

Audit inputs: current source in `services/platform-api/app`, `apps/web/src/app`, `infrastructure/iis/Aurex/web.config`; read-only scripts named above; SQL tables and timestamped query results described above; `docs/audits/AUREX_HOLISTIC_PLATFORM_REVIEW_2026-09-13.md`, `AUREX_GBPUSD_FROZEN_ECONOMIC_BRIDGE_2026-09-14.md`, `AUREX_SOURCE_VERSION_RECONCILIATION_2026-09-14.md`, `AUREX_API_RELEASE_GATE_EVIDENCE_2026-09-14.md`. Earlier reports were comparison evidence, never promoted to current fact.
