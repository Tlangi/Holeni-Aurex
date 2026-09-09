from datetime import datetime, timezone
import argparse, json, sys
from pathlib import Path

API_ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_ROOT))
from app.config import get_settings
from app.historical_backfill import enqueue_phase, reconcile_recent_campaign

parser=argparse.ArgumentParser(description="Queue bounded monthly historical M1 partitions for all research markets")
parser.add_argument("--from",dest="start"); parser.add_argument("--to",dest="end")
args=parser.parse_args()
if bool(args.start) != bool(args.end):
    parser.error("--from and --to must be supplied together")
if args.start:
    start=datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end=datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    result=enqueue_phase(get_settings(),start_utc=start,end_utc=end)
else:
    result=reconcile_recent_campaign(get_settings())
print(json.dumps(result,default=str))
