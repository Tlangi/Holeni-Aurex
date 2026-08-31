from datetime import datetime, time, timezone

from app.market_calendar import operational_session_state


def test_recovery_session_gate_defers_weekend_and_reopen_grace() -> None:
    weekend = operational_session_state(
        datetime(2026, 8, 30, 10, tzinfo=timezone.utc), calendar_code="FX_24X5",
        market_timezone="UTC", session_open=None, session_close=None,
    )
    grace = operational_session_state(
        datetime(2026, 8, 30, 21, 10, tzinfo=timezone.utc), calendar_code="FX_24X5",
        market_timezone="UTC", session_open=None, session_close=None,
    )
    assert not weekend.should_receive_data
    assert not grace.should_receive_data
