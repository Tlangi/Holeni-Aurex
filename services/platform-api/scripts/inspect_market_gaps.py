from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402


if __name__ == "__main__":
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT m.symbol,c.open_time_utc FROM app.candles c JOIN app.markets m ON m.market_id=c.market_id
               WHERE m.enabled=1 AND c.timeframe='M15' AND c.completed=1 AND c.quality_status='PASS'
               ORDER BY m.symbol,c.open_time_utc"""
        )
        previous = {}
        for row in cursor.fetchall():
            symbol, current = str(row["symbol"]), row["open_time_utc"]
            prior = previous.get(symbol)
            if prior and current - prior > timedelta(minutes=15):
                print({"symbol": symbol, "after": prior, "before": current,
                       "minutes": int((current-prior).total_seconds()/60)})
            previous[symbol] = current
