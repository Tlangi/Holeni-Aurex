"""Freeze the closed validation window and replay locked model binaries.

SQL reads stop at the registered validation end plus its 120-minute outcome
horizon. The command never reads the later holdout window for features, fits a
model, changes model state, or grants broker authority.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
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
from app.prospective_evaluation_readiness import evaluation_readiness
from app.prospective_validation import replay_metrics
from app.research_cohort_eligibility import canonical_sha256
from scripts.freeze_executable_research_universe import _frame
from scripts.freeze_prospective_executable_outcomes import ECONOMIC, OUTPUT as DEVELOPMENT_OUTCOMES, _utc
from scripts.freeze_selected_prospective_models import ARTIFACT_DIR, MANIFEST


ROOT = Path(__file__).resolve().parents[3]
WINDOWS = ROOT / "docs/research/AUREX_PROSPECTIVE_EVALUATION_WINDOWS_V1.json"
PROTOCOL = ROOT / "docs/research/AUREX_PROSPECTIVE_VALIDATION_FREEZE_V1.json"
OUTPUT = ROOT / "docs/audits/AUREX_FROZEN_PROSPECTIVE_VALIDATION_V1.json"


def _aware(value) -> datetime:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def _load_frames(cursor, market_id: str, start: datetime, end: datetime) -> tuple[dict, set]:
    frames = {}
    duplicate_m1: set = set()
    for timeframe in ("M1", "M5", "M15"):
        boundary = end + timedelta(minutes=120) if timeframe == "M1" else end
        cursor.execute("""SELECT candle_id,open_time_utc,close_time_utc,source,completed,
                              quality_status,is_regular_session,[high],[low],[close],bid_close,ask_close,
                              bid_open,bid_high,bid_low,ask_open,ask_high,ask_low,
                              ingested_at_utc,created_at_utc
                          FROM app.candles WHERE market_id=%s AND timeframe=%s
                            AND open_time_utc>=%s AND open_time_utc<%s
                          ORDER BY open_time_utc,candle_id""",
                       (market_id, timeframe, (start - timedelta(hours=6)).replace(tzinfo=None),
                        boundary.replace(tzinfo=None)))
        frames[timeframe], duplicates = _frame(cursor.fetchall(), timeframe)
        if timeframe == "M1":
            duplicate_m1 = duplicates
    return frames, duplicate_m1


def freeze(*, now_utc: datetime | None = None) -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(f"Immutable validation artifact already exists: {OUTPUT}")
    windows = json.loads(WINDOWS.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    economic = json.loads(ECONOMIC.read_text(encoding="utf-8"))
    development = json.loads(DEVELOPMENT_OUTCOMES.read_text(encoding="utf-8"))
    if canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"}) != manifest["manifest_sha256"]:
        raise ValueError("Selected model manifest hash mismatch")
    if (protocol["authority"] != "PRE_REGISTERED_LOCKED_MODEL_VALIDATION_FREEZE"
            or protocol["outcome_access_before_registration"] is not False
            or protocol["evaluation_windows_sha256"] != canonical_sha256(windows)
            or protocol["selected_model_manifest_sha256"] != manifest["manifest_sha256"]
            or protocol["holdout_accessed"] is not False
            or protocol["broker_submission_authority"] is not False):
        raise ValueError("Validation freeze protocol provenance or authority mismatch")
    readiness = evaluation_readiness(windows, phase="validation",
        now_utc=now_utc or datetime.now(timezone.utc), validation_report_frozen=False)
    if readiness["status"] != "READY_FOR_SEPARATE_GOVERNED_FREEZE":
        raise RuntimeError(f"VALIDATION_WINDOW_NOT_READY:{readiness['reason']}")
    start = _utc(protocol["validation_start_utc"])
    end = _utc(protocol["validation_end_exclusive_utc"])
    if start != _utc(windows["validation_start_utc"]) or end != _utc(windows["validation_end_exclusive_utc"]):
        raise ValueError("Validation protocol interval differs from registered windows")
    selected = {row["market"]: row for row in manifest["models"]}
    dev_costs = {row["market"]: row for row in development["markets"]}
    family_by_id = {row["id"]: row for row in economic["policy_families"]}
    market_results, frozen_members, all_outcomes = [], [], []

    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("""SELECT market_id,symbol,calendar_code,market_timezone,
                              session_open_local,session_close_local FROM app.markets
                          WHERE enabled=1 ORDER BY symbol""")
        registry = {row["symbol"]: row for row in cursor.fetchall()}
        for symbol, model_entry in sorted(selected.items()):
            market = registry[symbol]
            cursor.execute(""";WITH ranked AS (
                 SELECT e.evidence_json,e.transition_status,e.transition_reason,e.observed_at_utc,
                        ROW_NUMBER() OVER(PARTITION BY e.opportunity_id ORDER BY e.observed_at_utc DESC) rn
                 FROM app.prospective_opportunity_events e
                 JOIN app.candles c ON c.candle_id=e.m15_candle_id
                 WHERE e.market_id=%s AND c.open_time_utc>=%s AND c.open_time_utc<%s)
               SELECT evidence_json,transition_status,transition_reason FROM ranked WHERE rn=1""",
               (str(market["market_id"]), (start - timedelta(minutes=15)).replace(tzinfo=None), end.replace(tzinfo=None)))
            opportunities = []
            for event in cursor.fetchall():
                evidence = json.loads(event["evidence_json"])
                decision_at = _utc(evidence["decision_at_utc"])
                if start <= decision_at < end:
                    evidence["transition_status"] = event["transition_status"]
                    evidence["transition_reason"] = event["transition_reason"]
                    opportunities.append(evidence)
            opportunities.sort(key=lambda row: (row["decision_at_utc"], row["opportunity_id"]))
            state_counts = dict(sorted(Counter(row["transition_status"] for row in opportunities).items()))
            joined = [row for row in opportunities if row["transition_status"] == "JOINED"]
            frames, duplicate_m1 = _load_frames(cursor, str(market["market_id"]), start, end)
            cursor.execute("SELECT holiday_date FROM app.market_holidays WHERE calendar_code=%s AND session_close_local IS NULL",
                           (market["calendar_code"],))
            holidays = {row["holiday_date"] for row in cursor.fetchall()}
            def regular(at):
                return is_regular_session(at, calendar_code=market["calendar_code"],
                    market_timezone=market["market_timezone"], session_open=market["session_open_local"],
                    session_close=market["session_close_local"], holidays=holidays)
            verified = []
            validation_spreads = []
            for row in joined:
                decision_at = _utc(row["decision_at_utc"])
                atr = atr14_snapshot(decision_at, frames["M15"], market=symbol)
                features = feature_snapshot(decision_at, frames, market=symbol)
                recorded = RecordedDecision(
                    decision_id=f"PROSPECTIVE_M15:{symbol}:{row['m15_open_utc']}", market=symbol,
                    generated_at_utc=decision_at, candle_open_utc=_utc(row["m15_open_utc"]),
                    candle_timeframe="M15", model_version_id=None, decision="HOLD", executable=False)
                path_evidence = assess_recorded_path(recorded, frames["M1"], regular_session=regular,
                    now_utc=end + timedelta(minutes=120), horizon_minutes=120,
                    duplicate_timestamps=duplicate_m1)
                if (atr.get("snapshot_sha256") != row.get("atr_snapshot_sha256")
                        or features.get("snapshot_sha256") != row.get("feature_snapshot_sha256")
                        or path_evidence.get("source_ig_m1_path_sha256") != row.get("ig_m1_path_sha256")
                        or crosses_ig_funding_boundary(decision_at, 120)):
                    raise ValueError(f"Validation evidence changed: {row['opportunity_id']}")
                eligible = pd.Timestamp(decision_at).ceil("min")
                full_path = frames["M1"].loc[eligible:eligible + pd.Timedelta(119, unit="min")]
                for _, quote in full_path.iterrows():
                    midpoint = (float(quote.ask_close) + float(quote.bid_close)) / 2
                    validation_spreads.append((float(quote.ask_close) - float(quote.bid_close)) / midpoint * 10000)
                evidence_hash = canonical_sha256({
                    "validation_protocol_sha256": canonical_sha256(protocol),
                    "opportunity_id": row["opportunity_id"],
                    "atr_snapshot_sha256": row["atr_snapshot_sha256"],
                    "feature_snapshot_sha256": row["feature_snapshot_sha256"],
                    "ig_m1_path_sha256": row["ig_m1_path_sha256"],
                })
                member = {"market": symbol, "opportunity_id": row["opportunity_id"],
                    "decision_at_utc": row["decision_at_utc"], "m15_open_utc": row["m15_open_utc"],
                    "atr": atr["atr"], "atr_snapshot_sha256": row["atr_snapshot_sha256"],
                    "feature_snapshot_sha256": row["feature_snapshot_sha256"],
                    "ig_m1_path_sha256": row["ig_m1_path_sha256"],
                    "feature_cutoffs_utc": features["feature_cutoffs_utc"],
                    "features": features["features"], "evidence_sha256": evidence_hash}
                frozen_members.append(member)
                verified.append((member, full_path, atr, features))

            family = family_by_id[model_entry["family"]]
            costs = dev_costs[symbol]
            market_outcomes = []
            for member, full_path, atr, features in verified:
                stop = float(atr["atr"]) * float(family["stop_atr_multiple"])
                execution = ExecutionPolicy(version=family["id"], stop_distance=stop,
                    target_distance=stop * float(family["target_r_multiple"]),
                    max_holding_minutes=int(family["max_holding_minutes"]))
                path = full_path.iloc[:int(family["max_holding_minutes"])]
                for sensitivity, percentile in (("NORMAL_P75", float(costs["spread_p75_bps"])),
                                                  ("STRESSED_P95", float(costs["spread_p95_bps"]))):
                    cost = CostPolicy(version=f"{COST_AUTHORITY_VERSION}:{sensitivity}",
                        slippage_bps_per_side=(0.25 if sensitivity == "NORMAL_P75" else 1.0) * percentile,
                        commission_bps_round_trip=0.0, financing_bps_per_day=0.0)
                    for direction in ("LONG", "SHORT"):
                        decision = Decision(market=symbol, decision_at_utc=_utc(member["decision_at_utc"]),
                            feature_cutoff_at_utc=max(_utc(v) for v in features["feature_cutoffs_utc"].values()),
                            feature_version=features["feature_version"], research_version=protocol["version"],
                            dataset_sha256=member["evidence_sha256"], direction=direction)
                        outcome = evaluate_trade(decision, execution, cost, path, regular_session=regular)
                        outcome.update({"opportunity_id": member["opportunity_id"],
                            "cost_sensitivity": sensitivity, "spread_percentile_bps": percentile,
                            "atr_snapshot_sha256": member["atr_snapshot_sha256"],
                            "feature_snapshot_sha256": member["feature_snapshot_sha256"],
                            "ig_m1_path_sha256": member["ig_m1_path_sha256"]})
                        market_outcomes.append(outcome)
            all_outcomes.extend(market_outcomes)

            artifact = ARTIFACT_DIR / model_entry["artifact_file"]
            if sha256(artifact.read_bytes()).hexdigest() != model_entry["artifact_sha256"]:
                raise ValueError(f"Selected model binary hash mismatch: {symbol}")
            payload = joblib.load(artifact)
            if (payload["market"] != symbol or payload["family"] != model_entry["family"]
                    or payload["model_name"] != model_entry["model"]
                    or payload["feature_names"] != manifest["feature_names"]):
                raise ValueError(f"Selected model metadata mismatch: {symbol}")
            x = np.asarray([[float(row["features"][name]) for name in manifest["feature_names"]]
                            for row, *_ in verified], dtype=float)
            predictions = [int(value) for value in payload["model"].predict(x)] if len(x) else []
            replay = replay_metrics([row for row, *_ in verified], market_outcomes, predictions,
                family=model_entry["family"], minimum_trades=int(protocol["minimum_evaluable_trades"]))
            market_results.append({"market": symbol, "model": model_entry["model"],
                "family": model_entry["family"], "window_opportunities": len(opportunities),
                "state_counts": state_counts, "joined": len(joined),
                "validation_spread_observation_count": len(validation_spreads),
                "validation_spread_p75_bps_report_only": float(np.percentile(validation_spreads, 75)) if validation_spreads else None,
                "development_frozen_spread_p75_bps_used": float(costs["spread_p75_bps"]),
                "development_frozen_spread_p95_bps_used": float(costs["spread_p95_bps"]),
                "model_artifact_sha256": model_entry["artifact_sha256"],
                "prediction_sha256": canonical_sha256(predictions), **replay})

    result = {"authority": "FROZEN_LOCKED_MODEL_PROSPECTIVE_VALIDATION",
        "validation_protocol_sha256": canonical_sha256(protocol),
        "evaluation_windows_sha256": canonical_sha256(windows),
        "selected_model_manifest_sha256": manifest["manifest_sha256"],
        "validation_start_utc": protocol["validation_start_utc"],
        "validation_end_exclusive_utc": protocol["validation_end_exclusive_utc"],
        "sql_read_end_exclusive_utc": (end + timedelta(minutes=120)).isoformat(),
        "model_training_performed": False, "model_retuning_performed": False,
        "holdout_accessed": False, "model_promotion": "NONE", "broker_submission_authority": False,
        "markets": market_results, "members": frozen_members, "outcomes": all_outcomes}
    result["validation_report_sha256"] = canonical_sha256(result)
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"validation_report_sha256": result["validation_report_sha256"],
            "markets": market_results, "all_selected_markets_passed": all(
                row["validation_passed"] for row in market_results)}


if __name__ == "__main__":
    print(json.dumps(freeze(), indent=2))
