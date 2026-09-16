from datetime import datetime, timezone

import pandas as pd

from app.prediction_path_inventory import RecordedDecision, assess_recorded_path


NOW = datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc)


def _recorded(decision="BUY"):
    return RecordedDecision("decision-1", "EURUSD",
        datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 15, 11, 45, tzinfo=timezone.utc),
        "M15", "old-rejected-model", decision, False)


def _frame():
    index = pd.date_range("2026-09-15T12:00:00Z", periods=60, freq="min")
    return pd.DataFrame({"source": ["IG_LIGHTSTREAMER"] * 60,
        "completed": [True] * 60, "quality_status": ["PASS"] * 60,
        "bid_open": [1.1] * 60, "bid_high": [1.1004] * 60,
        "bid_low": [1.0998] * 60, "bid_close": [1.1002] * 60,
        "ask_open": [1.1002] * 60, "ask_high": [1.1006] * 60,
        "ask_low": [1.1] * 60, "ask_close": [1.1004] * 60}, index=index)


def _assess(recorded, frame, **kw):
    return assess_recorded_path(recorded, frame, regular_session=lambda _: True,
                                now_utc=NOW, **kw)


def test_complete_path_includes_rejected_recorded_decision_without_label_authority():
    result = _assess(_recorded(), _frame())
    assert result["status"] == "COMPLETE_IG_M1_PATH"
    assert result["complete_m1_minutes"] == 60
    assert result["recorded_executable"] is False
    assert result["label_authority"] == "NONE_COVERAGE_ONLY"
    assert len(result["source_ig_m1_path_sha256"]) == 64
    assert _assess(_recorded("HOLD"), _frame())["status"] == "COMPLETE_IG_M1_PATH"


def test_broker_quote_revision_changes_frozen_path_hash():
    original = _assess(_recorded(), _frame())
    revised = _frame()
    revised.loc[revised.index[5], "bid_high"] = 1.1005
    assert _assess(_recorded(), revised)["source_ig_m1_path_sha256"] != \
        original["source_ig_m1_path_sha256"]


def test_missing_minute_and_nonbroker_row_never_become_complete():
    frame = _frame().drop(_frame().index[7])
    result = _assess(_recorded(), frame)
    assert result["reason"] == "IG_M1_MISSING"
    assert result["complete_m1_minutes"] == 7
    frame = _frame()
    frame.loc[frame.index[4], "source"] = "DUKASCOPY_REPAIR"
    assert _assess(_recorded(), frame)["reason"] == "IG_M1_INVALID_OR_NONBROKER"


def test_duplicate_broker_timestamp_is_not_canonicalized_away():
    result = _assess(_recorded(), _frame(),
                     duplicate_timestamps={pd.Timestamp("2026-09-15T12:05:00Z")})
    assert result["reason"] == "DUPLICATE_IG_M1_TIMESTAMP"


def test_session_boundary_and_incomplete_horizon_are_unverifiable():
    result = assess_recorded_path(_recorded(), _frame(),
        regular_session=lambda at: at.minute < 30, now_utc=NOW)
    assert result["reason"] == "SESSION_BOUNDARY_IN_PATH"
    result = assess_recorded_path(_recorded(), _frame(),
        regular_session=lambda _: True,
        now_utc=datetime(2026, 9, 15, 12, 15, tzinfo=timezone.utc))
    assert result["reason"] == "HORIZON_NOT_YET_COMPLETE"


def test_between_minute_decision_requires_next_m1_open():
    recorded = RecordedDecision("decision-2", "EURUSD",
        datetime(2026, 9, 15, 12, 0, 30, tzinfo=timezone.utc),
        None, None, None, "HOLD", False)
    result = _assess(recorded, _frame(), horizon_minutes=59)
    assert result["eligible_entry_at_utc"].startswith("2026-09-15T12:01")
    assert result["status"] == "COMPLETE_IG_M1_PATH"
