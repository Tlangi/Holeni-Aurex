"""Freeze executable development outcomes from one preregistered prospective join.

Read-only SQL access is bounded to the frozen development cohort. This command
never trains, opens validation/holdout, changes broker controls or overwrites an
existing artifact.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.executable_trade_outcome import CostPolicy, Decision, ExecutionPolicy, evaluate_trade
from app.ig_cost_authority import COST_AUTHORITY_VERSION, crosses_ig_funding_boundary
from app.market_calendar import is_regular_session
from app.point_in_time_atr import atr14_snapshot
from app.point_in_time_features import feature_snapshot
from app.prediction_path_inventory import RecordedDecision, assess_recorded_path
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_executable_research_universe import _frame
from scripts.verify_prospective_joined_opportunities import main as verify_join


ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_EXECUTABLE_COHORT_PROTOCOL_V2.json"
ECONOMIC = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json"
ATR_AMENDMENT = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1_ATR_AMENDMENT.json"
COST_AUTHORITY = ROOT / "docs/research/AUREX_IG_ZA_COST_AUTHORITY_V1.json"
OUTPUT = ROOT / "docs/audits/AUREX_FROZEN_PROSPECTIVE_EXECUTABLE_OUTCOMES_V2.json"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_development_membership(protocol: dict, joined: dict) -> list[dict]:
    if (protocol["authority"] != "PRE_REGISTERED_NONPROMOTABLE_PROSPECTIVE_RESEARCH"
            or protocol["outcome_access_before_registration"] is not False
            or joined["snapshot_sha256"] != protocol["source_join_snapshot_sha256"]):
        raise ValueError("Prospective protocol or source join mismatch")
    cutoff = _utc(protocol["development_end_exclusive_utc"])
    validation = _utc(protocol["validation_start_utc"])
    holdout = _utc(protocol["holdout_start_utc"])
    if not cutoff < validation < holdout:
        raise ValueError("Prospective chronology invalid")
    rows = [row for row in joined["opportunities"] if row["status"] == "JOINED"]
    if any(_utc(row["decision_at_utc"]) >= cutoff for row in rows):
        raise ValueError("Frozen join contains non-development decision")
    if len(rows) != sum(int(market["joined_opportunities"]) for market in joined["markets"]):
        raise ValueError("Frozen joined-count mismatch")
    return rows


def freeze() -> dict:
    if OUTPUT.exists():
        raise FileExistsError(f"Immutable prospective outcome artifact already exists: {OUTPUT}")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    amendment = json.loads(ATR_AMENDMENT.read_text(encoding="utf-8"))
    costs = json.loads(COST_AUTHORITY.read_text(encoding="utf-8"))
    if costs["version"] != COST_AUTHORITY_VERSION or costs["broker_order_authority"] is not False:
        raise ValueError("IG research cost authority invalid")
    if amendment["amends_protocol_sha256"] != canonical_sha256(economic):
        raise ValueError("ATR amendment does not match economic protocol")
    source = ROOT / "docs/audits" / protocol["source_join_snapshot_file"]
    verify_join(source)
    joined = json.loads(source.read_text(encoding="utf-8"))
    members = assert_development_membership(protocol, joined)
    by_market = {market: [] for market in economic["markets"]}
    for row in members:
        by_market[row["market"]].append(row)
    families = economic["policy_families"]
    max_horizon = max(int(item["max_holding_minutes"]) for item in families)
    if max_horizon != 120:
        raise ValueError("Unexpected maximum outcome horizon")
    market_results, frozen_members, all_outcomes = [], [], []
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        registry = {row["symbol"]: row for row in cursor.fetchall()}
        if sorted(registry) != sorted(by_market):
            raise ValueError("Market registry differs from economic protocol")
        for symbol in sorted(by_market):
            rows = by_market[symbol]
            market = registry[symbol]
            if not rows:
                market_results.append({"market": symbol, "joined": 0, "outcome_count": 0,
                                       "minimum_met": False})
                continue
            first = min(_utc(row["decision_at_utc"]) for row in rows)
            last = max(_utc(row["decision_at_utc"]) for row in rows)
            query_start = first - pd.Timedelta(6, unit="h")
            query_end = last + pd.Timedelta(max_horizon + 1, unit="min")
            if query_end >= _utc(protocol["development_end_exclusive_utc"]):
                raise ValueError("Outcome query would cross development boundary")
            cursor.execute("""SELECT holiday_date FROM app.market_holidays
                              WHERE calendar_code=%s AND session_close_local IS NULL""",
                           (market["calendar_code"],))
            holidays = {r["holiday_date"] for r in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                    market_timezone=market["market_timezone"],
                    session_open=market["session_open_local"],
                    session_close=market["session_close_local"], holidays=holidays)
            frames = {}
            duplicate_m1 = set()
            for timeframe in ("M1", "M5", "M15"):
                cursor.execute("""SELECT candle_id,open_time_utc,close_time_utc,source,
                                      completed,quality_status,is_regular_session,
                                      [high],[low],[close],bid_close,ask_close,
                                      bid_open,bid_high,bid_low,ask_open,ask_high,ask_low,
                                      ingested_at_utc,created_at_utc
                                  FROM app.candles WHERE market_id=%s AND timeframe=%s
                                    AND open_time_utc>=%s AND open_time_utc<%s
                                  ORDER BY open_time_utc,candle_id""",
                               (str(market["market_id"]), timeframe,
                                query_start.replace(tzinfo=None), query_end.replace(tzinfo=None)))
                frames[timeframe], duplicates = _frame(cursor.fetchall(), timeframe)
                if timeframe == "M1":
                    duplicate_m1 = duplicates
            observed_spread = {}
            verified = []
            for row in rows:
                decision_at = _utc(row["decision_at_utc"])
                atr = atr14_snapshot(decision_at, frames["M15"], market=symbol)
                features = feature_snapshot(decision_at, frames, market=symbol)
                recorded = RecordedDecision(
                    decision_id=f"PROSPECTIVE_M15:{symbol}:{row['m15_open_utc']}",
                    market=symbol, generated_at_utc=decision_at,
                    candle_open_utc=_utc(row["m15_open_utc"]), candle_timeframe="M15",
                    model_version_id=None, decision="HOLD", executable=False)
                path_evidence = assess_recorded_path(recorded, frames["M1"],
                    regular_session=regular, now_utc=datetime.now(timezone.utc),
                    horizon_minutes=max_horizon, duplicate_timestamps=duplicate_m1)
                if (atr.get("snapshot_sha256") != row["atr_snapshot_sha256"]
                        or features.get("snapshot_sha256") != row["feature_snapshot_sha256"]
                        or path_evidence.get("source_ig_m1_path_sha256") != row["ig_m1_path_sha256"]
                        or crosses_ig_funding_boundary(decision_at, max_horizon)):
                    raise ValueError(f"Frozen ATR/feature/IG path evidence changed: {row['opportunity_id']}")
                eligible = pd.Timestamp(decision_at).ceil("min")
                path = frames["M1"].loc[eligible:eligible + pd.Timedelta(max_horizon - 1, unit="min")]
                for at, quote in path.iterrows():
                    midpoint = (float(quote.ask_close) + float(quote.bid_close)) / 2
                    observed_spread[at] = (float(quote.ask_close) - float(quote.bid_close)) / midpoint * 10000
                verified.append((row, atr, features, path))
            spread = np.asarray(list(observed_spread.values()), dtype=float)
            if spread.size == 0 or not np.isfinite(spread).all() or (spread <= 0).any():
                raise ValueError(f"Invalid development IG spread evidence: {symbol}")
            p75, p95 = (float(np.percentile(spread, p)) for p in (75, 95))
            market_outcomes = []
            for row, atr, features, path in verified:
                evidence_hash = canonical_sha256({
                    "source_join_snapshot_sha256": joined["snapshot_sha256"],
                    "opportunity_id": row["opportunity_id"],
                    "atr_snapshot_sha256": row["atr_snapshot_sha256"],
                    "feature_snapshot_sha256": row["feature_snapshot_sha256"],
                    "ig_m1_path_sha256": row["ig_m1_path_sha256"]})
                frozen_members.append({"market": symbol, "opportunity_id": row["opportunity_id"],
                    "decision_at_utc": row["decision_at_utc"], "m15_open_utc": row["m15_open_utc"],
                    "atr": atr["atr"], "atr_snapshot_sha256": row["atr_snapshot_sha256"],
                    "feature_snapshot_sha256": row["feature_snapshot_sha256"],
                    "ig_m1_path_sha256": row["ig_m1_path_sha256"],
                    "feature_cutoffs_utc": features["feature_cutoffs_utc"],
                    "features": features["features"], "evidence_sha256": evidence_hash})
                for family in families:
                    stop = float(atr["atr"]) * float(family["stop_atr_multiple"])
                    execution = ExecutionPolicy(version=family["id"], stop_distance=stop,
                        target_distance=stop * float(family["target_r_multiple"]),
                        max_holding_minutes=int(family["max_holding_minutes"]))
                    for sensitivity, percentile in (("NORMAL_P75", p75), ("STRESSED_P95", p95)):
                        cost = CostPolicy(version=f"{COST_AUTHORITY_VERSION}:{sensitivity}",
                            slippage_bps_per_side=(0.25 if sensitivity == "NORMAL_P75" else 1.0) * percentile,
                            commission_bps_round_trip=0.0, financing_bps_per_day=0.0)
                        for direction in ("LONG", "SHORT"):
                            decision = Decision(market=symbol,
                                decision_at_utc=_utc(row["decision_at_utc"]),
                                feature_cutoff_at_utc=max(_utc(v) for v in features["feature_cutoffs_utc"].values()),
                                feature_version=features["feature_version"],
                                research_version=protocol["protocol_version"],
                                dataset_sha256=evidence_hash, direction=direction)
                            outcome = evaluate_trade(decision, execution, cost, path,
                                                     regular_session=regular)
                            outcome.update({"opportunity_id": row["opportunity_id"],
                                "atr": atr["atr"], "atr_snapshot_sha256": row["atr_snapshot_sha256"],
                                "feature_snapshot_sha256": row["feature_snapshot_sha256"],
                                "ig_m1_path_sha256": row["ig_m1_path_sha256"],
                                "cost_sensitivity": sensitivity, "spread_percentile_bps": percentile})
                            market_outcomes.append(outcome)
            all_outcomes.extend(market_outcomes)
            market_results.append({"market": symbol, "joined": len(rows),
                "minimum_met": len(rows) >= protocol["minimum_joined_per_market"],
                "spread_observation_count": len(spread), "spread_p75_bps": p75,
                "spread_p95_bps": p95, "outcome_count": len(market_outcomes),
                "evaluated_count": sum(r["status"] == "EVALUATED" for r in market_outcomes),
                "non_evaluated_reasons": dict(sorted(Counter(r["reason"] for r in market_outcomes
                    if r["status"] != "EVALUATED").items()))})
    result = {"authority": "FROZEN_NONPROMOTABLE_PROSPECTIVE_EXECUTABLE_OUTCOMES",
        "prospective_protocol_sha256": canonical_sha256(protocol),
        "economic_protocol_sha256": canonical_sha256(economic),
        "atr_amendment_sha256": canonical_sha256(amendment),
        "cost_authority_sha256": canonical_sha256(costs),
        "source_join_snapshot_sha256": joined["snapshot_sha256"],
        "development_end_exclusive_utc": protocol["development_end_exclusive_utc"],
        "validation_accessed": False, "holdout_accessed": False,
        "model_training_performed": False, "broker_submission_authority": False,
        "markets": market_results, "members": frozen_members, "outcomes": all_outcomes}
    result["outcome_manifest_sha256"] = canonical_sha256(result)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"outcome_manifest_sha256": result["outcome_manifest_sha256"],
            "markets": market_results, "outcome_count": len(all_outcomes)}


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
