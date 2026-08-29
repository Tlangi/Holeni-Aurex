from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import requests

from app.config import Settings
from app.database import open_database
from app.daily_progress_report import send_due_daily_progress_reports
from app.email_delivery import send_email

logger = logging.getLogger("aurex.health_monitor")


@dataclass(frozen=True)
class HealthIssue:
    key: str
    severity: str
    summary: str
    detail: str


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
            f"http://{settings.web_host}:{settings.web_port}/_health", timeout=10,
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
                """SELECT m.symbol,MAX(c.open_time_utc) latest
                   FROM app.markets m LEFT JOIN app.candles c ON c.market_id=m.market_id
                     AND c.timeframe='M5' AND c.completed=1
                   WHERE m.enabled=1 GROUP BY m.symbol"""
            )
            for market in cursor.fetchall():
                latest = market["latest"]
                if latest is None or latest < now - timedelta(hours=24):
                    symbol = str(market["symbol"])
                    issues.append(HealthIssue(
                        f"market.{symbol}.no_daily_data", "WARNING",
                        f"No recent market data for {symbol}", f"latest_completed_m5={latest}",
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
