"""Research-only executable M1 outcomes; never grants trading authority."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json

import pandas as pd


LABEL_VERSIONS = {
    "direction": "FUTURE_CLOSE_DIRECTION_4_M15_V2",
    "net_return": "CFD_NET_RETURN_M1_V1_EXPERIMENTAL",
    "first_hit": "CFD_FIRST_HIT_M1_V1_EXPERIMENTAL",
    "realised_r": "CFD_REALISED_R_M1_V1_EXPERIMENTAL",
}
REQUIRED_QUOTES = ("bid_open", "ask_open", "bid_high", "bid_low", "bid_close",
                   "ask_high", "ask_low", "ask_close")


@dataclass(frozen=True)
class OutcomeRequest:
    market: str
    dataset_hash: str
    decision_at_utc: datetime
    signal_minutes: int
    direction: str
    stop_price: float
    target_price: float
    max_holding_minutes: int
    slippage_bps_per_side: float = 0.0
    funding_bps: float = 0.0

    def __post_init__(self) -> None:
        if (not self.market or len(self.dataset_hash) != 64 or self.direction not in {"LONG", "SHORT"}
                or self.signal_minutes not in {5, 15} or self.max_holding_minutes < 1
                or self.slippage_bps_per_side < 0 or self.funding_bps < 0
                or self.decision_at_utc.tzinfo is None
                or self.decision_at_utc.utcoffset() != timedelta(0)):
            raise ValueError("Invalid immutable research outcome request")

    @property
    def prediction_id(self) -> str:
        return prediction_identity(self.market, self.dataset_hash, self.decision_at_utc,
                                   self.signal_minutes, self.direction)


def prediction_identity(market: str, dataset_hash: str, decision_at_utc: datetime,
                        signal_minutes: int, direction: str) -> str:
    if not market or len(dataset_hash) != 64 or direction not in {"LONG", "SHORT"}:
        raise ValueError("Invalid prediction identity")
    identity = {"market": market, "dataset_hash": dataset_hash,
                "decision_at_utc": decision_at_utc.isoformat(),
                "signal_minutes": signal_minutes, "direction": direction}
    return sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def completed_m1_outcome(request: OutcomeRequest, candles: pd.DataFrame) -> dict[str, object]:
    """Return UNKNOWN/AMBIGUOUS instead of guessing a price path or future bar order.

    M1 indexes are UTC opening times. A signal at `decision_at_utc` is an M5/M15
    *opening* timestamp; entry uses the next M1 open after that signal completes.
    Price stops/targets are executable exit-side levels (bid for long, ask for short).
    """
    base: dict[str, object] = {"prediction_id": request.prediction_id,
                               "label_version": LABEL_VERSIONS["first_hit"],
                               "status": "INVALID", "reason": None,
                               "net_return_label": None, "net_r": None}
    if candles.index.tz is None or not candles.index.is_unique or not set(REQUIRED_QUOTES).issubset(candles.columns):
        return {**base, "reason": "M1_SCHEMA_OR_TIMESTAMP_INVALID"}
    entry_at = pd.Timestamp(request.decision_at_utc) + pd.Timedelta(request.signal_minutes, unit="min")
    path = candles.sort_index().loc[entry_at:entry_at + pd.Timedelta(request.max_holding_minutes - 1, unit="min")]
    if path.empty or path.index[0] != entry_at:
        return {**base, "reason": "M1_ENTRY_MISSING"}
    entry = path.iloc[0]
    if _invalid_quote(entry):
        return {**base, "reason": "M1_QUOTE_INVALID"}
    bid_entry, ask_entry = float(entry.bid_open), float(entry.ask_open)
    price_entry = ask_entry if request.direction == "LONG" else bid_entry
    risk_distance = (price_entry - request.stop_price if request.direction == "LONG"
                     else request.stop_price - price_entry)
    target_distance = (request.target_price - price_entry if request.direction == "LONG"
                       else price_entry - request.target_price)
    if risk_distance <= 0 or target_distance <= 0:
        return {**base, "reason": "INVALID_BARRIERS"}
    mfe = 0.0
    mae = 0.0
    previous: pd.Timestamp | None = None
    for timestamp, row in path.iterrows():
        if previous is not None and timestamp - previous != pd.Timedelta(1, unit="min"):
            return {**base, "reason": "M1_GAP"}
        if _invalid_quote(row):
            return {**base, "reason": "M1_QUOTE_INVALID"}
        previous = timestamp
        high = float(row.bid_high if request.direction == "LONG" else row.ask_low)
        low = float(row.bid_low if request.direction == "LONG" else row.ask_high)
        favourable = (high - price_entry if request.direction == "LONG" else price_entry - high)
        adverse = (price_entry - low if request.direction == "LONG" else low - price_entry)
        mfe, mae = max(mfe, favourable), max(mae, adverse)
        hit_target = high >= request.target_price if request.direction == "LONG" else high <= request.target_price
        hit_stop = low <= request.stop_price if request.direction == "LONG" else low >= request.stop_price
        if hit_target and hit_stop:
            return {**base, "status": "AMBIGUOUS", "reason": "BOTH_BARRIERS_IN_ONE_M1",
                    "entry_at_utc": entry_at.isoformat(), "exit_at_utc": timestamp.isoformat()}
        if hit_target or hit_stop:
            exit_price = request.target_price if hit_target else request.stop_price
            exit_open = float(row.bid_open if request.direction == "LONG" else row.ask_open)
            if hit_stop and ((request.direction == "LONG" and exit_open < exit_price)
                             or (request.direction == "SHORT" and exit_open > exit_price)):
                exit_price = exit_open  # adverse gap: never assume stop filled at the level
            status = "TARGET_FIRST" if hit_target else "STOP_FIRST"
            break
    else:
        if len(path) != request.max_holding_minutes:
            return {**base, "reason": "M1_PATH_INCOMPLETE"}
        row = path.iloc[-1]
        exit_price = float(row.bid_close if request.direction == "LONG" else row.ask_close)
        timestamp = path.index[-1]
        status = "TIME_EXIT"
    direction = 1 if request.direction == "LONG" else -1
    mid_entry = (bid_entry + ask_entry) / 2
    exit_bid = float(row.bid_close)
    exit_ask = float(row.ask_close)
    mid_exit = (exit_bid + exit_ask) / 2 if status == "TIME_EXIT" else exit_price
    gross_return = direction * (mid_exit - mid_entry) / mid_entry
    spread_adjusted = direction * (exit_price - price_entry) / price_entry
    cost_return = (2 * request.slippage_bps_per_side + request.funding_bps) / 10000
    net_return = spread_adjusted - cost_return
    return {**base, "status": status, "reason": None,
            "entry_at_utc": entry_at.isoformat(), "exit_at_utc": timestamp.isoformat(),
            "executable_entry": price_entry, "executable_exit": exit_price,
            "gross_directional_return": gross_return,
            "spread_adjusted_return": spread_adjusted, "net_return": net_return,
            "net_return_label": "POSITIVE_NET" if net_return > 0 else "NONPOSITIVE_NET",
            "net_r": net_return * price_entry / risk_distance,
            "mfe_r": mfe / risk_distance, "mae_r": mae / risk_distance,
            "cost_bps": 2 * request.slippage_bps_per_side + request.funding_bps}


def _invalid_quote(row: pd.Series) -> bool:
    try:
        values = [float(row[name]) for name in REQUIRED_QUOTES]
    except (ValueError, TypeError):
        return True
    if any(not pd.notna(value) or value <= 0 for value in values):
        return True
    return (row.ask_open < row.bid_open or row.ask_close < row.bid_close
            or row.bid_low > min(row.bid_open, row.bid_close)
            or row.bid_high < max(row.bid_open, row.bid_close)
            or row.ask_low > min(row.ask_open, row.ask_close)
            or row.ask_high < max(row.ask_open, row.ask_close)
            or row.bid_high < row.bid_low or row.ask_high < row.ask_low)
