# Aurex research and holdout policy

Research exists to discover a repeatable economic edge, not to make a backtest
look profitable. It has no broker execution authority.

## Evidence partitions

- **TRAIN** fits parameters.
- **VALIDATION** selects features, labels, regimes, thresholds and configuration.
- **HOLDOUT** is reserved for one final offline assessment of a frozen candidate.
- **FORWARD_SHADOW** is unseen, real-time evidence after offline validation.

Repeated inspection of HOLDOUT converts it into validation data. When that
happens, a new later holdout must be reserved and the experiment recorded.

## Enforced candidate lifecycle

Migrations 024 and 027 and policy `FROZEN_HOLDOUT_V2` enforce the boundary in the
database and application:

1. A chronological split must leave at least 2,000 feature-complete development
   rows and 500 feature-complete holdout rows.
2. Walk-forward development validation must pass every cost, baseline,
   calibration, drift, regime, trade-count and drawdown gate before an artifact
   is frozen.
3. The artifact and both data partitions are checksummed. A candidate artifact
   is deliberately excluded from `app.model_versions`.
4. Evaluation atomically changes `FROZEN` to `EVALUATING` and stamps the holdout
   as consumed before it loads any outcome. A unique database constraint permits
   only one evaluation per candidate. Failed or rejected evaluations cannot retry.
5. Passing a holdout remains non-promotable. A separate reviewed transition is
   required before market-specific forward shadow can begin.

All markets must reserve at least 2,000 feature-complete development rows and 500
untouched holdout rows. Availability is evaluated at reservation time; no target,
feature, cost or provider boundary may be changed after that reservation.

## Permitted research retraining

Scheduled retraining requires 96 genuinely new feature-complete M15 observations.
Immediate research retraining is permitted only for a named, versioned material
change to features, labels, regimes, model configuration, entry/exit logic or the
cost model. Every run creates an immutable experiment record.

## Promotion boundary

Markets promote independently. Offline validation never enables `DEMO_AUTO`.
Forward shadow still requires 30 closed trades over 10 South African trading
days, profit factor at least 1.10, positive cost-aware expectancy, drawdown at
most 3%, no more than four consecutive losses and complete cost evidence.

## Selective research protocol V4

Migrations 028 and 029 introduce target-bound research governance:

- Each market has predeclared cost-aware and volatility-adjusted BUY/SELL/HOLD
  targets with a market-specific horizon. Germany 40 targets are regular-session
  only.
- A lineage now binds the exact target checksum and protocol version before it
  reserves the final holdout. The target cannot be silently changed afterward.
- Dataset audits verify timestamp uniqueness, causal feature allow-listing,
  provider-boundary resets, chronological folds, label-horizon purging and
  holdout exclusion. Audits are immutable SQL evidence.
- Selective tournaments are durable background jobs. They compare logistic
  regression, random forest, histogram gradient boosting, LightGBM, XGBoost,
  CatBoost and a disagreement-aware ensemble on development data only.
- Probabilities are calibrated on trailing development data. A decision becomes
  HOLD unless estimated edge clears empirical cost plus a safety/uncertainty
  buffer. Ensemble disagreement also becomes HOLD.
- Evaluation records minimum-window results, bootstrap expectancy intervals,
  volatility/trend/session slices and P50/P75/P90/P95 cost, slippage, delayed
  execution and funding stress. A result depending on one exceptional window is
  rejected.
- Quarantined provider rows and bounded, session-aware recovery jobs are stored
  separately. Recovery never fills prices synthetically and never loops through
  historical API quota.

The V4 lifecycle remains `RESEARCH → ELIGIBLE_TO_FREEZE → FROZEN →
HOLDOUT_REVIEW → OWNER_APPROVED → FORWARD_SHADOW → PROMOTED`. Retraining a
forward-shadow candidate creates a new lineage and model version; it cannot alter
the candidate being evaluated.

The freeze adapter reconstructs only the exact target-bound tournament winner,
fits and calibrates it on development data, freezes partition and artifact
checksums, and records that holdout labels were not inspected. The one-use
holdout adapter applies the same multiclass BUY/SELL/HOLD and disagreement rules
to the reserved partition. A passed holdout still requires an explicit owner
approval and enables only frozen forward shadow.

Risk-on/risk-off and pre/post-event regimes remain deferred until Aurex has an
audited, point-in-time macro dataset. They must not be reconstructed from
information published after a prediction timestamp.

Every newly retrieved scheduled event is stored as an immutable retrieval-time
vintage with payload checksum and `available_from_utc`. Existing evidence can be
backfilled only as a snapshot retrieved now; it is not treated as proof of what
was known historically. Event regimes stay disabled until coverage is sufficient.

## Canonical governance introduced by migration 027

- Before a tournament, the owner pre-registers the hypothesis, chosen features,
  model families, target mode and target horizon through
  `POST /api/v1/research/lineage/reserve`. This reserves exact development and
  untouched holdout timestamps.
- `FUTURE_CLOSE_DIRECTION_4_M15_V2` is the canonical 4-bar/60-minute label.
  Purging, label metadata and feature-row calculations use the same definition.
- Scheduled training and tournaments may create development candidates, but can
  never set `VALIDATED` themselves. Every walk-forward window must meet its own
  minimum trade count.
- A successful one-use holdout becomes `OWNER_REVIEW_REQUIRED`. The owner-only
  approval route binds the exact artifact checksum to the validated model and
  enables forward shadow only. It cannot enable demo execution.
