# GBP/USD frozen prediction-to-trade evidence — 2026-09-14

This is a read-only, non-promotable development diagnostic, not model validation or trading authorization. The source is frozen cohort `830c0292-68c5-4e2e-9fcf-e3a2e62a9529` with manifest SHA-256 `3775f276ed914f99135ff169cc8be158eb9e2abcc7a2d628d01e223c839efddc`. The script checks manifest/outcome hashes and joins all comparisons by immutable prediction ID. Its query does not read holdout data.

From `services/platform-api`, run: `.venv/Scripts/python.exe scripts/report_frozen_gbpusd_economic_bridge.py`. It emits all 13 IDs with directional label, signed four-M15-bar return, IG M1 coverage, executable net return, first-hit result and net R. Unavailable values are JSON `null`, not zero or an assumed loss.

| Evidence | Result |
| --- | ---: |
| Selected predictions | 13 |
| Complete evaluable IG M1 paths | 1 |
| IG M1 entry missing | 10 |
| IG M1 path gap/incomplete | 2 |
| Vendor research path indicated | 13 |
| Development strategy tuning | Blocked: insufficient IG paths |
| Model promotion / Demo submission | Not authorized |

The one evaluable prediction (ID `6711b1462d063bc09bb00a1d9c29a2a1259926ae29a09f2e5245fd788a49bda6`, decision 2026-09-08 07:00 UTC) was SHORT. The four-bar direction label was down and its signed gross return was approximately `0.001071`; the executable net return was approximately `0.000823`, first-hit result `TIME_EXIT`, net result `+1.480 R`. This is a single observation, not profitability evidence.

The ten missing-entry predictions do not have an eligible IG M1 entry in the frozen diagnostic. Two further predictions have incomplete IG M1 paths. The coverage inventory finds Dukascopy history at those times, but that is research lineage only; it cannot recreate the IG bid/ask, spread, or execution path. In particular, the 12 missing outcomes are *not* evidence that the model lost 12 trades. Nor does the one positive result establish that the current four-bar direction label aligns with actual trade economics.

Next research sequence: collect uninterrupted forward IG M1 plus corresponding frozen, same-ID predictions; verify IG path and interval-level bid/ask completeness; then compare four-bar direction, cost-aware net-return and stop/target first-hit labels on development data. Pre-register no-trade, long/short, session, spread and exit variants before evaluation. Do not tune on the holdout. A candidate still requires positive net expectancy, baseline outperformance, walk-forward stability, untouched governed holdout and forward Shadow evidence. More M5/M15 rows alone cannot substitute for broker-quality M1 paths. Broker dealing-size authority is a separate execution blocker; Demo and Live remain disabled.
