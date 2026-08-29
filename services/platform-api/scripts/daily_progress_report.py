from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.config import get_settings  # noqa: E402
from app.daily_progress_report import build_daily_progress_report, send_due_daily_progress_reports  # noqa: E402
from app.database import open_database  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview, send or audit the Aurex daily progress report")
    parser.add_argument("action", choices=("preview", "send", "status"))
    parser.add_argument("--retry-failed", action="store_true",
                        help="Explicitly retry today's audited FAILED delivery")
    arguments = parser.parse_args()
    settings = get_settings()
    if arguments.action == "send":
        print(json.dumps(send_due_daily_progress_reports(
            settings, force=True, retry_failed=arguments.retry_failed,
        ), indent=2, default=str))
        raise SystemExit(0)
    with open_database(settings) as connection:
        cursor = connection.cursor(as_dict=True)
        if arguments.action == "status":
            cursor.execute(
                """SELECT TOP (30) report_date_sast,recipient_email,subject,status,
                          claimed_at_utc,sent_at_utc,failed_at_utc,failure_code
                   FROM app.daily_progress_reports ORDER BY report_date_sast DESC,claimed_at_utc DESC"""
            )
            print(json.dumps(cursor.fetchall(), indent=2, default=str))
            raise SystemExit(0)
        cursor.execute("SELECT TOP (1) tenant_id FROM app.tenants ORDER BY created_at_utc")
        tenant = cursor.fetchone()
    if not tenant:
        raise SystemExit("No tenant exists")
    today = datetime.now(ZoneInfo("Africa/Johannesburg")).date()
    report = build_daily_progress_report(settings, str(tenant["tenant_id"]), today)
    print(report.plain_text)
