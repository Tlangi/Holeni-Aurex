"""Non-executing, point-in-time research primitives.

Nothing in this module writes model or trading state. Prediction rows are joined
to execution evidence by timestamp and a caller-supplied immutable dataset hash.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json

import numpy as np
import pandas as pd


_MINUTES = {"M1": 1, "M5": 5, "M15": 15}


@dataclass(frozen=True)
class ResearchArchitecture:
    signal_timeframe: str
    context_timeframes: tuple[str, ...] = ()
    execution_timeframe: str = "M1"
    forecast_horizon_minutes: int = 60
    max_holding_minutes: int = 60
    feature_set_version: str = "FEATURES_V1"
    label_version: str = "FUTURE_CLOSE_DIRECTION_4_M15_V2"
    strategy_version: str = "RESEARCH_ONLY_V1"
    cost_model_version: str = "UNVERIFIED"

    def __post_init__(self) -> None:
        if self.signal_timeframe not in {"M5", "M15"}:
            raise ValueError("Signal timeframe must be M5 or M15")
        if self.execution_timeframe != "M1":
            raise ValueError("Research execution resolution must be M1")
        if any(value not in _MINUTES or value == "M1" for value in self.context_timeframes):
            raise ValueError("Unsupported context timeframe")
        if self.forecast_horizon_minutes <= 0 or self.max_holding_minutes <= 0:
            raise ValueError("Horizons must be positive")

    def digest(self) -> str:
        return sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def completed_context_join(signal: pd.DataFrame, context: pd.DataFrame, *,
                           signal_timeframe: str, context_timeframe: str) -> pd.DataFrame:
    """Attach only context bars completed when the signal bar completes.

    Indexes are UTC *opening* timestamps. Provider continuity is not inferred;
    callers retain provider columns and must still segment features at transitions.
    """
    if signal_timeframe not in _MINUTES or context_timeframe not in _MINUTES:
        raise ValueError("Unsupported timeframe")
    if signal.index.tz is None or context.index.tz is None:
        raise ValueError("UTC-aware candle indexes required")
    if not signal.index.is_unique or not context.index.is_unique:
        raise ValueError("Duplicate candle timestamps are not research-safe")
    left = signal.sort_index().copy()
    right = context.sort_index().copy()
    if "completed" in left.columns and not left["completed"].fillna(False).astype(bool).all():
        raise ValueError("Incomplete signal candle cannot form a research decision")
    if "completed" in right.columns:
        right = right.loc[right["completed"].fillna(False).astype(bool)]
    left["_signal_complete_at"] = left.index + pd.Timedelta(_MINUTES[signal_timeframe], unit="min")
    right["_context_complete_at"] = right.index + pd.Timedelta(_MINUTES[context_timeframe], unit="min")
    right["_context_open_at"] = right.index
    rename = {column: f"{context_timeframe.lower()}_{column}" for column in context.columns}
    right = right.rename(columns=rename)
    joined = pd.merge_asof(left.reset_index(names="signal_open_at").sort_values("_signal_complete_at"),
                           right.sort_values("_context_complete_at"),
                           left_on="_signal_complete_at", right_on="_context_complete_at",
                           direction="backward")
    if joined["_context_complete_at"].notna().any():
        assert (joined.loc[joined["_context_complete_at"].notna(), "_context_complete_at"]
                <= joined.loc[joined["_context_complete_at"].notna(), "_signal_complete_at"]).all()
    return joined.set_index("signal_open_at").drop(columns=["_signal_complete_at", "_context_complete_at"])


@dataclass(frozen=True)
class EconomicLabelPolicy:
    label_version: str = "CFD_NET_OPPORTUNITY_V1"
    signal_timeframe: str = "M5"
    execution_timeframe: str = "M1"
    forecast_horizon_minutes: int = 60
    required_edge_bps: float = 2.0
    slippage_bps: float = 0.5
    funding_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.signal_timeframe not in {"M5", "M15"} or self.execution_timeframe != "M1":
            raise ValueError("Unsupported signal/execution resolution")
        if self.forecast_horizon_minutes not in {30, 60}:
            raise ValueError("Only predeclared 30/60 minute horizons are supported")
        if min(self.required_edge_bps, self.slippage_bps, self.funding_bps) < 0:
            raise ValueError("Costs and required edge must be nonnegative")


def cfd_net_opportunity(signal: pd.DataFrame, execution: pd.DataFrame,
                        policy: EconomicLabelPolicy) -> pd.DataFrame:
    """Label a fixed-horizon executable opportunity; never fabricate M1 gaps.

    Entry is the first completed M1 bar after signal completion. Exit is the
    completed M1 bar at the predeclared horizon. Missing bid/ask or M1 bars
    yields UNKNOWN, not a mid-price substitute or a NO_TRADE observation.
    This is a *fixed-horizon* label, not a stop/target path label.
    """
    if signal.index.tz is None or execution.index.tz is None:
        raise ValueError("UTC-aware indexes required")
    if not signal.index.is_unique or not execution.index.is_unique:
        raise ValueError("Duplicate timestamps")
    required = {"bid_close", "ask_close"}
    if not required.issubset(execution.columns):
        raise ValueError("Executable bid and ask required")
    execution = execution.sort_index()
    results = []
    for timestamp in signal.sort_index().index:
        entry_time = timestamp + pd.Timedelta(_MINUTES[policy.signal_timeframe], unit="min")
        exit_time = entry_time + pd.Timedelta(policy.forecast_horizon_minutes - 1, unit="min")
        path = execution.loc[entry_time:exit_time]
        if (len(path) != policy.forecast_horizon_minutes or path.index[0] != entry_time
                or path.index[-1] != exit_time or not path.index.to_series().diff().iloc[1:].eq(pd.Timedelta(1, unit="min")).all()
                or path[["bid_close", "ask_close"]].isna().any().any()):
            results.append({"label": "UNKNOWN", "net_long_return": np.nan,
                            "net_short_return": np.nan, "entry_time": entry_time, "exit_time": exit_time})
            continue
        entry_bid, entry_ask = float(path.iloc[0]["bid_close"]), float(path.iloc[0]["ask_close"])
        exit_bid, exit_ask = float(path.iloc[-1]["bid_close"]), float(path.iloc[-1]["ask_close"])
        if min(entry_bid, entry_ask, exit_bid, exit_ask) <= 0 or entry_ask < entry_bid or exit_ask < exit_bid:
            raise ValueError("Invalid executable quote")
        other_cost = (policy.slippage_bps + policy.funding_bps) / 10000
        long_net = (exit_bid - entry_ask) / entry_ask - other_cost
        short_net = (entry_bid - exit_ask) / entry_bid - other_cost
        edge = policy.required_edge_bps / 10000
        label = ("LONG" if long_net > edge and long_net > short_net else
                 "SHORT" if short_net > edge and short_net > long_net else "NO_TRADE")
        results.append({"label": label, "net_long_return": long_net,
                        "net_short_return": short_net, "entry_time": entry_time, "exit_time": exit_time})
    return pd.DataFrame(results, index=signal.sort_index().index)


def same_cohort_bridge(predictions: pd.DataFrame, outcomes: pd.DataFrame, *,
                       experiment_id: str, market: str, dataset_hash: str) -> pd.DataFrame:
    """One-to-one, fail-closed join of out-of-fold predictions and trade outcomes."""
    keys = ["prediction_timestamp", "fold_id", "dataset_row_id"]
    if not experiment_id or not market or len(dataset_hash) != 64:
        raise ValueError("Immutable experiment, market and dataset identities required")
    for name, frame in (("predictions", predictions), ("outcomes", outcomes)):
        if not set(keys).issubset(frame.columns) or frame.duplicated(keys).any():
            raise ValueError(f"{name} lacks unique same-cohort keys")
    result = predictions.merge(outcomes, on=keys, validate="one_to_one", how="outer", indicator=True)
    if not result["_merge"].eq("both").all():
        raise ValueError("Missing prediction or outcome in cohort")
    result = result.drop(columns="_merge")
    result.insert(0, "experiment_id", experiment_id)
    result.insert(1, "market", market)
    result.insert(2, "dataset_hash", dataset_hash)
    return result.sort_values(keys).reset_index(drop=True)
