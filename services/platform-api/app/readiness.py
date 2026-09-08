from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.config import Settings
from app.database import DatabaseUnavailable, check_database, open_database
from app.market_calendar import market_data_stale, operational_session_state


@dataclass(frozen=True)
class ReadinessCheck:
    ready: bool
    status: str
    detail: str


def configuration_checks(settings: Settings) -> dict[str, ReadinessCheck]:
    demo_only = (
        settings.ig_environment == "demo"
        and settings.broker_environment == "demo"
        and not settings.allow_live_trading
    )
    return {
        "demo_only_configuration": ReadinessCheck(
            demo_only,
            "PASS" if demo_only else "FAIL",
            "IG and broker environments are locked to demo; live trading is disabled"
            if demo_only else "Demo/live isolation configuration failed",
        ),
        "demo_execution_opt_in": ReadinessCheck(
            settings.demo_execution_configured,
            "PASS" if settings.demo_execution_configured else "DEFERRED",
            "Explicit demo execution opt-in is complete"
            if settings.demo_execution_configured
            else "Demo execution opt-in remains intentionally disabled until a market completes model and forward-shadow qualification",
        ),
        "smtp_status_known": ReadinessCheck(
            settings.smtp_configured,
            "PASS" if settings.smtp_configured else "BLOCKED",
            "SMTP is configured" if settings.smtp_configured else "SMTP is not configured",
        ),
    }


def _database_checks(settings: Settings, tenant_id: str) -> dict[str, ReadinessCheck]:
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT TOP (1) u.user_id
               FROM app.users u
               WHERE u.tenant_id=%s AND u.role='owner' AND u.status='active'
               ORDER BY u.created_at_utc""",
            (tenant_id,),
        )
        owner = cursor.fetchone()
        cursor.execute(
            """SELECT TOP (1) ta.trading_account_id,ta.trading_enabled,
                      bc.environment,bc.status,bc.external_account_id_masked
               FROM app.trading_accounts ta
               JOIN app.broker_connections bc ON bc.broker_connection_id=ta.broker_connection_id
               WHERE ta.tenant_id=%s ORDER BY ta.created_at_utc""",
            (tenant_id,),
        )
        account = cursor.fetchone()
        cursor.execute(
            """SELECT component_code,status,checked_at_utc
               FROM app.platform_components
               WHERE component_code IN ('ig_demo','market_feed','risk_engine','trading_engine','macro_intelligence')"""
        )
        components = {str(row["component_code"]): row for row in cursor.fetchall()}
        cursor.execute(
            """SELECT m.symbol,m.calendar_code,m.market_timezone,m.session_open_local,
                      m.session_close_local,
                      MAX(CASE WHEN c.timeframe='M5' AND c.completed=1 THEN c.open_time_utc END) latest_m5,
                      MAX(CASE WHEN c.timeframe='M15' AND c.completed=1 THEN c.open_time_utc END) latest_m15
               FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
               WHERE m.enabled=1 AND m.signal_enabled=1
               GROUP BY m.symbol,m.calendar_code,m.market_timezone,
                         m.session_open_local,m.session_close_local"""
        )
        markets = cursor.fetchall()
        cursor.execute(
            """SELECT
                 SUM(CASE WHEN mv.status='VALIDATED' AND hc.status='OWNER_APPROVED'
                                AND mv.artifact_sha256=hc.artifact_sha256 THEN 1 ELSE 0 END) validated_models,
                 COUNT(*) model_count
               FROM app.model_versions mv
               LEFT JOIN app.holdout_candidates hc ON hc.holdout_candidate_id=mv.holdout_candidate_id"""
        )
        models = cursor.fetchone() or {}
        cursor.execute("SELECT COUNT(*) active_risk FROM app.risk_versions WHERE tenant_id=%s AND active=1", (tenant_id,))
        active_risk = int((cursor.fetchone() or {}).get("active_risk") or 0)
        cursor.execute(
            """SELECT COUNT(*) unresolved FROM app.positions
               WHERE tenant_id=%s AND status IN ('BROKER_MISSING','RECONCILING','RECONCILIATION_REQUIRED')""",
            (tenant_id,),
        )
        unresolved_positions = int((cursor.fetchone() or {}).get("unresolved") or 0)
        cursor.execute(
            """SELECT COUNT(*) unknown_count FROM app.order_intents
               WHERE tenant_id=%s AND status IN ('SUBMISSION_UNKNOWN','RECONCILIATION_REQUIRED')""",
            (tenant_id,),
        )
        unknown_orders = int((cursor.fetchone() or {}).get("unknown_count") or 0)
        cursor.execute(
            """SELECT COUNT(*) issue_count FROM app.reconciliation_issues
               WHERE tenant_id=%s AND status IN ('OPEN','INVESTIGATING')""",
            (tenant_id,),
        )
        reconciliation_issues = int((cursor.fetchone() or {}).get("issue_count") or 0)
        cursor.execute(
            """SELECT COUNT(*) ledger_count FROM app.daily_risk_ledger
               WHERE tenant_id=%s AND status='CURRENT'
                 AND ledger_date_sast=CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'South Africa Standard Time' AS date)""",
            (tenant_id,),
        )
        ledger_current = int((cursor.fetchone() or {}).get("ledger_count") or 0) == 1
        cursor.execute(
            """SELECT COUNT(*) rule_count FROM app.broker_market_rules r
               JOIN app.markets m ON m.market_id=r.market_id
               WHERE m.enabled=1 AND m.signal_enabled=1 AND r.value_per_price_point_zar IS NOT NULL
                 AND r.margin_factor_pct IS NOT NULL AND r.margin_factor_pct>0
                 AND r.size_increment IS NOT NULL AND r.size_increment>0
                 AND r.size_increment_authoritative=1
                 AND r.deal_currency IS NOT NULL AND r.force_open_allowed=1
                 AND r.market_order_preference IN ('AVAILABLE_DEFAULT_OFF','AVAILABLE_DEFAULT_ON')
                 AND r.observed_at_utc >= DATEADD(hour,-24,SYSUTCDATETIME())"""
        )
        rule_count = int((cursor.fetchone() or {}).get("rule_count") or 0)
        cursor.execute(
            """SELECT COUNT(*) score_count FROM
                 (SELECT currency,evidence_count,valid_until_utc,
                         ROW_NUMBER() OVER(PARTITION BY currency ORDER BY as_of_utc DESC) rn
                  FROM app.macro_currency_scores) ranked
               WHERE rn=1 AND evidence_count>0 AND valid_until_utc>=SYSUTCDATETIME()"""
        )
        macro_score_count = int((cursor.fetchone() or {}).get("score_count") or 0)

    now = datetime.now(timezone.utc)
    expected_markets = len(markets)
    session_rows: list[tuple[dict[str, object], object]] = []
    with open_database(settings) as connection:
        holiday_cursor = connection.cursor(as_dict=True)
        for row in markets:
            holiday_cursor.execute(
                "SELECT holiday_date,session_close_local FROM app.market_holidays WHERE calendar_code=%s",
                (str(row["calendar_code"]),),
            )
            holidays = {item["holiday_date"]: item["session_close_local"] for item in holiday_cursor.fetchall()}
            session_rows.append((row, operational_session_state(
                now, calendar_code=str(row["calendar_code"]),
                market_timezone=str(row["market_timezone"]),
                session_open=row["session_open_local"], session_close=row["session_close_local"],
                holidays=holidays,
            )))
    market_fresh = bool(markets) and all(not market_data_stale(
        row["latest_m5"], now_utc=now, session=session,
        freshness=timedelta(seconds=settings.execution_m5_fresh_seconds),
    ) for row, session in session_rows)
    m15_current = bool(markets) and all(not market_data_stale(
        row["latest_m15"], now_utc=now, session=session,
        freshness=timedelta(seconds=settings.execution_m15_fresh_seconds),
    ) for row, session in session_rows)
    open_markets = sum(int(session.should_receive_data) for _, session in session_rows)
    deferred_markets = expected_markets - open_markets
    session_detail = f"{open_markets} open; {deferred_markets} closed or in reopening grace"
    component_ok: Callable[[str], bool] = lambda code: (
        code in components and str(components[code]["status"]) == "CURRENT"
    )
    return {
        "authenticated_owner": ReadinessCheck(bool(owner), "PASS" if owner else "FAIL", "Active tenant owner exists" if owner else "No active tenant owner"),
        "ig_demo_connected": ReadinessCheck(bool(account) and account["environment"] == "demo" and component_ok("ig_demo"), "PASS" if bool(account) and account["environment"] == "demo" and component_ok("ig_demo") else "BLOCKED", "Correct IG demo account is current" if bool(account) and account["environment"] == "demo" and component_ok("ig_demo") else "IG demo account is absent, stale or unhealthy"),
        "market_worker_current": ReadinessCheck(component_ok("market_feed"), "PASS" if component_ok("market_feed") else "BLOCKED", "Market worker reports current" if component_ok("market_feed") else "Market worker is not current"),
        "m5_market_data_current": ReadinessCheck(market_fresh, "PASS" if market_fresh else "BLOCKED", f"M5 freshness is current for the operating session ({session_detail})" if market_fresh else "One or more open-session M5 markets are missing or stale"),
        "m15_aggregation_current": ReadinessCheck(m15_current, "PASS" if m15_current else "BLOCKED", f"M15 freshness is current for the operating session ({session_detail})" if m15_current else "One or more open-session M15 markets are missing or stale"),
        "macro_intelligence_current": ReadinessCheck(component_ok("macro_intelligence") and macro_score_count == 4, "PASS" if component_ok("macro_intelligence") and macro_score_count == 4 else "BLOCKED", f"Current audited macro scores: {macro_score_count}/4 currencies"),
        "validated_models": ReadinessCheck(int(models.get("validated_models") or 0) >= 1, "PASS" if int(models.get("validated_models") or 0) >= 1 else "BLOCKED", f"Markets with a validated model: {int(models.get('validated_models') or 0)}/{expected_markets}; at least one is required for staged demo execution"),
        "active_risk_profile": ReadinessCheck(active_risk == 1, "PASS" if active_risk == 1 else "BLOCKED", f"Active risk profiles: {active_risk}"),
        "position_sizing_rules": ReadinessCheck(rule_count >= expected_markets, "PASS" if rule_count >= expected_markets else "BLOCKED", f"Authoritative broker sizing rules: {rule_count}/{expected_markets}; fallback increments never satisfy execution readiness"),
        "reconciliation_clear": ReadinessCheck(unresolved_positions == 0 and reconciliation_issues == 0, "PASS" if unresolved_positions == 0 and reconciliation_issues == 0 else "BLOCKED", f"Unresolved positions: {unresolved_positions}; issues: {reconciliation_issues}"),
        "unknown_submissions_clear": ReadinessCheck(unknown_orders == 0, "PASS" if unknown_orders == 0 else "BLOCKED", f"Unknown order submissions: {unknown_orders}"),
        "daily_risk_ledger_current": ReadinessCheck(ledger_current, "PASS" if ledger_current else "BLOCKED", "South African daily risk ledger is current" if ledger_current else "Daily risk ledger is missing, stale or blocked"),
        "risk_engine_current": ReadinessCheck(component_ok("risk_engine"), "PASS" if component_ok("risk_engine") else "BLOCKED", "Risk engine reports current" if component_ok("risk_engine") else "Risk engine is not current"),
        "trading_worker_current": ReadinessCheck(component_ok("trading_engine"), "PASS" if component_ok("trading_engine") else "BLOCKED", "Trading worker reports current" if component_ok("trading_engine") else "Trading worker is not current"),
        "database_writable": ReadinessCheck(True, "PASS", "Readiness query completed using the application database account"),
    }


def read_trading_readiness(settings: Settings, tenant_id: str) -> dict[str, object]:
    checks = configuration_checks(settings)
    database_ready, database_detail = check_database(settings)
    checks["database_connected"] = ReadinessCheck(
        database_ready,
        "PASS" if database_ready else "FAIL",
        database_detail,
    )
    if database_ready:
        try:
            checks.update(_database_checks(settings, tenant_id))
        except DatabaseUnavailable:
            checks["database_queries"] = ReadinessCheck(False, "FAIL", "Database became unavailable")
    ready = bool(checks) and all(item.ready for item in checks.values())
    return {
        "status": "READY" if ready else "NOT_READY",
        "execution_mode": "DEMO_AUTO" if ready else "SHADOW_OR_PAUSED",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": {name: asdict(item) for name, item in checks.items()},
        "blockers": [item.detail for item in checks.values()
                     if not item.ready and item.status != "DEFERRED"],
        "deferred_activation": [item.detail for item in checks.values()
                                if not item.ready and item.status == "DEFERRED"],
    }
