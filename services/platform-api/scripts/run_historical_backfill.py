from pathlib import Path
from threading import Event
import signal,sys

API_ROOT=Path(__file__).resolve().parents[1]; PROJECT_ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(API_ROOT))
from app.config import get_settings
from app.historical_backfill_worker import HistoricalBackfillWorker
from app.observability import configure_logging

settings=get_settings(); configure_logging(settings.log_level); stopped=Event()
signal.signal(signal.SIGINT,lambda *_:stopped.set()); signal.signal(signal.SIGTERM,lambda *_:stopped.set())
HistoricalBackfillWorker(settings,stopped,PROJECT_ROOT).run()
