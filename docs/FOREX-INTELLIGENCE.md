# Aurex Forex intelligence boundary

The intelligence subsystem is research-only. It persists validated, structured evidence and has no
broker, position, risk-policy, reconciliation, or execution imports. An agent recommendation cannot
become an order. Existing Aurex qualification, deterministic risk controls, execution policy, and
reconciliation remain authoritative.

The current upstream TradingAgents project was reviewed as an architectural reference. Aurex does
not import its equity data adapters, simulated-exchange action, current-time memory, or ticker
assumptions. Those inputs are not proven point-in-time safe for Aurex Forex/CFD qualification.

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
Apply it through the existing migration runner before enabling the optional subsystem. Demo and Live
trading remain disabled.
