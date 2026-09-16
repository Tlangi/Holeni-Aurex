"""Read-only IG M1 path inventory for every stored market decision on nine markets.

Usage: .venv/Scripts/python.exe scripts/report_prediction_ig_m1_paths.py
       .venv/Scripts/python.exe scripts/report_prediction_ig_m1_paths.py --output PATH

The full artifact includes each immutable recorded decision. It contains no
training label, holdout read, model promotion or broker submission.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.market_calendar import is_regular_session
from app.prediction_path_inventory import (
    INVENTORY_POLICY_VERSION, RecordedDecision, assess_recorded_path,
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def collect() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        markets = cursor.fetchall()
        by_market = []
        for market in markets:
            cursor.execute("""SELECT holiday_date FROM app.market_holidays
                              WHERE calendar_code=%s AND session_close_local IS NULL""",
                           (market["calendar_code"],))
            holidays = {row["holiday_date"] for row in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                                          market_timezone=market["market_timezone"],
                                          session_open=market["session_open_local"],
                                          session_close=market["session_close_local"],
                                          holidays=holidays)
            cursor.execute("""SELECT d.market_decision_id,d.generated_at_utc,d.model_version_id,
                                  d.decision,d.executable,c.timeframe,c.open_time_utc
                              FROM app.market_decisions d
                              LEFT JOIN app.candles c ON c.candle_id=d.candle_id
                              WHERE d.market_id=%s ORDER BY d.generated_at_utc,d.market_decision_id""",
                           (str(market["market_id"]),))
            decision_rows = cursor.fetchall()
            cursor.execute("""SELECT open_time_utc,source,completed,quality_status,
                                  bid_open,bid_high,bid_low,bid_close,
                                  ask_open,ask_high,ask_low,ask_close,
                                  COALESCE(ingested_at_utc,created_at_utc) observed_at_utc
                              FROM app.candles WHERE market_id=%s AND timeframe='M1'
                                AND source LIKE 'IG_LIGHTSTREAMER%%'
                              ORDER BY open_time_utc,COALESCE(ingested_at_utc,created_at_utc)""",
                           (str(market["market_id"]),))
            candle_rows = cursor.fetchall()
            stamp_counts = Counter(row["open_time_utc"] for row in candle_rows)
            duplicate_stamps = {pd.Timestamp(at, tz="UTC") for at,count in
                                stamp_counts.items() if count > 1}
            canonical = {}
            for row in candle_rows:
                canonical[row["open_time_utc"]] = row
            if canonical:
                frame = pd.DataFrame(list(canonical.values()))
                frame.index = pd.DatetimeIndex(frame.pop("open_time_utc"), tz="UTC")
            else:
                frame = pd.DataFrame(columns=("source", "completed", "quality_status",
                    "bid_open", "bid_high", "bid_low", "bid_close", "ask_open",
                    "ask_high", "ask_low", "ask_close"),
                    index=pd.DatetimeIndex([], tz="UTC"))
            detail = []
            for row in decision_rows:
                recorded = RecordedDecision(
                    decision_id=str(row["market_decision_id"]),
                    market=str(market["symbol"]),
                    generated_at_utc=row["generated_at_utc"].replace(tzinfo=timezone.utc),
                    candle_open_utc=row["open_time_utc"].replace(tzinfo=timezone.utc)
                        if row["open_time_utc"] else None,
                    candle_timeframe=row["timeframe"],
                    model_version_id=str(row["model_version_id"])
                        if row["model_version_id"] else None,
                    decision=row["decision"], executable=bool(row["executable"]))
                detail.append(assess_recorded_path(
                    recorded, frame, regular_session=regular, now_utc=now,
                    duplicate_timestamps=duplicate_stamps))
            reasons = Counter(item["reason"] or item["status"] for item in detail)
            by_market.append({"market": market["symbol"],
                "recorded_decisions": len(detail),
                "buy_sell_decisions": sum(item["decision"] in {"BUY", "SELL"} for item in detail),
                "recorded_executable": sum(item["recorded_executable"] for item in detail),
                "complete_ig_m1_paths": sum(item["status"] == "COMPLETE_IG_M1_PATH" for item in detail),
                "raw_ig_m1_rows": len(candle_rows),
                "duplicate_ig_m1_timestamps": len(duplicate_stamps),
                "coverage_reasons": dict(sorted(reasons.items())),
                "predictions": detail})
    payload = {"authority": "NONPROMOTABLE_COVERAGE_ONLY",
               "inventory_policy_version": INVENTORY_POLICY_VERSION,
               "snapshot_at_utc": now.isoformat(), "holdout_accessed": False,
               "markets": by_market}
    payload["artifact_sha256"] = sha256(_canonical(payload).encode()).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Write full immutable-identity coverage artifact as JSON")
    args = parser.parse_args()
    payload = collect()
    if args.output:
        if args.output.exists():
            raise FileExistsError("Frozen inventory output already exists; choose a new snapshot path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"authority": payload["authority"],
        "inventory_policy_version": payload["inventory_policy_version"],
        "snapshot_at_utc": payload["snapshot_at_utc"],
        "artifact_sha256": payload["artifact_sha256"],
        "holdout_accessed": False,
        "output": str(args.output.resolve()) if args.output else None,
        "markets": [{key:value for key,value in market.items() if key != "predictions"}
                    for market in payload["markets"]]}, indent=2))


if __name__ == "__main__":
    main()
