from __future__ import annotations

import signal
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.observability import configure_logging  # noqa: E402
from app.shadow_worker import ShadowTradingWorker  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = ShadowTradingWorker(settings)
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    worker.run_forever()
