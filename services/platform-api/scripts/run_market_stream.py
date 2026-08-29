from __future__ import annotations

import signal
import sys
from pathlib import Path
from threading import Event

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.ig_demo import IGDemoClient  # noqa: E402
from app.market_data import seed_market_history  # noqa: E402
from app.observability import configure_logging  # noqa: E402
from app.streaming import IGMarketStream  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level)
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    with IGDemoClient(settings) as authenticated:
        print({"history_seed": seed_market_history(settings, authenticated)}, flush=True)
        stream = IGMarketStream(settings, authenticated)
        stream.start()
        try:
            stopped.wait()
        finally:
            stream.stop()
