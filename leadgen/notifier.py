from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Dict

import requests

from .env import get_project_env


def send_daily_ready_email(to_email: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    api_result = _send_with_resend(to_email, summary)
    if api_result is not None:
        return api_result
    return _send_with_smtp(to_email, summary)


def _message_payload(summary: Dict[str, Any]) -> Dict[str, str]:
    subject = f"Today's leads are ready: {summary.get('query', 'daily search')}"
    body = (
        "Your daily lead run finished.\n\n"
        f"Date: {summary.get('date', '')}\n"
        f"Search: {summary.get('query', '')}\n"
        f"Leads stored: {summary.get('stored', 0)}\n"
        f"Places API calls: {summary.get('apiCalls', 0)}\n\n"
        "Open the Leads Generator app to review and tick off today's leads."
    )
    return {"subject": subject, "body": body}


def _send_with_resend(to_email: str, summary: Dict[str, Any]) -> Dict[str, Any] | None:
    api_key = get_project_env("RESEND_API_KEY")
    from_email = get_project_env("RESEND_FROM_EMAIL") or get_project_env("SMTP_FROM")
    if not api_key:
        return None
    if not from_email:
        return {
            "sent": False,
            "reason": "RESEND_API_KEY is set but RESEND_FROM_EMAIL is missing.",
            "provider": "resend",
        }

    payload = _message_payload(summary)
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "subject": payload["subject"],
            "text": payload["body"],
        },
        timeout=20,
    )
    if response.status_code >= 400:
        return {
            "sent": False,
            "reason": f"Resend send failed: {response.status_code} {response.text}",
            "provider": "resend",
        }
    data = response.json() if response.text else {}
    return {"sent": True, "to": to_email, "provider": "resend", "id": data.get("id", "")}


def _send_with_smtp(to_email: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    host = get_project_env("SMTP_HOST")
    user = get_project_env("SMTP_USER")
    password = get_project_env("SMTP_PASSWORD")
    from_email = get_project_env("SMTP_FROM", user)
    port = int(get_project_env("SMTP_PORT", "587") or "587")
    use_tls = get_project_env("SMTP_USE_TLS", "true").strip().lower() != "false"

    if not host or not user or not password or not from_email:
        return {
            "sent": False,
            "reason": "No email transport configured. Set RESEND_API_KEY and RESEND_FROM_EMAIL for production, or SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and SMTP_FROM for SMTP fallback.",
            "provider": "smtp",
        }

    payload = _message_payload(summary)

    message = EmailMessage()
    message["From"] = from_email
    message["To"] = to_email
    message["Subject"] = payload["subject"]
    message.set_content(payload["body"])

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(message)

    return {"sent": True, "to": to_email, "provider": "smtp"}
