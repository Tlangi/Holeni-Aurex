# Aurex unused-code cleanup — 2026-09-14

Scope: remove only a verified duplicate read path. No broker, risk, model, database, or Live control was deleted or relaxed.

The owner frontend requests `/api/v1/owner/readiness` and `/api/v1/owner/markets`. The IIS rule routes those exact paths to the authenticated, GET-only `AurexOwnerOverviewAPI` on localhost port 8011. `AurexPlatformAPI` also defined copies of those two handlers, but they were bypassed on the owner-facing path. The duplicate main-API handlers and their unused import were removed. The dedicated owner-overview functions and service remain. A regression test asserts the two paths exist in the owner-overview service and not in the trading API.

Backend tests: 332 passed. This is a source change only, not an API restart or deployment. The expected trading API route count drops from 62 to 60; this is an intentional, read-only route difference that must be recorded in the next release attestation.

Not removed: `proposal_approval_reservations.py` (zero current challenge/reservation rows, but an authenticated, single-use pre-submission safety path); `experimental_demo.py` (controls/reconciliation and existing routes); `owner_overview.py` (used by port 8011); research diagnostics/scripts and tests (manual or scheduled entry points); migrations 051–058 (already applied and required for database recovery); audit history. These are unused *at a moment in time* or not owner-facing, not proven dead. The account-sync release gate remains in force and this cleanup does not authorize deploying the full checkpoint.
