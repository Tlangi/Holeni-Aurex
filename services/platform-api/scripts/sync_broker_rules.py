from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.broker_rules import sync_broker_market_rules  # noqa: E402
from app.config import get_settings  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synchronize IG demo market dealing rules")
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(sync_broker_market_rules(get_settings(), force=arguments.force), indent=2))
