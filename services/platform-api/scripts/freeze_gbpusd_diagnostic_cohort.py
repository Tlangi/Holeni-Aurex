"""Freeze the fixed GBP/USD diagnostic and unavailable broker paths, without promotion.

This is an append-only research record, deliberately outside the governed
candidate/holdout lineage. It cannot authorize Shadow or Demo execution.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from scripts.diagnose_gbpusd_economic_bridge import run
from scripts.diagnose_gbpusd_m1_coverage import classify


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def build_manifest(diagnostic: dict, candle_refs: list[dict]) -> dict:
    policy = diagnostic["policy"]
    return {"market": "GBPUSD", "authority": "NONPROMOTABLE_RESEARCH_ONLY",
            "decision_timeframe": "M15", "dataset_sha256": diagnostic["dataset_sha256"],
            "policy_sha256": diagnostic["policy_sha256"], "feature_version": policy["feature_version"],
            "label_version": policy["label_version"], "model_descriptor": policy["model"],
            "threshold_long": policy["direction_long_probability"],
            "threshold_short": policy["direction_short_probability"],
            "stop_atr_multiple": policy["stop_atr_multiple"],
            "target_r_multiple": policy["target_r_multiple"],
            "maximum_holding_minutes": policy["maximum_holding_minutes"],
            "slippage_bps_per_side": policy["slippage_bps_per_side"],
            "funding_bps": policy["funding_bps"],
            "cost_model_version": "FIXED_DIAGNOSTIC_COST_V1",
            "spread_model_version": "OBSERVED_IG_M1_BID_ASK_V1",
            "purge_policy": "FOUR_M15_LABEL_ROWS_AT_TRAIN_VALIDATION_BOUNDARY",
            "development_start_utc": policy["train_start_utc"],
            "validation_start_utc": policy["validation_start_utc"],
            "holdout_start_utc": policy["holdout_start_utc"],
            "holdout_governance": "NOT_RESERVED_DO_NOT_PROMOTE",
            "selected_prediction_ids": [r["prediction_id"] for r in diagnostic["rows"]],
            "source_candles": candle_refs}


def main() -> None:
    diagnostic = run()
    if diagnostic["selected_count"] != 13:
        raise ValueError("Frozen diagnostic changed; inspect before recording a new cohort")
    with open_database(get_settings(), query_timeout_seconds=120) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol='GBPUSD' AND enabled=1")
        market_id = str(cursor.fetchone()["market_id"])
        policy = diagnostic["policy"]
        start = datetime.fromisoformat(policy["train_start_utc"]).replace(tzinfo=None)
        holdout = datetime.fromisoformat(policy["holdout_start_utc"]).replace(tzinfo=None)
        cursor.execute(""";WITH ranked AS (
          SELECT candle_id,open_time_utc,source,
             ROW_NUMBER() OVER(PARTITION BY open_time_utc ORDER BY
              CASE WHEN source LIKE 'IG_LIGHTSTREAMER%%' THEN 1
                   WHEN source='IG_DEMO_HISTORICAL' THEN 2
                   WHEN source LIKE 'DUKASCOPY%%' THEN 3 ELSE 9 END,
              COALESCE(ingested_at_utc,created_at_utc) DESC) rn
          FROM app.candles WHERE market_id=%s AND timeframe='M15' AND completed=1
            AND quality_status='PASS' AND is_regular_session=1
            AND open_time_utc>=%s AND open_time_utc<%s)
          SELECT candle_id,open_time_utc,source FROM ranked WHERE rn=1
          ORDER BY open_time_utc""", (market_id, start, holdout))
        candle_refs = [{"candle_id": int(r["candle_id"]),
                        "open_time_utc": r["open_time_utc"].replace(tzinfo=timezone.utc).isoformat(),
                        "source": r["source"]} for r in cursor.fetchall()]
        manifest = build_manifest(diagnostic, candle_refs)
        manifest_json = canonical_json(manifest)
        manifest_hash = sha256(manifest_json.encode()).hexdigest()
        cursor.execute("""SELECT cohort_id,selected_count FROM app.frozen_research_diagnostic_cohorts
                          WHERE manifest_sha256=%s""", (manifest_hash,))
        prior = cursor.fetchone()
        if prior:
            print(canonical_json({"status": "ALREADY_FROZEN", "cohort_id": str(prior["cohort_id"]),
                                  "manifest_sha256": manifest_hash,
                                  "selected_count": int(prior["selected_count"])}))
            return
        cohort_id = str(uuid4())
        outcomes = []
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
            coverage = classify(entry, canonical, historical)
            broker_path = prediction["status"] in {"TARGET_FIRST", "STOP_FIRST", "TIME_EXIT"}
            outcomes.append({"prediction": prediction, "m1_coverage": coverage,
                             "broker_execution_path_available": broker_path,
                             "research_vendor_path_possible": bool(coverage["historical_vendor_entry"])})
        valid = sum(x["broker_execution_path_available"] for x in outcomes)
        cursor.execute("""INSERT app.frozen_research_diagnostic_cohorts
          (cohort_id,market_id,dataset_sha256,manifest_sha256,manifest_json,
           selected_count,valid_ig_outcome_count) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
          (cohort_id, market_id, diagnostic["dataset_sha256"], manifest_hash,
           manifest_json, len(outcomes), valid))
        for row in outcomes:
            prediction = row["prediction"]
            payload = canonical_json(row)
            cursor.execute("""INSERT app.frozen_research_prediction_outcomes
              (cohort_id,prediction_id,decision_utc,outcome_status,broker_path_available,
               outcome_sha256,outcome_json) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
              (cohort_id, prediction["prediction_id"],
               datetime.fromisoformat(prediction["decision_utc"]).replace(tzinfo=None),
               prediction["status"], int(row["broker_execution_path_available"]),
               sha256(payload.encode()).hexdigest(), payload))
        connection.commit()
    print(canonical_json({"status": "FROZEN_NONPROMOTABLE_RESEARCH", "cohort_id": cohort_id,
                          "manifest_sha256": manifest_hash, "dataset_sha256": diagnostic["dataset_sha256"],
                          "candle_refs": len(candle_refs), "selected_count": len(outcomes),
                          "valid_ig_outcomes": valid,
                          "failure_reasons": dict(Counter(x["prediction"].get("reason") or "VALID"
                                                          for x in outcomes))}))


if __name__ == "__main__":
    main()
