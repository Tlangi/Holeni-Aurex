from app.historical_failure_triage import classify_failure


def test_empty_vendor_partition_stays_ineligible():
    result = classify_failure("ValueError", "historical M1 batch has no candles")
    assert result["reason_code"] == "EMPTY_VENDOR_PARTITION"
    assert result["required_action"] == "VERIFY_VENDOR_AVAILABILITY_OR_SYMBOL_MAPPING"


def test_recent_gap_failure_extracts_governed_diagnostics():
    result = classify_failure(
        "RuntimeError",
        "failed_gates=COMPLETENESS_OR_RECENT_GAPS; coverage=95.833333%; "
        "invalid_ohlc=0; timestamp_errors=0; recent_gap_count=2",
    )
    assert result == {
        "reason_code": "RECENT_UNEXPECTED_GAPS",
        "required_action": "RECOVER_MISSING_MINUTES_AND_REVALIDATE",
        "coverage_percent": 95.833333,
        "recent_gap_count": 2,
    }


def test_old_coverage_failure_requires_calendar_review_without_eligibility_claim():
    result = classify_failure(
        "RuntimeError",
        "failed_gates=COMPLETENESS_OR_RECENT_GAPS; coverage=90.000000%; recent_gap_count=0",
    )
    assert result["reason_code"] == "BELOW_COVERAGE_THRESHOLD"
    assert result["required_action"] == "REVIEW_CALENDAR_AND_RECOVER_MISSING_MINUTES"
