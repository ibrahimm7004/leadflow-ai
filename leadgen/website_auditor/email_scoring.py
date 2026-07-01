from __future__ import annotations

import re

from .models import EmailScoreResult, LeadInput


GENERIC_PREFIXES = {"info", "contact", "support", "hello", "admin", "office", "help", "service", "sales"}
EXCELLENT_TITLE_WORDS = {
    "owner",
    "founder",
    "ceo",
    "president",
    "principal",
    "partner",
    "manager",
    "director",
    "marketing",
    "operations",
}


def score_email(lead: LeadInput) -> EmailScoreResult:
    email = (lead.email or "").strip().lower()
    if not email:
        return EmailScoreResult(email="", email_quality="no_email", score=0, reasons=["No email provided"])
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return EmailScoreResult(email=email, email_quality="no_email", score=0, reasons=["Provided email is not valid"])

    local = email.split("@", 1)[0]
    title_blob = f"{lead.email_contact_type} {lead.email_contact_title} {lead.email_recent_activity_signal}".lower()
    reasons: list[str] = []

    if any(word in title_blob for word in EXCELLENT_TITLE_WORDS):
        score = 95
        quality = "excellent_email"
        reasons.append("Contact title/type suggests a decision maker")
    elif lead.email_contact_name and local not in GENERIC_PREFIXES:
        score = 82
        quality = "good_email"
        reasons.append("Email appears tied to a named person")
    elif local in GENERIC_PREFIXES:
        score = 45
        quality = "generic_email"
        reasons.append(f"Generic mailbox prefix: {local}")
    else:
        score = 70
        quality = "good_email"
        reasons.append("Email appears usable and non-generic")

    if lead.email_recent_activity_signal:
        score = min(100, score + 5)
        reasons.append("Recent activity signal provided")
    if lead.email_source:
        reasons.append("Email source provided")
    return EmailScoreResult(email=email, email_quality=quality, score=score, reasons=reasons)
