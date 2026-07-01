from __future__ import annotations

import re
from urllib.parse import urlparse
from typing import List, Tuple

from .models import (
    CrawlResult,
    EmailScoreResult,
    FinalLeadAuditResult,
    LeadInput,
    VisualAuditResult,
    WebsiteStatusResult,
)


HIGH_OPPORTUNITY_STATUSES = {"no_website", "broken", "parked_domain", "placeholder", "redirected_unrelated", "thin_site"}


def score_final_lead(
    lead: LeadInput,
    status: WebsiteStatusResult,
    crawl: CrawlResult,
    visual: VisualAuditResult,
    email: EmailScoreResult,
) -> FinalLeadAuditResult:
    technical_score, technical_issues = _technical_issue_score(status, crawl)
    conversion_score, conversion_issues = _conversion_issue_score(crawl, visual)
    business_impact_score, business_impact_issues = _business_impact_issues(lead, status, crawl)
    opportunity_score = _website_opportunity_score(
        status,
        visual.visual_score,
        technical_score,
        conversion_score,
        business_impact_score,
    )
    business_value = _business_value_score(lead)
    evidence_confidence = _evidence_confidence(status, crawl, visual)
    contact_channels = _contact_channels(lead, crawl, email)
    contactability_score = _contactability_score(email, contact_channels)
    lead_quality = round(
        opportunity_score * 0.55
        + business_value * 0.20
        + evidence_confidence * 0.15
        + contactability_score * 0.10
    )
    priority = "high" if lead_quality >= 75 else "medium" if lead_quality >= 50 else "low"
    pitch_type, pitch_angle = _pitch(status, business_impact_issues, technical_issues, conversion_issues, visual)
    next_action = _next_action(status.website_status, priority, email.email_quality, contact_channels, pitch_type)

    subjective = [issue.evidence for issue in visual.subjective_design_issues[:3]]
    objective_visual = [issue.evidence for issue in visual.objective_visual_issues[:3]]
    verified = list(dict.fromkeys(business_impact_issues + status.detected_reasons + conversion_issues + technical_issues + objective_visual))[:7]
    evidence_summary = _evidence_summary(status, business_impact_issues, verified, subjective, visual)

    return FinalLeadAuditResult(
        business_name=lead.business_name,
        business_category=lead.business_category,
        website=lead.website,
        final_url=status.final_url or status.normalized_url,
        website_status=status.website_status,
        email=email.email,
        email_quality=email.email_quality,
        website_opportunity_score=opportunity_score,
        visual_score=visual.visual_score,
        technical_issue_score=technical_score,
        conversion_issue_score=conversion_score,
        lead_quality_score=max(0, min(100, lead_quality)),
        outreach_priority=priority,
        next_best_action=next_action,
        recommended_pitch_type=pitch_type,
        recommended_pitch_angle=pitch_angle,
        contact_channels=contact_channels,
        top_business_impact_issues=business_impact_issues[:5],
        top_verified_issues=verified,
        top_subjective_issues=subjective,
        evidence_summary=evidence_summary,
        screenshots_saved=crawl.screenshots_saved,
        audit_status="completed" if not crawl.error_message else "partial",
        error_message=crawl.error_message,
        debug={
            "business_value_score": business_value,
            "business_impact_score": business_impact_score,
            "contactability_score": contactability_score,
            "evidence_confidence": evidence_confidence,
            "email_reasons": email.reasons,
            "llm_model": visual.llm_model,
            "llm_error": visual.llm_error,
            "pages_crawled": len(crawl.pages),
        },
    )


def _website_opportunity_score(
    status: WebsiteStatusResult,
    visual_score: int,
    technical_score: int,
    conversion_score: int,
    business_impact_score: int,
) -> int:
    if status.website_status == "no_website":
        return 85
    if status.website_status in {"broken", "parked_domain", "placeholder"}:
        return 92
    if status.website_status == "redirected_unrelated":
        return 80
    if status.website_status in {"social_only", "external_platform_only", "thin_site"}:
        return 72
    if status.website_status != "live":
        return 55
    weakness = 100 - visual_score
    score = round(business_impact_score * 0.55 + conversion_score * 0.25 + technical_score * 0.10 + weakness * 0.10)
    return max(0, min(100, score))


def _technical_issue_score(status: WebsiteStatusResult, crawl: CrawlResult) -> Tuple[int, List[str]]:
    issues: List[str] = []
    if status.website_status in HIGH_OPPORTUNITY_STATUSES:
        issues.extend(status.detected_reasons or [f"Website status is {status.website_status}"])
    for page in crawl.pages:
        if page.http_status and page.http_status >= 400:
            issues.append(f"{page.page_type} page returned HTTP {page.http_status}")
        severe_console_errors = [
            error for error in page.console_errors
            if not any(noise in error.lower() for noise in ("favicon", "404 (not found)"))
        ]
        if severe_console_errors:
            issues.append(f"{page.page_type} page has console errors that may affect functionality")
        if page.network_errors:
            issues.append(f"{page.page_type} page has failed network requests")
        if page.broken_internal_links:
            issues.append(f"{page.page_type} page has broken internal links")
        if page.broken_image_count:
            issues.append(f"{page.page_type} page has broken images")
        if page.images_missing_alt >= 6:
            issues.append(f"{page.page_type} page has many images missing alt text")
        if not page.meta_description_present and page.page_type == "home":
            issues.append("Homepage is missing a meta description")
    score = min(100, len(issues) * 12)
    if status.website_status in {"broken", "parked_domain", "placeholder"}:
        score = max(score, 85)
    return score, list(dict.fromkeys(issues))


def _conversion_issue_score(crawl: CrawlResult, visual: VisualAuditResult) -> Tuple[int, List[str]]:
    issues: List[str] = []
    pages = crawl.pages
    home = pages[0] if pages else None
    has_contact_section = any(page.contact_info_present or page.forms_present for page in pages)
    has_booking_cta = any(page.booking_cta_links or any("book" in label.lower() for label in page.cta_labels) for page in pages)
    if home and not home.visible_cta_above_fold:
        issues.append("No clear CTA visible above the fold on the homepage")
    if home and home.cookie_banner_blocks_cta:
        issues.append("Cookie banner overlaps or blocks the primary above-the-fold CTA")
    if not any(page.page_type in {"contact", "booking"} for page in pages) and not has_contact_section:
        issues.append("No contact, booking, reservation, or order page or section found in limited crawl")
    if not any(page.forms_present for page in pages) and not any(page.phone_links_present or page.email_links_present or page.phone_numbers for page in pages):
        issues.append("No form, phone link, or email link detected on crawled pages")
    if has_booking_cta and not any(_has_dedicated_booking_target(page) for page in pages):
        issues.append("Booking CTA does not lead to a dedicated booking or appointment flow")
    if any(page.generic_contact_form for page in pages):
        issues.append("Contact form appears generic instead of appointment-focused")
    if home and home.mobile_horizontal_overflow:
        issues.append("Mobile homepage has horizontal overflow")
    if home and home.small_tap_targets > 12:
        issues.append("Mobile homepage has many small tap targets")
    if visual.conversion_score < 50 and visual.pitch_confidence != "low":
        issues.append("Vision audit rated conversion clarity weak")
    score = min(100, len(issues) * 22)
    if visual.conversion_score:
        score = max(score, 100 - visual.conversion_score)
    return max(0, min(100, score)), list(dict.fromkeys(issues))


def _business_impact_issues(lead: LeadInput, status: WebsiteStatusResult, crawl: CrawlResult) -> Tuple[int, List[str]]:
    if status.website_status != "live":
        return (80 if status.website_status in HIGH_OPPORTUNITY_STATUSES else 35), []

    pages = crawl.pages
    home = pages[0] if pages else None
    issues: List[Tuple[int, str]] = []
    phones = _all_phone_numbers(lead, crawl)
    socials = _all_social_links(crawl)

    if len(phones) > 1:
        issues.append((95, f"Conflicting contact information: multiple phone numbers found ({', '.join(phones[:3])})"))

    brand_issue = _brand_identity_issue(lead, status, crawl)
    if brand_issue:
        issues.append((88, brand_issue))

    if home and home.cookie_banner_blocks_cta:
        issues.append((84, "Cookie banner blocks or overlaps the primary Book Now CTA"))

    if any(page.booking_cta_links or any("book" in label.lower() for label in page.cta_labels) for page in pages) and not any(
        _has_dedicated_booking_target(page) for page in pages
    ):
        issues.append((82, "Book Now CTA does not lead to a dedicated appointment or booking flow"))

    if any(page.generic_contact_form for page in pages):
        issues.append((72, "Contact form appears generic and not tailored to appointment booking"))

    if _local_seo_underoptimized(lead, crawl):
        issues.append((68, "Local SEO appears underoptimized: missing meta description or thin local/service content"))

    if _weak_trust_signals(crawl):
        issues.append((60, "Trust signals are thin: no clear reviews, testimonials, gallery, or staff proof found"))

    if not phones and not socials and not any(page.email_addresses or page.email_links_present for page in pages):
        issues.append((90, "No practical contact channel found on the website"))
    elif not any(page.email_addresses or page.email_links_present for page in pages):
        issues.append((35, "No email found; outreach should use phone or social instead of automated email"))

    deduped = list(dict.fromkeys(text for _score, text in sorted(issues, key=lambda item: item[0], reverse=True)))
    if not deduped:
        return 10, []
    score = min(100, round(sum(score for score, _text in issues[:5]) / max(1, min(5, len(issues)))))
    return max(0, score), deduped


def _business_value_score(lead: LeadInput) -> int:
    score = 45
    if lead.phone:
        score += 10
    if lead.google_rating is not None:
        if lead.google_rating >= 4.2:
            score += 10
        elif lead.google_rating < 3.5:
            score -= 8
    if lead.review_count is not None:
        if lead.review_count >= 50:
            score += 15
        elif lead.review_count >= 10:
            score += 8
    category = lead.business_category.lower()
    category_blob = f"{lead.business_category} {lead.website}".lower()
    if any(word in category_blob for word in ("spa", "dental", "med", "law", "roof", "remodel", "salon", "barber", "restaurant", "fitness", "clinic")):
        score += 10
    return max(0, min(100, score))


def _evidence_confidence(status: WebsiteStatusResult, crawl: CrawlResult, visual: VisualAuditResult) -> int:
    score = 35
    if status.http_status:
        score += 15
    if crawl.pages:
        score += min(25, len(crawl.pages) * 5)
    if crawl.screenshots_saved:
        score += 15
    if visual.pitch_confidence == "high":
        score += 10
    elif visual.pitch_confidence == "medium":
        score += 5
    return max(0, min(100, score))


def _pitch(
    status: WebsiteStatusResult,
    business_impact: List[str],
    technical: List[str],
    conversion: List[str],
    visual: VisualAuditResult,
) -> Tuple[str, str]:
    if status.website_status == "no_website":
        return "no_website_pitch", "No website is listed; a simple local business site could improve trust and inquiries."
    if status.website_status == "broken":
        return "broken_website_fix", "The website appears broken or unreachable and should be repaired before prospects lose trust."
    if status.website_status in {"parked_domain", "placeholder"}:
        return "placeholder_site_fix", "The current site appears parked or unfinished and could be replaced with a complete business website."
    impact_blob = " ".join(business_impact).lower()
    if any(word in impact_blob for word in ("conflicting contact", "brand", "book now", "appointment", "local seo", "generic")):
        return (
            "booking_conversion_and_local_seo_cleanup",
            "The site has the basics, but contact clarity, branding, booking flow, and local SEO could be tightened to help more visitors become appointments.",
        )
    if any("overflow" in issue.lower() or "tap target" in issue.lower() for issue in conversion):
        return "mobile_redesign", "Mobile usability issues are visible in the audit and could be improved to drive more inquiries."
    if any("cta" in issue.lower() or "contact" in issue.lower() or "booking" in issue.lower() for issue in conversion):
        return "conversion_optimization", "The site could make the contact or booking path clearer for visitors."
    if technical:
        return "speed_performance_fix", "Technical issues found during the crawl could be cleaned up to improve reliability."
    if visual.design_status in {"outdated", "poor"}:
        return "visual_refresh", visual.recommended_visual_pitch_angle or "The visual design appears dated and could benefit from a focused refresh."
    return "skip_good_site", "The limited audit did not find a strong, evidence-backed website improvement angle."


def _next_action(status: str, priority: str, email_quality: str, contact_channels: List[str], pitch_type: str) -> str:
    if pitch_type == "skip_good_site":
        return "skip"
    has_phone = "phone" in contact_channels
    has_social = any(channel in contact_channels for channel in ("instagram", "social"))
    if status == "no_website":
        return "call_first" if has_phone else "no_contact_available"
    if priority == "high" and email_quality == "excellent_email":
        return "high_priority_manual_outreach"
    if email_quality in {"good_email", "excellent_email"}:
        return "auto_email" if priority == "medium" else "manual_email_review"
    if email_quality == "generic_email":
        return "manual_email_review" if not has_phone else "call_first"
    if has_phone and has_social:
        return "call_or_instagram_dm"
    return "call_first" if has_phone else "no_contact_available"


def _evidence_summary(
    status: WebsiteStatusResult,
    business_impact: List[str],
    verified: List[str],
    subjective: List[str],
    visual: VisualAuditResult,
) -> str:
    if status.website_status != "live":
        reason = verified[0] if verified else f"status is {status.website_status}"
        return f"The website audit found {reason}."
    if business_impact:
        compact = "; ".join(business_impact[:3])
        return f"The site is live and has basic business information, but the audit found practical conversion issues: {compact}."
    if verified:
        return f"The site is live, but the audit found: {verified[0]}."
    if subjective:
        return f"The site is live; visual review noted: {subjective[0]}."
    if visual.pitch_confidence == "low":
        return "The site is live; limited evidence did not support a strong pitch angle."
    return "The site is live and the limited audit did not find major issues."


def _contact_channels(lead: LeadInput, crawl: CrawlResult, email: EmailScoreResult) -> List[str]:
    channels: List[str] = []
    if email.email and email.email_quality != "no_email":
        channels.append("email")
    if _all_phone_numbers(lead, crawl):
        channels.append("phone")
    social_links = _all_social_links(crawl)
    if any("instagram.com" in link for link in social_links):
        channels.append("instagram")
    elif social_links:
        channels.append("social")
    return channels


def _contactability_score(email: EmailScoreResult, contact_channels: List[str]) -> int:
    if email.email_quality == "excellent_email":
        return 100
    if email.email_quality == "good_email":
        return 85
    if email.email_quality == "generic_email":
        return 65
    if "phone" in contact_channels and any(channel in contact_channels for channel in ("instagram", "social")):
        return 65
    if "phone" in contact_channels:
        return 55
    if any(channel in contact_channels for channel in ("instagram", "social")):
        return 45
    return 10


def _all_phone_numbers(lead: LeadInput, crawl: CrawlResult) -> List[str]:
    values = {_normalize_phone(lead.phone)}
    for page in crawl.pages:
        values.update(page.phone_numbers)
    return sorted(value for value in values if value)


def _all_social_links(crawl: CrawlResult) -> List[str]:
    links = []
    for page in crawl.pages:
        links.extend(page.social_links)
    return list(dict.fromkeys(links))


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return ""


def _brand_identity_issue(lead: LeadInput, status: WebsiteStatusResult, crawl: CrawlResult) -> str:
    names = []
    if lead.business_name and lead.business_name != "Manual Test Lead":
        names.append(lead.business_name)
    if status.title:
        names.append(status.title)
    for page in crawl.pages:
        names.extend(page.brand_candidates)
    meaningful = []
    for name in names:
        compact = _compact_name(name)
        if not compact or compact in {"look sharp feel confident", "home", "more"}:
            continue
        if any(word in compact for word in ("barber", "shop", "co", "company", "salon", "spa", "restaurant", "dental", "clinic")):
            meaningful.append(name.strip())
    normalized = list(dict.fromkeys(_compact_name(name) for name in meaningful))
    if len(normalized) <= 1:
        return ""
    examples = list(dict.fromkeys(name for name in meaningful if _compact_name(name) in normalized))[:3]
    return f"Inconsistent business identity across page title/header ({' vs '.join(examples)})"


def _compact_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _has_dedicated_booking_target(page) -> bool:
    for href in page.booking_cta_links:
        lower = href.lower()
        if lower.startswith("tel:"):
            continue
        if any(word in lower for word in ("book", "booking", "appointment", "schedule", "reserve", "reservation", "order")):
            return True
    return page.page_type == "booking"


def _local_seo_underoptimized(lead: LeadInput, crawl: CrawlResult) -> bool:
    home = crawl.pages[0] if crawl.pages else None
    if not home:
        return False
    blob = f"{home.title} {home.h1} {home.text_snippet}".lower()
    has_location = bool(lead.address and any(part.strip().lower() in blob for part in re.split(r"[,|]", lead.address) if len(part.strip()) > 2))
    has_category = any(word in blob for word in ("barber", "haircut", "beard", "spa", "salon", "restaurant", "dental", "clinic", "lawyer", "attorney"))
    return (not home.meta_description_present) or home.word_count < 250 or not (has_location and has_category)


def _weak_trust_signals(crawl: CrawlResult) -> bool:
    signals = set()
    for page in crawl.pages:
        signals.update(page.trust_signals)
    strong = {"reviews", "review", "testimonials", "testimonial", "gallery", "portfolio", "staff", "team"}
    return not bool(signals & strong)
