import pandas as pd

from app.prospective_m15_continuity import SOURCE, assess_window, summarize_accumulation
from app.streaming import IGMarketStream, accepts_direct_stream_candle


def _frame(count=15):
    index = pd.date_range("2026-09-16T00:00:00Z", periods=count, freq="15min")
    return pd.DataFrame({"candle_id": range(count), "source": SOURCE,
        "completed": True, "quality_status": "PASS", "is_regular_session": True,
        "close_time_utc": [at + pd.Timedelta(15, unit="min") for at in index],
        "ingested_at_utc": [at + pd.Timedelta(15, unit="min") + pd.Timedelta(2, unit="s") for at in index],
        "high": [101.] * count, "low": [99.] * count, "close": [100.] * count}, index=index)


def test_complete_prospective_lineage_is_hash_attested():
    result = assess_window(_frame(), market="EURUSD")
    assert result["status"] == "COMPLETE"
    assert len(result["evidence_sha256"]) == 64


def test_old_source_or_gap_cannot_enter_prospective_window():
    old = _frame()
    old.loc[old.index[-1], "source"] = "DERIVED_M1"
    assert assess_window(old, market="EURUSD")["reason"] == "SOURCE_NOT_PROSPECTIVE_AUTHORITY"
    gap = _frame().drop(_frame().index[-2])
    assert assess_window(gap, market="EURUSD")["status"] == "ACCUMULATING"


def test_ingestion_before_close_is_invalid():
    frame = _frame()
    frame.loc[frame.index[-1], "ingested_at_utc"] = frame.index[-1]
    assert assess_window(frame, market="EURUSD")["reason"] == "AVAILABILITY_INVALID"


def test_m1_aggregation_uses_versioned_source_and_bound_parameters_match():
    class Cursor:
        def __init__(self):
            self.calls = []
        def execute(self, query, args):
            assert query.count("%s") == len(args)
            self.calls.append((query, args))
    cursor = Cursor()
    IGMarketStream._aggregate_m1(cursor, "market", pd.Timestamp("2026-09-16T12:14:00Z").to_pydatetime())
    assert len(cursor.calls) == 4
    assert all("IG_LIGHTSTREAMER_M1_AGG_" in query for query, _ in cursor.calls)
    assert {args[-4] for _, args in cursor.calls} == {"M5", "M15", "M30", "H1"}


def test_accumulation_counts_warmup_separately_across_session_segments():
    first = _frame(20)
    second = _frame(25)
    second.index = second.index + pd.Timedelta(2, unit="D")
    result = summarize_accumulation(pd.concat([first, second]), market="EURUSD")
    assert result["warmed_opportunities"] == 17
    assert result["target_reached"] is False


def test_only_m1_can_write_directly_to_canonical_live_candles():
    assert accepts_direct_stream_candle("M1")
    assert not any(accepts_direct_stream_candle(value)
                   for value in ("M5", "M15", "M30", "H1"))
