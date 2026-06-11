from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Dict

from .env import get_project_env


def send_daily_ready_email(to_email: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    host = get_project_env("SMTP_HOST")
    user = get_project_env("SMTP_USER")
    password = get_project_env("SMTP_PASSWORD")
    from_email = get_project_env("SMTP_FROM", user)
    port = int(get_project_env("SMTP_PORT", "587") or "587")
    use_tls = get_project_env("SMTP_USE_TLS", "true").strip().lower() != "false"

    if not host or not user or not password or not from_email:
        return {
            "sent": False,
            "reason": "SMTP settings are incomplete. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM.",
        }

    subject = f"Today's leads are ready: {summary.get('query', 'daily search')}"
    body = (
        "Your daily lead run finished.\n\n"
        f"Date: {summary.get('date', '')}\n"
        f"Search: {summary.get('query', '')}\n"
        f"Leads stored: {summary.get('stored', 0)}\n"
        f"Places API calls: {summary.get('apiCalls', 0)}\n\n"
        "Open the Leads Generator app to review and tick off today's leads."
    )

    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)

    return {"sent": True, "to": to_email}
