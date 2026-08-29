from __future__ import annotations

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.market_data import bootstrap_markets  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import completed IG demo M15 candles")
    parser.add_argument("--count", type=int, default=96,
                        help="M15 candles to seed; 96 is approximately one weekday")
    arguments = parser.parse_args()
    if arguments.count < 1 or arguments.count > 200:
        parser.error("--count must be between 1 and 200; use streaming for ongoing data")
    print(bootstrap_markets(get_settings(), count=arguments.count))
