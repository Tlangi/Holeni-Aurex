from app.market_intelligence import _combined_validation_status, _provider_family


def test_provider_sources_are_grouped_without_cross_provider_continuity() -> None:
    assert _provider_family("DUKASCOPY_BID") == "DUKASCOPY"
    assert _provider_family("IG_LIGHTSTREAMER") == "IG"
    assert _provider_family("IG_HISTORICAL") == "IG"


def test_historical_provider_boundary_does_not_create_a_combined_warning() -> None:
    assert _combined_validation_status(failures=0, recent_missing=0) == "PASS"


def test_combined_validation_remains_fail_closed_for_bad_or_recent_data() -> None:
    assert _combined_validation_status(failures=1, recent_missing=0) == "FAIL"
    assert _combined_validation_status(failures=0, recent_missing=1) == "WARN"
