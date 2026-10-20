import pytest

from app.prospective_v4_hypothesis import (
    FEATURE_ORDER,
    derived_features,
    should_trade,
    signal_direction,
    target,
)


BASE = {
    "m15_return_window": 0.003,
    "m15_volatility": 0.001,
    "m5_return_window": 0.002,
    "m5_volatility": 0.0005,
    "m1_return_window": -0.0004,
    "m1_volatility": 0.0002,
    "m1_spread_bps": 1.2,
}


def test_long_trend_requires_m1_pullback() -> None:
    assert signal_direction(BASE) == 1
    assert signal_direction({**BASE, "m1_return_window": 0.0004}) == 0


def test_short_trend_requires_aligned_m5_and_opposing_m1() -> None:
    features = {**BASE, "m15_return_window": -0.003,
                "m5_return_window": -0.002, "m1_return_window": 0.0004}
    assert signal_direction(features) == -1
    assert signal_direction({**features, "m5_return_window": 0.002}) == 0


def test_derived_features_follow_registered_order() -> None:
    values = derived_features(BASE, 1)
    assert len(values) == len(FEATURE_ORDER)
    assert values == pytest.approx([3.0, 4.0, 2.0, 0.5, 1.2])


def test_meta_target_requires_both_cost_sensitivities_positive() -> None:
    assert target(0.001, 0.0002) == 1
    assert target(0.001, -0.0001) == 0


def test_threshold_is_fixed_and_inclusive() -> None:
    assert should_trade(0.65)
    assert not should_trade(0.649999)
