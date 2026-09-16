"""Point-in-time ATR evidence for preregistered execution distances."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
import math

import pandas as pd


ATR_VERSION = "M15_ATR14_SMA_POINT_IN_TIME_V1"


def atr14_snapshot(decision_at_utc: datetime, frame: pd.DataFrame, *,
                   market: str) -> dict[str, object]:
    if (not market or decision_at_utc.tzinfo is None or
            decision_at_utc.utcoffset() != timedelta(0)):
        raise ValueError("Market and UTC decision required")
    required = {"high", "low", "close", "completed", "source"}
    if frame.index.tz is None or not frame.index.is_unique or not required.issubset(frame.columns):
        return _failed(market, decision_at_utc, "FRAME_SCHEMA_INVALID")
    ordered = frame.sort_index()
    eligible = ordered.loc[ordered.index + pd.Timedelta(15, unit="min") <= pd.Timestamp(decision_at_utc)]
    eligible = eligible.loc[eligible["completed"].fillna(False).astype(bool)]
    bars = eligible.tail(15)
    if len(bars) != 15:
        return _failed(market, decision_at_utc, "INSUFFICIENT_COMPLETED_BARS")
    if not bars.index.to_series().diff().iloc[1:].eq(pd.Timedelta(15, unit="min")).all():
        return _failed(market, decision_at_utc, "TRAILING_BAR_GAP")
    availability_columns = [name for name in ("ingested_at_utc", "created_at_utc") if name in bars]
    if not availability_columns:
        return _failed(market, decision_at_utc, "AVAILABILITY_TIMESTAMP_MISSING")
    availability = pd.to_datetime(bars[availability_columns[0]], utc=True)
    if len(availability_columns) > 1:
        availability = availability.fillna(pd.to_datetime(bars[availability_columns[1]], utc=True))
    if availability.isna().any() or (availability > pd.Timestamp(decision_at_utc)).any():
        return _failed(market, decision_at_utc, "NOT_AVAILABLE_AT_DECISION")
    sources = set(bars["source"].astype(str))
    if len(sources) != 1:
        return _failed(market, decision_at_utc, "SOURCE_TRANSITION")
    numeric = bars[["high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric <= 0).any().any():
        return _failed(market, decision_at_utc, "OHLC_INVALID")
    if (numeric["high"] < numeric[["low", "close"]].max(axis=1)).any() or \
            (numeric["low"] > numeric[["high", "close"]].min(axis=1)).any():
        return _failed(market, decision_at_utc, "OHLC_INVALID")
    previous = numeric["close"].shift(1)
    true_range = pd.concat((numeric["high"] - numeric["low"],
                            (numeric["high"] - previous).abs(),
                            (numeric["low"] - previous).abs()), axis=1).max(axis=1).iloc[1:]
    atr = float(true_range.mean())
    if not math.isfinite(atr) or atr <= 0:
        return _failed(market, decision_at_utc, "ATR_INVALID")
    refs = [{"open_time_utc": at.isoformat(), "candle_id": int(row.candle_id)
             if "candle_id" in row and pd.notna(row.candle_id) else None,
             "source": str(row.source), "high": float(row.high), "low": float(row.low),
             "close": float(row.close)} for at, row in bars.iterrows()]
    payload = {"market": market, "decision_at_utc": decision_at_utc.isoformat(),
               "atr_version": ATR_VERSION, "atr": atr,
               "source": next(iter(sources)), "bars": refs}
    return {**payload, "status": "COMPLETE",
            "snapshot_sha256": sha256(json.dumps(payload, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()}


def _failed(market: str, decision: datetime, reason: str) -> dict[str, object]:
    return {"market": market, "decision_at_utc": decision.isoformat(),
            "atr_version": ATR_VERSION, "status": "UNVERIFIABLE",
            "reason": reason, "atr": None}
