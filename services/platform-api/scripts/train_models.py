from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.model_pipeline import train_all_markets  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chronologically train and validate M15 models")
    parser.add_argument("--minimum-rows", type=int, default=2000)
    parser.add_argument("--minimum-auc", type=float, default=0.52)
    parser.add_argument("--window-policy", choices=["FULL_HISTORY", "RECENT_CONSECUTIVE", "ROLLING_WINDOW"], default="FULL_HISTORY")
    parser.add_argument("--window-start", help="UTC ISO timestamp for RECENT_CONSECUTIVE")
    parser.add_argument("--window-end", help="UTC ISO timestamp")
    parser.add_argument("--rolling-days", type=int, default=90)
    parser.add_argument("--retrain-type", choices=["SCHEDULED_RETRAIN", "RESEARCH_RETRAIN"], default="SCHEDULED_RETRAIN")
    parser.add_argument("--material-change", default=None)
    args = parser.parse_args()
    floor = 500 if args.retrain_type == "RESEARCH_RETRAIN" else 2000
    if args.minimum_rows < floor:
        parser.error(f"--minimum-rows cannot be below the {floor}-row floor for this retrain type")
    if not 0.5 <= args.minimum_auc <= 0.9:
        parser.error("--minimum-auc must be between 0.5 and 0.9")
    print(json.dumps(train_all_markets(get_settings(), minimum_rows=args.minimum_rows,
                                       acceptance_auc=args.minimum_auc,
                                       retrain_type=args.retrain_type,
                                       material_change=args.material_change,
                                       window_policy=args.window_policy,
                                       window_start_utc=datetime.fromisoformat(args.window_start).replace(tzinfo=timezone.utc) if args.window_start else None,
                                       window_end_utc=datetime.fromisoformat(args.window_end).replace(tzinfo=timezone.utc) if args.window_end else None,
                                       rolling_days=args.rolling_days), indent=2))
