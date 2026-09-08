from datetime import datetime, timezone
import argparse, json, sys
from pathlib import Path

API_ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_ROOT))
from app.config import get_settings
from app.historical_backfill import enqueue_phase

parser=argparse.ArgumentParser(description="Queue bounded monthly historical M1 partitions for all research markets")
parser.add_argument("--from",dest="start",required=True); parser.add_argument("--to",dest="end",required=True)
args=parser.parse_args()
start=datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
end=datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
print(json.dumps(enqueue_phase(get_settings(),start_utc=start,end_utc=end),default=str))
