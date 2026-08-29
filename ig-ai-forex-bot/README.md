# IG API AI Forex Bot — demo-first

This Python project trains one directional model per forex instrument and trades through IG's HTTPS API. It is deliberately demo-first: the demo endpoint is the default, and the live endpoint requires two explicit safeguards.

This is experimental software, not evidence of a profitable strategy. Leveraged forex/CFD trading can lose money rapidly. Keep the system on demo until its cost-aware backtest and forward results meet the validation gates.

## Included

- IG demo REST authentication and account validation
- IG Lightstreamer live prices, account updates and trade notifications
- Local M5 persistence and completed M15 candle aggregation
- Closed-candle historical data retrieval with a weekly-quota-conscious default
- Separate gradient-boosted models for EURUSD, GBPUSD and USDJPY
- BUY, SELL and HOLD signals
- Explicit IG instrument mappings and conservative configured demo sizes
- Stops, limits, spread checks and exposure limits
- Persistent daily-loss baseline and one-decision-per-candle guard
- Three durable CSV market-history files, SQLite trade journal, Excel balance reports and Gmail SMTP delivery
- Dry-run and executable demo commands
- Automatic Windows Task Scheduler operation
- Double live-trading lock

## Installation

```powershell
cd C:\Projects\Forex\ig-ai-forex-bot
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

The `(.venv)` prefix should be visible in the PowerShell prompt before running the bot. You can avoid interpreter ambiguity by invoking `.\.venv\Scripts\python.exe` directly. Missing dependencies now produce a concise recovery message and exit code 4 instead of a Python traceback.

Create `.env` from `.env.example` and provide the IG demo credentials:

```dotenv
IG_API_KEY=
IG_USERNAME=
IG_PASSWORD=
IG_ACCOUNT_ID=
IG_ENVIRONMENT=demo

ALLOW_LIVE_TRADING=false
LIVE_UNLOCK_PHRASE=
```

`IG_ACCOUNT_ID` is an additional account-selection lock. It must equal the account returned by the demo login. Secrets must remain in `.env`; the file is excluded by `.gitignore`.

Configure Gmail reporting with a Google App Password, not the normal Gmail password:

```dotenv
GMAIL_SMTP_USER=
GMAIL_SMTP_APP_PASSWORD=
TRADE_REPORT_RECIPIENT=
```

## Safe operating sequence

```powershell
python -m pytest -q
python -m forexbot.cli check
python -m forexbot.cli stream-check
python -m forexbot.cli train
python -m forexbot.cli dry-run
python -m forexbot.cli email-report
```

`stream-check` is read-only and verifies all three live subscriptions. `dry-run` cannot place orders. After reviewing its output, one executable demo cycle is `python -m forexbot.cli run-once`; continuous demo operation is `python -m forexbot.cli run`.

For a small, automatically stopped streaming sample, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\sample_stream.ps1 -Seconds 60
```

The sample uses one prices-only subscription containing the three pairs, caps each item at approximately one update per ten seconds, stores only completed candles, never subscribes to account/trade events, and cannot place an order. The allowed duration is 10–300 seconds.

The guarded end-to-end command is:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\e2e_demo_test.ps1
```

Explicit demo execution and automatic startup require:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\e2e_demo_test.ps1 -ExecuteDemoTrade -StartContinuousTask
```

Each stage stops the workflow if its safety gate fails.

## Automatic Windows operation

The IG gateway does not require a desktop trading terminal. Register the task without starting it:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_service_task.ps1
```

After the full demo validation succeeds:

```powershell
Start-ScheduledTask -TaskName "IG AI Forex Bot"
powershell -ExecutionPolicy Bypass -File scripts\service_status.ps1
```

Stop or remove it with `scripts\stop_service_task.ps1` or `scripts\uninstall_service_task.ps1`. Logs are written to `logs/service.log`; persistent safety state is stored in `data/trading.db`; reports are written to `reports/`.

## IG quota and streaming design

- Training defaults to 2,300 M15 candles for each of three instruments: 6,900 historical points total.
- Every downloaded or streamed candle is cached persistently in exactly three market-data files: `data/candles/EURUSD.csv`, `data/candles/GBPUSD.csv` and `data/candles/USDJPY.csv`.
- Each currency file contains both M5 source candles and M15 model candles. Refresh-throttle metadata is stored inside the corresponding CSV, so no candle database or extra state file is required.
- Updates use a temporary file plus an atomic replacement to protect the existing history if the process is interrupted during a write.
- Continuous operation obtains live five-minute chart updates from Lightstreamer, persists them, and builds completed M15 candles locally.
- The trading loop reads its 300-candle feature window only from SQLite. It makes no historical-price calls.
- The last refresh attempt is persisted, so process or service restarts do not immediately repeat the same API request.
- Account and position calls are shared across all instruments in each cycle.
- IG instrument EPICs and dealing sizes can differ by account. `check` must pass before training or execution.

REST history is used only for initial bootstrap/training or deliberate gap recovery. While a historical allowance is exhausted, `python -m forexbot.cli collect` can safely accumulate fresh candles without placing orders. Stop it with Ctrl+C. The continuous `run` command includes the same collector and blocks orders whenever the stream is disconnected or stale.

IG does not charge a separate retail Web API or Lightstreamer subscription fee within its default limits. Demo streaming therefore costs nothing. A live account still incurs normal trading costs such as spreads and overnight funding; optional platform/data products are separate and are not required by this bot.

Inspect the local aggregate cache without calling IG:

```powershell
python -m forexbot.cli cache-status
```

The trading universe is fixed to EUR/USD, GBP/USD and USD/JPY. IG quotes the yen pair as USD/JPY; JPY/USD would be the inverse price and must not be substituted without retraining and reconfiguring the strategy.

## Live lock

Do not enable live operation during demo validation. Live requires all three settings:

```dotenv
IG_ENVIRONMENT=live
ALLOW_LIVE_TRADING=true
LIVE_UNLOCK_PHRASE=I_ACCEPT_LIVE_TRADING_RISK
```

Live activation must be a separate security, execution and performance review.
