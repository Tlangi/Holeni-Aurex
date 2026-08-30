from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.execution_simulator import resolve_candle_exit, spread_cost, transaction_cost_evidence
from app.market_calendar import is_regular_session, market_data_stale, operational_session_state


def test_germany_regular_session_uses_berlin_dst() -> None:
    assert is_regular_session(
        datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
    )
    assert not is_regular_session(
        datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
    )


def test_fx_weekend_is_not_model_evidence() -> None:
    assert not is_regular_session(
        datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC",
        session_open=None, session_close=None,
    )


def test_fx_friday_close_is_not_reported_as_missing_market_data() -> None:
    assert is_regular_session(
        datetime(2026, 8, 21, 20, 45, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )
    assert not is_regular_session(
        datetime(2026, 8, 21, 21, 0, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )


def test_fx_weekend_is_closed_and_sunday_reopen_has_grace() -> None:
    closed = operational_session_state(
        datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )
    grace = operational_session_state(
        datetime(2026, 8, 30, 21, 10, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )
    opened = operational_session_state(
        datetime(2026, 8, 30, 21, 25, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )
    assert (closed.status, closed.should_receive_data) == ("CLOSED", False)
    assert (grace.status, grace.should_receive_data) == ("OPEN_GRACE", False)
    assert (opened.status, opened.should_receive_data) == ("OPEN", True)


def test_xetra_monitoring_uses_local_session_holidays_and_reopen_grace() -> None:
    before = operational_session_state(
        datetime(2026, 8, 31, 6, 30, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
    )
    grace = operational_session_state(
        datetime(2026, 8, 31, 7, 10, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
    )
    opened = operational_session_state(
        datetime(2026, 8, 31, 7, 25, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
    )
    holiday = operational_session_state(
        datetime(2026, 12, 25, 10, 0, tzinfo=timezone.utc),
        calendar_code="XETRA_REGULAR", market_timezone="Europe/Berlin",
        session_open=time(9), session_close=time(17, 30),
        holidays={date(2026, 12, 25): None},
    )
    assert before.reason == "BEFORE_REGULAR_SESSION"
    assert grace.status == "OPEN_GRACE"
    assert opened.should_receive_data
    assert holiday.reason == "MARKET_HOLIDAY"


def test_stale_data_only_warns_when_session_should_be_producing() -> None:
    now = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)
    latest = datetime(2026, 8, 28, 20, 55, tzinfo=timezone.utc)
    closed = operational_session_state(
        datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc),
        calendar_code="FX_24X5", market_timezone="UTC", session_open=None, session_close=None,
    )
    opened = operational_session_state(
        now, calendar_code="FX_24X5", market_timezone="UTC",
        session_open=None, session_close=None,
    )
    assert not market_data_stale(
        latest, now_utc=now, session=closed, freshness=timedelta(minutes=15),
    )
    assert market_data_stale(
        latest, now_utc=now, session=opened, freshness=timedelta(minutes=15),
    )


def test_gap_through_stop_uses_worse_open_and_time_exit_is_deterministic() -> None:
    gap = resolve_candle_exit(
        "BUY", stop=Decimal("99"), target=Decimal("103"), opened=Decimal("98"),
        high=Decimal("100"), low=Decimal("97"), close=Decimal("99"),
        holding_candles=1, max_holding_candles=32,
    )
    assert gap.reason == "STOP_GAP" and gap.price == Decimal("98")
    timed = resolve_candle_exit(
        "SELL", stop=Decimal("103"), target=Decimal("97"), opened=Decimal("100"),
        high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"),
        holding_candles=32, max_holding_candles=32,
    )
    assert timed.reason == "MAX_HOLDING_TIME"


def test_observed_spread_cost_uses_broker_sides() -> None:
    assert spread_cost(
        bid=Decimal("100"), ask=Decimal("101"), size=Decimal("0.5"),
        value_per_price_point_zar=Decimal("20"),
    ) == Decimal("10.0")


def test_observed_spread_is_not_charged_twice_with_executable_fills() -> None:
    cost = transaction_cost_evidence(
        midpoint=Decimal("100"), bid=Decimal("99"), ask=Decimal("101"), size=Decimal("2"),
        value_per_price_point_zar=Decimal("5"), fallback_round_trip_cost_bps=Decimal("3"),
    )
    assert cost.spread_cost_zar == Decimal("20")
    assert cost.explicit_cost_zar == 0
    assert cost.spread_cost_in_price is True


def test_midpoint_only_replay_charges_fallback_cost() -> None:
    cost = transaction_cost_evidence(
        midpoint=Decimal("100"), bid=None, ask=None, size=Decimal("2"),
        value_per_price_point_zar=Decimal("5"), fallback_round_trip_cost_bps=Decimal("3"),
    )
    assert cost.explicit_cost_zar == Decimal("0.3")
    assert cost.spread_cost_in_price is False
