from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.replay_engine import ReplayRequest, run_replay  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline deterministic Aurex replay")
    parser.add_argument("--market", required=True, choices=("EURUSD", "GBPUSD", "USDJPY", "GERMANY40"))
    parser.add_argument("--mode", default="VALIDATED_MODEL", choices=("VALIDATED_MODEL", "TECHNICAL_DIAGNOSTIC"))
    parser.add_argument("--max-candles", type=int, default=2000)
    parser.add_argument("--initial-equity-zar", type=Decimal, default=Decimal("100000"))
    args = parser.parse_args()
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenant = cursor.fetchone()
    if not tenant:
        raise SystemExit("No tenant exists")
    result = run_replay(
        settings, str(tenant[0]), ReplayRequest(
            symbol=args.market, mode=args.mode, max_candles=args.max_candles,
            initial_equity_zar=args.initial_equity_zar,
        ),
    )
    print(json.dumps(result, indent=2, default=str))
