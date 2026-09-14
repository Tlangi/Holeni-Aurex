from datetime import datetime, timezone

import pandas as pd

from app.economic_outcomes import OutcomeRequest, completed_m1_outcome
from app.experimental_demo import effective_programme_status
from app.multi_timeframe_research import completed_context_join


def request(direction="LONG", **updates):
    values = dict(market="GBPUSD", dataset_hash="a" * 64,
                  decision_at_utc=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
                  signal_minutes=5, direction=direction,
                  stop_price=1.0990 if direction == "LONG" else 1.1020,
                  target_price=1.1020 if direction == "LONG" else 1.0990,
                  max_holding_minutes=3, slippage_bps_per_side=1)
    values.update(updates)
    return OutcomeRequest(**values)


def path(*, bid_high=(1.1010, 1.1025, 1.1010), bid_low=(1.0998, 1.1000, 1.1000),
         ask_high=(1.1012, 1.1012, 1.1012), ask_low=(1.1002, 1.0988, 1.1002)):
    index = pd.date_range("2026-09-08T12:05:00Z", periods=3, freq="min")
    return pd.DataFrame({"bid_open": [1.1000] * 3, "ask_open": [1.1002] * 3,
                         "bid_high": bid_high, "bid_low": bid_low, "bid_close": [1.1004] * 3,
                         "ask_high": ask_high, "ask_low": ask_low, "ask_close": [1.1006] * 3}, index=index)


def test_long_target_uses_ask_entry_bid_exit_and_slippage():
    outcome = completed_m1_outcome(request(), path())
    assert outcome["status"] == "TARGET_FIRST"
    assert outcome["executable_entry"] == 1.1002
    assert outcome["executable_exit"] == 1.1020
    assert outcome["net_return"] < outcome["spread_adjusted_return"]
    assert outcome["net_r"] > 0


def test_short_target_uses_bid_entry_ask_exit():
    outcome = completed_m1_outcome(request("SHORT"), path(ask_low=(1.1002, 1.0988, 1.1002)))
    assert outcome["status"] == "TARGET_FIRST"
    assert outcome["executable_entry"] == 1.1000
    assert outcome["executable_exit"] == 1.0990


def test_both_barriers_same_minute_is_ambiguous():
    outcome = completed_m1_outcome(request(), path(bid_high=(1.1025, 1.1010, 1.1010),
                                                   bid_low=(1.0985, 1.1000, 1.1000)))
    assert outcome["status"] == "AMBIGUOUS"
    assert outcome["net_r"] is None


def test_gap_or_missing_path_is_invalid_not_profitable():
    candles = path().drop(path().index[1])
    assert completed_m1_outcome(request(), candles)["reason"] == "M1_GAP"
    assert completed_m1_outcome(request(), path().iloc[:2].assign(bid_high=1.1010))["reason"] == "M1_PATH_INCOMPLETE"


def test_time_exit_and_deterministic_prediction_identity():
    candles = path(bid_high=(1.1010,) * 3, ask_low=(1.1002,) * 3)
    first = completed_m1_outcome(request(), candles)
    second = completed_m1_outcome(request(), candles)
    assert first["status"] == "TIME_EXIT"
    assert first["prediction_id"] == second["prediction_id"]


def test_expired_stored_armed_is_effectively_expired_without_mutation():
    expiry = datetime(2026, 9, 11, 7, 6, tzinfo=timezone.utc)
    assert effective_programme_status("ARMED", expiry,
                                     now_utc=datetime(2026, 9, 13, tzinfo=timezone.utc)) == "EXPIRED"
    assert effective_programme_status("KILLED", expiry,
                                     now_utc=datetime(2026, 9, 13, tzinfo=timezone.utc)) == "KILLED"


def test_incomplete_m15_never_joins_completed_m5_decision():
    signal = pd.DataFrame({"close": [1.0], "completed": [True]},
                          index=pd.DatetimeIndex(["2026-09-08T12:05:00Z"]))
    context = pd.DataFrame({"close": [2.0, 3.0], "completed": [True, False]},
                           index=pd.DatetimeIndex(["2026-09-08T11:45:00Z", "2026-09-08T12:00:00Z"]))
    joined = completed_context_join(signal, context, signal_timeframe="M5", context_timeframe="M15")
    assert joined.iloc[0]["m15_close"] == 2.0
