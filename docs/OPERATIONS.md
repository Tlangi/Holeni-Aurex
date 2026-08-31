# Aurex owner-server operations

## Automatic processes

| Component | Windows name | Purpose |
|---|---|---|
| Owner web | `AurexWeb` | Angular 21 production application on `127.0.0.1:4210` |
| Platform API | `AurexPlatformAPI` | Localhost API on `127.0.0.1:8010` |
| Market stream | `AurexMarketStream` | IG Lightstreamer M5 capture and M15 aggregation |
| Trading worker | `AurexTradingWorker` | Rules, readiness, intelligence and shadow lifecycle |
| Health monitor | `AurexHealthMonitor` | Health persistence and owner email alerts |
| Database backup | `Aurex SQL Backup` | Daily 02:15 checksum backup and `RESTORE VERIFYONLY` |
| Restore test | `Aurex Restore Verification` | Sunday 03:00 disposable restore and `DBCC CHECKDB` |

These processes do not depend on an interactive PowerShell window. All services
use automatic startup. The web service and API are localhost-only, and successful access requests
are suppressed; warnings and failures remain in rotating files under
`apps/web/logs` and `services/platform-api/logs`. The production web service
same-origin proxies only `/api` and `/health` to FastAPI; it does not expose SQL
Server or IG credentials.

The health monitor also generates one audited progress email per tenant and
South African calendar day after 18:00 SAST. It uses
`TRADE_REPORT_RECIPIENT`, falling back to `OWNER_EMAIL` and then
`SMTP_FROM_EMAIL`. The report summarizes training/model evidence, M5/M15 and
provider collection counts, shadow/demo activity, holdout progress, current
blockers and safe next improvements. Reporting has no order authority.

## Daily checks

Run from `C:\Projects\Forex\services\platform-api`:

```powershell
.\.venv\Scripts\python.exe scripts\operational_status.py
Invoke-RestMethod http://127.0.0.1:8010/health/ready
Get-Service AurexWeb,AurexPlatformAPI,AurexMarketStream,AurexTradingWorker,AurexHealthMonitor
Invoke-RestMethod http://127.0.0.1:4210/_health
```

`operational_status.py` reports candle freshness, spread evidence, per-market
readiness, forward-evidence snapshots, open alerts, backup verification and replay cost evidence. Never put
secrets or full `.env` contents in an incident report.

The authenticated dashboard's **Operational assurance** section provides the
same day-to-day evidence in the owner UI: daily email delivery, newest backup,
newest verified restore, open alerts and persisted component health. It is a
read-only projection; operational changes remain explicit administrator actions.

Inspect or preview the daily report without sending it:

```powershell
.\.venv\Scripts\python.exe scripts\daily_progress_report.py preview
.\.venv\Scripts\python.exe scripts\daily_progress_report.py status
```

Each daily delivery is claimed in `app.daily_progress_reports` before SMTP is
called. `SENT`, `FAILED` and in-progress rows are not automatically resent. After
fixing a recorded SMTP failure, an operator may explicitly retry only today's
failed ledger row:

```powershell
.\.venv\Scripts\python.exe scripts\daily_progress_report.py send --retry-failed
```

Do not use the retry command when the status is `SENDING`; first determine
whether the SMTP outcome is uncertain. This prevents duplicate owner emails.

## Web deployment

Build and atomically reinstall the localhost production service after verified
Angular changes:

```powershell
Set-Location C:\Projects\Forex\apps\web
npm test -- --watch=false
npm run build
.\scripts\install_web_service.ps1 -StartNow
```

Do not run `ng serve` beside `AurexWeb`; both use port 4210. When a domain is
available, put an HTTPS reverse proxy in front of this localhost listener, add
only the exact hostname to Angular `security.allowedHosts` and API origins, and
enable secure session cookies. Do not bind the Node or FastAPI processes directly
to a public interface.

It also reports the active forward-shadow promotion policy, recent promotion
evaluations and the one-off IG Demo execution-attempt ledger. An empty attempt
ledger is expected until a market passes every gate and the separate demo opt-in
is deliberately enabled.

## Backup and recovery

Backups are restricted to `ForexSaas`, written under
`C:\Projects\Forex\operations\backups`, protected with SQL checksums and retained
for 14 days. The recovery test uses only the exact disposable database
`ForexSaasRestoreVerification`, runs `DBCC CHECKDB`, and drops it afterwards.

Manual verification:

```powershell
& C:\Projects\Forex\operations\backup_database.ps1
& C:\Projects\Forex\operations\verify_restore.ps1
```

Do not point these scripts at another database or a broad filesystem location.

## Incident controls

- Pause new hypothetical cycles from the owner UI or engine-control API; this
  cannot enable broker orders.
- If ingestion is unhealthy, keep existing data, stop `AurexMarketStream`, and
  investigate the warning/error log. Do not fill gaps by unbounded REST polling.
- If reconciliation is unresolved, keep that market blocked. Never resubmit an
  uncertain intent merely because its first response is missing.
- A controlled IG Demo order remains prohibited until one market passes every
  data, model, risk, broker-rule, macro, reconciliation and explicit opt-in gate.

## Calendar maintenance

Germany 40 model evidence uses `Europe/Berlin`, the regular 09:00–17:30 window,
and the official Xetra non-trading dates. Load the next official calendar before
the current year ends. Broker `marketStatus` remains final execution authority.

## Dukascopy historical backfill

Dukascopy bid-only M5 history is an offline training backfill, not executable
broker-price evidence. The import keeps that provenance, leaves ask/spread fields
empty, assigns zero ticks because the CSV has no volume, and derives M15 only from
three complete, aligned M5 candles. Existing IG candles always win when timestamps
overlap.

The downloader is pinned by `dukascopy/package-lock.json` and uses conservative
batch pauses. Download one market at a time to avoid HTTP 429 responses:

```powershell
Set-Location C:\Projects\Forex\dukascopy
.\download_history.ps1 -Market GBPUSD
```

Never import a file merely because it exists. Validate its coverage and contents
first, then run the same command without `--dry-run`:

```powershell
Set-Location C:\Projects\Forex\services\platform-api
.\.venv\Scripts\python.exe scripts\import_dukascopy_history.py --file C:\Projects\Forex\dukascopy\download\gbpusd-m5-bid-2024-01-01-through-2026-02-27.csv --dry-run
.\.venv\Scripts\python.exe scripts\import_dukascopy_history.py --file C:\Projects\Forex\dukascopy\download\gbpusd-m5-bid-2024-01-01-through-2026-02-27.csv
```

An incomplete file must never be imported under a misleading requested end date.
If its rows and actual endpoint pass the full dry-run audit, it may be renamed as
a truthful bounded segment (for example `through-2026-02-27`) and imported; an
invalid or unverified file belongs under `dukascopy/quarantine`. Successful
imports are checksum-audited in
`app.historical_import_runs`; rerunning the same file is idempotent. Historical
backfill can make a market eligible for validation, but it cannot bypass model,
quality, cost, shadow, risk, macro, reconciliation or explicit demo gates.

## Strategy research operations

Refresh provider segments, execution freshness and empirical IG spread models
without training or execution:

```powershell
Set-Location C:\Projects\Forex\services\platform-api
.\.venv\Scripts\python.exe -c "from app.config import get_settings; from app.research_evidence import sync_quality_evidence,sync_cost_models; s=get_settings(); print(sync_quality_evidence(s)); print(sync_cost_models(s))"
```

The owner UI exposes the same authenticated evidence at `/research`. Diagnostic
replays use the latest model only when explicitly requested, remain
`TECHNICAL_DIAGNOSTIC`, and cannot promote or submit. A material research retrain
must name its versioned change:

```powershell
.\.venv\Scripts\python.exe scripts\research_retrain.py --material-change "LABEL_V2_EXPERIMENT_001"
```

Never use that command merely to bypass the 96-new-row scheduled threshold. A
research change must alter a recorded feature, label, regime, model, entry, exit
or cost version and creates an immutable experiment record.

Quality interpretation:

- `historical_research_quality` assesses declared provider segments.
- `cross_provider_continuity=KNOWN_GAP` is recorded and resets features.
- `recent_ig_continuity` and `execution_price_freshness` govern current safety.
- `overall_execution_quality=FAIL` always blocks execution.

## Frozen-candidate holdout

Read the audited status without consuming evidence:

```powershell
Set-Location C:\Projects\Forex\services\platform-api
.\.venv\Scripts\python.exe scripts\holdout_candidate.py status
```

Check whether Germany 40 can now reserve the minimum independent holdout while
preserving the 2,000-row development floor:

```powershell
.\.venv\Scripts\python.exe scripts\holdout_candidate.py freeze --market GERMANY40 --holdout-fraction 0.10
```

`DATA_BLOCKED` is expected until both floors are satisfied and does not consume
the holdout. Only a candidate with status `FROZEN` can be evaluated. Evaluation
requires the exact candidate id and is deliberately one-use:

```powershell
.\.venv\Scripts\python.exe scripts\holdout_candidate.py evaluate --candidate-id <candidate-guid>
```

Never run evaluation to test whether the command works. The atomic claim occurs
before outcome calculation and a failed attempt cannot be retried. No holdout
command changes `model_versions`, execution mode, demo opt-in or broker state.

## Durable research jobs and governance verification

`POST /api/v1/research/evidence/sync` enqueues an idempotent SQL job. The shadow
worker claims work with row locks, `READPAST`, a ten-minute lease and an attempt
counter. Read progress from `GET /api/v1/research/jobs`. An API restart no longer
loses accepted evidence work, and jobs have no execution authority.

Verify schema and safety from the API directory:

```powershell
.\.venv\Scripts\python.exe scripts\verify_governance.py
```

Safe output shows migration 027 present, zero demo attempts, demo/live disabled,
and zero governed validated models until an exact holdout-passed artifact receives
owner approval. Broker margin evidence should cover four markets after rule sync;
`EDITS_ONLY` during a closed session remains non-tradeable.

## Session-aware market-data monitoring

Operational candle freshness uses the shared market calendar instead of elapsed
wall-clock time:

- FX feeds are expected from Sunday 21:00 UTC through Friday 21:00 UTC. The first
  20 minutes after the Sunday reopen are a grace period.
- Germany 40 uses `Europe/Berlin`, the configured Xetra 09:00–17:30 regular
  session, the holiday table and the same 20-minute opening grace period.
- Candle-age alerts are suppressed while a market is closed or in reopen grace.
  Once the session is open, the configured M5 freshness limit applies.
- API, owner-web, database, service-component, IG authentication, risk-engine and
  worker-health checks remain active during market closures.

Operational freshness is different from research completeness. Quality audits
already count missing periods only inside configured regular sessions and record
`recent_missing_period_count` separately. Historical warnings may therefore
remain for bounded provider downloads or genuine gaps even when weekend alerts
are correctly suppressed. Feature construction continues to reset at every gap.

## Security, backup and retention hardening

Before public-domain exposure, configure a strong `AUTH_HASH_PEPPER`, HTTPS,
`SESSION_COOKIE_SECURE=true` and an MFA enrollment/verification flow. Login
attempts are rate-limited by hashed email and remote address and repeated owner
failures lock the account temporarily. Setting `mfa_required=1` currently fails
closed; it does not pretend that MFA verification already exists.

After all migrations, create and verify a separate deployment principal, then
run `database/operations/harden_runtime_user.sql` as an administrator. This moves
schema ownership to `dbo`, removes broad data/DDL roles from the runtime account
and grants only DML on `app`. Never remove migration privileges until the
deployment principal has been tested.

Encrypted off-server backups require three separately verified steps:

1. Run `database/operations/configure_backup_encryption.sql` with offline secrets
   and export the certificate plus private key to restricted off-server storage.
2. Run `operations/backup_database_encrypted.ps1 -OffServerDirectory <path>`.
   The script refuses a workspace destination, verifies the SQL backup, compares
   local/remote SHA-256 hashes and records a verified replication row.
3. Schedule only after a restore has succeeded on a separate test instance.

`scripts/retention_status.py` is deliberately dry-run. Policies in
`app.data_retention_policies` define hot/archive periods, but archive-required
records must never be deleted until an encrypted archive checksum and restore
test exist. Destructive retention execution remains an explicit later operation.
