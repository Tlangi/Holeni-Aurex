import pandas as pd

from forexbot.candle_store import CandleStore


def test_candle_store_upserts_and_returns_latest(tmp_path):
    store = CandleStore(str(tmp_path / "candles"), ["EURUSD"])
    frame = pd.DataFrame({
        "time": pd.to_datetime(["2026-08-17T10:00:00Z", "2026-08-17T10:15:00Z"]),
        "open": [1.0, 1.1], "high": [1.2, 1.3], "low": [.9, 1.0],
        "close": [1.1, 1.2], "tick_volume": [0, 0],
    })
    store.put("EURUSD", "M15", frame)
    frame.loc[1, "close"] = 1.25
    store.put("EURUSD", "M15", frame.iloc[1:])
    result = store.get("EURUSD", "M15", 1)
    assert len(result) == 1
    assert result.iloc[0].close == 1.25
    assert store.count("EURUSD", "M15") == 2
    assert store.bounds("EURUSD", "M15") == ("2026-08-17T10:00:00+00:00", "2026-08-17T10:15:00+00:00")


def test_refresh_metadata_persists(tmp_path):
    path = str(tmp_path / "candles")
    CandleStore(path, ["EURUSD"]).set_meta("last_refresh:EURUSD:M15", 123.5)
    assert CandleStore(path, ["EURUSD"]).get_meta("last_refresh:EURUSD:M15") == "123.5"
