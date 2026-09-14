"""Read-only per-prediction GBP/USD M1 source/quality/path inventory.

Never changes research, execution or broker state. The selected predictions are
recomputed by the frozen development diagnostic, then independently checked
against canonical and historical M1 stores.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from scripts.diagnose_gbpusd_economic_bridge import run


def classify(entry_at: datetime, canonical: list[dict], historical: list[dict],
             *, max_hold: int = 60) -> dict[str, object]:
    """Evidence classification; historical vendor rows never become IG execution rows."""
    required = {entry_at + timedelta(minutes=i) for i in range(max_hold)}
    canonical_at = {r["open_time_utc"].replace(tzinfo=timezone.utc): r for r in canonical}
    history_ig = {r["timestamp_utc"].replace(tzinfo=timezone.utc): r for r in historical
                  if str(r["source"]).startswith("IG_")}
    history_vendor = {r["timestamp_utc"].replace(tzinfo=timezone.utc): r for r in historical
                      if str(r["source"]).startswith("DUKASCOPY")}
    valid_ig = {stamp for stamp, r in canonical_at.items()
                if str(r["source"]).startswith("IG_LIGHTSTREAMER")
                and r["completed"] and r["quality_status"] == "PASS"
                and all(r.get(side) is not None for side in
                        ("bid_open", "bid_high", "bid_low", "bid_close",
                         "ask_open", "ask_high", "ask_low", "ask_close"))}
    valid_ig |= {stamp for stamp, r in history_ig.items()
                 if r["quality_state"] in {"VALIDATED", "GOOD", "ACCEPTABLE"}
                 and r["price_completeness"] == "BID_ASK_FULL"}
    present_path = sorted(required & valid_ig)
    missing = sorted(required - valid_ig)
    entry = canonical_at.get(entry_at)
    if entry_at in valid_ig:
        reason = "IG_ENTRY_PRESENT_PATH_GAP" if missing else "COMPLETE_IG_PATH"
    elif entry is not None and str(entry["source"]).startswith("IG_"):
        reason = "IG_ENTRY_PRESENT_BUT_FILTERED"
    elif entry_at in history_ig:
        reason = "IG_ENTRY_IN_HISTORICAL_STORE_ONLY"
    elif entry_at in history_vendor:
        reason = "BROKER_EXECUTION_PATH_UNAVAILABLE_VENDOR_RESEARCH_ONLY"
    else:
        reason = "M1_HISTORY_NOT_COLLECTED"
    return {
        "entry_timestamp": entry_at.isoformat(), "classification": reason,
        "canonical_entry_source": entry["source"] if entry else None,
        "canonical_entry_quality": entry["quality_status"] if entry else None,
        "canonical_entry_completed": bool(entry["completed"]) if entry else None,
        "historical_ig_entry": entry_at in history_ig,
        "historical_vendor_entry": entry_at in history_vendor,
        "ig_valid_m1_count": len(present_path), "missing_ig_m1_count": len(missing),
        "ig_path_start": present_path[0].isoformat() if present_path else None,
        "ig_path_end": present_path[-1].isoformat() if present_path else None,
        "first_missing_ig_m1": missing[0].isoformat() if missing else None,
        "bid_available": bool(entry and all(entry.get(x) is not None for x in
                                  ("bid_open", "bid_high", "bid_low", "bid_close"))),
        "ask_available": bool(entry and all(entry.get(x) is not None for x in
                                  ("ask_open", "ask_high", "ask_low", "ask_close"))),
        "spread_available": bool(entry and entry.get("spread_close") is not None),
        "canonical_sources": dict(Counter(str(r["source"]) for r in canonical)),
        "historical_sources": dict(Counter(str(r["source"]) for r in historical)),
    }


def main() -> None:
    diagnostic = run()
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol='GBPUSD'")
        market_id = str(cursor.fetchone()["market_id"])
        output = []
        for prediction in diagnostic["rows"]:
            decision = datetime.fromisoformat(prediction["decision_utc"])
            entry = decision + timedelta(minutes=15)
            end = entry + timedelta(minutes=60)
            cursor.execute("""SELECT open_time_utc,source,completed,quality_status,
                   bid_open,bid_high,bid_low,bid_close,ask_open,ask_high,ask_low,ask_close,spread_close
                   FROM app.candles WHERE market_id=%s AND timeframe='M1'
                     AND open_time_utc>=%s AND open_time_utc<%s""",
                   (market_id, entry.replace(tzinfo=None), end.replace(tzinfo=None)))
            canonical = cursor.fetchall()
            cursor.execute("""SELECT timestamp_utc,source,quality_state,price_completeness
                   FROM app.market_candles_m1 WHERE market_id=%s
                     AND timestamp_utc>=%s AND timestamp_utc<%s""",
                   (market_id, entry.replace(tzinfo=None), end.replace(tzinfo=None)))
            historical = cursor.fetchall()
            output.append({"prediction_id": prediction["prediction_id"],
                           "decision_timestamp": prediction["decision_utc"],
                           "direction": prediction["direction"],
                           "outcome_status": prediction["status"],
                           "outcome_reason": prediction.get("reason"),
                           **classify(entry, canonical, historical)})
    print(json.dumps({"market": "GBPUSD", "authority": "READ_ONLY_EVIDENCE_DIAGNOSTIC",
                      "dataset_sha256": diagnostic["dataset_sha256"],
                      "selected_count": len(output), "predictions": output}, indent=2, default=str))


if __name__ == "__main__":
    main()
