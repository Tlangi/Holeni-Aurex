import pandas as pd

from forexbot.candle_store import CandleStore
from forexbot.streaming import IGStreamingFeed


def test_three_m5_candles_aggregate_to_one_m15(tmp_path):
    store = CandleStore(str(tmp_path / "candles"), ["EURUSD"])
    feed = object.__new__(IGStreamingFeed)
    feed.store = store
    rows = pd.DataFrame([
        {"time": pd.Timestamp("2026-08-17T10:00:00Z"), "open": 1.10, "high": 1.12, "low": 1.09, "close": 1.11, "tick_volume": 10},
        {"time": pd.Timestamp("2026-08-17T10:05:00Z"), "open": 1.11, "high": 1.13, "low": 1.10, "close": 1.12, "tick_volume": 20},
        {"time": pd.Timestamp("2026-08-17T10:10:00Z"), "open": 1.12, "high": 1.14, "low": 1.08, "close": 1.13, "tick_volume": 30},
    ])
    store.put("EURUSD", "M5", rows)

    feed._aggregate_m15("EURUSD", rows.iloc[-1].time)

    result = store.get("EURUSD", "M15", 1).iloc[0]
    assert result.open == 1.10
    assert result.high == 1.14
    assert result.low == 1.08
    assert result.close == 1.13
    assert result.tick_volume == 60


def test_incomplete_bucket_is_not_aggregated(tmp_path):
    store = CandleStore(str(tmp_path / "candles"), ["EURUSD"])
    feed = object.__new__(IGStreamingFeed)
    feed.store = store
    rows = pd.DataFrame([
        {"time": pd.Timestamp("2026-08-17T10:05:00Z"), "open": 1, "high": 1, "low": 1, "close": 1, "tick_volume": 1},
        {"time": pd.Timestamp("2026-08-17T10:10:00Z"), "open": 1, "high": 1, "low": 1, "close": 1, "tick_volume": 1},
    ])
    store.put("EURUSD", "M5", rows)

    feed._aggregate_m15("EURUSD", rows.iloc[-1].time)

    assert store.count("EURUSD", "M15") == 0
