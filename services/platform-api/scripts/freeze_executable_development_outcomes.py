"""Freeze development-only executable LONG/SHORT outcomes.

Membership comes from the immutable universe. Each M1 path hash is reproduced,
ATR is point-in-time, rollover-crossing rows are excluded, and no validation or
holdout timestamp is queried. No model is trained and no broker action occurs.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
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
from app.prediction_path_inventory import RecordedDecision, assess_recorded_path
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_executable_research_universe import _frame

ROOT = Path(__file__).resolve().parents[3]
UNIVERSE_PATH = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_RESEARCH_UNIVERSE_2026-09-15.json"
PROTOCOL_PATH = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1.json"
AMENDMENT_PATH = ROOT / "docs/research/AUREX_EXECUTABLE_ECONOMIC_PROTOCOL_V1_ATR_AMENDMENT.json"
COST_PATH = ROOT / "docs/research/AUREX_IG_ZA_COST_AUTHORITY_V1.json"
OUTPUT_PATH = ROOT / "docs/audits/AUREX_FROZEN_EXECUTABLE_DEVELOPMENT_OUTCOMES_2026-09-16.json"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    if OUTPUT_PATH.exists():
        raise FileExistsError("Outcome freeze is immutable; use a new protocol/path")
    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    amendment = json.loads(AMENDMENT_PATH.read_text(encoding="utf-8"))
    cost_authority = json.loads(COST_PATH.read_text(encoding="utf-8"))
    if canonical_sha256({k: v for k, v in universe.items() if k != "manifest_sha256"}) != universe["manifest_sha256"]:
        raise ValueError("Frozen universe hash mismatch")
    if amendment["amends_protocol_sha256"] != universe["protocol_sha256"]:
        raise ValueError("ATR amendment does not match frozen protocol")
    if amendment["outcome_access_before_amendment"] is not False:
        raise ValueError("ATR amendment lacks no-outcome-access attestation")
    if cost_authority["version"] != COST_AUTHORITY_VERSION:
        raise ValueError("Unexpected cost authority")
    validation = _utc(protocol["chronology"]["validation_start_utc"])
    policies = protocol["policy_families"]
    max_horizon = max(item["max_holding_minutes"] for item in policies)
    market_outputs = []
    all_outcomes = []
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        registry = {row["symbol"]: row for row in cursor.fetchall()}
        for group in universe["markets"]:
            symbol = group["market"]
            market = registry[symbol]
            candidates = [row for row in group["opportunities"]
                          if row["feature_status"] == "COMPLETE" and
                          row["ig_path_status"] == "COMPLETE_IG_M1_PATH"]
            if not candidates:
                market_outputs.append({"market": symbol, "data_ready": 0,
                    "atr_ready": 0, "no_rollover_ready": 0, "outcome_count": 0,
                    "tournament_minimum_met": False, "reasons": {}})
                continue
            first = min(_utc(row["decision_at_utc"]) for row in candidates)
            last = max(_utc(row["decision_at_utc"]) for row in candidates)
            if last >= validation:
                raise ValueError("Validation timestamp present in development universe")
            cursor.execute("""SELECT holiday_date FROM app.market_holidays
                              WHERE calendar_code=%s AND session_close_local IS NULL""",
                           (market["calendar_code"],))
            holidays = {r["holiday_date"] for r in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                    market_timezone=market["market_timezone"],
                    session_open=market["session_open_local"],
                    session_close=market["session_close_local"], holidays=holidays)
            raw = {}
            for timeframe, start_at, end_at in (
                ("M1", first, last + pd.Timedelta(max_horizon, unit="min")),
                ("M15", first - pd.Timedelta(6, unit="h"), last)):
                cursor.execute("""SELECT candle_id,open_time_utc,source,completed,
                                      quality_status,[high],[low],[close],bid_close,ask_close,
                                      bid_open,bid_high,bid_low,ask_open,ask_high,ask_low,
                                      ingested_at_utc,created_at_utc
                                  FROM app.candles WHERE market_id=%s AND timeframe=%s
                                    AND open_time_utc>=%s AND open_time_utc<%s
                                  ORDER BY open_time_utc,candle_id""",
                               (str(market["market_id"]), timeframe,
                                start_at.replace(tzinfo=None), end_at.replace(tzinfo=None)))
                raw[timeframe] = cursor.fetchall()
            m1, duplicates = _frame(raw["M1"], "M1")
            m15, _ = _frame(raw["M15"], "M15")
            verified = []
            reasons = Counter()
            spread_observations = {}
            for row in candidates:
                decision_at = _utc(row["decision_at_utc"])
                recorded = RecordedDecision(
                    decision_id=f"CANONICAL_M15:{symbol}:{row['m15_open_utc']}",
                    market=symbol, generated_at_utc=decision_at,
                    candle_open_utc=_utc(row["m15_open_utc"]), candle_timeframe="M15",
                    model_version_id=None, decision="HOLD", executable=False)
                coverage = assess_recorded_path(recorded, m1, regular_session=regular,
                    now_utc=datetime.now(timezone.utc), horizon_minutes=max_horizon,
                    duplicate_timestamps=duplicates)
                if (coverage["status"] != "COMPLETE_IG_M1_PATH" or
                        coverage["source_ig_m1_path_sha256"] != row["source_ig_m1_path_sha256"]):
                    reasons["FROZEN_IG_PATH_HASH_MISMATCH"] += 1
                    continue
                atr = atr14_snapshot(decision_at, m15, market=symbol)
                if atr["status"] != "COMPLETE":
                    reasons[f"ATR:{atr['reason']}"] += 1
                    continue
                if crosses_ig_funding_boundary(decision_at, max_horizon):
                    reasons["FUNDING_BOUNDARY_IN_MAX_HORIZON"] += 1
                    continue
                eligible = pd.Timestamp(decision_at).ceil("min")
                path = m1.loc[eligible:eligible + pd.Timedelta(max_horizon - 1, unit="min")]
                for at, quote in path.iterrows():
                    midpoint = (float(quote.ask_close) + float(quote.bid_close)) / 2
                    spread_observations[at] = (float(quote.ask_close) - float(quote.bid_close)) / midpoint * 10000
                verified.append((row, atr, path))
            if spread_observations:
                values = np.array(list(spread_observations.values()), dtype=float)
                p75, p95 = (float(np.percentile(values, p)) for p in (75, 95))
            else:
                p75 = p95 = None
            market_outcomes = []
            if p75 is not None:
                for row, atr, path in verified:
                    dataset_hash = canonical_sha256({
                        "universe_manifest": universe["manifest_sha256"],
                        "feature_snapshot": row["feature_snapshot_sha256"],
                        "atr_snapshot": atr["snapshot_sha256"],
                        "ig_path": row["source_ig_m1_path_sha256"]})
                    for family in policies:
                        stop = float(atr["atr"]) * float(family["stop_atr_multiple"])
                        execution = ExecutionPolicy(version=family["id"], stop_distance=stop,
                            target_distance=stop * float(family["target_r_multiple"]),
                            max_holding_minutes=int(family["max_holding_minutes"]))
                        for sensitivity, percentile in (("NORMAL_P75", p75), ("STRESSED_P95", p95)):
                            costs = CostPolicy(version=f"{COST_AUTHORITY_VERSION}:{sensitivity}",
                                slippage_bps_per_side=0.25 * percentile if sensitivity == "NORMAL_P75" else percentile,
                                commission_bps_round_trip=0.0, financing_bps_per_day=0.0)
                            for direction in ("LONG", "SHORT"):
                                decision = Decision(market=symbol,
                                    decision_at_utc=_utc(row["decision_at_utc"]),
                                    feature_cutoff_at_utc=max(_utc(v) for v in row["feature_cutoffs_utc"].values()),
                                    feature_version=universe["feature_version"],
                                    research_version=protocol["protocol_version"],
                                    dataset_sha256=dataset_hash, direction=direction)
                                result = evaluate_trade(decision, execution, costs, path,
                                                        regular_session=regular)
                                result.update({"opportunity_id": row["opportunity_id"],
                                    "atr_version": atr["atr_version"], "atr": atr["atr"],
                                    "atr_snapshot_sha256": atr["snapshot_sha256"],
                                    "ig_path_sha256": row["source_ig_m1_path_sha256"],
                                    "cost_sensitivity": sensitivity,
                                    "spread_percentile_bps": percentile})
                                market_outcomes.append(result)
            all_outcomes.extend(market_outcomes)
            market_outputs.append({"market": symbol, "data_ready": len(candidates),
                "atr_ready": len(verified) + reasons["FUNDING_BOUNDARY_IN_MAX_HORIZON"],
                "no_rollover_ready": len(verified), "spread_observation_count": len(spread_observations),
                "spread_p75_bps": p75, "spread_p95_bps": p95,
                "outcome_count": len(market_outcomes),
                "evaluated_outcomes": sum(r["status"] == "EVALUATED" for r in market_outcomes),
                "unverifiable_outcomes": sum(r["status"] != "EVALUATED" for r in market_outcomes),
                "tournament_minimum_met": len(verified) >= protocol["cohort_gate"]["minimum_complete_ig_paths_per_market"],
                "reasons": dict(sorted(reasons.items()))})
    result = {"authority": "FROZEN_NONPROMOTABLE_DEVELOPMENT_OUTCOMES",
        "protocol_sha256": universe["protocol_sha256"],
        "protocol_amendment_sha256": canonical_sha256(amendment),
        "cost_authority_sha256": canonical_sha256(cost_authority),
        "source_universe_manifest_sha256": universe["manifest_sha256"],
        "label_version": universe["label_version"], "cost_authority_version": COST_AUTHORITY_VERSION,
        "holdout_accessed": False, "validation_accessed": False,
        "model_training_performed": False, "broker_submission_authority": False,
        "markets": market_outputs, "outcomes": all_outcomes}
    result["outcome_manifest_sha256"] = canonical_sha256(result)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({**{k: result[k] for k in ("authority", "outcome_manifest_sha256",
        "holdout_accessed", "validation_accessed", "model_training_performed")},
        "markets": market_outputs}, indent=2))


if __name__ == "__main__":
    main()
