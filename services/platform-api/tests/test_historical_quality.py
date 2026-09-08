from datetime import datetime, time, timezone

from app.historical_quality import classify_missing_minutes, expected_trading_minutes, ohlc_valid


def test_fx_weekend_is_not_expected_source_data() -> None:
    expected = expected_trading_minutes(
        datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc),
        datetime(2026, 9, 7, 0, 2, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC",
        session_open=None, session_close=None, holidays=set(),
    )
    assert datetime(2026, 9, 4, 20, 59) in expected
    assert datetime(2026, 9, 5, 12, 0) not in expected
    assert datetime(2026, 9, 6, 22, 0) not in expected
    assert datetime(2026, 9, 7, 0, 1) in expected


def test_index_closed_period_is_not_classified_as_missing() -> None:
    expected = expected_trading_minutes(
        datetime(2026, 9, 7, 5, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30), holidays=set(),
    )
    assert min(expected) == datetime(2026, 9, 7, 7, 0)
    assert datetime(2026, 9, 7, 6, 59) not in expected


def test_missing_minutes_are_grouped_into_partition_local_spans() -> None:
    expected = {datetime(2026, 9, 7, 0, minute) for minute in range(5)}
    gaps = classify_missing_minutes(expected, {min(expected), max(expected)}, symbol="USDJPY")
    assert len(gaps) == 1
    assert gaps[0].missing_minutes == 3
    assert gaps[0].reason_code == "SOURCE_MISSING"


def test_ohlc_structure_rejects_impossible_range() -> None:
    assert ohlc_valid("1.0", "1.2", "0.9", "1.1")
    assert not ohlc_valid("1.0", "1.05", "0.9", "1.1")
