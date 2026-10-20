"""Pure, preregistered V4 trend-pullback hypothesis transformations."""
from __future__ import annotations

import math

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


HYPOTHESIS_VERSION = "TREND_PULLBACK_META_V1"
FEATURE_ORDER = [
    "m15_trend_strength",
    "m5_trend_strength",
    "m1_pullback_strength",
    "m5_m15_volatility_ratio",
    "m1_spread_bps",
]
TRADE_PROBABILITY_THRESHOLD = 0.65


def signal_direction(features: dict[str, float]) -> int:
    """Return 1 for LONG, -1 for SHORT and 0 for deterministic NO_TRADE."""
    m15 = float(features["m15_return_window"])
    m5 = float(features["m5_return_window"])
    m1 = float(features["m1_return_window"])
    if not all(math.isfinite(value) for value in (m15, m5, m1)):
        raise ValueError("NON_FINITE_V4_SIGNAL_FEATURE")
    direction = 1 if m15 > 0 else -1 if m15 < 0 else 0
    if direction == 0 or direction * m5 <= 0 or direction * m1 >= 0:
        return 0
    return direction


def derived_features(features: dict[str, float], direction: int) -> list[float]:
    if direction not in (-1, 1):
        raise ValueError("V4_DIRECTION_REQUIRED")
    epsilon = 1e-12
    m15_vol = float(features["m15_volatility"])
    m5_vol = float(features["m5_volatility"])
    m1_vol = float(features["m1_volatility"])
    values = [
        direction * float(features["m15_return_window"]) / max(m15_vol, epsilon),
        direction * float(features["m5_return_window"]) / max(m5_vol, epsilon),
        -direction * float(features["m1_return_window"]) / max(m1_vol, epsilon),
        m5_vol / max(m15_vol, epsilon),
        float(features["m1_spread_bps"]),
    ]
    if not np.isfinite(values).all():
        raise ValueError("NON_FINITE_V4_DERIVED_FEATURE")
    return [float(value) for value in values]


def target(normal_return: float, stressed_return: float) -> int:
    return int(float(normal_return) > 0 and float(stressed_return) > 0)


def model_factory():
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=41,
        ),
    )


def should_trade(probability: float) -> bool:
    value = float(probability)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("INVALID_V4_PROBABILITY")
    return value >= TRADE_PROBABILITY_THRESHOLD
