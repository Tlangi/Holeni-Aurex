from __future__ import annotations

import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.ig_demo import IGDemoClient, IGDemoUnavailable  # noqa: E402
from app.market_data import seed_market_history  # noqa: E402
from app.market_data import _completed_historical_bucket, _timestamp  # noqa: E402
from app.market_intelligence import _persist_m5, aggregate_m15_history  # noqa: E402
from app.observability import configure_logging  # noqa: E402
from app.streaming import IGMarketStream  # noqa: E402


def repair_recent_m5(settings, authenticated: IGDemoClient, stream: IGMarketStream) -> dict[str, object]:
    """Use a small authoritative UTC REST window only after stream progression stalls."""
    outcomes: dict[str, object] = {}
    for epic, market in stream.markets.items():
        try:
            prices, _ = authenticated.historical_prices_page(epic, page_size=12, page_number=1)
        except IGDemoUnavailable as exc:
            quota = exc.error_code == "error.public-api.exceeded-account-historical-data-allowance"
            outcomes[str(market["symbol"])] = {
                "status": "DEFERRED" if quota else "FAILED",
                "reason": "IG_HISTORICAL_ALLOWANCE_EXHAUSTED" if quota else exc.error_code,
            }
            # A quota response applies to the authenticated account, so further
            # repair calls would only consume time and prevent stream renewal.
            if quota:
                break
            continue
        completed = [item for item in prices if item.get("snapshotTimeUTC") and
                     _completed_historical_bucket(
                         _timestamp(item["snapshotTimeUTC"]), 5,
                     )]
        persisted = _persist_m5(settings, str(market["market_id"]), completed)
        timestamps = [_timestamp(item["snapshotTimeUTC"]) for item in completed]
        aggregated = aggregate_m15_history(
            settings, str(market["market_id"]),
            start_utc=min(timestamps) if timestamps else None,
            end_utc=max(timestamps) if timestamps else None,
        ) if timestamps else 0
        outcomes[str(market["symbol"])] = {**persisted, "m15_aggregated": aggregated}
    return outcomes


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level)
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    # IG session tokens and Lightstreamer connections are deliberately renewed.
    # A transport can otherwise remain nominally connected while delivering no
    # updates, leaving the Windows service in a misleading Running state.
    while not stopped.is_set():
        with IGDemoClient(settings) as authenticated:
            print({"history_seed": seed_market_history(settings, authenticated)}, flush=True)
            stream = IGMarketStream(settings, authenticated)
            stream.start()
            renewal_at = datetime.now(timezone.utc) + timedelta(hours=8)
            try:
                while not stopped.wait(30):
                    stale = stream.stalled()
                    if datetime.now(timezone.utc) >= renewal_at or stale:
                        if stale:
                            print({"rest_repair": repair_recent_m5(settings, authenticated, stream)},
                                  flush=True)
                        print({"stream_restart": "TOKEN_RENEWAL" if not stale else "STALE_UPDATES"},
                              flush=True)
                        break
            finally:
                stream.stop()
        stopped.wait(5)
