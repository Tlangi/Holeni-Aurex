from app.market_intelligence import (
    _authoritative_provider_completeness,
    _combined_validation_status,
    _provider_family,
)


def test_provider_sources_are_grouped_without_cross_provider_continuity() -> None:
    assert _provider_family("DUKASCOPY_BID") == "DUKASCOPY"
    assert _provider_family("IG_LIGHTSTREAMER") == "IG"
    assert _provider_family("IG_HISTORICAL") == "IG"


def test_historical_provider_boundary_does_not_create_a_combined_warning() -> None:
    assert _combined_validation_status(failures=0, recent_missing=0) == "PASS"


def test_combined_validation_remains_fail_closed_for_bad_or_recent_data() -> None:
    assert _combined_validation_status(failures=1, recent_missing=0) == "FAIL"
    assert _combined_validation_status(failures=0, recent_missing=1) == "WARN"


def test_authoritative_completeness_uses_ig_lane_not_disjoint_vendor_eras() -> None:
    provider, observed, missing, completeness = _authoritative_provider_completeness({
        "DUKASCOPY": {"observed_regular_count": 4964, "missing_period_count": 8636},
        "IG": {"observed_regular_count": 1015, "missing_period_count": 45},
    })
    assert provider == "IG"
    assert (observed, missing) == (1015, 45)
    assert completeness == 1015 / 1060


def test_authoritative_completeness_falls_back_to_largest_available_lane() -> None:
    provider, observed, missing, completeness = _authoritative_provider_completeness({
        "VENDOR_A": {"observed_regular_count": 10, "missing_period_count": 2},
        "VENDOR_B": {"observed_regular_count": 20, "missing_period_count": 0},
    })
    assert provider == "VENDOR_B"
    assert (observed, missing, completeness) == (20, 0, 1.0)
