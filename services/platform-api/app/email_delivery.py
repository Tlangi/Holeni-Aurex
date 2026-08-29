from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import Settings


def send_email(
    settings: Settings, *, recipient: str, subject: str, plain_text: str,
    html: str | None = None,
) -> None:
    if not settings.smtp_configured:
        raise ValueError("SMTP is not configured")
    if not recipient.strip():
        raise ValueError("Email recipient is required")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = recipient.strip()
    message.set_content(plain_text)
    if html:
        message.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        if settings.smtp_use_tls:
            client.starttls()
        client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)

