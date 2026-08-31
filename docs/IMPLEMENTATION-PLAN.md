# Forex SaaS implementation plan

## Authoritative current status — 31 August 2026

This section is the current source of truth. The numbered delivery record below
is retained as implementation history and must not be read as current readiness.
Older status statements are indexed in
`docs/archive/IMPLEMENTATION-HISTORY-2026-08.md`.

- Owner-only localhost platform, SQL, IG streaming, API, web and background
  workers are operational. Live trading and third-party funds remain absent.
- Historical/training quality passes for all four enabled markets. Provider
  boundaries are explicit and no missing prices are manufactured.
- Selective Research V4 now binds target, lineage, tournament winner, calibrated
  multiclass artifact and single-use holdout evidence. No lineage or holdout is
  automatically created or consumed; those are owner research decisions.
- Model approval remains `0/4`. Each market must independently pass its exact
  development tournament, untouched holdout and frozen forward-shadow policy.
- Drift snapshot writers and alerts are active. Until a model is approved they
  correctly record `MODEL_UNAVAILABLE`, not fabricated drift scores.
- Point-in-time economic-event vintages are stored when scheduled events are
  retrieved. Event/risk-on regimes remain disabled until sufficient audited
  vintages exist.
- Quarantine and bounded recovery evidence is available through authenticated
  API and Research UI views. Recovery remains session-aware and synthetic fills
  remain prohibited.
- Authentication throttling and account lockout are implemented. MFA enrollment
  and verification, HTTPS, secure cookies and a real hash pepper remain mandatory
  before a public-domain deployment.
- Least-privilege SQL, encrypted off-server backup and retention operations are
  supplied as guarded administrator procedures. They are not considered active
  until separately configured, tested and evidenced on this server.
- Migration 031 removes the informational 2% daily objective, starts configurable
  profit protection at 0.5%, and calculates risk returns in the IG account's
  native currency. ZAR remains reporting-only, so exchange-rate movement cannot
  activate a trading-risk control.

### Current implementation order

1. Owner selects a predeclared target and hypothesis per market, reserves an
   immutable lineage, then runs a fresh lineage-bound boundary audit.
2. Run the V4 development tournament and freeze only its exact passing winner.
3. Consume the frozen candidate's untouched holdout once; owner approval can
   enable only forward shadow.
4. Accumulate the required frozen forward-shadow observations and monitor model,
   feature and cost drift.
5. Consider one non-retrying minimum-size IG Demo plumbing test only when that
   specific market passes every gate. No live path is enabled.

## 1. Decisions and boundaries

- Build a web platform, not a web wrapper around the existing bot.
- Use Angular for the UI, Python/FastAPI for backend services, and SQL Server
  Express for transactional storage.
- Initially support one owner, one IG demo connection, and localhost access.
- Design tenant boundaries into the schema and API now, but do not onboard other
  users or execute for third parties before regulatory and broker review.
- Keep live trading disabled. Profitability must be demonstrated using reproducible
  backtests and sustained demo forward testing; profit is not guaranteed.
- Retain `ig-ai-forex-bot` as a reference until each required component has been
  migrated and verified.

## 2. Server coexistence rules

The server already hosts other applications. The platform must therefore:

- use a dedicated database, SQL login, application directories, logs, and service
  identities;
- use configurable ports and bind to `127.0.0.1` during local development;
- never use SQL Server `sa`, a shared login, `db_owner`, or a hard-coded connection
  string;
- never change the SQL instance TCP port, firewall, IIS bindings, or global PATH as
  part of ordinary application setup;
- inventory a port immediately before starting a service, for example:
  `Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess`;
- start with UI port `4210` and API port `8010`, but treat both as configurable;
- use database migrations and never modify another application's database.

SQL Server Express commonly uses a named instance such as `localhost\\SQLEXPRESS`.
Confirm the actual instance name and whether SQL authentication (mixed mode) is
enabled with the server administrator. Enabling mixed mode or restarting the SQL
service is an administrator operation and can affect other applications.

## 3. Target structure

```text
Browser (Angular on 127.0.0.1:4210)
        |
        | HTTP/JSON
        v
Platform API (FastAPI on 127.0.0.1:8010)
        |                         |
        v                         v
SQL Server Express          Trading engine worker
ForexSaas                   (no public listener)
                                  |
                                  v
                            IG demo API
```

The Angular application never connects directly to SQL Server or IG. The trading
engine never accepts model output as an executable order without independent risk
approval and a persisted order intent.

## 4. Delivery phases

### Phase 0 — Foundation

- Record architecture and safety decisions.
- Create the repository boundaries shown above.
- Provision a dedicated SQL database and least-privilege login.
- Create local configuration templates; keep real secrets outside source control.
- Add health checks, structured logs, correlation IDs, and migration tooling.
- Confirm ports before each local run.

Exit gate: UI, API, and database connectivity work locally without touching other
server applications.

### Phase 1 — Owner-only application

- Add one owner account with secure password hashing and role-based authorization.
- Build dashboard, settings, broker connection status, risk configuration, signals,
  orders, positions, and audit views.
- Store broker credentials in a secret store or OS-protected secret mechanism; SQL
  stores only a secret reference.
- Import historical data and reporting concepts from the legacy bot, not its
  operational SQLite/CSV state.

Exit gate: the owner can sign in and inspect demo data; no order can be placed.

### Phase 2 — Trading engine hardening

- Define broker and market-data interfaces; implement IG demo first.
- Implement risk-based position sizing, exposure limits, daily-loss limits, stale
  data checks, spread limits, and a kill switch.
- Persist order intent before broker submission.
- Implement an idempotent order state machine and broker reconciliation worker.
- Version strategies and models and record the exact versions on every signal.

Exit gate: automated tests prove that duplicate requests, timeouts, restarts, and
risk failures cannot silently create or lose track of orders.

### Phase 3 — Demo execution and validation

- Enable only explicit IG demo execution.
- Add backtesting with spread, slippage, funding, and realistic data splits.
- Run sustained forward testing and publish factual risk/performance metrics.
- Add monitoring, alerting, backups, restore tests, and operational runbooks.

Exit gate: agreed validation thresholds and an observation period are met, with no
unresolved reconciliation or security issues.

### Phase 4 — SaaS readiness (deferred)

- Complete South African regulatory/legal assessment and broker/API approval.
- Implement true tenant isolation, invitations, subscriptions, consent records,
  privacy controls, support workflows, and incident response.
- Use a production secret manager and independently reviewed security controls.
- Reassess whether SQL Server Express limits and single-server hosting remain
  appropriate.

Exit gate: written regulatory, broker, security, and operational approvals. Only
then plan controlled live trading or third-party onboarding.

## 5. Angular creation command

This project is pinned to Angular 21. Run from `C:\Projects\Forex`:

```powershell
npx @angular/cli@21 new web `
  --directory apps/web `
  --routing `
  --style=scss `
  --strict `
  --standalone `
  --skip-git `
  --package-manager=npm
```

Do not replace `@21` with `@latest`, because that may scaffold Angular 22 or a later
major release. After generation, verify that all `@angular/*` packages use major
version 21, commit `package-lock.json`, and use `npm ci`; future builds should use
the recorded CLI/package versions. Start locally on the reserved candidate port:

```powershell
Set-Location C:\Projects\Forex\apps\web
npm start -- --host 127.0.0.1 --port 4210
```

Before starting, confirm that `4210` is free. Do not expose the Angular development
server to the network.

## 6. Initial API setup command (next implementation step)

```powershell
Set-Location C:\Projects\Forex\services\platform-api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi "uvicorn[standard]" sqlalchemy alembic pyodbc pydantic-settings
```

Pin the resolved dependencies in the project before repeatable deployment. The API
should bind to `127.0.0.1:8010` in development and allow only the exact Angular
origin, `http://127.0.0.1:4210` (plus `http://localhost:4210` if deliberately used).

## 7. Configuration contract

Use environment variables or an untracked local settings file:

```dotenv
APP_ENV=development
API_HOST=127.0.0.1
API_PORT=8010
WEB_ORIGIN=http://127.0.0.1:4210
SQL_SERVER=localhost\SQLEXPRESS
SQL_DATABASE=ForexSaas
SQL_USERNAME=ForexSaasApp
SQL_PASSWORD=replace-locally
TRADING_MODE=disabled
BROKER_ENVIRONMENT=demo
```

The connection password must not appear in Git, Angular configuration, logs, URLs,
or exception responses.

## 8. Immediate backlog

1. Confirm the SQL instance name, authentication mode, database file location, and
   availability of ports 4210/8010.
2. Open the pure T-SQL provisioning script in SQL Server Management Studio,
   replace its password placeholder with a unique strong password, run it through
   a protected administrator workflow, and do not save the real password in Git.
3. Generate Angular and verify its default tests/build.
4. Scaffold FastAPI with `/health/live` and `/health/ready` endpoints.
5. Add Alembic migrations for owner identity, tenant, broker connection metadata,
   audit log, strategies, signals, risk decisions, order intents, and order events.
6. Build read-only dashboard flows before enabling any demo order execution.

## 9. Current implementation status (26 August 2026)

- Phase 0 is complete: Angular 21, FastAPI, SQL connectivity, migrations, health
  checks, correlation IDs, structured logs, and localhost-only development ports
  are in place.
- Phase 1 exit gate is complete: owner authentication works, IG demo account data
  is tenant-scoped and persisted, scheduled account/position reconciliation is
  implemented, and the owner UI covers market data, models, strategies, orders,
  positions, trade history, risk, reconciliation, system status and research.
- Phase 2 is in progress: the market, candle, strategy/model version, signal,
  risk decision, order intent, and engine-control schema is provisioned. Three
  legacy model artifacts are registered but deliberately marked `REGISTERED`, not
  `VALIDATED`, because their original validation evidence is unavailable.
- Chronological model training now persists its non-overlapping training and
  validation windows, row counts, AUC threshold, result, artifact checksum, and
  immutable model version. Insufficient datasets are blocked; sub-threshold
  candidates are stored as `REJECTED`.
- The shadow engine creates deterministic signals, independent persisted risk
  decisions, and idempotent `WOULD_SUBMIT` intents. Its hard blocks include an
  unvalidated model, stale candles, daily drawdown, exposure limits, unresolved
  reconciliation, missing broker rules, and sizes below the broker minimum.
- The engine is set to `SHADOW`; `new_orders_enabled` is false. Live trading is
  unsupported by design.
- A tenant-scoped `GET /api/v1/trading/readiness` gate reports every known blocker
  without enabling execution. The Angular header and system-status card consume
  this result instead of displaying a hard-coded execution badge.
- Demo execution requires both `TRADING_MODE=demo` and
  `ALLOW_DEMO_TRADING=true`; live environment or live-trading settings fail
  configuration validation. Demo execution remains fail-closed by default.
- The T-SQL migration runner records migration checksums in
  `app.schema_migrations` and rejects changes to an already recorded migration.
- IG Demo broker rules are synchronized for EUR/USD, GBP/USD, USD/JPY and Germany 40 using
  broker-provided minimum sizes, stop distances, scaling factors, pip values and
  quote-currency-to-ZAR rates. Unsupported or incomplete values block risk.
- `AurexTradingWorker` runs continuously as an automatic Windows service. It
  refreshes dealing rules, checks chronological training eligibility and runs
  idempotent shadow cycles. It has no broker order-submission capability.
- Model promotion still requires at least 2,000 feature-complete M15 rows and the
  complete enhanced validation gate. All four markets now exceed the row floor,
  but their cost-aware chronological candidates are `REJECTED`; data quantity no
  longer appears as the primary blocker.
- Migration 010 adds append-only order-intent events, a South African daily risk
  ledger, reconciliation issues, and explicit position origin/order linkage.
- Shadow intents now transition through `CREATED`, `RISK_APPROVED`, then terminal
  `WOULD_SUBMIT`; unsafe state skips and attempts to submit an existing shadow
  intent are rejected.
- Broker positions without an Aurex order intent are recorded as
  `RECONCILIATION_REQUIRED`, create a blocking issue, and cannot silently appear
  as platform-managed positions.
- The dashboard now reads tenant-scoped order intents, daily risk status and
  reconciliation state from authenticated APIs. No static sample orders or
  reconciliation results are displayed.
- Migration 011 adds append-only engine-control events, tenant ownership for
  strategies, and broker-sourced execution metadata such as dealing currency,
  expiry, force-open capability and market-order preference.
- Owner controls now support only `PAUSE` and `RESUME_SHADOW`; there is no UI or
  API control that can enable orders or live trading. Strategy `ACTIVE`/`PAUSED`
  changes are tenant-scoped, confirmed in the UI and audited.
- A separate IG Demo execution adapter implements one-shot acknowledgement and
  confirmation handling behind all readiness, account, mode and intent gates.
  It is deliberately disconnected from the active worker until models validate
  and the complete readiness gate passes.
- Account reconciliation can match a broker position back to its deterministic
  Aurex client reference, advance uncertain intent states to `OPEN`, link the
  position, and resolve the reconciliation issue without resubmitting.

### Demo Trading Operational gate

Before changing the engine from `SHADOW` to `DEMO_AUTO`, all of the following must
be evidenced:

1. IG demo historical M15 candles are persisted and fresh for each enabled market.
2. Models are retrained with chronological train/validation splits and meet the
   recorded acceptance threshold; failed models remain rejected.
3. Risk tests cover daily loss, stale data, unresolved reconciliation, duplicate
   signals/intents, exposure limits, broker minimum size, and mandatory stops.
4. Shadow signals and `WOULD_SUBMIT` intents run without duplicates or unexplained
   reconciliation states.
5. One deliberately small, manually enabled IG demo order is submitted with a
   stop and take-profit, confirmed, persisted, and reconciled after restart.

Profit is never an activation gate that can be guaranteed. Next-week evaluation
will report out-of-sample and forward-demo return, drawdown, win rate, profit
factor, costs, sample size, and model/data versions. A losing or statistically
weak result blocks promotion and triggers iteration; it is not relabelled as a
successful model.

### Market-data acquisition policy

- Bootstrap at most one weekday (96 M15 candles per enabled market) through the
  historical REST endpoint.
- Thereafter use IG Lightstreamer `CHART:<epic>:5MINUTE` subscriptions, persist
  only completed M5 candles, and deterministically aggregate three contiguous M5
  candles into each completed M15 candle.
- Do not poll the historical endpoint as the normal market feed and do not use it
  to compensate for an unhealthy streaming connection.
- The market stream runs as a separate worker (`scripts/run_market_stream.py`) so
  Angular/API reloads cannot create duplicate subscriptions.
- Migration 012 adds persisted M5/M15 quality audits and market-specific execution
  states. Historical backfill is explicitly page-budgeted, idempotent and stops
  subsequent markets on IG quota exhaustion.
- Automatic demo readiness is now evaluated per market. One validated market may
  eventually progress through controlled deployment while other markets remain
  in `SHADOW`; the execution adapter independently requires the selected market
  to be ready.
- Preferred daily profit is reporting-only. Daily loss, intraday drawdown,
  consecutive-loss, profit give-back and daily profit-lock states are binding
  controls and can only preserve, reduce or stop new-trade risk.
- Migration 013 adds cost-aware expanding walk-forward model evidence, four
  baseline comparisons, and an isolated hypothetical shadow-trade lifecycle.
  AUC alone can no longer promote a model. Shadow trades include estimated costs,
  conservative intrabar stop/target resolution, mark-to-market P/L and append-only
  events, with no broker submission path.

### Authoritative market inventory

| Symbol | Asset class | IG Demo instrument | Epic | Model status | Execution mode |
|---|---|---|---|---|---|
| EURUSD | FX | EUR/USD Cash CFD | `CS.D.EURUSD.CFD.IP` | REJECTED | SHADOW |
| GBPUSD | FX | GBP/USD Cash CFD | `CS.D.GBPUSD.CFD.IP` | REJECTED | SHADOW |
| USDJPY | FX | USD/JPY Cash CFD | `CS.D.USDJPY.CFD.IP` | REJECTED | SHADOW |
| GERMANY40 | INDEX | Germany 40 Cash (E1) | `IX.D.DAX.BMU.IP` | REJECTED | SHADOW |

Every market owns a separate model artifact and readiness state. Model methodology
may be shared, but an FX artifact is never reused to authorize Germany 40.

At the 26 August 2026 strategy-evidence checkpoint, feature-complete counts were
61,435 for EUR/USD, 50,983 for GBP/USD, 10,997 for USD/JPY and 2,225 for Germany
40. These are moving observations; authenticated research/readiness APIs and the
database remain authoritative as IG ingestion continues.

## 10. Operational hardening and unified replay milestone

The ordered milestone is:

1. Run market ingestion, trading intelligence, API and health monitoring as
   independently recoverable localhost-only Windows services.
2. Create scheduled SQL backups, record their checksums, and verify restoration
   into a disposable, explicitly named validation database.
3. Persist market calendars and distinguish Germany 40 regular cash-session
   evidence from IG extended-hours tradeability.
4. Preserve bid and ask OHLC values, observed spread and realistic cost inputs;
   midpoint-only history is retained but marked as incomplete cost evidence.
5. Use one deterministic replay core for feature calculation, signal evidence,
   risk sizing, conservative fills and trade lifecycle events. Diagnostic replay
   without a validated model is non-promotable and cannot enable execution.
6. Add calibration, feature drift and market-regime evidence to model promotion.
7. Surface market-specific blockers and explanations in the owner UI.

Implementation status:

- Items 1–5 and 7 are implemented. Four automatic Windows services are running;
  daily backups and weekly restore tests run under `SYSTEM`; checksum backup,
  disposable restore and `DBCC CHECKDB` have passed.
- Migration 018 seeds Deutsche Börse's official 2026 Xetra non-trading dates.
  New bid/ask stream evidence is persisted for every enabled market, including
  spread and regular-session flags.
- Replay version `UNIFIED_V3_REJECTED_MODEL_DIAGNOSTICS` uses executable side prices where
  available, records spread attribution without double charging it, uses an
  explicit fallback for midpoint-only history, and persists slippage, funding,
  fills and lifecycle events. Diagnostic runs remain non-promotable.
- Item 6 is implemented in the validator: promotion requires cost-aware expanding
  walk-forward evidence, baseline outperformance, calibration error at most 0.20,
  feature drift at most 1.0 and at least 50% regime coverage, in addition to the
  existing sample, AUC, trade, expectancy, profit-factor and drawdown gates.
- The realistic shadow lifecycle shares the same conservative candle resolver and
  executable-price cost convention. It still has no automatic broker submission
  path.

The 2,000 feature-complete M15 evidence floor remains unchanged. A controlled
minimum-size IG Demo order remains conditional on one market passing every gate;
this milestone does not authorize an order merely to demonstrate activity.

SaaS onboarding, live trading, third-party funds, subscriptions and public
exposure remain deferred until regulatory, broker, privacy and security approval.

## 11. Sustained accumulation and forward shadow evidence

- Migration 020 adds an immutable, market-specific forward-evidence snapshot for
  each newly completed regular-session M15 candle.
- Each snapshot records retained history coverage, feature-complete progress,
  spread evidence, quality, model state, audited market decision, execution mode,
  daily risk status, reconciliation status and hypothetical shadow lifecycle P/L.
- The continuous trading worker captures evidence every 15 minutes and runs a
  session-aware quality audit hourly. Duplicate worker cycles cannot duplicate a
  market/candle observation.
- `ACCUMULATING` means the evidence floor has not been met. `FORWARD_SHADOW` is
  possible only after a validated market model exists. `DEMO_TEST_READY` remains
  conditional on every market-specific and platform gate.
- EUR/USD and GBP/USD regular-session M15 continuity currently pass. Germany 40
  passes for its available regular-session interval. USD/JPY retains one genuine
  missing M15 interval and is correctly marked `WARN`; one bounded 500-point
  backfill request returned only ten newest candles and was not repeatedly retried.
- Configuration and the manual training command now both enforce the full 2,000
  feature-row floor. A lower manual value cannot promote a model.

## 12. Forward-shadow promotion and controlled IG Demo execution

- Migration 021 adds a versioned per-tenant promotion policy. The initial
  fail-closed policy requires at least 30 closed shadow trades across 10 South
  African trading days, profit factor of at least 1.10, positive cost-aware
  expectancy, maximum drawdown of 3%, no more than four consecutive losses and
  complete entry-cost evidence.
- Promotion is evaluated independently for the latest validated model in each
  market. Trades from legacy, rejected or retired artifacts cannot contribute.
- `DEMO_TEST_READY` now requires the promotion policy in addition to data quality,
  validated model, fresh prices, current broker rules, audited macro decision,
  risk, reconciliation, platform and execution-mode gates.
- The one-off IG Demo orchestrator accepts only a fresh `RISK_APPROVED` intent at
  the broker minimum size. It commits a unique execution attempt and changes the
  intent to `SUBMITTING` before the network call. The IG POST is issued at most
  once; uncertain outcomes enter reconciliation and are never resubmitted.
- The background worker still has no broker-order capability. One-off submission
  also requires an owner, the exact acknowledgement phrase, `DEMO_AUTO`, and the
  separate environment opt-in.

The opt-in remains disabled, no market currently has a validated model, and no
IG order was submitted while implementing this stage.

## 13. Source-aware historical backfill

- Migration 022 adds a checksum and row-count audit ledger for external history.
- The Dukascopy importer accepts only mapped, bid-side, UTC-aligned M5 CSV files;
  validates OHLC envelopes and timestamps; and builds M15 only from complete
  three-candle groups.
- Imported rows retain `DUKASCOPY_BID_M5` or `DUKASCOPY_BID_M15` provenance.
  Ask and observed-spread fields remain null, so validators and replay use the
  explicit conservative fallback cost rather than fabricated executable prices.
- Existing IG rows take precedence at overlapping market/timeframe/timestamps,
  and checksum plus unique-key controls make reruns idempotent.
- Feature generation is segmented at data gaps, preventing weekend, session or
  missing-candle leakage into rolling indicators and labels.
- Model retraining requires at least 96 new feature-complete M15 rows after the
  prior evaluation, avoiding repeated full-history retraining every worker cycle.
- Audited, bid-only history now exists for all four markets: EUR/USD from January
  2024 through August 2026, GBP/USD through February 2026, Germany 40 through July
  2024 and USD/JPY through June 2024. Bounded files created before a provider 429
  were relabelled to their truthful coverage before import.
- Cost-aware, three-window chronological evaluation rejected every resulting
  model. None beat its required baseline with positive expectancy and acceptable
  supporting evidence, so every market remains outside demo readiness while IG
  streaming continues and retraining waits for 96 new feature-complete M15 rows.

This backfill accelerates statistical testing only. It does not lower the 2,000
feature-row floor, count as forward-shadow evidence, or enable any broker order.

## 14. Strategy evidence and research

- Migration 023 separates provider-segment research quality from current
  execution quality. Dukascopy and IG M5/M15 segments record expected/actual
  rows, completeness, gaps, purpose and provenance independently.
- Cross-provider gaps are explicitly classified. A declared Dukascopy-to-IG
  boundary is `KNOWN_GAP`, resets features and trades, and is not itself an
  execution failure. Recent unexpected IG gaps remain execution-blocking.
- Per-market execution snapshots independently gate M5/M15, bid, ask, spread,
  broker-rule and market-session freshness. The system remains fail-closed.
- Versioned IG empirical cost models persist overall, session, weekday and
  quarter-hour spread distributions. Research replay supports optimistic (p50),
  normal (p75) and stressed (p95) spread evidence.
- Diagnostic replay reuses the unified replay engine, may explicitly inspect the
  latest rejected artifact, is always non-promotable and force-closes at segment
  boundaries. It records cost, MAE/MFE, R multiple, holding time, confidence,
  deterministic session and explainable trend/volatility regimes.
- Every deliberate diagnostic or research retrain is immutable in the experiment
  registry with strategy, feature, label, model, regime, cost and configuration
  versions. Scheduled retraining still requires 96 new M15 observations;
  research retraining requires an explicit material-change identifier.
- Experimental economic labels support `LONG_OPPORTUNITY`, `SHORT_OPPORTUNITY`
  and `NO_TRADE` using future path, costs, minimum edge and adverse-excursion
  limits. They remain research-only and never enter the feature matrix.
- The authenticated Angular `/research` page exposes real quality, cost,
  experiment and diagnostic evidence. It has no execution capability.

Holdout discipline is mandatory: TRAIN fits, VALIDATION selects, final HOLDOUT is
used once for offline acceptance, and FORWARD_SHADOW is unseen real-time evidence.
No result in this phase changes `SHADOW`, enables demo opt-in or submits an order.

Implementation checkpoint (26 August 2026): provider-quality evidence,
empirical cost models, immutable experiments, explainable regimes, rejected-model
diagnostics and the research UI are implemented. The first full four-market
diagnostic is recorded in `STRATEGY-EVIDENCE-REPORT-2026-08-26.md`. True frozen
candidate holdout evaluation and forward-shadow evidence remain outstanding;
therefore every market remains blocked.

## 15. Frozen-candidate holdout enforcement

- Migration 024 adds immutable frozen candidates and a one-evaluation-per-candidate
  ledger. Database constraints enforce chronological periods, evidence floors,
  artifact presence and single-use evaluation.
- `FROZEN_HOLDOUT_V1` trains only on pre-holdout data, refits a fixed candidate
  after development validation, and checksums the development data, reserved
  holdout and artifact.
- Final evaluation uses the fixed model, features, thresholds, empirical cost
  version and gates. It records AUC, Brier score, calibration, drift, regimes,
  baselines, trades, expectancy, profit factor and drawdown.
- Candidate artifacts never enter `model_versions`. Even `HOLDOUT_PASSED` cannot
  promote a market or enable forward shadow automatically.
- The authenticated research page and CLI expose reservation status and require
  an explicit one-use acknowledgement for evaluation.

The first Germany 40 reservation check is correctly `DATA_BLOCKED`: 2,006
feature-complete development rows pass the 2,000 floor, but only 234 independent
holdout rows are available against the 500-row floor. No candidate artifact was
created and the holdout was not consumed. IG streaming must continue before the
same policy is checked again.

## 16. Daily evidence reporting and research reliability

- The authenticated research endpoints encode database Decimal and UUID values
  through FastAPI's JSON-safe encoder, so evidence payloads load correctly in
  the Angular research page.
- Migration 025 adds an exact-once, per-tenant/SAST-date delivery ledger for
  owner progress reports.
- `AurexHealthMonitor` sends the report after 18:00 SAST using the configured
  Google SMTP account. Late service starts still send that day's report, while
  the ledger prevents repeated emails on every health cycle.
- The report uses current database evidence for training, provider-specific
  candle collection, model/quality blockers, shadow activity, demo attempts,
  holdout progress and recommended safe improvements.
- SMTP failures are recorded and are never retried automatically. A dedicated
  operator command explicitly retries only today's failed audited row.
- Report generation and delivery cannot alter trading modes, promote a model,
  enable demo opt-in or submit an order.

## 17. Owner-web operational close-out

- The Angular 21 production SSR bundle runs as the automatic `AurexWeb` Windows
  service on `127.0.0.1:4210`; the development server is no longer required.
- The service has a dedicated `/_health` endpoint, rotating output/error logs,
  restart throttling and localhost-only binding.
- Browser API traffic remains same-origin. The web process forwards only `/api`
  and `/health` to FastAPI on `127.0.0.1:8010` and returns a bounded 502 response
  when the API is unavailable.
- Angular SSR permits only `127.0.0.1` and `localhost` hostnames. A future domain
  must be deliberately allow-listed when an HTTPS reverse proxy is configured.
- `AurexHealthMonitor` now checks both the API and owner-web health endpoints.

### Remaining work is gated, not unfinished plumbing

- **Evidence-dependent:** a model must pass development validation, Germany 40
  must accumulate the independent holdout floor, a frozen candidate must pass
  its one-use holdout, and that market must then accumulate the sustained
  forward-shadow promotion sample. These results cannot be manufactured in code.
- **Conditionally executable:** the one-off, minimum-size IG Demo orchestrator is
  implemented but stays opt-in disabled until one market passes every gate.
- **External/deferred:** domain/HTTPS exposure, SaaS onboarding, subscriptions,
  live trading and third-party funds require the previously defined broker,
  regulatory, privacy and security work.

All owner-only localhost platform plumbing is therefore implemented. Runtime
evidence collection and research iteration continue without lowering any gate.

## 18. Operational assurance projection

- Authenticated endpoint `GET /api/v1/operations/status` consolidates live
  component state, open persisted alerts, recent checksum backups, the latest
  successful restore test and the tenant's daily-email delivery ledger.
- Local backup paths are reduced to filenames before reaching the browser.
- The owner dashboard exposes this evidence under **Operational assurance** and
  clearly distinguishes the newest daily backup from the newest verified restore.
- The projection is read-only and reports the enforced trading safety state; it
  cannot change a service, retry an email, restore a database or enable trading.

## 19. Dynamic owner-interface cleanup

- Authenticated `GET /api/v1/markets` is now the UI authority for enabled market
  names, asset classes, currencies, price precision, calendars, timeframes and
  supported history periods. Market selectors no longer duplicate that inventory.
- The top-right identity comes from the authenticated `/api/v1/auth/me` session;
  no owner name or role is embedded in the dashboard template.
- Portfolio chart dates and ZAR axis values are derived from account-snapshot
  timestamps and equity values. Empty or single-snapshot series remain explicit.
- Component success/error marks reflect API status instead of always displaying a
  success tick. Position descriptions use backend instrument metadata, including
  Germany 40 as an index CFD.
- Decorative metric-menu buttons and permanently disabled position-row buttons
  were removed. Every remaining button either invokes an audited API operation or
  performs an explicit local interaction such as navigation, selection or zoom.
- The candlestick trendline and its legend were removed. Candles, fixed axes,
  panning and zoom remain, with no derived directional overlay.

## 20. Trustworthy model challenger research

- Migration 026 registers `MODEL_TOURNAMENT` as a separate immutable research
  experiment type. Tournament results cannot create artifacts, change a model
  status, consume holdout data, enable execution or submit an order.
- Expanding walk-forward training now purges the four M15 rows immediately before
  every validation window. This matches the four-candle label horizon and prevents
  boundary labels from reading prices inside validation.
- The first local tournament compares deterministic logistic regression, random
  forest and Aurex histogram gradient boosting on identical features, folds,
  fixed HOLD thresholds, empirical/fallback costs, regimes and baselines.
- Selection is based on complete development gates, cross-window stability, net
  expectancy, profit factor, AUC and then lower complexity. A leaderboard winner
  is only a research leader; it is not a promoted model.
- Any interval already reserved as final holdout is removed before a tournament.
  Public frameworks and pretrained forecasts may later be added as versioned
  challengers, but never as execution authorities and never after inspecting the
  reserved holdout.
- The authenticated `POST /api/v1/research/model-tournament` route and CLI command
  expose the same audited workflow. Research status now returns stored tournament
  outcomes as well as replay diagnostics.

First USD/JPY result (27 August 2026): histogram gradient boosting remains the
development leader with profit factor 1.174 and positive cost-aware expectancy,
but fails AUC (0.507 versus 0.52) and maximum drawdown (3.54% versus 3%). Logistic
regression is unstable and exceeds drawdown; random forest is unprofitable with
too few trades. No challenger passes every gate, so no candidate was frozen and
demo execution remains blocked.

Open-source Model Lab V3 now extends the same tournament independently to all
four markets with LightGBM, XGBoost and CatBoost. It adds PR AUC, log loss,
calibration buckets, native feature importance, a predeclared selective
BUY/SELL/HOLD threshold grid and a two-thread research ceiling. Exact candidate
and gate configurations are persisted. Freeze eligibility uses the stricter 3%
holdout drawdown ceiling. The first strict four-market run rejected every raw and
selective candidate; its evidence is recorded in
`OPEN-SOURCE-MODEL-LAB-REPORT-2026-08-27.md`. Qlib, SHAP, deep learning, pooled
global models and automatic holdout-to-validation promotion remain deferred.

## 21. Canonical model governance and risk hardening

- A checksum-verified 333 MB SQL backup completed before migration 027.
- Research now starts with an immutable `research_lineages` reservation; a
  tournament can only see that lineage's development interval.
- One policy owns label horizon, purge gap, development gates, minimum trades per
  window, feature-row calculation and source identity.
- Scheduled training can create a candidate but cannot mark it validated.
- A single-use holdout pass requires explicit owner review of the exact artifact
  checksum before a governed model version exists. This enables forward shadow
  only.
- Readiness counts only checksum-matched, owner-approved holdout models. Broker
  readiness also requires an observed IG margin factor.
- Risk fails closed for blocked/stale ledgers, portfolio and daily-trade limits,
  absent/insufficient margin evidence and invalid reward/risk policy.
- Evidence refresh uses a durable, leased and idempotent SQL job processed by the
  existing continuous shadow worker.
- Demo and live flags remain disabled. No holdout was consumed and no order was
  submitted during this tranche.

This former P1 statement is superseded by the authoritative status at the top of
this document. Its completed and deferred items are recorded in the August 2026
implementation-history archive.

## 22. Session-aware monitoring correction

- Market-data alerting now distinguishes `CLOSED`, `OPEN_GRACE` and `OPEN`.
- Expected FX weekend closure and Germany 40/Xetra closed sessions do not create
  stale-candle alerts.
- A 20-minute reopening grace avoids warning while the first completed M5 candle
  and stream connection settle.
- Genuine stale data after grace still warns using the configured M5 threshold.
- Infrastructure, API, authentication and worker failures remain monitored at
  all times; market closure suppresses only the data-age symptom.
- Existing calendar-aware quality audits were verified: the current weekend has
  zero recent missing periods.
- Combined quality validation now groups candles by provider family. Declared
  Dukascopy-to-IG boundaries are excluded from missing-period status while the
  provider-specific `app.data_quality_segments` records remain the authoritative
  98.5% historical-completeness gate.
- Recalculation on 30 August 2026 returned `PASS` for M5 and M15 on EUR/USD,
  GBP/USD, USD/JPY and Germany 40. Real corrupt candles and recent gaps inside a
  provider segment still fail or warn; no candles were manufactured or removed.

## 23. Readiness blocker normalization

- Global and market-specific freshness checks now use each market's operational
  calendar. A closed market or reopening grace period is reported as `CLOSED` or
  `OPEN_GRACE`, not as failed continuity or stale execution pricing.
- Raw freshness flags remain factual and broker execution still requires an open
  session. Calendar deferral therefore cannot make an order executable.
- Historical and training quality currently pass for all four markets; the most
  recent audit contains zero invalid OHLC, non-positive, future, partial or recent
  missing candles.
- Demo execution opt-in remains disabled and is reported separately as a deferred
  activation step. It becomes an actionable gate only after a market has a
  governed validated model and passes forward-shadow promotion.
- The sole active platform development blocker is now model validation (`0/4`).
  Candidate training uses development history. Forward shadow evidence begins
  only after a frozen candidate passes governance and holdout acceptance; shadow
  observations do not train or repair a rejected candidate.

## 24. Selective, target-bound model research

- Migration 028 adds immutable target definitions, chronological-boundary
  audits, lifecycle events, market-row quarantine, bounded recovery jobs and
  model-monitoring snapshots.
- Migration 029 binds the target checksum and protocol version to both the
  research lineage and every selective tournament experiment.
- `AUREX_SELECTIVE_RESEARCH_V4` implements market-specific ternary labels,
  development-only calibration, cost-sensitive HOLD decisions, purged
  walk-forward windows, bootstrap confidence intervals, regime slices and
  realistic execution-cost stresses.
- Provider changes reset rolling features and labels. The final holdout is
  excluded before target construction and cannot be read by the tournament.
- The market-specific challenger tournament runs through the durable SQL worker
  and has no artifact, promotion or execution authority.
- The Research UI displays target and audit evidence and no longer exposes the
  misleading hard-coded Germany 40 freeze button.
- Current leakage audits pass for all eight declared market/target combinations.
  This proves dataset separation, not model profitability. No V4 lineage,
  candidate, holdout evaluation, model promotion or broker order was created.

Next evidence-dependent work is to reserve one explicit target-bound lineage per
market, run the durable selective tournaments and freeze only a leader that
passes every development gate. Event regimes and sustained forward-shadow
evidence remain blocked until their prerequisite evidence exists. Drift writers
are active, but real drift scores necessarily require an approved model and
post-approval observations.
