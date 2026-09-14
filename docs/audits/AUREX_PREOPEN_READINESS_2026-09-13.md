# Aurex preopen operational handoff — 2026-09-13

Checked at approximately **20:00 UTC / 22:00 SAST**, before the configured FX weekly reopen at **21:00 UTC / 23:00 SAST**. This is readiness to **collect data and generate research feedback**, not trade-execution clearance.

## Operational state

- IIS site `Aurex`: **Started**. The separate legacy `AurexWeb` Windows service is disabled; IIS, not that service, serves the owner site.
- `AurexPlatformAPI`, `AurexMarketStream`, `AurexHealthMonitor`, `AurexHistoricalBackfill`, `AurexOwnerOverviewAPI`, `AurexTradingWorker`: **Running / Automatic**.
- API `http://127.0.0.1:8010/health/ready`: **HTTP 200**. An independent local HTTPS probe could not complete due to the shell's Schannel credential context; IIS is started and the operational alert table has no web alert. This is not a browser-level live-site attestation.
- SQL Server `MSSQL$SQLEXPRESS`: **Running / Automatic**; read-only database check succeeded.
- Open operational alerts: **0**. Unresolved submission/reconciliation intents: **0**. Pending proposals: **0**.
- Engine control: **SHADOW**, `new_orders_enabled=false`. Live permission **false**. Broker increments authoritative for **0/9** markets. `demo_execution_configured=true` is an opt-in configuration flag, **not** execution permission while engine/broker/model gates remain closed.
- Last backup: `RESTORE_VERIFIED`; backup completed 13 Sep 00:17 UTC and restore verified 01:01 UTC.
- Research jobs: 7 succeeded, 1 older failed; the most recent three jobs (11/10 Sep) succeeded. No active research job was observed in the status counts.
- Stream/API/health monitor service failure recovery includes automatic restart. The current market-feed/IG component heartbeat is older because markets are closed; the session-aware monitor suppresses stale-data alerts during a legitimate closure, then expects fresh data after reopen grace.

## Market-open expectations

At the check, all nine enabled markets were session-classified **CLOSED**. FX's configured Sunday reopen is 21:00 UTC, with a 20-minute grace before a missing-feed alert is actionable. Latest completed IG M1 for FX is Friday 11 Sep 20:58 UTC and M5 20:55 UTC (Gold M5 19:50 UTC). That age is expected during closure; it is **not proof of current stream continuity**. Germany 40 remains on its independent weekday exchange session. The first new IG M1/M5 after reopen is the decisive evidence. If no fresh stream/complete candles appear after grace, the existing health monitor should raise a market-feed alert; do not infer an active stream merely from Windows `Running`.

## Release/worktree caveat

The worktree has **104** changed/untracked paths from ongoing implementation. `git diff --check` exits 0 for tracked edits, but the repository is **not a clean release tree**. The API and market-stream Windows services point directly to `C:\Projects\Forex\services\platform-api`; an automatic restart could load the current dirty source. No service was restarted or deployment changed during this preopen check, and no user edits were discarded, stashed, or committed. A versioned isolated backend release/attestation remains outstanding before calling the deployment clean.

The locally implemented approval-reservation API is not a broker submission workflow and is not attested as deployed. Do not arm Demo or promote a model on the basis of this preopen check. Historical broker-size authority, current IG execution quality, model economics, final risk revalidation, and owner approval remain hard gates. Demo Auto and Live remain disabled/unqualified.

## System feedback to expect

Healthy market-open feedback is fresh session-aware IG M1 and completed M5 timestamps, renewed market-feed/IG component checks, no unresolved alerts, and continued `new_orders_enabled=false`. A missing or stale feed after the configured grace, a component degrading, or reconciliation uncertainty requires investigation; it does **not** authorize disabling safeguards. Research/model updates can proceed independently, with Dukascopy marked research-only and no automatic promotion from a single diagnostic result.

Read-only check command for a later operator: `C:\Projects\Forex\services\platform-api\.venv\Scripts\python.exe C:\Projects\Forex\services\platform-api\scripts\preopen_readiness_check.py`.
