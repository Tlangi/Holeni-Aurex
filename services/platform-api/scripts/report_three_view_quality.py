"""Read-only, calendar-aware M5 quality snapshot. Never changes trading state.

Usage: .venv/Scripts/python.exe scripts/report_three_view_quality.py
The three views are separate even when their latest 2,000 rows overlap.
"""
from __future__ import annotations

import json
import sys
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.market_calendar import is_regular_session
from app.recent_window import assess_recent_m5_window

POLICY = {"version": "THREE_VIEW_M5_CALENDAR_M1_RECOVERY_V3", "latest_completed_m5": 2000,
          "authority": "RESEARCH_DIAGNOSTIC_ONLY"}


def _gap_m1_support(gap: dict, timestamps: set[datetime], is_expected=None) -> dict[str, object]:
    """Count complete M1 support for each missing M5 bar, without filling it."""
    first = datetime.fromisoformat(gap["after_utc"]) + timedelta(minutes=5)
    last = datetime.fromisoformat(gap["before_utc"])
    complete = 0
    partial = 0
    absent = 0
    minute_rows = 0
    missing_intervals = []
    cursor = first
    while cursor < last:
        if is_expected is not None and not is_expected(cursor):
            cursor += timedelta(minutes=5)
            continue
        found = sum(cursor + timedelta(minutes=offset) in timestamps for offset in range(5))
        minute_rows += found
        if found == 5:
            complete += 1
        elif found:
            partial += 1
            missing_intervals.append(cursor.isoformat())
        else:
            absent += 1
            missing_intervals.append(cursor.isoformat())
        cursor += timedelta(minutes=5)
    return {"complete_m5_intervals": complete, "partial_m5_intervals": partial,
            "absent_m5_intervals": absent, "m1_minutes_present": minute_rows,
            "m5_intervals_without_full_m1": missing_intervals}


def _view(rows, market, holidays, view):
    if view == "RAW_IG":
        eligible = [r for r in rows if str(r["source"]).startswith("IG_")]
    elif view == "CURRENT_IG_EXECUTION":
        eligible = [r for r in rows if str(r["source"]).startswith("IG_LIGHTSTREAMER")]
    else:
        eligible = rows
    if market["symbol"] == "GERMANY40":
        # The agreed rolling experiment must not silently pull sparse 2024 rows.
        eligible = [r for r in eligible if r["open_time_utc"].year >= 2026]
    def expected(timestamp):
        return is_regular_session(timestamp, calendar_code=market["calendar_code"],
                                  market_timezone=market["market_timezone"],
                                  session_open=market["session_open_local"],
                                  session_close=market["session_close_local"], holidays=holidays)
    eligible = [r for r in eligible if expected(r["open_time_utc"])]
    # One regular-session row per timestamp, with IG stream > IG historical > research provider.
    rank = lambda r: (0 if str(r["source"]).startswith("IG_LIGHTSTREAMER")
                      else 1 if str(r["source"]).startswith("IG_")
                      else 3 if r.get("research_recovery_store") else 2)
    selected = {}
    for row in sorted(eligible, key=rank, reverse=True):
        selected[row["open_time_utc"]] = row
    canonical = sorted(selected.values(), key=lambda r: r["open_time_utc"])[-2000:]
    result = assess_recent_m5_window(canonical, is_expected_timestamp=expected)
    providers = Counter(str(row["source"]) for row in canonical)
    recovery_refs = [{"open_time_utc": row["open_time_utc"].isoformat(),
                      "source": row["source"], "import_batch_id": str(row["import_batch_id"]),
                      "source_candle_ref": row["source_candle_ref"],
                      "retrieved_at_utc": row["retrieved_at_utc"].isoformat()
                          if row.get("retrieved_at_utc") else None,
                      "source_m1_times_utc": [
                          (row["open_time_utc"] + timedelta(minutes=offset)).isoformat()
                          for offset in range(5)]}
                     for row in canonical if row.get("research_recovery_store")]
    raw_duplicates = sum(count - 1 for count in Counter(r["open_time_utc"] for r in eligible).values())
    return {"view": view, "score_authority": "PROVISIONAL_CALENDAR_DIAGNOSTIC",
            "quality_score_version": POLICY["version"],
            "quality_formula": "100 * observed_quality_passed_completed_regular_session_m5 / (observed + missing_expected_regular_session_m5)",
            "expected": result.observed_rows + sum(g[2] for g in result.gap_ranges),
            "observed": result.observed_rows, "valid_candles": result.observed_rows,
            "missing": sum(g[2] for g in result.gap_ranges),
            "quality_pct": result.completeness_percentage, "duplicates_in_source_rows": raw_duplicates,
            "bid_ask_rows": sum(r["bid_close"] is not None and r["ask_close"] is not None for r in canonical),
            "spread_rows": sum(r["spread_close"] is not None for r in canonical),
            "providers": dict(providers), "first_utc": result.start_utc.isoformat() if result.start_utc else None,
            "research_recovery_count": len(recovery_refs),
            "research_recovery_provenance": recovery_refs,
            "last_utc": result.end_utc.isoformat() if result.end_utc else None,
            "status": "PASS" if result.passed else "BLOCKED",
            "reasons": result.reasons,
            "gaps": [{"after_utc": a.isoformat(), "before_utc": b.isoformat(), "missing": n}
                     for a, b, n in result.gap_ranges]}


def _persist_snapshot(cursor, market_id: str, view: dict) -> None:
    evidence = json.dumps(view, sort_keys=True, separators=(",", ":"), default=str)
    policy = json.dumps(POLICY, sort_keys=True, separators=(",", ":"))
    complete = sum(g["m1_support"]["complete_m5_intervals"] for g in view["gaps"])
    partial = sum(g["m1_support"]["partial_m5_intervals"] for g in view["gaps"])
    absent = sum(g["m1_support"]["absent_m5_intervals"] for g in view["gaps"])
    cursor.execute("""INSERT app.three_view_research_quality_snapshots
        (quality_snapshot_id,market_id,view_code,first_utc,last_utc,observed_count,
         expected_count,missing_count,quality_pct,complete_m1_gap_intervals,
         partial_m1_gap_intervals,absent_m1_gap_intervals,score_authority,
         qualification_status,policy_sha256,evidence_sha256,evidence_json)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid4()), market_id, view["view"],
         datetime.fromisoformat(view["first_utc"]).replace(tzinfo=None) if view["first_utc"] else None,
         datetime.fromisoformat(view["last_utc"]).replace(tzinfo=None) if view["last_utc"] else None,
         view["observed"], view["expected"], view["missing"], view["quality_pct"],
         complete, partial, absent, view["score_authority"], view["status"],
         sha256(policy.encode()).hexdigest(), sha256(evidence.encode()).hexdigest(), evidence))


def main(*, persist: bool = False):
    with open_database(get_settings()) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                          session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        markets = cursor.fetchall()
        report = []
        for market in markets:
            cursor.execute("SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s AND session_close_local IS NULL",
                           (market["calendar_code"],))
            holidays = {item["holiday_date"] for item in cursor.fetchall()}
            def expected(timestamp):
                return is_regular_session(
                    timestamp, calendar_code=market["calendar_code"],
                    market_timezone=market["market_timezone"],
                    session_open=market["session_open_local"],
                    session_close=market["session_close_local"], holidays=holidays)
            cursor.execute("""SELECT TOP(12000) open_time_utc,[open],high,low,[close],source,
                              bid_close,ask_close,spread_close FROM app.candles
                              WHERE market_id=%s AND timeframe='M5' AND completed=1 AND quality_status='PASS'
                              ORDER BY open_time_utc DESC,candle_id DESC""", (str(market["market_id"]),))
            rows = cursor.fetchall()
            cursor.execute("""SELECT TOP(12000) timestamp_utc,source,source_symbol,
                  mid_open,mid_high,mid_low,mid_close,bid_close,ask_close,spread_close,
                  import_batch_id,quality_state,price_completeness,ingested_at_utc
                  FROM app.market_candles_m5 WHERE market_id=%s
                    AND source LIKE 'DUKASCOPY%%' AND research_eligible=1
                    AND quality_state='VALIDATED' AND is_derived=1
                    AND price_completeness='BID_ASK_FULL'
                    AND mid_open IS NOT NULL AND mid_high IS NOT NULL
                    AND mid_low IS NOT NULL AND mid_close IS NOT NULL
                  ORDER BY timestamp_utc DESC""", (str(market["market_id"]),))
            recovery_rows = cursor.fetchall()
            for recovery in recovery_rows:
                stamp = recovery["timestamp_utc"]
                rows.append({"open_time_utc": stamp, "open": recovery["mid_open"],
                             "high": recovery["mid_high"], "low": recovery["mid_low"],
                             "close": recovery["mid_close"], "source": recovery["source"],
                             "bid_close": recovery["bid_close"], "ask_close": recovery["ask_close"],
                             "spread_close": recovery["spread_close"],
                             "research_recovery_store": True,
                             "import_batch_id": recovery["import_batch_id"],
                             "source_candle_ref": f"{market['market_id']}:{stamp.isoformat()}:{recovery['source']}",
                             "retrieved_at_utc": recovery["ingested_at_utc"]})
            views = [_view(rows, market, holidays, view) for view in
                     ("RAW_IG", "HYBRID_RESEARCH", "CURRENT_IG_EXECUTION")]
            for view in views:
                if view["first_utc"] and view["last_utc"]:
                    source_clause = ("AND source LIKE 'IG_LIGHTSTREAMER%%'" if view["view"] == "CURRENT_IG_EXECUTION"
                                     else "AND source LIKE 'IG_%%'" if view["view"] == "RAW_IG" else "")
                    cursor.execute(f"""SELECT COUNT(DISTINCT open_time_utc) AS support_rows FROM app.candles
                        WHERE market_id=%s AND timeframe='M1' AND completed=1 AND quality_status='PASS'
                        AND open_time_utc>=%s AND open_time_utc<DATEADD(minute,5,%s) {source_clause}""",
                                   (str(market["market_id"]),
                                    datetime.fromisoformat(view["first_utc"]).replace(tzinfo=None),
                                    datetime.fromisoformat(view["last_utc"]).replace(tzinfo=None)))
                    view["m1_support_rows"] = int(cursor.fetchone()["support_rows"] or 0)
                    cursor.execute(f"""SELECT
                          COUNT(DISTINCT CASE WHEN completed=0 THEN open_time_utc END) incomplete_timestamps,
                          COUNT(DISTINCT CASE WHEN completed=1 AND quality_status<>'PASS'
                                              THEN open_time_utc END) invalid_timestamps,
                          COUNT(*) raw_rows,
                          COUNT(DISTINCT open_time_utc) distinct_timestamps
                        FROM app.candles WHERE market_id=%s AND timeframe='M5'
                          AND open_time_utc>=%s AND open_time_utc<=%s {source_clause}""",
                        (str(market["market_id"]),
                         datetime.fromisoformat(view["first_utc"]).replace(tzinfo=None),
                         datetime.fromisoformat(view["last_utc"]).replace(tzinfo=None)))
                    quality_rows = cursor.fetchone()
                    view["incomplete_candles"] = int(quality_rows["incomplete_timestamps"] or 0)
                    view["invalid_candles"] = int(quality_rows["invalid_timestamps"] or 0)
                    view["raw_duplicate_rows_in_window"] = int(quality_rows["raw_rows"] or 0) - int(quality_rows["distinct_timestamps"] or 0)
                    for gap in view["gaps"]:
                        # Research may use a repaired provider; broker execution may not.
                        cursor.execute(f"""SELECT DISTINCT open_time_utc FROM app.candles
                            WHERE market_id=%s AND timeframe='M1' AND completed=1
                              AND quality_status='PASS' AND open_time_utc>=%s
                              AND open_time_utc<%s {source_clause}""",
                            (str(market["market_id"]),
                             datetime.fromisoformat(gap["after_utc"]).replace(tzinfo=None) + timedelta(minutes=5),
                             datetime.fromisoformat(gap["before_utc"]).replace(tzinfo=None)))
                        timestamps = {item["open_time_utc"].replace(tzinfo=timezone.utc)
                                      for item in cursor.fetchall()}
                        gap["m1_support"] = _gap_m1_support(gap, timestamps, expected)
                else:
                    view["m1_support_rows"] = 0
                    view["incomplete_candles"] = 0
                    view["invalid_candles"] = 0
                    view["raw_duplicate_rows_in_window"] = 0
            report.append({"market": market["symbol"], "calendar": market["calendar_code"],
                           "views": views})
            if persist:
                for view in views:
                    _persist_snapshot(cursor, str(market["market_id"]), view)
        if persist:
            connection.commit()
    print(json.dumps({"authority": "RESEARCH_DIAGNOSTIC_ONLY", "persisted": persist,
                      "policy": POLICY, "markets": report}, default=str, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persist", action="store_true", help="Append research-only quality snapshots")
    main(persist=parser.parse_args().persist)
