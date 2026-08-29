# Aurex market inventory

This file is the operational source of truth for enabled instruments. Database
`app.markets` remains the runtime authority.

| Symbol | Display name | Asset class | Broker epic | Currency | Calendar | Regular model session |
|---|---|---|---|---|---|---|
| EURUSD | EUR/USD | FX | `CS.D.EURUSD.CFD.IP` | USD quote | `FX_24X5` | 24-hour weekday evidence |
| GBPUSD | GBP/USD | FX | `CS.D.GBPUSD.CFD.IP` | USD quote | `FX_24X5` | 24-hour weekday evidence |
| USDJPY | USD/JPY | FX | `CS.D.USDJPY.CFD.IP` | JPY quote | `FX_24X5` | 24-hour weekday evidence |
| GERMANY40 | Germany 40 Cash (E1) | INDEX | `IX.D.DAX.BMU.IP` | EUR deal currency | `XETRA_REGULAR` | 09:00–17:30 Europe/Berlin; official 2026 non-trading dates seeded |

The Germany calendar identifies the regular cash evidence window. The broker's
current `marketStatus` remains the execution authority for extended-hours dealing.
Weekend instruments, options and expiring Germany 40 futures are not allow-listed.

The Xetra dates must be refreshed from Deutsche Börse's official calendar before
each new calendar year. A missing future-year calendar is a readiness blocker,
not permission to assume a normal session.

## Strategy-evidence state — 26 August 2026

| Symbol | Feature-complete M15 rows | Historical sufficiency | Latest model | Execution |
|---|---:|---|---|---|
| EURUSD | 61,435 | SUFFICIENT | REJECTED | SHADOW |
| GBPUSD | 50,983 | SUFFICIENT | REJECTED | SHADOW |
| USDJPY | 10,997 | SUFFICIENT | REJECTED | SHADOW |
| GERMANY40 | 2,225 | SUFFICIENT | REJECTED | SHADOW |

Counts change as IG streaming continues. The database and authenticated research
API are runtime authority. A provider boundary is not market continuity: every
feature and replay trade resets or closes at a declared discontinuity.

Germany 40 holdout checkpoint: 2,006 feature-complete development rows and 234
independent holdout rows are available under the safe 500-raw-row reservation.
The required holdout floor is 500 feature-complete rows, so candidate freezing is
`DATA_BLOCKED`; no final holdout was consumed.

Calendar source: [Deutsche Börse — Trading calendar 2026](https://www.cashmarket.deutsche-boerse.com/resource/blob/4580826/3e974decb414d6769cc2bc8e601f6c9a/data/xetra-trading-calendar-2026.pdf).
