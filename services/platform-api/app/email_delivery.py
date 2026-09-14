from __future__ import annotations

import smtplib
from email.message import EmailMessage
from html import escape

from app.config import Settings


def aurex_email_html(
    *, title: str, eyebrow: str, summary: str, details: list[tuple[str, str]] | None = None,
    action_label: str | None = None, action_url: str | None = None,
    severity: str = "INFO",
) -> str:
    """Render a restrained, email-client-safe Aurex notification."""
    tones = {"CRITICAL": ("#b42318", "#fef3f2"), "WARNING": ("#b54708", "#fffaeb"),
             "SUCCESS": ("#067647", "#ecfdf3"), "INFO": ("#175cd3", "#eff8ff")}
    accent, tint = tones.get(severity.upper(), tones["INFO"])
    rows = "".join(
        f'<tr><td style="padding:9px 0;color:#667085;font-size:13px">{escape(label)}</td>'
        f'<td style="padding:9px 0;text-align:right;color:#101828;font-size:13px;font-weight:600">{escape(value)}</td></tr>'
        for label, value in (details or [])
    )
    action = ""
    if action_label and action_url:
        action = (f'<p style="margin:26px 0 8px"><a href="{escape(action_url, quote=True)}" '
                  f'style="display:inline-block;background:{accent};color:#fff;text-decoration:none;'
                  'padding:12px 18px;border-radius:8px;font-weight:700;font-size:14px">'
                  f'{escape(action_label)}</a></p>')
    return f"""<!doctype html><html><body style="margin:0;background:#f2f4f7;font-family:Arial,sans-serif;color:#101828">
<div style="display:none;max-height:0;overflow:hidden">{escape(summary)}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#fff;border:1px solid #eaecf0;border-radius:14px;overflow:hidden">
<tr><td style="padding:22px 28px;background:#0b1739;color:#fff"><div style="font-size:20px;font-weight:800;letter-spacing:1px">AUREX</div><div style="font-size:12px;color:#b2ccff;margin-top:4px">HOLENI · IG DEMO</div></td></tr>
<tr><td style="padding:28px"><div style="display:inline-block;padding:5px 9px;border-radius:20px;background:{tint};color:{accent};font-size:11px;font-weight:800">{escape(eyebrow.upper())}</div>
<h1 style="font-size:24px;line-height:1.25;margin:16px 0 10px">{escape(title)}</h1><p style="color:#475467;line-height:1.6;margin:0 0 18px">{escape(summary)}</p>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-top:1px solid #eaecf0;border-bottom:1px solid #eaecf0">{rows}</table>{action}
<p style="font-size:12px;line-height:1.5;color:#667085;margin:22px 0 0">For security, email links can only open Aurex. Approval and broker submission require authenticated, audited controls inside the platform.</p></td></tr>
</table></td></tr></table></body></html>"""


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
