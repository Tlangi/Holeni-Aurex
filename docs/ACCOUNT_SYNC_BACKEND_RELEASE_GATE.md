# Account-sync backend release gate

Status: **required before restarting `AurexPlatformAPI`**. This is a release procedure, not permission to enable Demo orders.

## Scope and isolation

1. Capture the currently running API service command, application directory, active source/release hash, latest successful `app.sync_runs` row, `ig_demo` component heartbeat, open alerts, engine controls, and unresolved order intents. Record the previous executable path for rollback. Never include credentials or the contents of `.env` in the evidence bundle.
2. Build a **versioned API release outside the shared dirty checkout** from a known commit. Curate only the account-sync startup/retry fix and its tests. The required behavior is: start the scheduler even when the operational schema is temporarily unavailable at API startup; retry schema readiness without authenticating to IG or syncing until it is ready; retain authentication circuit-breaking, one-sync-at-a-time locking, and fail-closed trading controls. Do not copy the entire working versions of `main.py` or `scheduler.py`: they contain unrelated in-progress API and trading changes.
3. Record a manifest of the base commit, exact patch, dependency lockfile/hash, Python version, and SHA-256 of every release file. Compare the API routes and imported modules with the running release. Any extra order route, changed risk/broker logic, migration dependency, or unexplained diff fails attestation.

## Pre-restart gate

- Run the complete backend suite against the isolated release. Include `test_account_sync_startup_recovery.py` and a retry test that simulates database-unavailable-at-startup followed by recovery. Assert that no IG authentication or account sync is attempted before schema readiness.
- Start the isolated release on a **different localhost port** with the same read-only health configuration. Verify startup with the database available and unavailable, then recovery. Do not bind an extra public endpoint or enable submission.
- Confirm the production engine is `SHADOW`, `new_orders_enabled=0`, Live disabled, and unresolved submission/reconciliation intents are zero. Confirm the database backup and restore verification remain current. A model or broker-rule gate must not be waived to ship this fix.
- Have the release owner approve the recorded manifest, exact service target, restart window, and rollback path. Do not restart the API merely because source tests pass in the dirty checkout.

## Controlled switch and acceptance

1. Point **only** `AurexPlatformAPI` at the attested versioned release and restart that service once. Leave the market stream, trading worker, IIS site, and owner-summary service untouched.
2. Verify `/health/ready` returns HTTP 200 and the authenticated owner routes still enforce authentication. Check the actual service path and process start time against the manifest.
3. Observe **three consecutive scheduled** `app.sync_runs` successes at approximately the configured five-minute cadence. Do not count a manual one-off sync. Confirm `ig_demo.checked_at_utc` advances, the stale account-sync alert resolves, and no authentication/session circuit opens.
4. Recheck engine controls and unresolved intents after each observation. A `CURRENT` status alone is insufficient: the timestamp must be fresh and the scheduled run history must progress.

## Rollback

If the API fails readiness, scheduled sync does not resume, account state becomes uncertain, or any execution control changes unexpectedly: keep new orders disabled, stop the new API service, restore its recorded previous executable/application directory, restart only `AurexPlatformAPI`, and verify readiness and engine controls. Preserve logs and failed-run evidence. Do **not** clear alerts manually or repeatedly submit account-sync requests to make the dashboard look healthy. The pre-release account-sync warning remains actionable until a subsequent attested release succeeds.
