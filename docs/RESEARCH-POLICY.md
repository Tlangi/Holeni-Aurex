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

Germany 40 is currently `DATA_BLOCKED`: a split that preserves 2,000 development
rows provides only 234 feature-complete holdout rows against the required 500.
The holdout has not been consumed.

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

## Canonical governance introduced by migration 027

- Before a tournament, the owner pre-registers the hypothesis, chosen features,
  model families and policy through `POST /api/v1/research/lineage/reserve`. This
  reserves exact development and untouched holdout timestamps.
- `FUTURE_CLOSE_DIRECTION_4_M15_V2` is the canonical 4-bar/60-minute label.
  Purging, label metadata and feature-row calculations use the same definition.
- Scheduled training and tournaments may create development candidates, but can
  never set `VALIDATED` themselves. Every walk-forward window must meet its own
  minimum trade count.
- A successful one-use holdout becomes `OWNER_REVIEW_REQUIRED`. The owner-only
  approval route binds the exact artifact checksum to the validated model and
  enables forward shadow only. It cannot enable demo execution.
