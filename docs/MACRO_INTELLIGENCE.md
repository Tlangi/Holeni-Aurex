# Aurex macro-intelligence pipeline

## Purpose

The macro-intelligence subsystem continuously retrieves allow-listed official material for USD, EUR, GBP and JPY. It creates auditable currency scores and combines them with M15 technical features and any validated market model. It cannot submit an order; the deterministic risk engine remains the final authority.

## Evidence flow

1. The existing `AurexTradingWorker` polls twelve HTTPS sources from the Federal Reserve, BLS, ECB, Eurostat, Bank of England, ONS, Bank of Japan and Statistics Bureau of Japan.
2. Every request is restricted to an exact configured host and an official-domain allowlist. Redirect targets, response content type and a 2 MB response limit are validated.
3. RSS entries or changed HTML snapshots are normalized into `app.macro_evidence`. Aurex stores a bounded excerpt, retrieval time, canonical URL, classification, parser version and SHA-256 revision hash.
4. Recent evidence produces separate policy, inflation and event-risk scores for each currency. A score expires if any required evidence category is absent.
5. For each enabled market, Aurex combines:
   - M15 EMA trend, four-period momentum and RSI;
   - the base-minus-quote macro score;
   - a validated model direction and confidence, when available.
6. The result is persisted in `app.market_decisions` as `BUY`, `SELL` or `HOLD`, together with its inputs, confidence, blocker and deterministic input hash.
7. `app.signals.market_decision_id` links an executable combined decision to the existing signal/risk/order-intent lifecycle.

## Fail-closed rules

- Missing or stale macro coverage produces `HOLD / MACRO_EVIDENCE_STALE`.
- A high-impact event inside the configured blackout window produces `HOLD / HIGH_IMPACT_EVENT_WINDOW`.
- Weak combined evidence produces `HOLD / NO_COMBINED_EDGE`.
- A directional decision without a validated model is visible but non-executable with `MODEL_NOT_VALIDATED`.
- A model `HOLD` or a model/macro direction conflict blocks execution.
- Even an executable combined decision must still pass market freshness, broker rules, reconciliation, daily risk, exposure, position sizing, stop and take-profit controls.

## Configuration

Optional `.env` settings and their defaults:

```dotenv
MACRO_INTELLIGENCE_ENABLED=true
MACRO_SYNC_SECONDS=900
MACRO_SOURCE_TIMEOUT_SECONDS=15
MACRO_EVIDENCE_MAX_AGE_HOURS=168
MACRO_EVENT_BLACKOUT_MINUTES=60
MACRO_DECISION_THRESHOLD=0.35
```

`MACRO_SYNC_SECONDS` cannot be below five minutes. Live trading remains prohibited independently of these settings.

## Operations

The Windows service `AurexTradingWorker` owns continuous synchronization. The authenticated API exposes:

- `GET /api/v1/macro/status` — source health, evidence-derived currency scores and latest market decisions.
- `POST /api/v1/macro/sync` — manual official-source refresh and decision regeneration; it cannot submit an order.

Database migrations:

- `014_macro_intelligence.sql`
- `015_link_macro_decisions_to_signals.sql`
