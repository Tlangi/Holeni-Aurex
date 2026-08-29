# Platform API

FastAPI service for identity, authorization, configuration, dashboards, audit data,
and orchestration. It is the only browser-facing backend.

## Local setup

```powershell
Set-Location C:\Projects\Forex\services\platform-api
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Enter the SQL Server and Google SMTP details manually in `.env`. Use a Google App
Password for SMTP. The real `.env` is ignored by Git.

Start the development API:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

Health endpoints:

- `GET http://127.0.0.1:8010/health/live`
- `GET http://127.0.0.1:8010/health/ready`
- `GET http://127.0.0.1:8010/api/v1/trading/readiness` (authenticated, fail-closed demo gate)

The readiness response reports only safe status labels and never returns credentials
or raw SQL driver errors. Trading remains `disabled` by default.

Demo execution has two independent configuration locks: `TRADING_MODE=demo` and
`ALLOW_DEMO_TRADING=true`. Live configuration is rejected during settings loading,
and neither setting changes the database engine control by itself.

## Database migration

After database readiness succeeds, apply migrations with the tracked runner:

```powershell
.\.venv\Scripts\python.exe scripts\apply_migration.py ..\..\database\scripts\002_create_platform_schema.sql
```

The runner records the migration name and SHA-256 checksum in
`app.schema_migrations`. Re-running an unchanged migration is a no-op; changing an
already recorded migration is rejected. Create a new ordered migration instead.

## Continuous shadow worker

The shadow worker synchronizes read-only IG Demo dealing rules, checks whether
enough completed M15 data exists for chronological model validation, and creates
signals, risk decisions and `WOULD_SUBMIT` intents. It contains no broker order
submission method.

```powershell
.\scripts\install_shadow_worker_service.ps1 -StartNow
Get-Service AurexTradingWorker
```

The automatic service logs to `logs\shadow-worker-service.log` and starts with a
database application lock so a duplicate process cannot run the same cycle.

The IG Lightstreamer feed is also installed independently as the automatic
`AurexMarketStream` Windows service. When `Get-Service` reports `Running`, closing
PowerShell does not stop candle ingestion. The development Uvicorn command is not
a service and closing its console stops only the browser-facing API.

```powershell
Get-Service AurexMarketStream,AurexTradingWorker
```

## Quota-bounded historical backfill

Historical backfill always imports canonical M5 candles first and derives M15
candles from three complete, contiguous M5 buckets. Start with one small page:

```powershell
.\.venv\Scripts\python.exe scripts\backfill_market_history.py --page-size 100 --max-pages-per-market 1
```

The command is idempotent, records data-quality results, and stops all later
market requests immediately when IG reports the account historical allowance is
exhausted. Do not schedule it as a polling feed; Lightstreamer remains the normal
data source.

Germany 40 uses the account-provisioned, non-expiring E1 cash CFD
`IX.D.DAX.BMU.IP`. A deliberately small Germany-only M5 import is:

```powershell
.\.venv\Scripts\python.exe scripts\backfill_market_history.py --market GERMANY40 --page-size 50 --max-pages-per-market 1
```

Routine successful HTTP access and worker heartbeat events are not written to
the console. Warnings and failed calls retain structured JSON detail; successful
API calls return their normal HTTP status and response payload.

Market-specific model evidence is available from authenticated endpoint
`GET /api/v1/models/readiness`. A market remains in `SHADOW` unless its own data,
quality, model, freshness and broker-rule gates pass. Profit objectives are
informational only and are never inputs to signal frequency or position sizing.

Enhanced validation is persisted through three expanding walk-forward windows.
Promotion requires the configured AUC, a minimum cost-aware trade sample,
positive expectancy, profit factor above one, bounded drawdown and outperformance
of HOLD, moving-average, momentum and deterministic random baselines. Evidence is
available at `GET /api/v1/models/validation`.

Approved shadow intents create a separate hypothetical trade in
`app.shadow_trades`. Completed M15 candles mark it and close it at stop or target;
when both are touched in one candle, Aurex conservatively records the stop first.
The append-only lifecycle is exposed at `GET /api/v1/shadow/trades` and is never
mixed with IG Demo positions or broker trade history.

Authenticated operational projections are available at:

- `GET /api/v1/orders` — tenant-scoped persistent order intents
- `GET /api/v1/risk/status` — active policy and the current South African daily ledger
- `GET /api/v1/reconciliation` — broker-only and uncertain-state issues
- `POST /api/v1/trading/control` — owner-only `PAUSE` or `RESUME_SHADOW`
- `GET /api/v1/strategies` — tenant-scoped immutable strategy-version status
- `PATCH /api/v1/strategies/{id}` — owner-only `ACTIVE`/`PAUSED` control

Shadow intents use the audited path `CREATED → RISK_APPROVED → WOULD_SUBMIT`.
Every transition is append-only in `app.order_intent_events`. `WOULD_SUBMIT` is a
terminal shadow state and cannot transition to broker submission.

`app.ig_execution.IGDemoExecutionAdapter` implements the narrow IG Demo
acknowledgement/confirmation contract. It is not called by the shadow worker or
an HTTP route. Every submission call independently requires `READY`, `DEMO_AUTO`,
new orders enabled, the configured demo account, and a newly `RISK_APPROVED`
intent. A network timeout becomes `SUBMISSION_UNKNOWN` and is never retried.

If the connection returns SQLSTATE `08001`, follow
`docs/SQL-SERVER-CONNECTION.md` from the repository root. Do not restart SQL Server
until the other applications on this shared host have been considered.

If the FreeTDS/pymssql connection reaches SQL Server but reports a login failure,
run `database/scripts/003_sync_application_login_password.sql` in SSMS after setting
its temporary value to the exact `SQL_PASSWORD` from `.env`. Do not grant `db_owner`.

Set an Aurex user's password without placing it in shell history:

```powershell
.\.venv\Scripts\python.exe scripts\set_owner_password.py --email user@example.com
```
