"""Prospective evidence for the sole M1-derived live M15 lineage."""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json

import pandas as pd


SOURCE = "IG_LIGHTSTREAMER_M1_AGG_M15_V1"
VERSION = "PROSPECTIVE_M15_CONTINUITY_V1"


def assess_window(frame: pd.DataFrame, *, market: str,
                  minimum_candles: int = 15) -> dict[str, object]:
    if minimum_candles < 15 or frame.index.tz is None or not frame.index.is_unique:
        raise ValueError("Prospective M15 window must be unique UTC and at least 15 candles")
    required = {"candle_id", "source", "completed", "quality_status", "is_regular_session",
                "close_time_utc", "ingested_at_utc", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return _failed(market, "FRAME_SCHEMA_INVALID", len(frame))
    rows = frame.sort_index()
    rows = rows.loc[(rows["completed"].fillna(False).astype(bool)) &
                    (rows["quality_status"] == "PASS") &
                    rows["is_regular_session"].fillna(False).astype(bool)]
    if len(rows) < minimum_candles:
        return _failed(market, "INSUFFICIENT_PROSPECTIVE_CANDLES", len(rows))
    if set(rows["source"].astype(str)) != {SOURCE}:
        return _failed(market, "SOURCE_NOT_PROSPECTIVE_AUTHORITY", len(rows))
    if not rows.index.to_series().diff().iloc[1:].eq(pd.Timedelta(15, unit="min")).all():
        return _failed(market, "M15_GAP", len(rows))
    close_at = pd.to_datetime(rows["close_time_utc"], utc=True)
    available = pd.to_datetime(rows["ingested_at_utc"], utc=True)
    if close_at.isna().any() or available.isna().any() or (available < close_at).any():
        return _failed(market, "AVAILABILITY_INVALID", len(rows))
    refs = [{"candle_id": int(row.candle_id), "open_time_utc": at.isoformat(),
             "close_time_utc": pd.Timestamp(row.close_time_utc, tz="UTC").isoformat()
                if pd.Timestamp(row.close_time_utc).tzinfo is None else pd.Timestamp(row.close_time_utc).isoformat(),
             "ingested_at_utc": pd.Timestamp(row.ingested_at_utc, tz="UTC").isoformat()
                if pd.Timestamp(row.ingested_at_utc).tzinfo is None else pd.Timestamp(row.ingested_at_utc).isoformat(),
             "source": str(row.source), "high": float(row.high),
             "low": float(row.low), "close": float(row.close)}
            for at, row in rows.iterrows()]
    payload = {"market": market, "version": VERSION, "source": SOURCE,
               "candle_count": len(rows), "first_open_utc": rows.index[0].isoformat(),
               "last_open_utc": rows.index[-1].isoformat(), "candles": refs}
    return {**payload, "status": "COMPLETE",
            "evidence_sha256": sha256(json.dumps(payload, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()}


def _failed(market: str, reason: str, count: int) -> dict[str, object]:
    return {"market": market, "version": VERSION, "source": SOURCE,
            "status": "ACCUMULATING", "reason": reason, "candle_count": count,
            "evidence_sha256": None}


def summarize_accumulation(frame: pd.DataFrame, *, market: str,
                           target: int = 30) -> dict[str, object]:
    """Count warmed opportunities across separate contiguous session segments."""
    if frame.empty:
        return {**_failed(market, "NO_DEPLOYED_SOURCE_ROWS", 0),
                "contiguous_segments": [], "warmed_opportunities": 0,
                "minimum_opportunities_target": target, "target_reached": False}
    required = {"candle_id", "source", "completed", "quality_status", "is_regular_session",
                "close_time_utc", "ingested_at_utc", "high", "low", "close"}
    if frame.index.tz is None or not frame.index.is_unique or not required.issubset(frame.columns):
        return {**_failed(market, "FRAME_SCHEMA_INVALID", len(frame)),
                "contiguous_segments": [], "warmed_opportunities": 0,
                "minimum_opportunities_target": target, "target_reached": False}
    rows = frame.sort_index()
    valid = rows.loc[(rows["source"].astype(str) == SOURCE) &
        rows["completed"].fillna(False).astype(bool) & (rows["quality_status"] == "PASS") &
        rows["is_regular_session"].fillna(False).astype(bool)].copy()
    close_at = pd.to_datetime(valid["close_time_utc"], utc=True)
    available = pd.to_datetime(valid["ingested_at_utc"], utc=True)
    valid = valid.loc[close_at.notna() & available.notna() & (available >= close_at)]
    segments = []
    if not valid.empty:
        group = valid.index.to_series().diff().ne(pd.Timedelta(15, unit="min")).cumsum()
        for _, segment in valid.groupby(group):
            segments.append({"first_open_utc": segment.index[0].isoformat(),
                "last_open_utc": segment.index[-1].isoformat(), "candle_count": len(segment),
                "warmed_opportunities": max(0, len(segment) - 14)})
    warmed = sum(item["warmed_opportunities"] for item in segments)
    payload = {"market": market, "version": VERSION, "source": SOURCE,
        "candle_count": len(valid), "contiguous_segments": segments,
        "warmed_opportunities": warmed, "minimum_opportunities_target": target,
        "target_reached": warmed >= target}
    return {**payload, "status": "TARGET_REACHED" if warmed >= target else "ACCUMULATING",
        "reason": None if warmed >= target else "MINIMUM_NOT_REACHED",
        "evidence_sha256": sha256(json.dumps(payload, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()}
