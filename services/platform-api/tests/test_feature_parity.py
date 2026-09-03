import numpy as np
import pandas as pd

from app.model_pipeline import FEATURES, add_features, feature_vector_hash, inference_feature_vector


def candles() -> pd.DataFrame:
    index = pd.date_range("2026-01-05", periods=80, freq="15min", tz="UTC")
    close = pd.Series(np.linspace(1.1, 1.12, len(index)) + np.sin(np.arange(len(index))) / 10000,
                      index=index)
    return pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "high": close + .0002,
        "low": close - .0002, "close": close, "tick_volume": np.arange(len(index)) + 10,
        "provider": "IG"}, index=index)


def test_live_and_research_golden_vector_are_identical() -> None:
    frame = candles()
    research = add_features(frame, labelled=False).iloc[-1][FEATURES].astype(float)
    live = inference_feature_vector(frame)
    np.testing.assert_allclose(live.to_numpy(), research.to_numpy(), rtol=0, atol=1e-12)
    assert list(live.index) == FEATURES
    assert feature_vector_hash(live) == feature_vector_hash(research)


def test_gap_and_provider_boundaries_reset_lookback() -> None:
    frame = candles()
    frame.iloc[60:, frame.columns.get_loc("provider")] = "DUKASCOPY"
    featured = add_features(frame, labelled=False)
    second_provider = featured.loc[featured.index >= frame.index[60]]
    assert second_provider.index.min() >= frame.index[74]


def test_timezone_representation_does_not_change_vector() -> None:
    utc = candles()
    sast = utc.copy(); sast.index = sast.index.tz_convert("Africa/Johannesburg")
    np.testing.assert_allclose(inference_feature_vector(utc), inference_feature_vector(sast),
                               rtol=0, atol=1e-12)
