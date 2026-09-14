"""Read-only IG Demo market-hour evidence; never changes broker or trading state."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.ig_demo import IGDemoClient


def main() -> None:
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT symbol,ig_epic FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
    result = []
    with IGDemoClient(settings) as client:
        for symbol, epic in markets:
            payload = client.market_details(str(epic))
            instrument = payload.get("instrument") or {}
            snapshot = payload.get("snapshot") or {}
            result.append({"market": symbol, "epic": epic,
                           "opening_hours": instrument.get("openingHours"),
                           "market_status": snapshot.get("marketStatus"),
                           "snapshot_update_utc": snapshot.get("updateTimestampUTC"),
                           "raw_sha256": sha256(json.dumps(payload, sort_keys=True,
                                                            separators=(",", ":"), default=str).encode()).hexdigest()})
    print(json.dumps({"checked_at_utc": datetime.now(timezone.utc).isoformat(),
                      "authority": "READ_ONLY_IG_DEMO_MARKET_HOURS", "markets": result},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
