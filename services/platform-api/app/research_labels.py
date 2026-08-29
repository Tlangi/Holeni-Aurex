from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EconomicLabelPolicy:
    version: str = "ECONOMIC_PATH_LABEL_V1_EXPERIMENTAL"
    horizon: int = 8
    minimum_edge_bps: float = 2.0
    transaction_cost_bps: float = 1.0
    maximum_adverse_bps: float = 8.0

    def configuration(self) -> dict[str, object]:
        return asdict(self)


def economic_path_labels(frame: pd.DataFrame, policy: EconomicLabelPolicy) -> pd.Series:
    """Build experimental LONG/SHORT/NO_TRADE targets from future paths.

    Future prices are used only here to construct the supervised target. The
    function returns no future-path columns that could enter the feature matrix.
    """
    if policy.horizon < 1:
        raise ValueError("Label horizon must be positive")
    close = frame["close"].astype(float)
    threshold = (policy.minimum_edge_bps + policy.transaction_cost_bps) / 10000.0
    adverse_limit = policy.maximum_adverse_bps / 10000.0
    future_high = pd.concat([frame["high"].shift(-step) for step in range(1, policy.horizon + 1)], axis=1).max(axis=1)
    future_low = pd.concat([frame["low"].shift(-step) for step in range(1, policy.horizon + 1)], axis=1).min(axis=1)
    long_favourable = future_high / close - 1
    long_adverse = 1 - future_low / close
    short_favourable = 1 - future_low / close
    short_adverse = future_high / close - 1
    labels = pd.Series("NO_TRADE", index=frame.index, dtype="object")
    long_ok = (long_favourable > threshold) & (long_adverse <= adverse_limit)
    short_ok = (short_favourable > threshold) & (short_adverse <= adverse_limit)
    labels = labels.mask(long_ok & ~short_ok, "LONG_OPPORTUNITY")
    labels = labels.mask(short_ok & ~long_ok, "SHORT_OPPORTUNITY")
    labels.iloc[-policy.horizon:] = np.nan
    return labels
