# Safe research recovery and approval continuation — 2026-09-13

## Result

Implemented an explicit read path from validated, research-eligible `app.market_candles_m5` Dukascopy derivatives into the **HYBRID_RESEARCH** M5 diagnostic. IG stream and IG historical candles retain precedence at identical timestamps. `RAW_IG` and `CURRENT_IG_EXECUTION` still reject Dukascopy. Recovery evidence records source, import batch, derived M5 composite reference, five M1 source timestamps and ingestion time in the append-only quality snapshot. No `app.candles` IG row was overwritten or relabelled. The score policy is `THREE_VIEW_M5_CALENDAR_M1_RECOVERY_V3`; snapshots remain research diagnostics, not execution authority.

Latest research score effects: USD/JPY uses **99** approved derived M5 candles, moving provisional hybrid quality **90.99% → 95.28%** and missing intervals **198 → 99**. Its raw IG and current IG execution scores remain unchanged. GBP/USD remained **90.99%**, 198 missing intervals, zero eligible derived M5 in this source; its IG execution score remains **64.23%**. Other markets did not gain eligible recovery rows in the bounded read.

## GBP/USD bounded recovery check

The importer was constrained to GBP/USD's existing 7, 8 and 9 September local files. All three were `ALREADY_IMPORTED`; no new tick import occurred. Revalidation found:

| Day UTC | Partition outcome | Coverage | Why research view did not accept it |
| --- | --- | ---: | --- |
| 7 Sep | `QUARANTINED` | 98.26% | 16 unexpected gaps; completeness gate failed |
| 8 Sep | `CALENDAR_VALIDATED` | 99.51% | Required primary HISTDATA comparison had `NO_OVERLAP`; IG overlap independently passed 394/394, but primary gate did not |
| 9 Sep | `QUARANTINED` | 79.17% | One 300-minute unexpected gap; completeness gate failed |

These whole-partition gates are stricter than a future **interval-level** research repair policy. The importer reported zero new M5 derivatives for these batches. It previously returned negative `m1_gaps_with_m5_fallback` counts because the SQL driver can report `rowcount=-1`; the counter now reads an explicit insert count in SQL. Previously printed negative counts were not real negative data. The partition validator's primary source selection and an interval-level five-M1 repair approval need separate tests before any GBP/USD vendor interval is made research-eligible. Do not bypass the current quarantine in bulk.

## Frozen GBP/USD diagnostic cohort

Migration `057_frozen_nonpromotable_research_cohorts.sql` was applied. Cohort `830c0292-68c5-4e2e-9fcf-e3a2e62a9529` records **1,270 canonical M15 source-candle references**, fixed policy and dataset identity, the pre-10-Sep holdout boundary, and **13** stable prediction IDs/outcomes. Manifest SHA-256: `3775f276ed914f99135ff169cc8be158eb9e2abcc7a2d628d01e223c839efddc`. One broker IG M1 path is valid and twelve are unavailable/incomplete. The rows and cohort are append-only; a rerun returned `ALREADY_FROZEN` without rewriting them. This record is deliberately `NONPROMOTABLE_RESEARCH_ONLY`: no new governed lineage or holdout approval was fabricated from the existing 2025 lineage. It cannot authorize Shadow, Experimental Demo or any order.

## One-use approval reservation — no submission

Migration `058_proposal_approval_reservations_no_submission.sql` was applied. New owner-authenticated POST endpoints issue a 256-bit random challenge (only its SHA-256 is stored) and consume it once under a locked proposal row. The existing authenticated-user dependency requires CSRF for POST; challenge and proposal are tenant/owner-bound and expire no later than the proposal, at most two minutes after issue. Unique proposal/challenge reservation constraints prevent duplicate reservations. The only allowed reservation status is `PRE_SUBMISSION_BLOCKED`; approval changes the proposal to `OWNER_APPROVED_FOR_RISK` and returns `broker_order_submitted=false`. It neither calls the IG adapter nor creates an order intent. Existing owner review remains risk-review-only, so there is no alternate submission route created by this change. API source is tested locally but **not deployed/restarted** from the dirty checkout.

This is **not** a completed Human-Approved Demo workflow. Final quote/spread/session, broker-size, stop, margin, exposure, risk-ledger and reconciliation checks; durable `SUBMITTING` transition; unknown-submission recovery; and an authenticated phone-width real-proposal check remain required before any broker submission path may be enabled. No challenge was issued for a real proposal and no order was submitted.

## Verification and changed files

Full backend suite: **320 passed**, two pre-existing NumPy/joblib deprecation warnings. Frontend suite: **39 passed**. Angular production build: **PASS**. Focused approval-reservation tests after UUID request validation: **3 passed**. The final V3 quality snapshot was persisted and read back with 99 USD/JPY hybrid recovery provenance rows and zero recovery rows in both IG-only views. No backend or frontend service was restarted.

Changed this cycle: `services/platform-api/scripts/report_three_view_quality.py`, `scripts/recover_local_dukascopy_gaps.py`, `scripts/freeze_gbpusd_diagnostic_cohort.py`, `app/timeframe_fallback.py`, `app/proposal_approval_reservations.py`, `app/main.py`, `tests/test_three_view_quality.py`, `tests/test_proposal_approval_reservations.py`; migrations 057 and 058; this report. Existing unrelated dirty worktree changes were left in place.

## Safety and next work

No model retraining, Shadow start, Demo arming, Demo Auto enablement or Live change. Broker increments remain non-authoritative for all nine markets; missing IG M1 paths remain broker-execution-unavailable. Immediate next work: add **interval-level** Dukascopy repair qualification for only five-complete-M1 gaps with reviewed source equivalence and cross-source evidence, and verify the new read path without weakening the execution view. Separately complete final proposal-to-order safety gates in an isolated deployable API release. Owner action is not required to trade now; a later explicit per-trade decision is required only after all execution gates pass.
