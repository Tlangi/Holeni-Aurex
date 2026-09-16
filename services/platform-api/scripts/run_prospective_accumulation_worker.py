"""Periodic, idempotent worker for prospective opportunity transitions."""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from threading import Event

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings
from app.observability import configure_logging
from scripts.run_prospective_accumulation_cycle import run_cycle


if __name__ == "__main__":
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("aurex.prospective_accumulation")
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            logger.info("prospective accumulation cycle", extra={"result": run_cycle()})
        except Exception:
            logger.exception("prospective accumulation cycle failed")
        stopped.wait(300)
