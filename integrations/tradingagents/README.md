# Aurex TradingAgents isolation boundary

This directory integrates the official `TauricResearch/TradingAgents` release as
an internal, research-only dependency. The pinned checkout and virtual
environment are deliberately untracked and reproducible from
`PINNED-UPSTREAM.json` and `install.ps1`.

The Aurex worker does not construct the upstream stock graph because that graph
registers external Yahoo/news/fundamental tools. It reuses the pinned official
TradingAgents local-provider client and role framework through a tool-free Forex
orchestration layer. Its only input is a minimized, point-in-time Aurex context.

Security invariants:

- provider is `ollama` or `openai_compatible`;
- endpoint is HTTP loopback or an explicit RFC1918 literal;
- redirects and cloud fallback are forbidden;
- no native TradingAgents data tools are registered;
- no IG, database, SMTP, user, filesystem, or session secrets are accepted;
- output is research evidence and cannot promote a model or reach execution;
- raw chain-of-thought is neither requested nor persisted.

The worker communicates using one JSON request and response. It has no database
or broker credentials. A separate orchestrator may persist validated output in
the additive migration `049_tradingagents_research.sql`.
