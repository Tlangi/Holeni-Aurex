# Routes

| Route | Purpose | Owner-facing role |
|---|---|---|
| `/` | Operations dashboard with market, portfolio, research, shadow, proposals, risk and system sections | Primary command centre |
| `/research` | Strategy evidence, experiments, replay and holdout controls | Advanced research |
| `/experimental-lab` | Experimental programme/canary controls | Advanced operational research |
| `/login` | Owner authentication | Required entry point |

# Screens

The dashboard currently contains the major operational screens as anchored sections: portfolio overview, market data/chart, macro intelligence, model readiness, forward evidence, replay, strategies, orders, proposals, shadow trades, open positions, history, assurance, risk, reconciliation and system status. Research and Experimental Lab are separate advanced routes.

# Navigation

Current navigation has three groups: Overview, Trading, and Operations. Trading currently mixes market data, research, proposals, shadow, strategies, orders and history. Operations mixes assurance, risk, reconciliation and system status.

Recommended owner structure:

```text
Dashboard
Markets
Trading (approvals, shadow, positions, history)
Research (models, experiments, data)
Risk
System (services, broker, audit)
```

# Buttons

| Screen | Button/action | Purpose | Functional? | Classification | Recommendation |
|---|---|---|---|---|---|
| Dashboard | Refresh IG data | Refresh account/market data | Yes | KEEP | Show loading/result |
| Dashboard | Pause/Resume shadow | Change protected operational control | Yes | KEEP | Require clear mode confirmation |
| Dashboard | Approvals | Navigate to pending proposals | Yes | KEEP | Keep count visible |
| Dashboard | Shadow trading | Navigate to shadow evidence | Yes | KEEP | Use owner terminology |
| Dashboard | Research / Experimental Lab | Navigate advanced research | Yes | MOVE_TO_ADVANCED | Keep out of primary action emphasis |
| Dashboard | Start shadow testing | Starts shadow control path | Yes, protected | KEEP | Explain eligibility and confirmation |
| Dashboard | Replay market | Run diagnostic replay | Yes | MOVE_TO_ADVANCED | Keep in Research |
| Dashboard | Refresh official sources | Refresh macro evidence | Yes | MOVE_TO_ADVANCED | Keep in Research/System |
| Dashboard | Fit/zoom/chart controls | Chart navigation | Yes | KEEP | Reduce visual prominence |
| Dashboard | Approve/Decline proposal | Owner decision | Yes | KEEP | Add expiry/loading/error feedback |
| Research | Sync evidence / protocol audit | Refresh evidence | Yes | MOVE_TO_ADVANCED | Show last successful sync |
| Research | Replay / tournament / holdout actions | Research workflows | Yes | MOVE_TO_ADVANCED | Keep technical details behind Advanced |
| Experimental Lab | Arm/Pause/Resume/Kill | Experimental controls | Yes, high impact | KEEP | Strong confirmation and audit trail |
| Experimental Lab | Submit/close attempt | Experimental position control | Yes, high impact | FIX | Make state and confirmation explicit |
| Login | Sign in / logout | Session control | Yes | KEEP | Preserve authentication safeguards |

# Duplicate Information

Readiness, model status, data quality, broker state and execution blockers are represented in several dashboard panels and API payloads. The frontend should consume one canonical readiness payload and present owner summaries first, with technical evidence in Advanced details.

# Obsolete Components

No component was removed during this pass because the dashboard actions are wired to live handlers and some controls are safety-critical. Static or stale shadow references should be hidden from active views rather than deleted from history.

# Technical Information to Move to Advanced

Provider lineage, raw gate codes, payload hashes, migration versions, feature metrics, reconciliation diagnostics, raw broker rules and historical gap details.

# Missing Owner Workflows

The primary dashboard needs a single “Why Aurex is not trading” summary, visible Demo/Live environment banners, consolidated pending approvals, and a clear distinction between Shadow, Human-Approved Demo, Demo Auto and Live.

# Recommended Dashboard

Top-to-bottom: environment banner; overall health/mode; account/P&L/risk; pending approvals; open positions; market summary; “Why Aurex is not trading”; model/shadow summary; advanced evidence lower on the page.

# Safe first-pass changes

- Add persistent `IG DEMO / NO LIVE CAPITAL` and `LIVE DISABLED` banners.
- Add owner-level “Why Aurex is not trading” copy without exposing raw exception text.
- Keep research controls available but visually secondary.
- Preserve all backend evidence and high-risk confirmations.

# Implemented follow-up

The primary sidebar is now grouped by Dashboard, Markets, Trading, Research, Risk, and System. Technical research and assurance destinations remain reachable through their existing dashboard sections. The owner attention panel now derives its explanation and destination from pending proposals, service attention, paused or shadow mode, and Demo readiness; it no longer claims an inactive model unconditionally. The persistent Demo/Live banner remains visible. No route, backend evidence, or protected trading action was removed.
