from datetime import datetime, time, timedelta, timezone

from scripts.report_three_view_quality import _gap_m1_support, _view


MARKET = {"symbol": "GBPUSD", "calendar_code": "FX_24X5", "market_timezone": "UTC",
          "session_open_local": time(0), "session_close_local": time(23, 59)}


def row(minute, source):
    return {"open_time_utc": datetime(2026, 9, 8, 12, minute, tzinfo=timezone.utc),
            "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1,
            "bid_close": 1.0999 if source.startswith("IG_") else None,
            "ask_close": 1.1001 if source.startswith("IG_") else None,
            "spread_close": .0002 if source.startswith("IG_") else None,
            "source": source}


def test_research_repair_never_becomes_current_execution_quote():
    rows = [row(0, "IG_LIGHTSTREAMER_M5"), row(5, "DUKASCOPY_M1_AGGREGATED")]
    hybrid = _view(rows, MARKET, set(), "HYBRID_RESEARCH")
    execution = _view(rows, MARKET, set(), "CURRENT_IG_EXECUTION")
    assert hybrid["observed"] == 2
    assert hybrid["providers"]["DUKASCOPY_M1_AGGREGATED"] == 1
    assert execution["observed"] == 1
    assert "DUKASCOPY_M1_AGGREGATED" not in execution["providers"]
    assert execution["status"] == "BLOCKED"
    assert hybrid["expected"] == hybrid["observed"] + hybrid["missing"]
    assert hybrid["valid_candles"] == hybrid["observed"]
    assert hybrid["quality_score_version"].endswith("_V3")


def test_broker_candle_wins_same_timestamp_in_hybrid():
    rows = [row(0, "IG_LIGHTSTREAMER_M5"), row(0, "DUKASCOPY_M1_AGGREGATED")]
    result = _view(rows, MARKET, set(), "HYBRID_RESEARCH")
    assert result["providers"] == {"IG_LIGHTSTREAMER_M5": 1}


def test_recovery_store_is_research_only_and_keeps_import_provenance():
    recovery = {**row(5, "DUKASCOPY_M1_DERIVED"),
                "research_recovery_store": True, "import_batch_id": "batch-a",
                "source_candle_ref": "market:time:source"}
    rows = [row(0, "IG_LIGHTSTREAMER_M5"), recovery]
    hybrid = _view(rows, MARKET, set(), "HYBRID_RESEARCH")
    execution = _view(rows, MARKET, set(), "CURRENT_IG_EXECUTION")
    assert hybrid["research_recovery_count"] == 1
    assert hybrid["research_recovery_provenance"][0]["import_batch_id"] == "batch-a"
    assert execution["research_recovery_count"] == 0
    assert execution["observed"] == 1


def test_gap_support_requires_all_five_m1_minutes_for_each_missing_m5():
    start = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    gap = {"after_utc": start.isoformat(), "before_utc": (start + timedelta(minutes=15)).isoformat(),
           "missing": 2}
    minutes = {start + timedelta(minutes=5 + offset) for offset in range(5)}
    minutes.add(start + timedelta(minutes=10))
    support = _gap_m1_support(gap, minutes)
    assert support["complete_m5_intervals"] == 1
    assert support["partial_m5_intervals"] == 1
    assert support["absent_m5_intervals"] == 0
    assert support["m1_minutes_present"] == 6


def test_gap_support_excludes_closed_session_intervals():
    start = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    gap = {"after_utc": start.isoformat(), "before_utc": (start + timedelta(minutes=15)).isoformat(),
           "missing": 1}
    support = _gap_m1_support(gap, set(), lambda timestamp: timestamp.minute == 10)
    assert support["absent_m5_intervals"] == 1
    assert support["complete_m5_intervals"] + support["partial_m5_intervals"] == 0
