# Aurex implementation history — August 2026

This file indexes historical progress statements preserved in
`docs/IMPLEMENTATION-PLAN.md`. It is not a readiness source.

## Superseded milestones

- Initial Angular/FastAPI/SQL Express foundation and localhost service setup.
- IG Demo authentication repair, streaming M5 aggregation and account sync.
- Dukascopy historical imports with explicit Dukascopy-to-IG boundaries.
- Session-aware market monitoring and quality recalculation for EUR/USD,
  GBP/USD, USD/JPY and Germany 40.
- Binary research, replay, holdout and forward-shadow prototypes through V3.
- Governance migrations 027–029 and Selective Research V4 dataset audits.

Statements such as “next milestone”, “sole blocker” and row counts in those
sections describe the date on which they were written. Use the authoritative
status at the top of `docs/IMPLEMENTATION-PLAN.md` and live API/SQL evidence for
current decisions.

## Safety state at archive time

- No live-trading path or third-party-funds path was enabled.
- Demo execution opt-in remained disabled.
- No V4 lineage, holdout evaluation or broker order had been created.
- Model readiness was zero approved markets; data availability alone was not
  model approval.
