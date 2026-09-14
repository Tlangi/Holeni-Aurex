"""Read-only owner summaries. IG remains the sole execution-price authority."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.config import Settings
from app.database import open_database
from app.operations_status import read_operational_assurance
from app.readiness import read_trading_readiness
from app.trading_operations import read_reconciliation_status
from app.trading_status import read_trading_status


def market_summary_row(row: dict[str, object], now: datetime) -> dict[str, object]:
    observed = row.get("open_time_utc")
    observed_utc = observed.replace(tzinfo=timezone.utc) if isinstance(observed, datetime) and observed.tzinfo is None else observed
    age_seconds = int((now - observed_utc).total_seconds()) if isinstance(observed_utc, datetime) else None
    bid, ask = row.get("bid_close"), row.get("ask_close")
    executable_quote = (
        observed_utc is not None and age_seconds is not None and 0 <= age_seconds <= 15 * 60
        and str(row.get("source") or "").startswith("IG_LIGHTSTREAMER")
        and bid is not None and ask is not None and Decimal(str(bid)) > 0
        and Decimal(str(ask)) >= Decimal(str(bid))
    )
    return {
        "symbol": str(row["symbol"]), "display_name": str(row["display_name"]),
        "bid": str(bid) if executable_quote else None,
        "ask": str(ask) if executable_quote else None,
        "spread": str(row["spread_close"]) if executable_quote and row.get("spread_close") is not None else None,
        "quote_observed_at_utc": observed_utc.isoformat() if isinstance(observed_utc, datetime) else None,
        "quote_age_seconds": age_seconds,
        "quote_status": "CURRENT_IG" if executable_quote else "STALE_OR_UNAVAILABLE",
        "quote_source": str(row["source"]) if observed is not None else None,
        "model_status": str(row["model_status"] or "NONE"),
        "demo_configured": bool(row["demo_trading_enabled"]),
        "trading_eligibility": "UNVERIFIED",  # Never infer risk/broker authority from candles.
    }


def read_market_summary(settings: Settings, tenant_id: str) -> dict[str, object]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT 1 AS has_account FROM app.trading_accounts WHERE tenant_id=%s", (tenant_id,))
        if not cursor.fetchone():
            raise PermissionError("Tenant has no trading account")
        cursor.execute(
            """SELECT m.symbol,m.display_name,m.demo_trading_enabled,
                     quote.open_time_utc,quote.bid_close,quote.ask_close,quote.spread_close,quote.source,
                     model.status AS model_status
               FROM app.markets m
               OUTER APPLY (SELECT TOP(1) c.open_time_utc,c.bid_close,c.ask_close,c.spread_close,c.source
                 FROM app.candles c WHERE c.market_id=m.market_id AND c.timeframe='M5'
                   AND c.completed=1 AND c.quality_status='PASS' AND c.is_regular_session=1
                   AND c.source LIKE 'IG_LIGHTSTREAMER%%'
                   AND c.bid_close IS NOT NULL AND c.ask_close IS NOT NULL
                 ORDER BY c.open_time_utc DESC,c.candle_id DESC) quote
               OUTER APPLY (SELECT TOP(1) mv.status FROM app.model_versions mv
                 WHERE mv.market_id=m.market_id ORDER BY mv.registered_at_utc DESC) model
               WHERE m.enabled=1 ORDER BY m.market_tier,m.symbol""")
        rows = cursor.fetchall()
    now = datetime.now(timezone.utc)
    return {"generated_at_utc": now.isoformat(), "environment": "IG_DEMO",
            "markets": [market_summary_row(row, now) for row in rows]}


def summarize_owner_readiness(operations: dict[str, object], trading: dict[str, object],
                              demo_auto: dict[str, object], reconciliation: dict[str, object],
                              pending_approvals: int) -> dict[str, object]:
    mode = str(trading.get("mode") or "UNKNOWN").upper()
    owner_mode = "SHADOW" if mode == "SHADOW" else "DISABLED" if mode in {"PAUSED", "READ_ONLY"} else mode
    unresolved = int(reconciliation.get("unresolved") or 0)
    alert_count = int(operations.get("open_alert_count") or 0)
    service_status = str(operations.get("status") or "UNAVAILABLE").upper()
    health = ("ACTION_REQUIRED" if unresolved else "DEGRADED" if alert_count or service_status != "HEALTHY"
              else "HEALTHY")
    reasons: list[dict[str, str]] = []
    if unresolved:
        reasons.append({"code": "RECONCILIATION", "message": "Broker reconciliation needs attention.", "action": "View System reconciliation"})
    if pending_approvals:
        reasons.append({"code": "PENDING_APPROVAL", "message": f"{pending_approvals} proposal(s) await owner review.", "action": "Review Trading approvals"})
    if owner_mode == "SHADOW":
        reasons.append({"code": "SHADOW_ONLY", "message": "Shadow mode is selected. Forward model activity is not attested by this summary; no IG order is sent.", "action": "View Trading activity"})
    elif owner_mode == "DISABLED":
        reasons.append({"code": "TRADING_DISABLED", "message": "Trading evaluation is paused or read-only.", "action": "View Trading controls"})
    if demo_auto.get("status") != "READY":
        reasons.append({"code": "DEMO_AUTO_NOT_READY", "message": "Automated Demo execution has not passed its safety gates.", "action": "View System readiness"})
    return {
        "overall_health": health, "trading_mode": owner_mode,
        "broker_environment": "IG_DEMO", "live_status": "DISABLED",
        "data_status": "SEE_MARKET_SUMMARY", "model_status": "SEE_MARKET_SUMMARY",
        "shadow_status": "MODE_SELECTED_NOT_ATTESTED" if owner_mode == "SHADOW" else "NOT_RUNNING",
        "broker_status": "NOT_ATTESTED_BY_THIS_PAYLOAD", "risk_status": "NOT_ATTESTED_BY_THIS_PAYLOAD",
        "demo_auto_status": str(demo_auto.get("status") or "NOT_READY"),
        "human_approved_demo_status": "NOT_ATTESTED_BY_THIS_PAYLOAD",
        "pending_approvals": pending_approvals, "reconciliation_unresolved": unresolved,
        "blocking_reasons": reasons,
    }


def read_owner_readiness(settings: Settings, tenant_id: str) -> dict[str, object]:
    operations = read_operational_assurance(settings, tenant_id, limit=1)
    trading = read_trading_status(settings, tenant_id)
    demo_auto = read_trading_readiness(settings, tenant_id)
    reconciliation = read_reconciliation_status(settings, tenant_id)
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("""SELECT COUNT(*) FROM app.trade_proposals WHERE tenant_id=%s
                          AND status='PENDING_OWNER' AND expires_at_utc>SYSUTCDATETIME()""", (tenant_id,))
        pending = int(cursor.fetchone()[0])
    return {"evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            **summarize_owner_readiness(operations, trading, demo_auto, reconciliation, pending)}
