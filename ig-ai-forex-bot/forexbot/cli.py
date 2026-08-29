from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time
from datetime import date, datetime

from .startup import missing_dependency_message

try:
    from .core import load_settings
    from .model import predict, train
    from .ig_gateway import IGGateway
    from .risk import daily_loss_blocked
    from .journal import Journal
    from .reporting import create_trade_report
    from .emailing import send_report
    from .errors import BotError, CycleFailed
    from .candle_store import CandleStore
    from .streaming import IGStreamingFeed
except ModuleNotFoundError as exc:
    print(missing_dependency_message(exc.name), file=sys.stderr)
    raise SystemExit(4) from None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("forexbot")


def train_all(gateway, settings):
    for symbol in settings.data["symbols"]:
        df = gateway.bars(symbol, settings.data["history_bars"])
        model_cfg = settings.data["model"]
        stats = train(df, model_cfg["horizon_bars"], f"models/{symbol}.joblib",
                      model_cfg["minimum_training_rows"], model_cfg["minimum_validation_auc"])
        log.info("trained %s: %s", symbol, json.dumps(stats))


def write_and_optionally_email_report(settings, journal, account, email=False, label="Trade summary"):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = create_trade_report(journal, f"reports/trade-report-{stamp}.xlsx", account)
    log.info("report written: %s", path)
    if email:
        send_report(settings, path, f"IG demo bot - {label}",
                    "Attached is the latest IG demo trading balance and trade-event summary.")
        log.info("report emailed to %s", settings.report_recipient)
    return path


def run(gateway, settings, journal, once=False, execute=True, stream=None):
    buy_at, sell_at = settings.data["model"]["buy_probability"], settings.data["model"]["sell_probability"]
    while True:
        evaluated = failures = orders = 0
        account = gateway.account()
        journal.snapshot(account)
        start_equity = journal.daily_start_equity(account.equity)
        blocked = daily_loss_blocked(account.equity, start_equity, settings.data["risk"]["max_daily_loss_pct"])
        positions = ()
        if blocked:
            log.error("daily loss limit reached; new entries blocked until next local day")
        else:
            positions = gateway.open_positions()
        if not blocked and len(positions) >= settings.data["risk"]["max_open_positions"]:
            log.warning("global position limit reached")
        elif not blocked:
            for symbol in settings.data["symbols"]:
                try:
                    if stream and not stream.is_healthy():
                        raise CycleFailed(f"{symbol}: live price stream is unavailable or stale; order blocked")
                    bars = gateway.cached_bars(symbol, 300) if stream else gateway.bars(symbol, 300)
                    bar_time = bars.iloc[-1].time.to_pydatetime()
                    if journal.bar_processed(symbol, bar_time):
                        log.info("%s closed candle already processed", symbol); continue
                    epic = settings.data["instruments"][symbol]["epic"]
                    symbol_positions = [p for p in positions if (p.get("market") or {}).get("epic") == epic]
                    if len(symbol_positions) >= settings.data["risk"]["max_positions_per_symbol"]:
                        journal.mark_bar(symbol, bar_time); continue
                    model_path = f"models/{symbol}.joblib"
                    if not Path(model_path).exists():
                        log.warning("missing model for %s; run train", symbol); continue
                    probability, atr = predict(bars, model_path)
                    evaluated += 1
                    side = "BUY" if probability >= buy_at else "SELL" if probability <= sell_at else None
                    log.info("%s probability_up=%.3f signal=%s mode=%s", symbol, probability, side or "HOLD", "EXECUTE" if execute else "DRY-RUN")
                    if execute:
                        journal.mark_bar(symbol, bar_time)
                    if side and execute:
                        result = gateway.market_order(symbol, side, atr)
                        orders += 1
                        request = result.request
                        journal.record_trade(symbol=symbol, side=side, volume=request.volume, price=result.price,
                                             stop_loss=request.sl, take_profit=request.tp, probability=probability,
                                             ticket=str(result.order), status="submitted", message=str(result.comment))
                        account = gateway.account(); journal.snapshot(account)
                        if settings.data["reporting"]["email_on_trade"]:
                            write_and_optionally_email_report(settings, journal, account, email=True, label=f"{side} {symbol}")
                except BotError as exc:
                    failures += 1
                    log.error("%s", exc)
                except Exception:
                    failures += 1
                    log.error("unexpected symbol failure for %s; %s", symbol, "see service logs and run tests")
        report_cfg = settings.data["reporting"]
        today = date.today().isoformat()
        if execute and report_cfg["daily_email_enabled"] and datetime.now().hour >= report_cfg["daily_email_hour_local"] and journal.get("last_daily_email") != today:
            try:
                write_and_optionally_email_report(settings, journal, account, email=True, label="Daily summary")
                journal.set("last_daily_email", today)
            except Exception:
                log.exception("daily email failed; will retry on next cycle")
        log.info("cycle summary evaluated=%d failed=%d orders=%d", evaluated, failures, orders)
        if once:
            if evaluated == 0 and failures:
                raise CycleFailed("Cycle failed: no symbols were evaluated and no orders were submitted. "
                                  "Wait for the IG historical allowance to reset, then run dry-run once to seed the cache.")
            return
        time.sleep(settings.data["poll_seconds"])


def stream_status(gateway, settings, collect=False) -> None:
    feed = IGStreamingFeed(gateway)
    feed.start()
    try:
        if not feed.wait_until_ready(30):
            health = feed.health()
            raise CycleFailed(
                f"IG stream did not become healthy within 30s (status={health.status}, "
                f"symbols_seen={health.symbols_seen}/{len(settings.data['symbols'])})"
            )
        health = feed.health()
        log.info("IG stream verified status=%s symbols=%d", health.status, health.symbols_seen)
        if not collect:
            return
        log.info("collector running; completed M5 and aggregated M15 candles are stored in data/candles/<symbol>.csv")
        while True:
            time.sleep(30)
            health = feed.health()
            if health.last_update_age is None or health.last_update_age > 90:
                log.error("IG stream stale status=%s age=%s", health.status, health.last_update_age)
    except KeyboardInterrupt:
        log.info("collector stopped by operator")
    finally:
        feed.stop()


def collect_sample(gateway, settings, seconds: int) -> None:
    if not 10 <= seconds <= 300:
        raise CycleFailed("--sample-seconds must be between 10 and 300")
    store = gateway.candles
    before = {
        (symbol, timeframe): store.count(symbol, timeframe)
        for symbol in settings.data["symbols"] for timeframe in ("M5", "M15")
    }
    # 0.1 updates/second caps each price item at approximately one update every ten seconds.
    feed = IGStreamingFeed(gateway, prices_only=True, max_frequency="0.1")
    feed.start()
    try:
        if not feed.wait_until_ready(30):
            health = feed.health()
            raise CycleFailed(
                f"Sample stream did not become healthy (status={health.status}, "
                f"symbols_seen={health.symbols_seen}/{len(settings.data['symbols'])})"
            )
        log.info("prices-only sample started duration=%ds pairs=%d max_frequency=0.1/s",
                 seconds, len(settings.data["symbols"]))
        deadline = time.time() + seconds
        while time.time() < deadline:
            time.sleep(min(1, max(0, deadline - time.time())))
        health = feed.health()
        if not feed.is_healthy():
            raise CycleFailed(f"Sample ended with a stale or disconnected stream (status={health.status})")
    except KeyboardInterrupt:
        log.info("sample stopped early by operator")
    finally:
        feed.stop()
    for symbol in settings.data["symbols"]:
        added_m5 = store.count(symbol, "M5") - before[(symbol, "M5")]
        added_m15 = store.count(symbol, "M15") - before[(symbol, "M15")]
        log.info("sample result symbol=%s completed_M5_added=%d completed_M15_added=%d file=%s",
                 symbol, added_m5, added_m15, store.file_path(symbol))
    log.info("sample complete; no account/trade subscriptions were opened and no orders were possible")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "train", "dry-run", "run", "run-once", "report", "email-report", "cache-status", "stream-check", "collect", "sample-stream"])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--sample-seconds", type=int, default=60,
                        help="Duration for sample-stream (10-300 seconds; default 60)")
    args = parser.parse_args()
    if args.command == "sample-stream" and not 10 <= args.sample_seconds <= 300:
        parser.error("--sample-seconds must be between 10 and 300")
    settings, gateway, journal = load_settings(args.config), None, Journal()
    try:
        if args.command == "cache-status":
            store = CandleStore(symbols=settings.data["symbols"])
            timeframe = settings.data["timeframe"]
            for symbol in settings.data["symbols"]:
                first, latest = store.bounds(symbol, timeframe)
                log.info("cache symbol=%s timeframe=%s candles=%d first=%s latest=%s",
                         symbol, timeframe, store.count(symbol, timeframe), first or "none", latest or "none")
            return 0
        if args.command == "report":
            write_and_optionally_email_report(settings, journal, None); return 0
        gateway = IGGateway(settings); gateway.connect()
        account = gateway.account()
        log.info("connected environment=%s equity=%.2f account_lock=verified", account.trade_mode, account.equity)
        if args.command == "check":
            gateway.assert_execution_allowed(); gateway.assert_execution_ready()
            for symbol in settings.data["symbols"]:
                gateway.validate_instrument(symbol)
            log.info("IG demo configuration, account and instruments verified (no historical allowance used)")
        elif args.command == "train": train_all(gateway, settings)
        elif args.command == "email-report": write_and_optionally_email_report(settings, journal, account, email=True)
        elif args.command in {"stream-check", "collect"}: stream_status(gateway, settings, collect=args.command == "collect")
        elif args.command == "sample-stream": collect_sample(gateway, settings, args.sample_seconds)
        elif args.command == "dry-run": run(gateway, settings, journal, once=True, execute=False)
        elif args.command == "run-once": run(gateway, settings, journal, once=True, execute=True)
        else:
            stream = IGStreamingFeed(gateway)
            stream.start()
            try:
                if not stream.wait_until_ready(30):
                    raise CycleFailed("IG live price stream did not become healthy; continuous trading was not started")
                run(gateway, settings, journal, execute=True, stream=stream)
            finally:
                stream.stop()
        return 0
    except BotError as exc:
        log.error("%s", exc)
        return 2
    except Exception as exc:
        log.error("Unexpected failure (%s): %s", type(exc).__name__, exc)
        return 3
    finally:
        if gateway: gateway.close()


if __name__ == "__main__": raise SystemExit(main())
