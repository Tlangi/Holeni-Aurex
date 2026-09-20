# Sunday spot-Gold stale-market alert remediation — 21 September 2026

The operational health monitor sent stale open-market emails after the Sunday 20 September 2026 reopening. At 21:45 UTC the shared alert included XAU/USD and USD/JPY; at 21:52 UTC only XAU/USD remained. The XAU/USD alert resolved at 22:01 UTC. The current read-only health inspection reports no issues, and all nine markets have recent M5 and live snapshot timestamps. The market-stream and health-monitor Windows services are running.

## Cause and authority

The XAU/USD market row uses the generic `FX_24X5` calendar. Its operational monitor therefore expected data from 21:20 UTC on Sunday, even though [IG South Africa's spot-metal product terms](https://www.ig.com/za/help-and-support/articles/767200-what-are-ig-s-commodities-cfd-product-details) normally quote metals from 23:00 London time Sunday, with a 22:00–23:00 London daily break. On 20 September that Sunday opening was 22:00 UTC. Broker-native XAU/USD M1 first appeared at 22:01 UTC on both 13 and 20 September, consistent with those terms.

USD/JPY is separate: its M1 feed produced some Sunday data but had actual missing intervals, and its completed M5 lagged during the alert. The change does not suppress USD/JPY or other FX staleness.

## Change and verification

`operational_session_state` now accepts an optional market symbol. XAU/USD alone uses a DST-aware Europe/London spot-metal operating window and a 20-minute reopen grace. Health, readiness, stream watchdog, research status and recovery callers pass the symbol. The research `is_regular_session` rules, historical candles and execution gates are unchanged. Broker status and executable M1 path requirements remain independent.

Focused calendar/monitor/recovery checks passed (34). The full backend suite passed (404). The engine remains `SHADOW` with `new_orders_enabled=false`. Only `AurexHealthMonitor` was restarted to load the change; `AurexMarketStream` was not restarted. Post-restart `inspect_health` returned no issues and both stale-market alert keys were `RESOLVED`. A future genuine open-session gap still alerts.
