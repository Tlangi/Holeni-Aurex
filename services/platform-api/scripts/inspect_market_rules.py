from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402
from app.ig_demo import IGDemoClient  # noqa: E402


if __name__ == "__main__":
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT symbol,ig_epic FROM app.markets WHERE enabled=1 ORDER BY symbol")
        markets = cursor.fetchall()
    safe: list[dict[str, object]] = []
    with IGDemoClient(settings) as client:
        for symbol, epic in markets:
            payload = client.market_details(str(epic))
            instrument = payload.get("instrument") or {}
            snapshot = payload.get("snapshot") or {}
            rules = payload.get("dealingRules") or {}
            safe.append({
                "symbol": symbol,
                "lot_size": instrument.get("lotSize"),
                "one_pip_means": instrument.get("onePipMeans"),
                "value_of_one_pip": instrument.get("valueOfOnePip"),
                "instrument_unit": instrument.get("unit"),
                "decimal_places_factor": snapshot.get("decimalPlacesFactor"),
                "scaling_factor": snapshot.get("scalingFactor"),
                "min_deal_size": rules.get("minDealSize"),
                "min_normal_stop": rules.get("minNormalStopOrLimitDistance"),
            })
    print(json.dumps(safe, indent=2))
