from datetime import datetime, timedelta, timezone

from scripts.diagnose_gbpusd_m1_coverage import classify


ENTRY = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)


def test_vendor_only_entry_never_becomes_broker_execution_path():
    vendor = [{"timestamp_utc": ENTRY.replace(tzinfo=None), "source": "DUKASCOPY_TICK_BID_ASK",
               "quality_state": "VALIDATED", "price_completeness": "BID_ASK_FULL"}]
    result = classify(ENTRY, [], vendor)
    assert result["classification"] == "BROKER_EXECUTION_PATH_UNAVAILABLE_VENDOR_RESEARCH_ONLY"
    assert result["ig_valid_m1_count"] == 0
    assert result["historical_vendor_entry"] is True


def test_complete_ig_path_and_missing_minute_are_distinct():
    canonical = [{"open_time_utc": (ENTRY + timedelta(minutes=i)).replace(tzinfo=None),
                  "source": "IG_LIGHTSTREAMER_M1", "completed": True,
                  "quality_status": "PASS", "bid_open": 1, "bid_high": 1,
                  "bid_low": 1, "bid_close": 1, "ask_open": 2,
                  "ask_high": 2, "ask_low": 2, "ask_close": 2,
                  "spread_close": 1} for i in range(60)]
    assert classify(ENTRY, canonical, [])["classification"] == "COMPLETE_IG_PATH"
    missing = classify(ENTRY, canonical[:13] + canonical[14:], [])
    assert missing["classification"] == "IG_ENTRY_PRESENT_PATH_GAP"
    assert missing["missing_ig_m1_count"] == 1
    assert missing["first_missing_ig_m1"] == (ENTRY + timedelta(minutes=13)).isoformat()


def test_present_ig_entry_filtered_by_quality_is_not_mislabelled_absent():
    canonical = [{"open_time_utc": ENTRY.replace(tzinfo=None), "source": "IG_LIGHTSTREAMER_M1",
                  "completed": False, "quality_status": "INCOMPLETE"}]
    assert classify(ENTRY, canonical, [])["classification"] == "IG_ENTRY_PRESENT_BUT_FILTERED"
