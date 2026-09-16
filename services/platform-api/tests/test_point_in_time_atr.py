from datetime import datetime, timezone

import pandas as pd

from app.point_in_time_atr import atr14_snapshot


DECISION = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _frame():
    index = pd.date_range(end=pd.Timestamp(DECISION) - pd.Timedelta(15, unit="min"),
                          periods=15, freq="15min")
    close = [100 + n for n in range(15)]
    return pd.DataFrame({"candle_id": range(15), "high": [v + 1 for v in close],
        "low": [v - 1 for v in close], "close": close, "completed": True,
        "source": "IG_DEMO_HISTORICAL",
        "ingested_at_utc": [at + pd.Timedelta(15, unit="min") for at in index]}, index=index)


def test_atr14_uses_15_contiguous_available_m15_bars():
    result = atr14_snapshot(DECISION, _frame(), market="EURUSD")
    assert result["status"] == "COMPLETE"
    assert result["atr"] == 2.0
    assert len(result["bars"]) == 15


def test_late_or_gapped_atr_input_is_unverifiable():
    late = _frame()
    late.loc[late.index[-1], "ingested_at_utc"] = pd.Timestamp(DECISION) + pd.Timedelta(1, unit="min")
    assert atr14_snapshot(DECISION, late, market="EURUSD")["reason"] == "NOT_AVAILABLE_AT_DECISION"
    gapped = _frame().drop(_frame().index[-2])
    assert atr14_snapshot(DECISION, gapped, market="EURUSD")["status"] == "UNVERIFIABLE"
