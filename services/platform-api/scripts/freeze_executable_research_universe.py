"""Freeze a non-promotable all-M15 development universe, without training/labels.

The pre-registered protocol and every canonical completed PASS M15 candle define
membership independently of model decision or observed outcome. This script reads
SQL only and writes one no-overwrite hash-attested JSON evidence artifact.
"""
from __future__ import annotations

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
from app.point_in_time_features import feature_snapshot
from app.prediction_path_inventory import RecordedDecision, assess_recorded_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = PROJECT_ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json"
OUTPUT_PATH = PROJECT_ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _rank(source: object) -> int:
    name = str(source)
    return (0 if name.startswith("IG_LIGHTSTREAMER") else
            1 if name.startswith("IG_") else
            2 if name == "DERIVED_M1" else 3)


def _frame(rows: list[dict], timeframe: str) -> tuple[pd.DataFrame, set[pd.Timestamp]]:
    """Canonical source precedence; return IG M1 duplicates separately."""
    stamp_count = Counter(row["open_time_utc"] for row in rows
                          if timeframe == "M1" and str(row["source"]).startswith("IG_LIGHTSTREAMER"))
    duplicate = {pd.Timestamp(at, tz="UTC") for at,n in stamp_count.items() if n > 1}
    chosen = {}
    for row in sorted(rows, key=lambda r: (_rank(r["source"]),
                       -(r["ingested_at_utc"] or r["created_at_utc"]).timestamp()),
                      reverse=True):
        chosen[row["open_time_utc"]] = row
    if not chosen:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC")), duplicate
    frame = pd.DataFrame(list(chosen.values()))
    frame.index = pd.DatetimeIndex(frame.pop("open_time_utc"), tz="UTC")
    return frame.sort_index(), duplicate


def collect() -> dict[str, object]:
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    if (protocol.get("authority") != "PRE_REGISTERED_NONPROMOTABLE_RESEARCH" or
            protocol.get("cohort_gate", {}).get("model_promotion") != "NONE"):
        raise ValueError("Unrecognized non-promotable research protocol")
    protocol_hash = sha256(_canonical(protocol).encode()).hexdigest()
    start = datetime.fromisoformat(protocol["chronology"]["development_start_utc"].replace("Z", "+00:00"))
    validation = datetime.fromisoformat(protocol["chronology"]["validation_start_utc"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if not start < now < validation:
        raise ValueError("Development snapshot must precede untouched validation")
    horizon = max(item["max_holding_minutes"] for item in protocol["policy_families"])
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        markets = cursor.fetchall()
        if [m["symbol"] for m in markets] != sorted(protocol["markets"]):
            raise ValueError("Protocol market universe differs from enabled registry")
        by_market = []
        for market in markets:
            cursor.execute("""SELECT holiday_date FROM app.market_holidays
                              WHERE calendar_code=%s AND session_close_local IS NULL""",
                           (market["calendar_code"],))
            holidays = {r["holiday_date"] for r in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                                          market_timezone=market["market_timezone"],
                                          session_open=market["session_open_local"],
                                          session_close=market["session_close_local"],
                                          holidays=holidays)
            raw = {}
            for timeframe in ("M1", "M5", "M15"):
                clause = "AND source LIKE 'IG_LIGHTSTREAMER%%'" if timeframe == "M1" else ""
                cursor.execute(f"""SELECT candle_id,open_time_utc,close_time_utc,
                                      source,completed,quality_status,[close],bid_close,ask_close,
                                      bid_open,bid_high,bid_low,ask_open,ask_high,ask_low,
                                      ingested_at_utc,created_at_utc
                                  FROM app.candles WHERE market_id=%s AND timeframe=%s
                                    AND open_time_utc>=DATEADD(day,-3,%s)
                                    AND open_time_utc<%s {clause}
                                  ORDER BY open_time_utc,candle_id""",
                               (str(market["market_id"]), timeframe,
                                start.replace(tzinfo=None), validation.replace(tzinfo=None)))
                raw[timeframe] = cursor.fetchall()
            frames = {}
            duplicates = set()
            for timeframe in ("M1", "M5", "M15"):
                frames[timeframe], duplicate = _frame(raw[timeframe], timeframe)
                if timeframe == "M1": duplicates = duplicate
            universe = []
            for at, row in frames["M15"].iterrows():
                completed_at = at + pd.Timedelta(15, unit="min")
                available_raw = (row.ingested_at_utc if pd.notna(row.ingested_at_utc)
                                 else row.created_at_utc)
                available_at = (pd.Timestamp(available_raw, tz="UTC")
                                if pd.notna(available_raw) else None)
                decision_at = max(completed_at, available_at) if available_at else completed_at
                if (decision_at < pd.Timestamp(start) or decision_at >= pd.Timestamp(validation)
                        or decision_at > pd.Timestamp(now) or not bool(row.completed)
                        or row.quality_status != "PASS" or not regular(at.to_pydatetime())):
                    continue
                feature = feature_snapshot(decision_at.to_pydatetime(),
                                           frames, market=market["symbol"])
                recorded = RecordedDecision(
                    decision_id=f"CANONICAL_M15:{market['symbol']}:{at.isoformat()}",
                    market=market["symbol"], generated_at_utc=decision_at.to_pydatetime(),
                    candle_open_utc=at.to_pydatetime(), candle_timeframe="M15",
                    model_version_id=None, decision="HOLD", executable=False)
                coverage = assess_recorded_path(recorded, frames["M1"],
                    regular_session=regular, now_utc=now, horizon_minutes=horizon,
                    duplicate_timestamps=duplicates)
                universe.append({"opportunity_id": coverage["inventory_prediction_id"],
                    "market": market["symbol"], "decision_at_utc": decision_at.isoformat(),
                    "m15_completed_at_utc": completed_at.isoformat(),
                    "m15_available_at_utc": available_at.isoformat() if available_at else None,
                    "m15_candle_id": int(row.candle_id),
                    "m15_open_utc": at.isoformat(), "m15_source": str(row.source),
                    "m15_completed": True, "m15_quality_status": "PASS",
                    "feature_status": feature["status"],
                    "feature_snapshot_sha256": feature.get("snapshot_sha256"),
                    "feature_cutoffs_utc": feature.get("feature_cutoffs_utc"),
                    "feature_source_identity": feature.get("source_identity"),
                    "feature_values": feature.get("features"),
                    "feature_failure_reason": feature.get("reason"),
                    "ig_path_status": coverage["status"],
                    "ig_path_failure_reason": coverage["reason"],
                    "ig_path_first_missing_utc": coverage["first_missing_m1_utc"],
                    "ig_path_complete_minutes": coverage["complete_m1_minutes"],
                    "source_ig_m1_path_sha256": coverage["source_ig_m1_path_sha256"],
                    "economic_label": None,
                    "economic_label_authority": "NONE_OUTCOMES_NOT_YET_FROZEN"})
            by_market.append({"market": market["symbol"],
                "all_completed_m15_opportunities": len(universe),
                "complete_feature_snapshots": sum(r["feature_status"] == "COMPLETE" for r in universe),
                "complete_ig_120m_paths": sum(r["ig_path_status"] == "COMPLETE_IG_M1_PATH" for r in universe),
                "complete_features_and_ig_paths": sum(r["feature_status"] == "COMPLETE"
                    and r["ig_path_status"] == "COMPLETE_IG_M1_PATH" for r in universe),
                "ig_path_reasons": dict(sorted(Counter(r["ig_path_failure_reason"] or
                    r["ig_path_status"] for r in universe).items())),
                "opportunities": universe})
    result = {"authority": "FROZEN_NONPROMOTABLE_DEVELOPMENT_UNIVERSE",
              "protocol_sha256": protocol_hash,
              "protocol_version": protocol["protocol_version"],
              "feature_version": protocol["decision_universe"]["feature_version"],
              "label_version": protocol["label_version"],
              "frozen_at_utc": now.isoformat(), "holdout_accessed": False,
              "model_training_performed": False, "economic_outcomes_frozen": False,
              "broker_submission_authority": False,
              "development_start_utc": start.isoformat(),
              "validation_start_utc": validation.isoformat(),
              "untouched_holdout_start_utc": protocol["chronology"]["untouched_holdout_start_utc"],
              "markets": by_market}
    result["manifest_sha256"] = sha256(_canonical(result).encode()).hexdigest()
    return result


def main() -> None:
    if OUTPUT_PATH.exists():
        raise FileExistsError("Frozen universe already exists; use a new dated path/protocol version")
    result = collect()
    OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"authority": result["authority"],
        "protocol_sha256": result["protocol_sha256"],
        "manifest_sha256": result["manifest_sha256"],
        "holdout_accessed": False, "economic_outcomes_frozen": False,
        "output": str(OUTPUT_PATH),
        "markets": [{k:v for k,v in market.items() if k != "opportunities"}
                    for market in result["markets"]]}, indent=2))


if __name__ == "__main__":
    main()
