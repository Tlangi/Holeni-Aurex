from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.daily_progress_report import send_due_daily_progress_reports
from app.email_delivery import send_email


def test_daily_report_can_be_disabled_without_touching_external_state() -> None:
    settings = Settings(_env_file=None, daily_progress_report_enabled=False)
    assert send_due_daily_progress_reports(settings) == [{"status": "DISABLED"}]


def test_daily_report_waits_for_south_african_delivery_hour() -> None:
    settings = Settings(_env_file=None, daily_progress_report_hour_sast=18)
    at_early_sast = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)
    assert send_due_daily_progress_reports(settings, now=at_early_sast) == [
        {"status": "NOT_DUE", "report_date_sast": "2026-08-26"},
    ]


def test_email_delivery_uses_tls_login_and_multipart_content() -> None:
    settings = Settings(
        _env_file=None, smtp_username="sender@example.com", smtp_password="secret",
        smtp_from_email="sender@example.com", smtp_use_tls=True,
    )
    client = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = client
    context.__exit__.return_value = False
    with patch("app.email_delivery.smtplib.SMTP", return_value=context):
        send_email(
            settings, recipient="owner@example.com", subject="Aurex report",
            plain_text="Plain evidence", html="<p>HTML evidence</p>",
        )
    client.starttls.assert_called_once_with()
    client.login.assert_called_once_with("sender@example.com", "secret")
    message = client.send_message.call_args.args[0]
    assert message["To"] == "owner@example.com"
    assert message.is_multipart()

