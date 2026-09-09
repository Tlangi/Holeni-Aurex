# Aurex Forex intelligence boundary

The intelligence subsystem is research-only. It persists validated, structured evidence and has no
broker, position, risk-policy, reconciliation, or execution imports. An agent recommendation cannot
become an order. Existing Aurex qualification, deterministic risk controls, execution policy, and
reconciliation remain authoritative.

The official `TauricResearch/TradingAgents` v0.4.0 source is installed in a dedicated environment
and pinned to commit `c95f83dfafa748801ab2be4855e6fcffc93804e4`. It is an internal model-enhancement
framework, not merely a reference and not a replacement for Aurex ML. Aurex deliberately does not
construct its stock graph because that graph registers external equity/news/fundamental tools.
Instead, a tool-free Forex adapter invokes its local-provider client with only an approved,
point-in-time `AurexTradingAgentsContext`.

TradingAgents inference is `LOCAL_ONLY`. The only accepted providers are local Ollama and a local
OpenAI-compatible server over HTTP at loopback or an explicit private IP. Public providers, public
addresses, DNS hostnames, redirects, and cloud fallback are rejected. Hosted-provider environment
keys are removed from the isolated worker before imports. Network-layer service isolation remains
required before activation.

Provider configuration is optional and environment-driven. Missing credentials produce an explicit
`DEGRADED` state, never a neutral value that can silently permit a trade. Raw provider keys are held
only in process configuration and are never returned by the status API or persisted with evidence.

`llm_runtime.py` supplies an asynchronous OpenAI-compatible transport with a configurable timeout,
bounded exponential retry, rate-limit handling, strict JSON/schema parsing, and an in-process circuit
breaker. Provider failures raise an explicit unavailable state; they are never converted into an
agent decision. The transport accepts an injected implementation so timeout, retry, malformed-output,
schema, and circuit behaviour can be tested without network access or real credentials.

Only decisions marked `POINT_IN_TIME_VERIFIED` with an audit result of `PASS` may express LONG or
SHORT. All other evidence must be NEUTRAL or REJECT. Database constraints repeat this invariant.

Migration `041_forex_intelligence_gateway.sql` creates the immutable decision/provenance ledger.
Migration `049_tradingagents_research.sql` adds TradingAgents run, decision, feature-hypothesis and
outcome provenance. Migration `050_owner_trade_proposals.sql` adds an expiring owner-review queue.
Approving a proposal records `OWNER_APPROVED_FOR_RISK` only; it does not submit an order. Demo and
Live trading remain independently governed.

## Authority and improvement flow

```text
Aurex canonical market/macro/event/cost evidence
          + Aurex ML and native-agent outputs
                            |
              local TradingAgents research
                            |
        structured rationale, critique and hypotheses
                            |
       governed experiment / model tournament / shadow
                            |
              deterministic Aurex risk
                            |
                 reconciliation / IG
```

TradingAgents and the local LLM have no broker credentials, model-promotion permission, risk
override, or execution authority. Suggested features remain hypotheses until definition, leakage,
availability, training-only preprocessing, and chronological evaluation gates pass. Raw
chain-of-thought is never requested or stored.

The server audit on 2026-09-09 found no local inference runtime, no usable GPU, six logical CPU
cores, 16 GB RAM with approximately 0.9 GB available at inspection time, and about 95 GB free disk.
Downloading or activating a model on the live host is therefore deferred until memory capacity is
available or a separately approved private inference host is provisioned. Failure state is
`LOCAL_LLM_UNAVAILABLE`; no external fallback occurs.
