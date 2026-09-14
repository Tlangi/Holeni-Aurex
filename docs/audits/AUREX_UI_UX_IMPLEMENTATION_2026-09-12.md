# Aurex UI/UX implementation — 2026-09-12

## Outcome

The owner shell now has six canonical, guarded routes and a route-driven section view. The same existing API-backed component preserves trading controls and evidence while presenting Dashboard, Markets, Trading, Research, Risk and System separately. This is a substantial information-architecture improvement, **not a claim that the full UX brief is complete**. Frontend tests: **32/32 pass**; production build: **pass**.

## Old navigation

One `/` dashboard with five local tabs and many anchored links; `/research` was a separate technical screen and `/experimental-lab` a separate high-impact control screen. Sidebar labels mixed owner areas with model readiness, forward evidence and other deep links.

## New navigation and routes

| Route | Owner purpose |
| --- | --- |
| `/dashboard` | Health, environment, mode, account, approvals, positions, risk and why-not-trading summary |
| `/markets` | Compact market inventory and freshness/model summary |
| `/markets/:market` | Selected market overview, chart, model/data/trades drill-down |
| `/trading` | Approvals, protected Shadow control, positions, simulated Shadow, intents and history |
| `/research` | Model/validation/training/forward evidence and strategy configuration |
| `/research/advanced` | Existing deep research protocol, replay, tournament and holdout workflows |
| `/risk` | Daily risk ledger |
| `/system` | Services, assurance, execution readiness and reconciliation |
| `/experimental-lab` | Existing protected experimental Demo programme controls; linked from Trading |
| `/login` | Owner authentication |
| `/` | Redirect to `/dashboard` |

Unknown routes redirect to `/dashboard`. The legacy `/research` bookmark remains valid as the main Research area; deep tools moved to `/research/advanced`. `/experimental-lab` remains valid. Direct old hash anchors should be considered legacy and are not guaranteed to land on their new owning route.

## Screens created, merged, removed

Created route-level Markets overview and market detail views within the existing operational component. Split the former local-tab content into routed owner areas. No backend screen or evidence was deleted. Removed the five-button local dashboard tab bar and most topbar shortcuts; their destinations remain in primary navigation or area-level links.

## Button and link inventory

Classification uses KEEP, FIXED, MERGED, MOVED_TO_ADVANCED or REMOVED. Dynamic market/timeframe/period and per-row action buttons are classified as their corresponding group.

| Route / component | Action | Backend or effect | Classification | Change |
| --- | --- | --- | --- | --- |
| All / shell | Six primary navigation links, brand, mobile menu/backdrop, Logout | Router/auth logout | KEEP | Canonical routes; active route and mobile drawer retained |
| Dashboard / operational | Refresh IG data | Dashboard sync | KEEP | Existing loading state retained |
| Dashboard / operational | Why-not-trading action; approvals, positions, risk links | Routed navigation | FIXED | Navigate to owning route and section |
| Dashboard / operational | Old local tabs, topbar Research/Shadow/Lab shortcuts | Navigation only | MERGED | Removed from topbar/tab strip; main navigation and area links replace them |
| Markets / operational | Market selection | Route + candle load | FIXED | Each market opens `/markets/:market`; list has explicit drill-down |
| Market detail / operational | Timeframe, period, chart zoom/reset/fit/latest, retry | Candle API and local chart viewport | KEEP | Only backend-supported choices shown; chart controls retained |
| Market detail / operational | Overview/Chart/Model/Data Quality/Trades links | In-page drill-down / owning route | KEEP | Sections labelled; deep evidence preserved |
| Trading / operational | Pause/resume evaluation, start Shadow | Protected control API | MOVED_TO_ADVANCED | Removed from global topbar/market chart; available in Trading control panel with existing confirmation/backend checks |
| Trading / operational | Approve/Decline proposal | Proposal decision API | FIXED | Countdown, expired disable, duplicate-click guard and honest “risk review, no order” wording |
| Trading / operational | Strategy enable/pause | Strategy API | MOVED_TO_ADVANCED | Located in Research, with existing confirmation |
| Research / operational | Diagnostic replay, macro official-source refresh | Research/macro APIs | MOVED_TO_ADVANCED | Located only in Research area |
| Research Advanced / research component | Sync evidence, protocol audit, replay, select target, reserve lineage, queue tournament, freeze leader, consume/approve holdout, experiment selection/dimensions | Existing research APIs/local selection | KEEP | Retained behind `/research/advanced`; no governance action changed |
| Experimental Lab / lab component | Refresh, reconcile, arm/pause/resume/kill, attempt/position actions | Existing protected experimental APIs | KEEP | Retained at legacy route linked from Trading; confirmation behavior unchanged |
| Login / login component | Sign in | Owner auth API | KEEP | Unchanged |

No remaining button was intentionally made inert. The existing technical detail screens have not yet had every individual action re-reviewed against live backend permissions; this inventory covers their visible action groups, not a completed endpoint-by-endpoint safety audit.

## Dashboard changes

Added one six-card owner summary for health, mode, pending approvals, positions, risk and Shadow, while preserving the IG Demo equity/P&L view and why-not-trading panel. Removed deep research, chart, risk ledger and service assurance from the default visible route. The existing operations-status payload is the health source used for the summary, but a single backend `PlatformReadiness` endpoint has **not** been implemented; cross-API status harmonization remains open.

## Markets changes

The `/markets` list exposes inventory, data freshness, model status and Demo configuration without fabricating all-market quotes. A market detail route shows selected M1/M5/M15 etc. only when advertised by the backend, latest bid/ask/spread if available, chart, quality details and links to model/trade evidence. The existing chart's auto-follow/latest viewport and error/loading behavior are retained. Full all-market current bid/ask and authoritative eligibility still need a canonical backend market-summary payload.

## Trading changes

Approval and positions remain distinctly IG Demo; Shadow rows are explicitly simulated. The proposal timer is live, an expired proposal cannot be approved or declined in the UI, and the handler rechecks status/expiry before calling the API. This is a UI safety check; the backend remains the authority. High-impact Shadow control and strategy confirmation remain intact. The Experimental Lab is linked from Trading but not yet fully embedded.

## Research, Risk and System changes

Research retains validation, readiness, jobs, forward evidence, replay and strategy details; the existing deep research page is Advanced. Risk has the daily ledger, while System has service/assurance, readiness and reconciliation. Technical values are no longer visible by default on Dashboard. More progressive disclosure within each destination, especially Risk and System, remains to be done.

## Mobile and accessibility

Added stacked owner summary/market rows and full-width, 44px-minimum proposal actions at phone width. Six primary links remain in the existing mobile drawer. Added visible keyboard focus to route links and proposal buttons. Browser preview reached the owner sign-in screen but could not enter authenticated Trading without an owner session, so **real-device/mobile approval visual verification is outstanding**. The component tests verify expiry behavior but not an authenticated phone render.

## Tests and build

Frontend: 32/32 passing (up from 29), including route inventory, owner summary/navigation and expired proposal guard. Production Angular build passes. No quant, broker, risk or submission logic was changed.

## Remaining UI work

1. Backend-provided canonical readiness/attention and all-market quote/eligibility summary, with stale/partial-state semantics. Do not derive a definitive Demo-ready claim in several frontend views.
2. Complete a narrow-phone authenticated review of pending approvals and the Experimental Lab; add explicit success/error/loading coverage for every high-impact control.
3. Split the still-large shared operational component into route-owned components/services and lazy-load only each area's data; finish per-button endpoint audit and progressive detail for Research/Risk/System.

## Continuation: owner summaries and route-owned loading

Added authenticated, read-only `/api/v1/owner/readiness` and `/api/v1/owner/markets` endpoints. The readiness payload separates operational health, selected trading mode, pending approvals, reconciliation, and Demo Auto readiness. It does not claim that selecting Shadow mode proves a forward model is running. Broker, risk, and Human-Approved Demo states are explicitly unverified by this summary; Live remains disabled. The markets endpoint fetches enabled markets in one query, publishes bid/ask/spread only from fresh quality-passed IG M5 candles, and never infers trading eligibility from a candle. Stale, future-dated, or non-IG rows do not yield a current quote. Neither endpoint submits an order or changes trading settings.

The main frontend now consumes these summaries for the owner dashboard and Markets list. Initial route loads fetch only their owning area's evidence. Research training streaming runs only on Research, market streaming only on market detail, and duplicate trade-proposal fetching was removed. This reduces cross-area polling but the 1,157-line shared operational component has **not** yet been split into route-owned components; that architectural work remains.

The authenticated phone-width approval visual check remains **unverified**: the available browser session reaches owner sign-in, without an authenticated owner session. Expiry/disabled-state component tests do not substitute for the visual check. No authentication safeguard was bypassed.

Verification for this continuation: owner-summary backend unit tests **2/2 pass**; frontend tests **33/33 pass**; production Angular build **PASS**. Read-only database execution returned the enabled-market list, with stale quotes correctly withheld on the weekend. An authenticated phone-width approval walkthrough and the route-owned component split are the remaining UI blockers.

## 2026-09-13 continuation: approval component split

The owner trade-proposal panel was extracted from the 1,157-line shared operational template into `trade-approvals.ts`, `trade-approvals.html`, and `trade-approvals.scss`. It owns proposal display, countdown and disabled-action presentation; it emits a decision request to the parent, which retains the existing owner confirmation, duplicate-click guard, API call and post-decision refresh. No broker submission behaviour changed. The responsive 44px-minimum buttons moved with the panel. Two dedicated component tests cover countdown/event emission and expired/busy disabled states. Frontend tests: **35/35 PASS**; production build: **PASS**.

The authenticated phone-width visual check remains **NOT VERIFIED**. A local browser reached the owner sign-in page at `/trading`; the connected browser had no owner session, and no alternate signed-in browser was available. The owner must sign in before the real approval screen can be inspected at phone width. This is not covered by the component tests. Further route-owned component separation beyond approvals remains outstanding.

## 2026-09-13 live frontend release and phone-width verification

The owner signed in to the live IIS-hosted site. At 390px, the previous live build exposed the old anchor-heavy navigation and a 422px document width. The newer six-area frontend was built and activated using the Aurex-only, versioned IIS static release procedure. The final active frontend release is `C:\sites\aurex\releases\20260913-105108`; the prior release path was `C:\sites\aurex\releases\20260910-161236`. No API, trading-worker, broker or risk service was restarted.

The mobile fix constrains the page shell and keeps wide history rows in their own scrollable table. Authenticated live checks after deployment showed `/trading` and `/markets` at a 390px viewport with a 375px document width, no page-level horizontal overflow, six primary navigation destinations, `IG DEMO · NO LIVE CAPITAL` and `LIVE DISABLED` visible, and the trading mode shown as `SHADOW`. Wide historical tables still scroll internally by design.

The production API does **not** yet include `/api/v1/owner/readiness` or `/api/v1/owner/markets`: unauthenticated read-only checks returned 404, while an existing trading-status endpoint returned 401. The frontend therefore falls back to existing read-only trading-status and model-readiness endpoints, verified live on Markets (`REJECTED` model and `Stale or closed` data on the weekend); quote values and trading eligibility remain unavailable/unverified rather than invented. Deploying the new backend endpoints was deliberately deferred because restarting the API would activate unrelated in-progress quant/trading code in the dirty checkout. That remains a separate backend rollout task.

No proposal was pending on the authenticated live account (`0 PROPOSALS`), so the phone-width **empty state and layout** are verified, but the visual Approve/Decline flow on a real pending proposal is still unverified. No synthetic proposal was inserted and no order or approval action occurred. Final frontend tests: **36/36 PASS**; production Angular build: **PASS**.

## 2026-09-13 isolated owner API rollout and approval preview

To avoid restarting the API from a dirty checkout, the two owner-summary GET routes were deployed in a separate localhost-only `AurexOwnerOverviewAPI` service on `127.0.0.1:8011`, with no trading scheduler, order routes or docs. IIS routes only those two exact paths to it; the existing `AurexPlatformAPI` and trading workers were not restarted. Unauthenticated live GETs now return 401 rather than 404; the existing trading-status route still returns 401. An authenticated live browser check showed the nine-market summary and the Dashboard owner readiness response (`HEALTHY`, `SHADOW`, zero approvals, Shadow activity not attested by mode alone). The Sunday market quotes remain withheld as stale, and trading eligibility remains `UNVERIFIED`. The active IIS release containing the proxy rule is `C:\sites\aurex\releases\20260913-113048`.

The owner overview API and market-summary focused tests passed **4/4**. A localhost network check confirmed the isolated app responds 401 without a session, 405 to POST, and 404 for `/docs` and `/api/v1/trading/status`.

For the pending-proposal mobile visual gap, the actual approval component was rendered at 390px in a temporary local-only preview with active and expired test rows. The page stayed within the viewport (375px document width), both action buttons measured about 126px wide by 50px high, expired buttons were disabled, and the preview action produced only a local notice. The temporary preview route and fixture were removed after inspection; they were never deployed or connected to a broker/API. A **real, authenticated live pending-proposal flow is still unverified** because the account has no pending proposal. No live proposal or order was fabricated.

## 2026-09-13 continuation: Risk split and advanced evidence

The authenticated live Trading page still reports **0 proposals**. A real owner Approve/Decline interaction at phone width therefore remains unverified; no proposal was manufactured and no trading action was taken.

Risk's read-only ledger presentation was extracted from the shared operational template into `risk-summary.ts`, `risk-summary.html`, and `risk-summary.scss`. The normal Risk view prioritises daily drawdown, daily loss limit, reserved risk and per-trade risk; other ledger fields are retained behind an accessible Advanced details disclosure. This does not change risk policy or calculations. Research forward-evidence cards and System operational assurance cards now use native Advanced disclosures, retaining the underlying evidence and read-only APIs.

The button search covered Angular templates in `apps/web/src/app`. The new Risk disclosure is a native summary, not a backend action. The Research replay and official-source refresh actions remain functional advanced research actions; Shadow controls, trade approval actions and experimental programme controls retain their existing backend handlers and safety checks. A complete action-by-action classification and remaining shared-component split are **not yet done**; do not treat this pass as the full UI definition of done.

Verification for this continuation: frontend tests **37/37 PASS** and production Angular build **PASS**. These changes are local only; they have **not** been deployed to the live site or visually verified there.
