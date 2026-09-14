from datetime import datetime, timezone

from app.historical_validation import (
    effective_observed_end, effective_validation_end, validation_failure_detail,
)


def test_active_partition_stops_at_latest_completed_utc_minute() -> None:
    now = datetime(2026, 9, 9, 20, 37, 42, tzinfo=timezone.utc)
    requested = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)
    assert effective_validation_end(requested, now_utc=now) == datetime(2026, 9, 9, 20, 37)


def test_closed_partition_keeps_immutable_requested_end() -> None:
    now = datetime(2026, 9, 9, 20, 37, tzinfo=timezone.utc)
    requested = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    assert effective_validation_end(requested, now_utc=now) == datetime(2026, 8, 1)


def test_active_vendor_tail_stops_after_latest_observed_candle() -> None:
    end = datetime(2026, 9, 9, 20, 37)
    observed = [datetime(2026, 9, 9, 18, 59), datetime(2026, 9, 9, 19, 0)]
    assert effective_observed_end(end, observed, active_partition=True) == datetime(2026, 9, 9, 19, 1)
    assert effective_observed_end(end, observed, active_partition=False) == end


def test_failure_detail_names_gate_and_recent_interval() -> None:
    detail = validation_failure_detail({
        "failed_gates": ["COMPLETENESS_OR_RECENT_GAPS"],
        "coverage_percentage": 0.989,
        "invalid_ohlc_count": 0,
        "timestamp_error_count": 0,
        "recent_unexpected_gaps": [{
            "start_utc": "2026-09-09T20:00:00",
            "end_utc": "2026-09-09T20:05:00",
        }],
    })
    assert "COMPLETENESS_OR_RECENT_GAPS" in detail
    assert "98.900000%" in detail
    assert "2026-09-09T20:00:00" in detail
