from datetime import datetime, timedelta, timezone

from app.recent_window import assess_recent_m5_window


def rows(count: int = 2000) -> list[dict[str, object]]:
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    return [{"open_time_utc": start + timedelta(minutes=5 * i),
             "open": "100", "high": "101", "low": "99", "close": "100",
             "source": "IG_LIGHTSTREAMER"} for i in range(count)]


def test_recent_window_ignores_older_history_but_requires_latest_window() -> None:
    result = assess_recent_m5_window(rows(2100), required_rows=2000)
    assert result.passed is True
    assert result.observed_rows == 2000


def test_recent_window_rejects_gap_duplicate_bad_ohlc_and_missing_lineage() -> None:
    sample = rows()
    sample[1000]["open_time_utc"] = sample[999]["open_time_utc"]
    sample[1200]["high"] = "98"
    sample[1500]["source"] = ""
    result = assess_recent_m5_window(sample)
    assert result.passed is False
    assert "DUPLICATE_RECENT_M5_TIMESTAMP" in result.reasons
    assert "INVALID_RECENT_M5_OHLC" in result.reasons
    assert "RECENT_M5_LINEAGE_MISSING" in result.reasons


def test_recent_window_reports_completeness_and_gap_boundaries() -> None:
    sample = rows()
    sample[1000]["open_time_utc"] = sample[999]["open_time_utc"] + timedelta(minutes=10)
    result = assess_recent_m5_window(sample)
    assert result.completeness_percentage < 100
    assert result.gap_ranges[0][2] == 1


def test_recent_window_keeps_older_gaps_outside_the_window() -> None:
    sample = rows(2001)
    sample[0]["open_time_utc"] = sample[0]["open_time_utc"] - timedelta(days=30)
    result = assess_recent_m5_window(sample)
    assert result.passed is True
