import pytest
from datetime import datetime

from app.config import Settings
from app.health_monitor import component_attention_message, component_requires_attention, component_stale_after


@pytest.mark.parametrize("code", ["market_feed", "ig_demo"])
def test_stale_current_feed_is_not_an_incident_while_markets_closed(code):
    assert not component_requires_attention(
        "CURRENT", stale=True, code=code,
        sessions_evaluated=True, any_open_session=False,
    )


@pytest.mark.parametrize("code", ["market_feed", "ig_demo"])
def test_stale_current_feed_alerts_while_market_open_or_calendar_unknown(code):
    assert component_requires_attention(
        "CURRENT", stale=True, code=code,
        sessions_evaluated=True, any_open_session=True,
    )
    assert component_requires_attention(
        "CURRENT", stale=True, code=code,
        sessions_evaluated=False, any_open_session=False,
    )


def test_explicit_disconnect_still_alerts_while_closed():
    assert component_requires_attention(
        "DEGRADED", stale=False, code="ig_demo",
        sessions_evaluated=True, any_open_session=False,
    )


def test_risk_engine_heartbeat_never_uses_market_closure_exception():
    assert component_requires_attention(
        "CURRENT", stale=True, code="risk_engine",
        sessions_evaluated=True, any_open_session=False,
    )


def test_stale_current_ig_demo_email_explains_missing_sync_not_healthy_status():
    summary, detail = component_attention_message(
        "ig_demo", "CURRENT", "Authenticated read-only demo connection",
        datetime(2026, 9, 14, 14, 26, 17), stale=True,
    )
    assert summary == "IG Demo account sync has not refreshed"
    assert "14:26:17 UTC" in detail
    assert "Trading readiness is unverified" in detail
    assert "status=CURRENT" not in detail


def test_explicit_ig_disconnect_remains_visible_even_with_fresh_heartbeat():
    summary, detail = component_attention_message(
        "ig_demo", "ERROR", "IG session rejected", None, stale=False,
    )
    assert "requires attention" in summary
    assert "status=ERROR" in detail


def test_macro_heartbeat_uses_schedule_not_broker_account_sync():
    settings = Settings(macro_sync_seconds=900)
    assert component_stale_after("macro_intelligence", settings).total_seconds() == 1800
    assert component_stale_after("ig_demo", settings).total_seconds() == 1200
    summary, detail = component_attention_message(
        "macro_intelligence", "CURRENT", "Official sources current: 12/12",
        datetime(2026, 9, 14, 18, 8, 32), stale=True,
    )
    assert "macro_intelligence" in summary
    assert "18:08:32 UTC / 2026-09-14 20:08:32 SAST" in detail
    assert "Shadow worker" in detail
    assert "account-sync" not in detail
