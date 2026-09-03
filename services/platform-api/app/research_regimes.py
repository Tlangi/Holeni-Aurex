from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd


REGIME_VERSION = "EXPLAINABLE_REGIMES_V1"


def market_session(symbol: str, opened: datetime) -> str:
    moment = opened if opened.tzinfo else opened.replace(tzinfo=timezone.utc)
    if symbol == "GERMANY40":
        local = moment.astimezone(ZoneInfo("Europe/Berlin")).time()
        if local < time(9):
            return "PRE_OPEN"
        if local < time(10):
            return "OPENING"
        if local < time(14, 30):
            return "MID_SESSION"
        if local < time(16, 30):
            return "US_OVERLAP"
        if local < time(17, 30):
            return "CLOSING"
        return "CLOSED"
    london = moment.astimezone(ZoneInfo("Europe/London")).time()
    new_york = moment.astimezone(ZoneInfo("America/New_York")).time()
    tokyo = moment.astimezone(ZoneInfo("Asia/Tokyo")).time()
    london_open = time(8) <= london < time(17)
    new_york_open = time(8) <= new_york < time(17)
    if london_open and new_york_open:
        return "LONDON_NEW_YORK_OVERLAP"
    if london_open:
        return "LONDON"
    if new_york_open:
        return "NEW_YORK"
    if time(9) <= tokyo < time(18):
        return "ASIA"
    return "OFF_HOURS"


def trend_regime(ema_gap: float, atr_pct: float) -> str:
    strength = ema_gap / max(abs(atr_pct), 1e-12)
    if strength >= 0.75:
        return "STRONG_UPTREND"
    if strength >= 0.20:
        return "UPTREND"
    if strength <= -0.75:
        return "STRONG_DOWNTREND"
    if strength <= -0.20:
        return "DOWNTREND"
    return "RANGE"


def volatility_regimes(atr_pct: pd.Series, *, window: int = 200) -> pd.Series:
    # Shifted expanding/rolling quantiles use only information available before
    # the classified candle. The warm-up defaults to NORMAL rather than peeking.
    history = atr_pct.shift(1)
    low = history.rolling(window, min_periods=50).quantile(0.25)
    high = history.rolling(window, min_periods=50).quantile(0.75)
    extreme = history.rolling(window, min_periods=50).quantile(0.95)
    result = pd.Series("NORMAL", index=atr_pct.index, dtype="object")
    result = result.mask(atr_pct <= low, "LOW")
    result = result.mask(atr_pct > high, "HIGH")
    result = result.mask(atr_pct > extreme, "EXTREME")
    return result


def confidence_bucket(confidence: float, boundaries: tuple[float, ...]) -> str:
    value = max(0.5, min(1.0, confidence))
    for lower, upper in zip(boundaries, boundaries[1:]):
        if lower <= value < upper or (upper == boundaries[-1] and value <= upper):
            return f"{lower:.2f}-{upper:.2f}"
    return f"{boundaries[-2]:.2f}-{boundaries[-1]:.2f}"
