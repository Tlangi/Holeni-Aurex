"""Read-only, nine-market, three-view IG M1 quality diagnostic. Never persists."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker_m1_quality import assess_m1_rows
from app.config import get_settings
from app.database import open_database
from app.market_calendar import is_regular_session


def main() -> None:
    now = datetime.now(timezone.utc)
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        markets = cursor.fetchall()
        report = []
        for market in markets:
            cursor.execute("""SELECT holiday_date FROM app.market_holidays
                              WHERE calendar_code=%s AND session_close_local IS NULL""",
                           (market["calendar_code"],))
            holidays = {row["holiday_date"] for row in cursor.fetchall()}
            def expected(at: datetime) -> bool:
                return is_regular_session(at, calendar_code=market["calendar_code"],
                                          market_timezone=market["market_timezone"],
                                          session_open=market["session_open_local"],
                                          session_close=market["session_close_local"],
                                          holidays=holidays)
            cursor.execute("""SELECT TOP(12000) open_time_utc,source,completed,
                                  quality_status,ingested_at_utc,bid_open,bid_high,
                                  bid_low,bid_close,ask_open,ask_high,ask_low,ask_close
                              FROM app.candles WHERE market_id=%s AND timeframe='M1'
                              ORDER BY open_time_utc DESC,candle_id DESC""",
                           (str(market["market_id"]),))
            rows = cursor.fetchall()
            views = [assess_m1_rows(rows, view=view, expected_session=expected,
                                    now_utc=now) for view in (
                                        "RAW_IG", "HYBRID_RESEARCH", "CURRENT_IG_EXECUTION")]
            report.append({"market": market["symbol"], "views": views})
    print(json.dumps({"authority": "RESEARCH_DIAGNOSTIC_ONLY", "persisted": False,
                      "checked_at_utc": now.isoformat(), "markets": report},
                     indent=2, default=str))


if __name__ == "__main__":
    main()
