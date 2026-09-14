"""Read-only, fixed-policy GBP/USD development diagnostic; never promotes a model.

Uses data before 10 Sep 2026 only. The four-M15-bar direction label is a
baseline, not economic proof. No SQL/model artefact is written and no holdout
row is read. Run only after reviewing the fixed dates, thresholds and costs.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import open_database
from app.economic_outcomes import OutcomeRequest, completed_m1_outcome, prediction_identity
from app.model_governance import LABEL_VERSION, FEATURE_VERSION
from app.model_pipeline import FEATURES, _market_frame, add_features, training_dataset_identity

TRAIN_START = pd.Timestamp("2026-08-20T00:00:00Z")
VALIDATION_START = pd.Timestamp("2026-09-07T00:00:00Z")
HOLDOUT_START = pd.Timestamp("2026-09-10T00:00:00Z")
POLICY = {"direction_long_probability": 0.70, "direction_short_probability": 0.30,
          "stop_atr_multiple": 1.5, "target_r_multiple": 2.0,
          "maximum_holding_minutes": 60, "slippage_bps_per_side": 0.5,
          "funding_bps": 0.0, "model": "HGB_DEPTH3_LR0.05_ITER200_L2_1_SEED42",
          "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION,
          "train_start_utc": TRAIN_START.isoformat(),
          "validation_start_utc": VALIDATION_START.isoformat(),
          "holdout_start_utc": HOLDOUT_START.isoformat()}


def _m1_frame(cursor, market_id: str) -> pd.DataFrame:
    cursor.execute(""";WITH ranked AS (
        SELECT open_time_utc,bid_open,bid_high,bid_low,bid_close,
               ask_open,ask_high,ask_low,ask_close,
               ROW_NUMBER() OVER(PARTITION BY open_time_utc ORDER BY candle_id DESC) rn
        FROM app.candles WHERE market_id=%s AND timeframe='M1' AND completed=1
          AND quality_status='PASS' AND source LIKE 'IG_LIGHTSTREAMER%%'
          AND open_time_utc>=%s AND open_time_utc<%s)
        SELECT open_time_utc,bid_open,bid_high,bid_low,bid_close,
               ask_open,ask_high,ask_low,ask_close FROM ranked WHERE rn=1
        ORDER BY open_time_utc""",
                   (market_id, VALIDATION_START.to_pydatetime().replace(tzinfo=None),
                    HOLDOUT_START.to_pydatetime().replace(tzinfo=None)))
    rows = cursor.fetchall()
    columns = ["open_time_utc", "bid_open", "bid_high", "bid_low", "bid_close",
               "ask_open", "ask_high", "ask_low", "ask_close"]
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return pd.DataFrame(columns=columns[1:], index=pd.DatetimeIndex([], tz="UTC"))
    frame["open_time_utc"] = pd.to_datetime(frame["open_time_utc"], utc=True)
    return frame.set_index("open_time_utc")


def run() -> dict[str, object]:
    with open_database(get_settings()) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT market_id FROM app.markets WHERE symbol=%s AND enabled=1", ("GBPUSD",))
        market_id = str(cursor.fetchone()[0])
        # SQL bounds prevent holdout rows from being fetched, even transiently.
        frame = _market_frame(
            cursor, market_id,
            from_utc=TRAIN_START.to_pydatetime().replace(tzinfo=None),
            before_utc=HOLDOUT_START.to_pydatetime().replace(tzinfo=None),
        )
        m1 = _m1_frame(cursor, market_id)
    if frame.empty or m1.empty:
        raise ValueError("Frozen development M15 or IG M1 evidence absent")
    dataset_hash = training_dataset_identity(frame)
    features = add_features(frame, labelled=True)
    training = features.loc[features.index < VALIDATION_START]
    validation = features.loc[(features.index >= VALIDATION_START) & (features.index < HOLDOUT_START)]
    # Purge four labelled rows: their future-close target could reach validation.
    training = training.iloc[:-4]
    if len(training) < 500 or len(validation) < 30:
        raise ValueError(f"Insufficient frozen cohort: train={len(training)}, validation={len(validation)}")
    model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                           max_iter=200, l2_regularization=1, random_state=42)
    model.fit(training[FEATURES], training["target"].astype(int))
    probabilities = model.predict_proba(validation[FEATURES])[:, 1]
    auc = roc_auc_score(validation["target"].astype(int), probabilities)
    outcomes = []
    for timestamp, (_, row), probability in zip(validation.index, validation.iterrows(), probabilities):
        direction = "LONG" if probability >= POLICY["direction_long_probability"] else (
            "SHORT" if probability <= POLICY["direction_short_probability"] else "NO_TRADE")
        if direction == "NO_TRADE":
            continue
        signed_four_bar = float(row["future_return"]) * (1 if direction == "LONG" else -1)
        prediction_id = prediction_identity("GBPUSD", dataset_hash, timestamp.to_pydatetime(), 15, direction)
        entry_at = timestamp + pd.Timedelta(15, unit="min")
        if entry_at not in m1.index:
            outcomes.append({"prediction_id": prediction_id, "decision_utc": timestamp.isoformat(),
                             "direction": direction, "probability": float(probability),
                             "direction_label": int(row["target"]), "gross_four_bar_return": signed_four_bar,
                             "status": "INVALID", "reason": "M1_ENTRY_MISSING"})
            continue
        quote = m1.loc[entry_at]
        entry = float(quote["ask_open"] if direction == "LONG" else quote["bid_open"])
        distance = float(row["atr"]) * POLICY["stop_atr_multiple"]
        stop = entry - distance if direction == "LONG" else entry + distance
        target = entry + distance * POLICY["target_r_multiple"] if direction == "LONG" else entry - distance * POLICY["target_r_multiple"]
        request = OutcomeRequest("GBPUSD", dataset_hash, timestamp.to_pydatetime(), 15,
                                 direction, stop, target, POLICY["maximum_holding_minutes"],
                                 POLICY["slippage_bps_per_side"], POLICY["funding_bps"])
        result = completed_m1_outcome(request, m1)
        outcomes.append({"decision_utc": timestamp.isoformat(), "direction": direction,
                         "probability": float(probability), "direction_label": int(row["target"]),
                         "gross_four_bar_return": signed_four_bar, **result})
    valid = [r for r in outcomes if r["status"] in {"TARGET_FIRST", "STOP_FIRST", "TIME_EXIT"}]
    net_r = np.asarray([float(r["net_r"]) for r in valid], dtype=float)
    wins, losses = net_r[net_r > 0], net_r[net_r < 0]
    return {"authority": "DIAGNOSTIC_RESEARCH_ONLY", "market": "GBPUSD",
            "policy": POLICY, "dataset_sha256": dataset_hash,
            "policy_sha256": sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest(),
            "training_rows": len(training), "validation_rows": len(validation),
            "ig_m1_rows": len(m1), "directional_auc": float(auc),
            "selected_count": len(outcomes), "valid_first_hit_count": len(valid),
            "status_counts": dict(Counter(r["status"] for r in outcomes)),
            "gross_four_bar_mean": float(np.mean([r["gross_four_bar_return"] for r in outcomes if "gross_four_bar_return" in r])) if outcomes else None,
            "net_r_mean_valid_only": float(net_r.mean()) if len(net_r) else None,
            "net_r_profit_factor_valid_only": float(wins.sum() / -losses.sum()) if len(losses) else None,
            "holdout_accessed": False, "model_promoted": False,
            "rows": outcomes}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2, default=str))
