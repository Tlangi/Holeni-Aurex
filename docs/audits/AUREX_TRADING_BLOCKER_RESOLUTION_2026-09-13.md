# Aurex trading blocker resolution — 2026-09-13

## 1. Executive result

This focused cycle isolated the GBP/USD executable-outcome blocker. The 13 selected decisions are **7–8 September**, not August. Ten have no IG M1 at the required entry timestamp in either inspected M1 store; those ten do have Dukascopy research rows at entry. Two more have partial IG paths; only one has a complete 60-minute IG bid/ask path. No prediction-to-candle join defect was demonstrated. The practical next step is to preserve the unavailable IG evidence, collect forward IG M1, and use vendor data only for clearly labelled research comparisons. No model, Shadow worker, experimental programme, trading mode, or broker order was changed.

Progress toward Forward Shadow: **diagnostic blocker isolated, NO-GO**. Experimental Demo: **NO-GO**. Demo Auto: **NO-GO**. Live: **DISABLED**.

## 2. Market quality and score semantics

Latest append-only V2 snapshots, all `BLOCKED`. `quality_pct = 100 × observed / (observed + missing)`, where observed is the latest up-to-2,000 completed, PASS, regular-session M5 timestamps from the specified provider set and missing is the expected in-session M5 timestamps between first and last selected bars. The selection window differs between views; these percentages cannot be subtracted. `quality_score_version=THREE_VIEW_M5_CALENDAR_M1_INTERVAL_V2`. Each persisted JSON includes exact expected, observed/valid, missing, invalid, incomplete, duplicate and per-gap M1 support. Invalid/incomplete timestamps are counted separately from the PASS selection; they are not added again to the denominator. In these selected ranges they all measured zero. Closed sessions are excluded by the configured calendar predicate. The score remains a provisional calendar diagnostic, **not execution authority**.

| Market | Raw IG | Research | IG execution | Main remaining data blocker |
| --- | ---: | ---: | ---: | --- |
| AUD/JPY | 72.91% | 90.95% | 62.56% | 199 research and 912 IG-execution in-session M5 gaps |
| EUR/JPY | 72.29% | 90.91% | 61.86% | 200 research and 929 IG-execution gaps |
| EUR/USD | 70.17% | 90.99% | 64.45% | 198 research and 1,103 IG-execution gaps |
| GBP/JPY | 63.92% | 90.95% | 53.49% | 199 research and 1,133 IG-execution gaps |
| GBP/USD | 69.93% | 90.99% | 64.23% | 198 research and 1,114 IG-execution gaps; sparse IG M1 paths |
| Germany 40 | 92.50% | 97.25% | 81.96% | Only 1,309/2,000 recent research M5 bars; 37 research gaps |
| USD/JPY | 71.33% | 90.99% | 65.40% | 198 research and 1,058 IG-execution gaps |
| USD/ZAR | 63.01% | 90.95% | 52.59% | 199 research and 1,155 IG-execution gaps |
| Gold | 61.09% | 86.92% | 50.56% | 301 research and 1,198 IG-execution gaps; session policy needs further validation |

All 27 V2 snapshots were persisted using migration 056's append-only research evidence table. M1 gap support is source-filtered: Dukascopy never enters `CURRENT_IG_EXECUTION`. For example, GBP/USD hybrid's 198 missing M5 intervals have 0 fully supported, 12 partially supported, and 186 absent M1 intervals in the current research store. This is a store/recovery-integration issue, not permission to synthesize IG execution history.

## 3. Broker authority

Fresh **read-only** IG Demo market-details calls were made for all nine markets. The response supplied the listed `minDealSize`, stop rule, price decimal factor, scaling factor and lot size but **no separately identified deal-size increment**. IG's [published market-details schema](https://labs.ig.com/reference/markets-epic.html) likewise identifies `minDealSize` and `minStepDistance` (a stop-distance field), not a distinct size increment. A minimum, lot size, price precision or previous accepted trade is not proof of an increment. No fallback was promoted.

| Market | Minimum size | Increment | Authoritative | Source | Blocker |
| --- | ---: | --- | --- | --- | --- |
| AUD/JPY | 1 | Unknown | No | IG Demo market details | `BROKER_SIZE_INCREMENT_NOT_AUTHORITATIVE` |
| EUR/JPY | 0.1 | Unknown | No | IG Demo market details | Same |
| EUR/USD | 1 | Unknown | No | IG Demo market details | Same |
| GBP/JPY | 0.1 | Unknown | No | IG Demo market details | Same |
| GBP/USD | 0.04 | Unknown | No | IG Demo market details | Same |
| Germany 40 | 0.5 | Unknown | No | IG Demo market details | Same |
| USD/JPY | 0.2 | Unknown | No | IG Demo market details | Same |
| USD/ZAR | 0.1 | Unknown | No | IG Demo market details | Same |
| Gold | 0.1 | Unknown | No | IG Demo market details | Same |

## 4. GBP/USD 13-prediction investigation

Frozen diagnostic dataset hash `bf08345e4972dd612017b0aa7ce9e1ded418d341f323b58981e5022aa01f68ac`; development before 2026-09-10 UTC. `IG valid M1` counts refer to the required 60-minute path beginning 15 minutes after the M15 decision. Every listed vendor-only entry has no IG entry in either inspected store, but a Dukascopy row in the historical research store. Full prediction IDs make the rows independently traceable.

| Prediction ID | Decision UTC | Side | Entry UTC | IG valid M1 / 60 | Exact reason |
| --- | --- | --- | --- | ---: | --- |
| `b562d4462fac10a709a6b9f1cc8b72fb03b8106a604acac2094c3de23356cd97` | 7 Sep 05:45 | Short | 06:00 | 0 | IG entry absent; vendor research only |
| `6492306e82ff152dac98e8bd019e667d8c5c5b5b3d024ec82f8692bf05bbb188` | 8 Sep 04:15 | Long | 04:30 | 0 | IG entry absent; vendor research only |
| `687b5979c4c7178bdf0a364872b77c2568890b1449943ee38f9ce4b4328f0b88` | 8 Sep 07:30 | Short | 07:45 | 0 | IG entry absent; vendor research only |
| `1457396d258639681d7b9de13a677a2f51d9c62f18a3725e31295e7bc3e46963` | 8 Sep 07:45 | Short | 08:00 | 10 | IG entry absent; 50/60 path minutes absent; vendor entry only |
| `0a8ab1a68bbac9bcbed84e3953a46b4694cd05f07b553152fb0d09d849e63947` | 8 Sep 08:00 | Short | 08:15 | 24 | IG entry absent; 36/60 path minutes absent; vendor entry only |
| `0ed94af92accac4df3552810851475f5535b1d16fe0c1a6df5f92d6401e7eb64` | 8 Sep 08:45 | Short | 09:00 | 59 | IG path missing 09:13; evaluator `M1_GAP` |
| `6711b1462d063bc09bb00a1d9c29a2a1259926ae29a09f2e5245fd788a49bda6` | 8 Sep 09:00 | Short | 09:15 | 60 | Valid IG path; `TIME_EXIT` |
| `136689dc1d8e8d6c2e404fdc4a1d31786b41ca4f3831191cca1f94f00709d542` | 8 Sep 09:15 | Short | 09:30 | 47 | IG path ends at 10:16; missing 10:17–10:29; `M1_PATH_INCOMPLETE` |
| `97435d4ed4486dd95061e8f07286e6b5454ff8c1b3e3bce2c86ac932faf7f2e5` | 8 Sep 11:30 | Short | 11:45 | 0 | IG entry absent; vendor research only |
| `9ad9a7508ea1f76c63f1a9f41a004da77b3dc776c7b049d23aafe90af284e5e1` | 8 Sep 12:00 | Short | 12:15 | 0 | IG entry absent; vendor research only |
| `1457b420ec78f78a1a65be1b0376811151050378979ff9e160163766be4095aa` | 8 Sep 13:00 | Long | 13:15 | 0 | IG entry absent; vendor research only |
| `01fefee101e091567502ea9a6c87cd037dbf6f17891f4bfab6abb73f48f85d1d` | 8 Sep 14:15 | Short | 14:30 | 0 | IG entry absent; vendor research only |
| `421bfe03cc281dece76f0149d1d6adee0d06ecf4fbea76b5135592442c054418` | 8 Sep 14:30 | Short | 14:45 | 0 | IG entry absent; vendor research only |

No present-but-filtered IG entry was observed in this cohort. This supports *missing broker history*, not an observed timestamp join failure. The read-only diagnostic checks quality, completeness, bid/ask and source at entry across both stores and counts each required minute. It does not claim that all possible approved external IG archives have been exhausted. A vendor-only path remains `BROKER_EXECUTION_PATH_UNAVAILABLE`.

## 5. GBP/USD same-ID economic bridge and 6. model economics

Only prediction `6711b146…a49bda6` produced a complete IG outcome: short entry **bid 1.35388** at 09:15 UTC, time exit **ask 1.35263** at 10:14, gross directional return **0.0009897**, spread-adjusted return **0.0009233**, declared two-sided slippage **1 bp**, net return **0.0008233**, net R **+1.4798**, MFE **1.7259 R**, MAE **0.1460 R**. The same frozen diagnostic yielded 13 selected predictions, 1 valid and 12 invalid paths: **7.69% executable-outcome coverage**. Directional AUC was **0.6052** on 48 validation rows, but that is not profitability evidence. Net expectancy and profit factor: **INSUFFICIENT EXECUTABLE OUTCOME EVIDENCE**; no model promotion or threshold tuning from this one observation.

## 7–10. Readiness

Forward Shadow: **NO-GO** — executable-outcome coverage/sample size insufficient, no demonstrated net expectancy, no governed candidate/untouched-holdout pass. Experimental Demo: **NO-GO** — broker size increment non-authoritative, IG execution quality blocked, programme/owner approval workflow incomplete. Demo Auto: **NO-GO** — stronger model/holdout/forward/operational gates unchanged. Live: **DISABLED**. The application default `daily_profit_target_enabled` is `false` and enabling it is rejected by configuration validation; no fixed daily return target was introduced.

## 11. Remaining P0/P1 blockers

P0: authoritative broker size increment for all nine markets; complete authenticated single-use Human-Approved Demo proposal-to-order path; 12/13 GBP/USD decisions lack valid full IG M1 replay paths. P1: integrate the bounded Dukascopy recovery store into the **research-only** quality view without overwriting IG; qualify the configured calendar against broker sessions (especially Gold/Germany 40); establish a new governed GBP/USD cohort lineage/manifest and persist same-ID outcomes; isolate/attest backend release before deploying the expired-programme API fix; current owner readiness remains unverified for per-market execution eligibility. No new lineage or economic result row was falsely persisted.

## 12. Tests, 13. files changed, 14. migrations, 15. owner action

Backend **316 passed**, two existing third-party warnings. Frontend **39 passed**. Angular production build **PASS**. This cycle added `scripts/diagnose_gbpusd_m1_coverage.py` and `tests/test_gbpusd_m1_coverage.py`, and revised `scripts/report_three_view_quality.py` and `tests/test_three_view_quality.py`; this report was created. Migration **056** (applied in the preceding continuation) holds append-only three-view snapshots; this cycle persisted 27 additional V2 snapshots. No migration was newly created in this cycle. The owner need not approve a trade now. To resolve size increment authority, an account-specific written IG dealing-rule/API confirmation may be required; absent that, keep the gate closed. No IG order was submitted.

### Next recommended action

Confirm whether an approved IG historical M1 archive exists for the exact 7–8 Sep missing minutes. If not, stop replaying this 13-prediction cohort as broker-executable evidence and accumulate forward IG M1 while running separately labelled Dukascopy research-path experiments. In parallel, obtain IG's authoritative size-increment specification through their supported channel; never infer it from `minDealSize`.
