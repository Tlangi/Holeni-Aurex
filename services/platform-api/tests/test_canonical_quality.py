from app.market_intelligence import _provider_family


def test_complete_m1_derivatives_share_the_ig_canonical_lineage() -> None:
    assert _provider_family("IG_LIGHTSTREAMER") == "IG"
    assert _provider_family("IG_DEMO_HISTORICAL") == "IG"
    assert _provider_family("DERIVED_M1") == "IG"
    assert _provider_family("DUKASCOPY_TICK_M1") == "DUKASCOPY"
