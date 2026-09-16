"""Freeze prospective ATR/feature/M1-path joins without training or labels."""
from __future__ import annotations

from collections import Counter
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.ig_cost_authority import crosses_ig_funding_boundary
from app.market_calendar import is_regular_session
from app.point_in_time_atr import atr14_snapshot
from app.point_in_time_features import feature_snapshot
from app.prediction_path_inventory import RecordedDecision, assess_recorded_path
from app.prospective_m15_continuity import SOURCE
from app.prospective_opportunity_join import JOIN_VERSION, join_opportunity
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_executable_research_universe import _frame

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = ROOT / "docs/research/AUREX_PROSPECTIVE_M15_CONTINUITY_PROTOCOL_V1.json"
OUTPUT_PATH = ROOT / "docs/audits/AUREX_PROSPECTIVE_JOINED_OPPORTUNITIES_SNAPSHOT_2026-09-16.json"


def collect_snapshot() -> dict[str, object]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    markets_out = []
    all_rows = []
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        for market in cursor.fetchall():
            cursor.execute("SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s AND session_close_local IS NULL",
                           (market["calendar_code"],))
            holidays = {row["holiday_date"] for row in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                    market_timezone=market["market_timezone"],
                    session_open=market["session_open_local"],
                    session_close=market["session_close_local"], holidays=holidays)
            cursor.execute("""SELECT MIN(open_time_utc) first_open FROM app.candles
                              WHERE market_id=%s AND timeframe='M15' AND source=%s""",
                           (str(market["market_id"]), SOURCE))
            first = cursor.fetchone()["first_open"]
            if first is None:
                markets_out.append({"market": market["symbol"], "prospective_m15": 0,
                    "joined_opportunities": 0, "target_reached": False,
                    "reasons": {"NO_DEPLOYED_SOURCE_ROWS": 1}})
                continue
            raw = {}
            for timeframe in ("M1", "M5", "M15"):
                source_clause = "AND source=%s" if timeframe == "M15" else ""
                params = [str(market["market_id"]), timeframe,
                    first - pd.Timedelta(6, unit="h"), now.replace(tzinfo=None)]
                if timeframe == "M15": params.append(SOURCE)
                cursor.execute(f"""SELECT candle_id,open_time_utc,close_time_utc,source,completed,
                                      quality_status,is_regular_session,[high],[low],[close],bid_close,ask_close,
                                      bid_open,bid_high,bid_low,ask_open,ask_high,ask_low,
                                      ingested_at_utc,created_at_utc FROM app.candles
                                  WHERE market_id=%s AND timeframe=%s AND open_time_utc>=%s
                                    AND open_time_utc<%s {source_clause}
                                  ORDER BY open_time_utc,candle_id""", tuple(params))
                raw[timeframe] = cursor.fetchall()
            frames = {}
            duplicates = set()
            for timeframe in ("M1", "M5", "M15"):
                frames[timeframe], duplicate = _frame(raw[timeframe], timeframe)
                if timeframe == "M1": duplicates = duplicate
            rows = []
            for at, candle in frames["M15"].iterrows():
                if not bool(candle.completed) or candle.quality_status != "PASS" or not bool(candle.is_regular_session):
                    continue
                close_at = pd.Timestamp(candle.close_time_utc, tz="UTC") if pd.Timestamp(candle.close_time_utc).tzinfo is None else pd.Timestamp(candle.close_time_utc)
                available = pd.Timestamp(candle.ingested_at_utc, tz="UTC") if pd.Timestamp(candle.ingested_at_utc).tzinfo is None else pd.Timestamp(candle.ingested_at_utc)
                decision_at = max(close_at, available).to_pydatetime()
                atr = atr14_snapshot(decision_at, frames["M15"], market=market["symbol"])
                feature = feature_snapshot(decision_at, frames, market=market["symbol"])
                recorded = RecordedDecision(decision_id=f"PROSPECTIVE_M15:{market['symbol']}:{at.isoformat()}",
                    market=market["symbol"], generated_at_utc=decision_at,
                    candle_open_utc=at.to_pydatetime(), candle_timeframe="M15",
                    model_version_id=None, decision="HOLD", executable=False)
                path = assess_recorded_path(recorded, frames["M1"], regular_session=regular,
                    now_utc=now, horizon_minutes=120, duplicate_timestamps=duplicates)
                joined = join_opportunity(market=market["symbol"],
                    decision_at_utc=decision_at.isoformat(), m15_candle_id=int(candle.candle_id),
                    atr=atr, feature=feature, path=path,
                    crosses_rollover=crosses_ig_funding_boundary(decision_at, 120))
                joined.update({"m15_open_utc": at.isoformat(), "m15_source": SOURCE})
                rows.append(joined)
            all_rows.extend(rows)
            joined_count = sum(row["status"] == "JOINED" for row in rows)
            markets_out.append({"market": market["symbol"], "prospective_m15": len(rows),
                "joined_opportunities": joined_count, "target_reached": joined_count >= 30,
                "reasons": dict(sorted(Counter(row["reason"] for row in rows).items()))})
    result = {"authority": "IMMUTABLE_NONPROMOTABLE_PROSPECTIVE_JOIN_SNAPSHOT",
        "join_version": JOIN_VERSION, "protocol_sha256": canonical_sha256(protocol),
        "captured_at_utc": now.isoformat(), "minimum_joined_per_market": 30,
        "historical_rows_rewritten": False, "validation_accessed": False,
        "holdout_accessed": False, "economic_outcomes_calculated": False,
        "model_training_performed": False, "broker_submission_authority": False,
        "markets": markets_out, "opportunities": all_rows}
    result["snapshot_sha256"] = canonical_sha256(result)
    return result


def main(output_path: Path = OUTPUT_PATH) -> dict[str, object]:
    if output_path.exists():
        raise FileExistsError("Prospective join snapshot is immutable; use a new timestamped path")
    if output_path.parent.resolve() != (ROOT / "docs/audits").resolve() or output_path.suffix != ".json":
        raise ValueError("Output must be a JSON file in docs/audits")
    result = collect_snapshot()
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot_sha256": result["snapshot_sha256"],
        "markets": result["markets"]}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH,
        help="Immutable JSON path under docs/audits; an existing file is never replaced")
    main(parser.parse_args().output.resolve())
