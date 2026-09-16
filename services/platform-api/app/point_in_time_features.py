"""Research-only M1/M5/M15 features with completed-candle decision cutoffs."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json

import pandas as pd


FEATURE_VERSION = "M1_M5_M15_EXECUTABLE_POINT_IN_TIME_V1_RESEARCH"
MINUTES = {"M1": 1, "M5": 5, "M15": 15}
REQUIRED_BARS = {"M1": 4, "M5": 4, "M15": 5}


def feature_snapshot(
    decision_at_utc: datetime, frames: dict[str, pd.DataFrame], *,
    market: str, version: str = FEATURE_VERSION,
) -> dict[str, object]:
    """Use only contiguous, completed bars whose end <= decision timestamp.

    Opening timestamps index each input frame. Missing, revised, hybrid M1 or
    future-completing bars never fill a feature value. Source transitions within
    a trailing window fail rather than silently mixing provenance.
    """
    if (not market or version != FEATURE_VERSION or decision_at_utc.tzinfo is None
            or decision_at_utc.utcoffset() != timedelta(0)
            or set(frames) != set(MINUTES)):
        raise ValueError("Invalid point-in-time feature request")
    values = {}
    cutoffs = {}
    source_identity = {}
    for timeframe, minutes in MINUTES.items():
        frame = frames[timeframe]
        if (frame.index.tz is None or not frame.index.is_unique
                or not all(at.utcoffset() == timedelta(0) for at in frame.index)
                or not {"completed", "source", "close"}.issubset(frame.columns)):
            return _unverifiable(market, decision_at_utc, timeframe, "FRAME_SCHEMA_INVALID")
        ordered = frame if frame.index.is_monotonic_increasing else frame.sort_index()
        eligible = ordered.loc[
            ordered.index + pd.Timedelta(minutes, unit="min")
            <= pd.Timestamp(decision_at_utc)]
        eligible = eligible.loc[eligible["completed"].fillna(False).astype(bool)]
        bars = eligible.tail(REQUIRED_BARS[timeframe])
        if len(bars) != REQUIRED_BARS[timeframe]:
            return _unverifiable(market, decision_at_utc, timeframe, "INSUFFICIENT_COMPLETED_BARS")
        availability_columns = [name for name in ("ingested_at_utc", "created_at_utc")
                                if name in bars.columns]
        if not availability_columns:
            return _unverifiable(market, decision_at_utc, timeframe,
                                 "AVAILABILITY_TIMESTAMP_MISSING")
        availability = pd.to_datetime(bars[availability_columns[0]], utc=True)
        if len(availability_columns) > 1:
            fallback = pd.to_datetime(bars[availability_columns[1]], utc=True)
            availability = availability.fillna(fallback)
        if availability.isna().any():
            return _unverifiable(market, decision_at_utc, timeframe,
                                 "AVAILABILITY_TIMESTAMP_MISSING")
        if (availability > pd.Timestamp(decision_at_utc)).any():
            return _unverifiable(market, decision_at_utc, timeframe,
                                 "FEATURE_NOT_AVAILABLE_AT_DECISION")
        if not bars.index.to_series().diff().iloc[1:].eq(pd.Timedelta(minutes, unit="min")).all():
            return _unverifiable(market, decision_at_utc, timeframe, "TRAILING_BAR_GAP")
        sources = set(bars["source"].astype(str))
        if len(sources) != 1 or (timeframe == "M1" and
                                not next(iter(sources)).startswith("IG_LIGHTSTREAMER")):
            return _unverifiable(market, decision_at_utc, timeframe, "SOURCE_AUTHORITY_OR_TRANSITION")
        closes = pd.to_numeric(bars["close"], errors="coerce")
        if closes.isna().any() or (closes <= 0).any():
            return _unverifiable(market, decision_at_utc, timeframe, "CLOSE_INVALID")
        ret = closes.pct_change().dropna()
        values[f"{timeframe.lower()}_return_window"] = float(closes.iloc[-1] / closes.iloc[0] - 1)
        values[f"{timeframe.lower()}_volatility"] = float(ret.std(ddof=0))
        if timeframe == "M1":
            if not {"bid_close", "ask_close"}.issubset(bars.columns):
                return _unverifiable(market, decision_at_utc, timeframe, "M1_BID_ASK_MISSING")
            bid, ask = bars.iloc[-1][["bid_close", "ask_close"]]
            if pd.isna(bid) or pd.isna(ask) or float(bid) <= 0 or float(ask) <= float(bid):
                return _unverifiable(market, decision_at_utc, timeframe, "M1_SPREAD_INVALID")
            values["m1_spread_bps"] = float((ask - bid) / ((ask + bid) / 2) * 10000)
        cutoffs[timeframe] = (bars.index[-1] + pd.Timedelta(minutes, unit="min")).isoformat()
        source_identity[timeframe] = next(iter(sources))
    payload = {"market": market, "feature_version": version,
               "decision_at_utc": decision_at_utc.isoformat(),
               "feature_cutoffs_utc": cutoffs, "source_identity": source_identity,
               "features": values}
    digest = sha256(json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode()).hexdigest()
    return {**payload, "status": "COMPLETE", "snapshot_sha256": digest}


def _unverifiable(market: str, decision: datetime, timeframe: str,
                  reason: str) -> dict[str, object]:
    return {"market": market, "decision_at_utc": decision.isoformat(),
            "feature_version": FEATURE_VERSION, "status": "UNVERIFIABLE",
            "timeframe": timeframe, "reason": reason, "features": None}
