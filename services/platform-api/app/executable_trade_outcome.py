"""Versioned, research-only CFD outcome from completed broker-native M1 quotes.

No database write, model promotion, programme arming or broker submission occurs here.
The historical M15 directional label remains available for comparison only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from math import isfinite
from typing import Callable

import pandas as pd


LABEL_VERSION = "EXECUTABLE_TRADE_OUTCOME_M1_V1_RESEARCH"
ENTRY_POLICY_VERSION = "FIRST_BROKER_M1_OPEN_AT_OR_AFTER_DECISION_V1"
AMBIGUITY_POLICY_VERSION = "SAME_M1_BOTH_BARRIERS_UNVERIFIABLE_V1"
REQUIRED = ("bid_open", "bid_high", "bid_low", "bid_close",
            "ask_open", "ask_high", "ask_low", "ask_close", "source", "completed")


@dataclass(frozen=True)
class ExecutionPolicy:
    version: str
    stop_distance: float
    target_distance: float
    max_holding_minutes: int
    entry_policy_version: str = ENTRY_POLICY_VERSION
    ambiguity_policy_version: str = AMBIGUITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if (not self.version or self.entry_policy_version != ENTRY_POLICY_VERSION
                or self.ambiguity_policy_version != AMBIGUITY_POLICY_VERSION
                or not isfinite(self.stop_distance) or self.stop_distance <= 0
                or not isfinite(self.target_distance) or self.target_distance <= 0
                or self.max_holding_minutes < 1):
            raise ValueError("Invalid declared execution policy")


@dataclass(frozen=True)
class CostPolicy:
    version: str
    slippage_bps_per_side: float | None
    commission_bps_round_trip: float | None
    financing_bps_per_day: float | None
    financing_rollover_hour_utc: int | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("Cost policy version required")
        for value in (self.slippage_bps_per_side, self.commission_bps_round_trip,
                      self.financing_bps_per_day):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError("Invalid declared CFD cost")
        if (self.financing_rollover_hour_utc is not None and
                not 0 <= self.financing_rollover_hour_utc <= 23):
            raise ValueError("Invalid financing rollover hour")

    @property
    def complete(self) -> bool:
        return (all(value is not None for value in (
            self.slippage_bps_per_side, self.commission_bps_round_trip,
            self.financing_bps_per_day)) and
            (self.financing_bps_per_day == 0 or
             self.financing_rollover_hour_utc is not None))


@dataclass(frozen=True)
class Decision:
    market: str
    decision_at_utc: datetime
    feature_cutoff_at_utc: datetime
    feature_version: str
    research_version: str
    dataset_sha256: str
    direction: str
    label_version: str = LABEL_VERSION

    def __post_init__(self) -> None:
        if (not self.market or not self.feature_version or not self.research_version
                or len(self.dataset_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.dataset_sha256.lower())
                or self.direction not in {"LONG", "SHORT", "NO_TRADE"}
                or self.label_version != LABEL_VERSION):
            raise ValueError("Invalid immutable decision identity")
        for value in (self.decision_at_utc, self.feature_cutoff_at_utc):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("Decision and feature cutoff must be UTC")
        if self.feature_cutoff_at_utc > self.decision_at_utc:
            raise ValueError("Future feature cutoff is lookahead")


def prediction_id(decision: Decision, execution: ExecutionPolicy, costs: CostPolicy) -> str:
    """Policy-sensitive immutable ID: unequal assumptions cannot share an outcome."""
    payload = {"decision": asdict(decision), "execution": asdict(execution),
               "costs": asdict(costs)}
    return sha256(json.dumps(payload, sort_keys=True, default=str,
                             separators=(",", ":")).encode()).hexdigest()


def evaluate_trade(
    decision: Decision, execution: ExecutionPolicy, costs: CostPolicy,
    candles: pd.DataFrame, *, regular_session: Callable[[datetime], bool] | None = None,
) -> dict[str, object]:
    """Evaluate first executable M1 open and chronological bid/ask exit.

    Index values are UTC M1 *opening* times. `decision_at_utc` must represent a
    completed feature candle; no M1 opening before it is eligible. A missing
    broker candle, unknown cost or ambiguous OHLC ordering has no net label.
    A market-specific session callback is mandatory for session-exit claims;
    otherwise paths are limited to the explicit holding window only.
    """
    identity = prediction_id(decision, execution, costs)
    base: dict[str, object] = {
        "prediction_id": identity, "market": decision.market,
        "decision_at_utc": decision.decision_at_utc.isoformat(),
        "feature_cutoff_at_utc": decision.feature_cutoff_at_utc.isoformat(),
        "feature_version": decision.feature_version,
        "research_version": decision.research_version,
        "dataset_sha256": decision.dataset_sha256,
        "label_version": LABEL_VERSION,
        "execution_policy_version": execution.version,
        "entry_policy_version": execution.entry_policy_version,
        "ambiguity_policy_version": execution.ambiguity_policy_version,
        "cost_policy_version": costs.version,
        "direction": decision.direction,
        "status": "UNVERIFIABLE", "reason": None, "economic_label": "UNVERIFIABLE",
        "net_return": None, "gross_return": None, "r_multiple": None,
    }
    if decision.direction == "NO_TRADE":
        return {**base, "status": "NO_TRADE", "economic_label": "NO_TRADE",
                "reason": "DECLARED_NO_TRADE_DECISION"}
    if not costs.complete:
        return {**base, "reason": "COST_COMPONENT_UNVERIFIED"}
    if (candles.index.tz is None or not candles.index.is_unique
            or not set(REQUIRED).issubset(candles.columns)
            or not all(timestamp.utcoffset() == timedelta(0) for timestamp in candles.index)):
        return {**base, "reason": "M1_SCHEMA_OR_UTC_INVALID"}
    eligible_at = pd.Timestamp(decision.decision_at_utc).ceil("min")
    end_at = eligible_at + pd.Timedelta(execution.max_holding_minutes - 1, unit="min")
    path = candles.sort_index().loc[eligible_at:end_at]
    if path.empty or path.index[0] != eligible_at:
        return {**base, "eligible_entry_at_utc": eligible_at.isoformat(),
                "reason": "BROKER_M1_ENTRY_MISSING"}
    if regular_session and not regular_session(eligible_at.to_pydatetime()):
        return {**base, "reason": "ENTRY_OUTSIDE_REGULAR_SESSION"}
    entry = path.iloc[0]
    if not _valid_broker_quote(entry):
        return {**base, "reason": "BROKER_M1_QUOTE_OR_SOURCE_INVALID",
                "invalid_at_utc": eligible_at.isoformat()}
    entry_bid, entry_ask = float(entry.bid_open), float(entry.ask_open)
    entry_price = entry_ask if decision.direction == "LONG" else entry_bid
    stop = entry_price - execution.stop_distance if decision.direction == "LONG" else entry_price + execution.stop_distance
    target = entry_price + execution.target_distance if decision.direction == "LONG" else entry_price - execution.target_distance
    if stop <= 0 or target <= 0:
        return {**base, "reason": "INVALID_PRICE_BARRIERS"}
    mfe = mae = 0.0
    exit_at: pd.Timestamp | None = None
    exit_row: pd.Series | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    previous_at = previous_row = None
    for at, row in path.iterrows():
        if previous_at is not None and at - previous_at != pd.Timedelta(1, unit="min"):
            return {**base, "reason": "BROKER_M1_PATH_GAP",
                    "first_missing_at_utc": (previous_at + pd.Timedelta(1, unit="min")).isoformat()}
        if not _valid_broker_quote(row):
            return {**base, "reason": "BROKER_M1_QUOTE_OR_SOURCE_INVALID",
                    "invalid_at_utc": at.isoformat()}
        if regular_session and not regular_session(at.to_pydatetime()):
            if previous_at is None or previous_row is None:
                return {**base, "reason": "ENTRY_OUTSIDE_REGULAR_SESSION"}
            exit_at, exit_row = previous_at, previous_row
            exit_price = _exit_close(previous_row, decision.direction)
            exit_reason = "SESSION_EXIT"
            break
        favorable = (float(row.bid_high) - entry_price if decision.direction == "LONG"
                     else entry_price - float(row.ask_low))
        adverse = (entry_price - float(row.bid_low) if decision.direction == "LONG"
                   else float(row.ask_high) - entry_price)
        mfe, mae = max(mfe, favorable), max(mae, adverse)
        stop_hit = (float(row.bid_low) <= stop if decision.direction == "LONG"
                    else float(row.ask_high) >= stop)
        target_hit = (float(row.bid_high) >= target if decision.direction == "LONG"
                      else float(row.ask_low) <= target)
        if stop_hit and target_hit:
            return {**base, "status": "AMBIGUOUS", "reason": "BOTH_BARRIERS_SAME_M1",
                    "economic_label": "UNVERIFIABLE", "entry_at_utc": eligible_at.isoformat(),
                    "exit_at_utc": at.isoformat(), "entry_bid": entry_bid,
                    "entry_ask": entry_ask, "stop_price": stop, "target_price": target}
        if stop_hit or target_hit:
            exit_at, exit_row = at, row
            exit_reason = "STOP" if stop_hit else "TARGET"
            level = stop if stop_hit else target
            open_exit = float(row.bid_open if decision.direction == "LONG" else row.ask_open)
            # Adverse gap cannot be assigned an optimistic stop-level fill.
            exit_price = (min(level, open_exit) if decision.direction == "LONG" else
                          max(level, open_exit)) if stop_hit else level
            break
        previous_at, previous_row = at, row
    if exit_at is None:
        if len(path) != execution.max_holding_minutes or path.index[-1] != end_at:
            return {**base, "reason": "BROKER_M1_PATH_INCOMPLETE"}
        exit_at, exit_row = path.index[-1], path.iloc[-1]
        exit_price = _exit_close(exit_row, decision.direction)
        exit_reason = "TIME_EXIT"
    assert exit_price is not None and exit_row is not None and exit_at is not None
    sign = 1 if decision.direction == "LONG" else -1
    entry_mid = (entry_bid + entry_ask) / 2
    exit_mid = ((float(exit_row.bid_close) + float(exit_row.ask_close)) / 2
                if exit_reason in {"TIME_EXIT", "SESSION_EXIT"} else None)
    executable_return = sign * (exit_price - entry_price) / entry_price
    # Stop/target OHLC does not reveal the opposite quote at the first hit.
    # Never invent an exact exit-mid/spread decomposition in that case.
    mid_directional_return = (sign * (exit_mid - entry_mid) / entry_mid
                              if exit_mid is not None else None)
    spread_cost = (mid_directional_return - executable_return
                   if mid_directional_return is not None else None)
    gross_return = executable_return  # Gross executable return before explicit CFD fees.
    holding_minutes = int((exit_at - eligible_at) / pd.Timedelta(1, unit="min")) + 1
    slippage_cost = 2 * float(costs.slippage_bps_per_side) / 10000
    commission_cost = float(costs.commission_bps_round_trip) / 10000
    rollovers = 0
    if costs.financing_rollover_hour_utc is not None:
        day = eligible_at.normalize()
        while day <= exit_at.normalize():
            rollover = day + pd.Timedelta(costs.financing_rollover_hour_utc, unit="h")
            if eligible_at < rollover < exit_at + pd.Timedelta(1, unit="min"):
                rollovers += 1
            day += pd.Timedelta(1, unit="day")
    financing_cost = float(costs.financing_bps_per_day) * rollovers / 10000
    net_return = executable_return - slippage_cost - commission_cost - financing_cost
    risk_return = execution.stop_distance / entry_price
    return {**base, "status": "EVALUATED", "reason": None,
            "economic_label": "PROFITABLE_LONG" if net_return > 0 and sign == 1 else (
                "PROFITABLE_SHORT" if net_return > 0 else "NONPROFITABLE_TRADE"),
            "entry_at_utc": eligible_at.isoformat(), "exit_at_utc": exit_at.isoformat(),
            "eligible_entry_at_utc": eligible_at.isoformat(),
            "entry_bid": entry_bid, "entry_ask": entry_ask,
            "entry_spread": entry_ask - entry_bid,
            "entry_source": str(entry.source), "entry_completed": True,
            "executable_entry": entry_price, "executable_exit": exit_price,
            "stop_price": stop, "target_price": target, "exit_reason": exit_reason,
            "gross_return": gross_return, "executable_return": executable_return,
            "gross_mid_directional_return": mid_directional_return,
            "net_return": net_return, "r_multiple": net_return / risk_return,
            "mfe_price": mfe, "mae_price": mae,
            "mfe_r": mfe / execution.stop_distance,
            "mae_r": mae / execution.stop_distance,
            "holding_minutes": holding_minutes,
            "spread_cost_return": spread_cost,
            "entry_half_spread_return": (entry_ask - entry_bid) / (2 * entry_mid),
            "slippage_cost_return": slippage_cost,
            "commission_cost_return": commission_cost,
            "financing_cost_return": financing_cost,
            "financing_rollovers": rollovers}


def _exit_close(row: pd.Series, direction: str) -> float:
    return float(row.bid_close if direction == "LONG" else row.ask_close)


def _valid_broker_quote(row: pd.Series) -> bool:
    try:
        values = {key: float(row[key]) for key in REQUIRED[:8]}
    except (ValueError, TypeError, KeyError):
        return False
    if (not str(row.source).startswith("IG_LIGHTSTREAMER")
            or row.completed is not True and row.completed != 1
            or any(not isfinite(value) or value <= 0 for value in values.values())):
        return False
    for side in ("bid", "ask"):
        if (values[f"{side}_low"] > min(values[f"{side}_open"], values[f"{side}_close"])
                or values[f"{side}_high"] < max(values[f"{side}_open"], values[f"{side}_close"])
                or values[f"{side}_low"] > values[f"{side}_high"]):
            return False
    return not any(values[f"bid_{point}"] > values[f"ask_{point}"]
                   for point in ("open", "high", "low", "close"))
