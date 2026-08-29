from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import PureWindowsPath
from uuid import UUID

from app.config import Settings
from app.database import open_database


def _serial(value: object) -> object:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return current.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _row(row: dict[str, object]) -> dict[str, object]:
    return {key: _serial(value) for key, value in row.items()}


def read_operational_assurance(
    settings: Settings, tenant_id: str, *, limit: int = 10,
) -> dict[str, object]:
    bounded = max(1, min(limit, 30))
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(
            """SELECT component_code,display_name,status,status_detail,checked_at_utc
               FROM app.platform_components ORDER BY component_code"""
        )
        components = [_row(item) for item in cursor.fetchall()]
        cursor.execute(
            f"""SELECT TOP ({bounded}) alert_key,severity,status,summary,detail,
                       first_seen_at_utc,last_seen_at_utc,last_notified_at_utc,occurrence_count
                FROM app.operational_alerts WHERE status='OPEN'
                ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 ELSE 1 END,last_seen_at_utc DESC"""
        )
        alerts = [_row(item) for item in cursor.fetchall()]
        cursor.execute(
            f"""SELECT TOP ({bounded}) backup_file,backup_sha256,backup_size_bytes,
                       backup_completed_at_utc,restore_verified_at_utc,status,detail,created_at_utc
                FROM app.backup_verifications ORDER BY created_at_utc DESC"""
        )
        backups = []
        for item in cursor.fetchall():
            serial = _row(item)
            serial["backup_file"] = PureWindowsPath(str(item["backup_file"])).name
            backups.append(serial)
        cursor.execute(
            f"""SELECT TOP ({bounded}) report_date_sast,recipient_email,subject,status,
                       claimed_at_utc,sent_at_utc,failed_at_utc,failure_code
                FROM app.daily_progress_reports WHERE tenant_id=%s
                ORDER BY report_date_sast DESC,claimed_at_utc DESC""",
            (tenant_id,),
        )
        reports = [_row(item) for item in cursor.fetchall()]

    latest_backup = backups[0] if backups else None
    latest_verified_restore = next(
        (item for item in backups if item.get("status") == "RESTORE_VERIFIED"), None,
    )
    latest_report = reports[0] if reports else None
    healthy_components = sum(
        1 for item in components if str(item["status"]).upper() in {"CURRENT", "HEALTHY"}
    )
    return {
        "status": "ATTENTION" if alerts else "HEALTHY",
        "open_alert_count": len(alerts),
        "component_summary": {"healthy": healthy_components, "total": len(components)},
        "latest_backup": latest_backup,
        "latest_verified_restore": latest_verified_restore,
        "latest_daily_report": latest_report,
        "components": components,
        "alerts": alerts,
        "backups": backups,
        "daily_reports": reports,
        "safety": {
            "trading_mode": settings.trading_mode,
            "live_trading_allowed": False,
            "reporting_has_execution_authority": False,
        },
    }
