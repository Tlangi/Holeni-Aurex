from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
import smtplib


def send_report(settings, attachment: Path, subject: str, body: str) -> None:
    if not settings.gmail_user or not settings.gmail_app_password:
        raise ValueError("GMAIL_SMTP_USER and GMAIL_SMTP_APP_PASSWORD are required")
    if not settings.report_recipient:
        raise ValueError("TRADE_REPORT_RECIPIENT is required")
    message = EmailMessage()
    message["From"] = settings.gmail_user
    message["To"] = settings.report_recipient
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=attachment.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(settings.gmail_user, settings.gmail_app_password.replace(" ", ""))
        smtp.send_message(message)
