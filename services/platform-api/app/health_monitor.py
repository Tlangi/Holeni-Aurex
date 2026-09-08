from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests

from app.config import Settings
from app.database import open_database
from app.daily_progress_report import send_due_daily_progress_reports
from app.email_delivery import send_email
from app.market_calendar import market_data_stale, operational_session_state

logger = logging.getLogger("aurex.health_monitor")
SAST = ZoneInfo("Africa/Johannesburg")


def dual_time(value: datetime | None) -> str:
    if value is None:
        return "NONE"
    utc=value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC / {utc.astimezone(SAST).strftime('%Y-%m-%d %H:%M:%S')} SAST"


@dataclass(frozen=True)
class HealthIssue:
    key: str
    severity: str
    summary: str
    detail: str


def _web_health_url(settings: Settings) -> str:
    if settings.app_env.lower() == "production":
        external = next((origin for origin in settings.allowed_origins
                         if origin.lower().startswith("https://")), None)
        if external:
            return f"{external.rstrip('/')}/_health"
    return f"http://{settings.web_host}:{settings.web_port}/_health"


def inspect_health(settings: Settings) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    try:
        response = requests.get(
            f"http://{settings.api_host}:{settings.api_port}/health/ready", timeout=10,
        )
        if response.status_code != 200:
            issues.append(HealthIssue("api.not_ready", "CRITICAL", "Platform API is not ready",
                                      f"Health endpoint returned HTTP {response.status_code}"))
    except requests.RequestException as exc:
        issues.append(HealthIssue("api.unreachable", "CRITICAL", "Platform API is unreachable",
                                  type(exc).__name__))

    try:
        response = requests.get(
            _web_health_url(settings), timeout=10,
        )
        if response.status_code != 200:
            issues.append(HealthIssue("web.not_ready", "WARNING", "Owner web application is not ready",
                                      f"Health endpoint returned HTTP {response.status_code}"))
    except requests.RequestException as exc:
        issues.append(HealthIssue("web.unreachable", "WARNING", "Owner web application is unreachable",
                                  type(exc).__name__))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with open_database(settings) as connection:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(
                """SELECT component_code,status,status_detail,checked_at_utc
                   FROM app.platform_components
                   WHERE component_code IN ('ig_demo','market_feed','risk_engine','trading_engine','macro_intelligence')"""
            )
            for component in cursor.fetchall():
                checked = component["checked_at_utc"]
                stale = checked is None or checked < now - timedelta(minutes=20)
                if str(component["status"]) not in {"CURRENT", "HEALTHY"} or stale:
                    code = str(component["component_code"])
                    issues.append(HealthIssue(
                        f"component.{code}", "CRITICAL" if code in {"market_feed", "risk_engine"} else "WARNING",
                        f"Aurex component requires attention: {code}",
                        f"status={component['status']}; detail={component['status_detail']}; checked={checked}",
                    ))
            cursor.execute(
                """SELECT m.symbol,m.calendar_code,m.market_timezone,m.session_open_local,
                          m.session_close_local,MAX(c.open_time_utc) latest_open,
                          MAX(c.close_time_utc) latest_close,
                          MAX(l.open_time_utc) live_latest,MAX(l.updated_at_utc) live_updated
                   FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
                     AND c.timeframe='M5' AND c.completed=1
                   LEFT JOIN app.live_candle_snapshots l ON l.market_id=m.market_id
                     AND l.timeframe='M5'
                   WHERE m.enabled=1
                   GROUP BY m.symbol,m.calendar_code,m.market_timezone,
                            m.session_open_local,m.session_close_local"""
            )
            stale_markets: list[tuple[str, object, object]] = []
            for market in cursor.fetchall():
                latest_open = market["latest_open"]
                latest_close = market["latest_close"]
                cursor.execute(
                    """SELECT holiday_date,session_close_local FROM app.market_holidays
                       WHERE calendar_code=%s""", (str(market["calendar_code"]),),
                )
                holidays = {row["holiday_date"]: row["session_close_local"] for row in cursor.fetchall()}
                session = operational_session_state(
                    now.replace(tzinfo=timezone.utc),
                    calendar_code=str(market["calendar_code"]),
                    market_timezone=str(market["market_timezone"]),
                    session_open=market["session_open_local"],
                    session_close=market["session_close_local"],
                    holidays=holidays,
                )
                # Feed health follows the current streaming heartbeat. Completed
                # candles remain the authority for models and execution, but IG's
                # CONS_END marker can lag while current price updates are healthy.
                live_latest = market["live_latest"] if (
                    market["live_updated"] is not None
                    and market["live_updated"] >= now - timedelta(seconds=settings.execution_m5_fresh_seconds)
                ) else None
                # A completed M5 is fresh from its close, not its open. A live
                # update is fresh from receipt, irrespective of its bucket open.
                feed_latest = max((value for value in (latest_close, market["live_updated"] if live_latest else None)
                                   if value is not None),
                                  default=None)
                if market_data_stale(
                    feed_latest, now_utc=now.replace(tzinfo=timezone.utc), session=session,
                    freshness=timedelta(seconds=settings.execution_m5_fresh_seconds),
                ):
                    stale_markets.append((str(market["symbol"]), latest_open, latest_close, session))
            if len(stale_markets) == 1:
                symbol, latest_open, latest_close, session = stale_markets[0]
                issues.append(HealthIssue(
                    f"market.{symbol}.session_data_stale", "WARNING",
                    f"No market data during the open session for {symbol}",
                    f"latest_completed_m5_open={dual_time(latest_open)}; "
                    f"latest_completed_m5_close={dual_time(latest_close)}; session_state={session.status}; "
                    f"session_reason={session.reason}",
                ))
            elif stale_markets:
                details = "; ".join(f"{symbol}={dual_time(latest_close)}"
                                    for symbol, _, latest_close, _ in stale_markets)
                issues.append(HealthIssue(
                    "market_feed.session_data_stale", "CRITICAL",
                    f"Shared market feed is stale for {len(stale_markets)} open markets",
                    f"latest_completed_m5_close: {details}",
                ))
            cursor.execute(
                """WITH latest AS (
                     SELECT s.*,m.symbol,ROW_NUMBER() OVER(PARTITION BY s.tenant_id,s.market_id
                       ORDER BY s.evaluated_at_utc DESC) rn
                     FROM app.model_monitoring_snapshots s JOIN app.markets m ON m.market_id=s.market_id)
                   SELECT symbol,status,feature_drift_score,calibration_drift_score,cost_drift_score,
                          evaluated_at_utc FROM latest WHERE rn=1 AND status IN ('WARN','FAIL')"""
            )
            for drift in cursor.fetchall():
                symbol = str(drift["symbol"])
                issues.append(HealthIssue(
                    f"model.{symbol}.drift", "CRITICAL" if drift["status"] == "FAIL" else "WARNING",
                    f"Model evidence drift requires attention: {symbol}",
                    f"status={drift['status']}; feature={drift['feature_drift_score']}; "
                    f"calibration={drift['calibration_drift_score']}; cost={drift['cost_drift_score']}; "
                    f"evaluated={drift['evaluated_at_utc']}",
                ))
    except Exception as exc:
        issues.append(HealthIssue("database.health_query", "CRITICAL", "Health database query failed",
                                  type(exc).__name__))
    return issues


def persist_and_notify(settings: Settings, issues: list[HealthIssue]) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    active = {issue.key for issue in issues}
    notifications: list[HealthIssue] = []
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        for issue in issues:
            cursor.execute("SELECT * FROM app.operational_alerts WHERE alert_key=%s", (issue.key,))
            previous = cursor.fetchone()
            should_notify = not previous or previous["status"] == "RESOLVED"
            if previous and previous["last_notified_at_utc"]:
                notified = previous["last_notified_at_utc"].replace(tzinfo=timezone.utc)
                should_notify = should_notify or notified <= now - timedelta(
                    minutes=settings.operational_alert_cooldown_minutes
                )
            if previous:
                cursor.execute(
                    """UPDATE app.operational_alerts SET severity=%s,status='OPEN',summary=%s,detail=%s,
                       last_seen_at_utc=%s,resolved_at_utc=NULL,occurrence_count=occurrence_count+1
                       WHERE alert_key=%s""",
                    (issue.severity, issue.summary, issue.detail, now, issue.key),
                )
            else:
                cursor.execute(
                    """INSERT app.operational_alerts
                       (operational_alert_id,alert_key,severity,status,summary,detail,first_seen_at_utc,last_seen_at_utc)
                       VALUES(%s,%s,%s,'OPEN',%s,%s,%s,%s)""",
                    (str(uuid4()), issue.key, issue.severity, issue.summary, issue.detail, now, now),
                )
            if should_notify:
                notifications.append(issue)
        cursor.execute("SELECT alert_key FROM app.operational_alerts WHERE status='OPEN'")
        for row in cursor.fetchall():
            if str(row["alert_key"]) not in active:
                cursor.execute(
                    """UPDATE app.operational_alerts SET status='RESOLVED',resolved_at_utc=%s,
                       last_seen_at_utc=%s WHERE alert_key=%s""", (now, now, str(row["alert_key"])),
                )
        connection.commit()

    notified = 0
    if notifications and _send_email(settings, notifications):
        with open_database(settings) as connection:
            cursor = connection.cursor()
            for issue in notifications:
                cursor.execute(
                    "UPDATE app.operational_alerts SET last_notified_at_utc=%s WHERE alert_key=%s",
                    (now, issue.key),
                )
            connection.commit()
        notified = len(notifications)
    return {"open": len(issues), "notified": notified}


def _send_email(settings: Settings, issues: list[HealthIssue]) -> bool:
    recipient = settings.trade_report_recipient or settings.owner_email or settings.smtp_from_email
    if not settings.smtp_configured or not recipient:
        logger.warning("Operational alert email is not configured")
        return False
    try:
        send_email(
            settings, recipient=recipient,
            subject=f"Aurex operational alert ({len(issues)})",
            plain_text="\n\n".join(
                f"[{item.severity}] {item.summary}\n{item.detail}" for item in issues
            ),
        )
        return True
    except Exception:
        logger.exception("Operational alert email failed")
        return False


class HealthMonitor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stopped = Event()

    def stop(self) -> None:
        self.stopped.set()

    def run_forever(self) -> None:
        while not self.stopped.is_set():
            try:
                persist_and_notify(self.settings, inspect_health(self.settings))
                send_due_daily_progress_reports(self.settings)
            except Exception:
                logger.exception("Operational health cycle failed")
            self.stopped.wait(self.settings.health_monitor_seconds)
