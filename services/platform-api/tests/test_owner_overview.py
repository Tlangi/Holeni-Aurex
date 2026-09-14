from datetime import datetime, timedelta, timezone

from app.owner_overview import market_summary_row, summarize_owner_readiness


def test_market_summary_requires_current_ig_quote_and_never_infers_eligibility():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    row = {"symbol": "GBPUSD", "display_name": "GBP/USD", "demo_trading_enabled": True,
           "open_time_utc": now - timedelta(minutes=5), "bid_close": "1.2500",
           "ask_close": "1.2502", "spread_close": "0.0002",
           "source": "IG_LIGHTSTREAMER_M5", "model_status": "REJECTED"}
    current = market_summary_row(row, now)
    assert current["quote_status"] == "CURRENT_IG"
    assert current["bid"] == "1.2500"
    assert current["trading_eligibility"] == "UNVERIFIED"
    stale = market_summary_row({**row, "open_time_utc": now - timedelta(hours=1)}, now)
    assert stale["quote_status"] == "STALE_OR_UNAVAILABLE"
    assert stale["bid"] is None
    research = market_summary_row({**row, "source": "DUKASCOPY_BID_M5"}, now)
    assert research["quote_status"] == "STALE_OR_UNAVAILABLE"
    future = market_summary_row({**row, "open_time_utc": now + timedelta(minutes=5)}, now)
    assert future["quote_status"] == "STALE_OR_UNAVAILABLE"
    assert future["bid"] is None


def test_owner_readiness_separates_operational_health_from_model_and_demo_auto():
    summary = summarize_owner_readiness(
        {"status": "HEALTHY", "open_alert_count": 0}, {"mode": "SHADOW"},
        {"status": "NOT_READY"}, {"unresolved": 0}, 1,
    )
    assert summary["overall_health"] == "HEALTHY"
    assert summary["trading_mode"] == "SHADOW"
    assert summary["shadow_status"] == "MODE_SELECTED_NOT_ATTESTED"
    assert summary["demo_auto_status"] == "NOT_READY"
    assert summary["human_approved_demo_status"] == "NOT_ATTESTED_BY_THIS_PAYLOAD"
    assert summary["live_status"] == "DISABLED"
    assert {item["code"] for item in summary["blocking_reasons"]} >= {"PENDING_APPROVAL", "SHADOW_ONLY"}
    attention = summarize_owner_readiness(
        {"status": "HEALTHY", "open_alert_count": 0}, {"mode": "PAUSED"},
        {"status": "NOT_READY"}, {"unresolved": 1}, 0,
    )
    assert attention["overall_health"] == "ACTION_REQUIRED"
