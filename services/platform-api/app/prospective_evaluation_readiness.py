"""Closed-window time gates for future prospective validation and holdout."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def evaluation_readiness(windows: dict, *, phase: str, now_utc: datetime,
                         validation_report_frozen: bool = False) -> dict:
    if phase not in {"validation", "holdout"} or now_utc.tzinfo is None or now_utc.utcoffset() != timedelta(0):
        raise ValueError("Evaluation phase and aware UTC clock required")
    if windows.get("authority") != "PRE_REGISTERED_CLOSED_FUTURE_EVALUATION_WINDOWS":
        raise ValueError("Unrecognized prospective evaluation windows")
    start_key = f"{phase}_start_utc"
    end_key = f"{phase}_end_exclusive_utc"
    start = datetime.fromisoformat(windows[start_key].replace("Z", "+00:00"))
    end = datetime.fromisoformat(windows[end_key].replace("Z", "+00:00"))
    if end <= start or windows["max_outcome_horizon_minutes"] != 120:
        raise ValueError("Invalid closed evaluation interval or outcome horizon")
    ready_at = end + timedelta(minutes=windows["max_outcome_horizon_minutes"])
    if now_utc < ready_at:
        status, reason = "BLOCKED", "WINDOW_OR_OUTCOME_HORIZON_INCOMPLETE"
    elif phase == "holdout" and not validation_report_frozen:
        status, reason = "BLOCKED", "VALIDATION_REPORT_NOT_FROZEN"
    else:
        status, reason = "READY_FOR_SEPARATE_GOVERNED_FREEZE", None
    return {"phase": phase, "status": status, "reason": reason,
            "window_start_utc": start.isoformat(), "window_end_exclusive_utc": end.isoformat(),
            "earliest_freeze_at_utc": ready_at.isoformat(),
            "validation_or_holdout_accessed": False}
