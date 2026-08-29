from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.market_intelligence import backfill_historical_m5  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quota-bounded IG Demo M5 historical backfill")
    parser.add_argument("--page-size", type=int, default=500, choices=range(50, 1001))
    parser.add_argument("--max-pages-per-market", type=int, default=1, choices=range(1, 11))
    parser.add_argument(
        "--market", action="append",
        choices=("EURUSD", "GBPUSD", "USDJPY", "GERMANY40"),
    )
    args = parser.parse_args()
    result = backfill_historical_m5(
        get_settings(), symbols=tuple(args.market or ("EURUSD", "GBPUSD", "USDJPY")),
        page_size=args.page_size, max_pages_per_market=args.max_pages_per_market,
    )
    print(json.dumps(result, indent=2, default=str))
