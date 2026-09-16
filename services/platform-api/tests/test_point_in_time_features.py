from datetime import datetime, timezone

import pandas as pd

from app.point_in_time_features import feature_snapshot


DECISION = datetime(2026, 9, 15, 12, 15, tzinfo=timezone.utc)


def _frame(timeframe, periods, source):
    minutes = {"M1": 1, "M5": 5, "M15": 15}[timeframe]
    index = pd.date_range(end=pd.Timestamp(DECISION) - pd.Timedelta(minutes, unit="min"),
                          periods=periods, freq=f"{minutes}min")
    return pd.DataFrame({"completed": [True] * periods,
                         "source": [source] * periods,
                         "ingested_at_utc": [at + pd.Timedelta(minutes, unit="min")
                                             for at in index],
                         "close": [1 + n * 0.001 for n in range(periods)],
                         "bid_close": [1 + n * 0.001 for n in range(periods)],
                         "ask_close": [1.0002 + n * 0.001 for n in range(periods)]},
                        index=index)


def _frames():
    return {"M1": _frame("M1", 4, "IG_LIGHTSTREAMER"),
            "M5": _frame("M5", 4, "IG_DEMO_HISTORICAL"),
            "M15": _frame("M15", 5, "IG_DEMO_HISTORICAL")}


def test_completed_three_timeframe_snapshot_is_immutable_and_cutoff_safe():
    first = feature_snapshot(DECISION, _frames(), market="EURUSD")
    second = feature_snapshot(DECISION, _frames(), market="EURUSD")
    assert first["status"] == "COMPLETE"
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert all(pd.Timestamp(value) <= pd.Timestamp(DECISION)
               for value in first["feature_cutoffs_utc"].values())
    assert first["features"]["m1_spread_bps"] > 0


def test_candle_completing_after_decision_cannot_change_features():
    frames = _frames()
    baseline = feature_snapshot(DECISION, frames, market="EURUSD")
    future = _frame("M1", 1, "IG_LIGHTSTREAMER")
    future.index = pd.DatetimeIndex(["2026-09-15T12:15:00Z"])
    future.loc[future.index[0], "close"] = 999
    frames["M1"] = pd.concat([frames["M1"], future])
    assert feature_snapshot(DECISION, frames, market="EURUSD") == baseline


def test_incomplete_or_hybrid_m1_cannot_satisfy_feature_window():
    frames = _frames()
    frames["M1"].loc[frames["M1"].index[-1], "completed"] = False
    assert feature_snapshot(DECISION, frames, market="EURUSD")["status"] == "UNVERIFIABLE"
    frames = _frames()
    frames["M1"].loc[frames["M1"].index[-1], "source"] = "DUKASCOPY_REPAIR"
    assert feature_snapshot(DECISION, frames, market="EURUSD")["reason"] == "SOURCE_AUTHORITY_OR_TRANSITION"


def test_later_ingestion_cannot_enter_historical_feature_snapshot():
    frames = _frames()
    frames["M15"].loc[frames["M15"].index[-1], "ingested_at_utc"] = \
        pd.Timestamp("2026-09-15T12:16:00Z")
    assert feature_snapshot(DECISION, frames, market="EURUSD")["reason"] == \
        "FEATURE_NOT_AVAILABLE_AT_DECISION"


def test_missing_trailing_bar_is_not_filled_from_earlier_time():
    frames = _frames()
    frames["M5"] = frames["M5"].drop(frames["M5"].index[-2])
    assert feature_snapshot(DECISION, frames, market="EURUSD")["timeframe"] == "M5"
