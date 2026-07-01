from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


WebsiteStatus = Literal[
    "no_website",
    "live",
    "broken",
    "parked_domain",
    "placeholder",
    "social_only",
    "external_platform_only",
    "redirected_unrelated",
    "thin_site",
    "unknown_error",
]

EmailQuality = Literal["no_email", "generic_email", "good_email", "excellent_email"]
Priority = Literal["low", "medium", "high"]
NextBestAction = Literal[
    "skip",
    "auto_email",
    "manual_email_review",
    "call_first",
    "sms_first",
    "call_or_instagram_dm",
    "manual_research_needed",
    "no_contact_available",
    "high_priority_manual_outreach",
]
PitchType = Literal[
    "no_website_pitch",
    "broken_website_fix",
    "placeholder_site_fix",
    "mobile_redesign",
    "full_redesign",
    "conversion_optimization",
    "booking_or_contact_flow_fix",
    "booking_conversion_and_local_seo_cleanup",
    "speed_performance_fix",
    "local_seo_improvement",
    "visual_refresh",
    "skip_good_site",
]


class LeadInput(BaseModel):
    business_name: str = ""
    business_category: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    google_rating: Optional[float] = None
    review_count: Optional[int] = None
    google_maps_url: str = ""
    email: str = ""
    email_source: str = ""
    email_contact_type: str = ""
    email_contact_name: str = ""
    email_contact_title: str = ""
    email_recent_activity_signal: str = ""

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "LeadInput":
        def first(*keys: str) -> Any:
            for key in keys:
                value = row.get(key)
                if value not in (None, ""):
                    return value
            return ""

        return cls(
            business_name=str(first("business_name", "name", "business", "Business Name")),
            business_category=str(first("business_category", "category", "businessType", "business_type")),
            address=str(first("address", "formattedAddress", "shortFormattedAddress")),
            phone=str(first("phone", "nationalPhoneNumber")),
            website=str(first("website", "websiteUrl", "website_url", "websiteUri")),
            google_rating=_float_or_none(first("google_rating", "rating")),
            review_count=_int_or_none(first("review_count", "userRatingCount", "user_rating_count")),
            google_maps_url=str(first("google_maps_url", "googleMapsUri", "google_maps_uri")),
            email=str(first("email", "bestEmail", "best_email")),
            email_source=str(first("email_source", "bestEmailSourceUrl", "best_email_source_url")),
            email_contact_type=str(first("email_contact_type", "bestEmailType", "best_email_type")),
            email_contact_name=str(first("email_contact_name", "contactName", "contact_name")),
            email_contact_title=str(first("email_contact_title", "contactTitle", "contact_title")),
            email_recent_activity_signal=str(first("email_recent_activity_signal")),
        )


class WebsiteStatusResult(BaseModel):
    input_url: str = ""
    normalized_url: str = ""
    final_url: str = ""
    website_status: WebsiteStatus = "unknown_error"
    http_status: Optional[int] = None
    redirect_chain: List[str] = Field(default_factory=list)
    title: str = ""
    text_snippet: str = ""
    detected_reasons: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class PageAuditResult(BaseModel):
    url: str
    final_url: str = ""
    page_type: str = "other"
    http_status: Optional[int] = None
    title: str = ""
    h1: str = ""
    text_snippet: str = ""
    word_count: int = 0
    meta_description_present: bool = False
    internal_links: int = 0
    external_links: int = 0
    images: int = 0
    images_missing_alt: int = 0
    broken_image_count: int = 0
    console_errors: List[str] = Field(default_factory=list)
    network_errors: List[str] = Field(default_factory=list)
    broken_internal_links: List[str] = Field(default_factory=list)
    forms_present: bool = False
    generic_contact_form: bool = False
    phone_links_present: bool = False
    email_links_present: bool = False
    phone_numbers: List[str] = Field(default_factory=list)
    email_addresses: List[str] = Field(default_factory=list)
    social_links: List[str] = Field(default_factory=list)
    cta_labels: List[str] = Field(default_factory=list)
    cta_hrefs: List[str] = Field(default_factory=list)
    booking_cta_links: List[str] = Field(default_factory=list)
    brand_candidates: List[str] = Field(default_factory=list)
    trust_signals: List[str] = Field(default_factory=list)
    cta_buttons_present: bool = False
    visible_cta_above_fold: bool = False
    cookie_banner_blocks_cta: bool = False
    mobile_horizontal_overflow: bool = False
    small_tap_targets: int = 0
    small_font_elements: int = 0
    contact_info_present: bool = False
    screenshot_path_mobile: str = ""
    screenshot_path_desktop: str = ""
    notes: List[str] = Field(default_factory=list)


class CrawlResult(BaseModel):
    pages: List[PageAuditResult] = Field(default_factory=list)
    discovered_urls: List[str] = Field(default_factory=list)
    screenshots_saved: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None


class VisualIssue(BaseModel):
    category: str
    severity: Literal["low", "medium", "high"] = "medium"
    evidence: str


class VisualAuditResult(BaseModel):
    visual_score: int = 50
    design_status: Literal["modern", "acceptable", "outdated", "poor", "unknown"] = "unknown"
    mobile_usability_score: int = 50
    conversion_score: int = 50
    pitch_confidence: Literal["low", "medium", "high"] = "low"
    objective_visual_issues: List[VisualIssue] = Field(default_factory=list)
    subjective_design_issues: List[VisualIssue] = Field(default_factory=list)
    recommended_visual_pitch_angle: str = ""
    llm_model: str = ""
    llm_prompt: str = ""
    llm_raw_response: str = ""
    llm_error: Optional[str] = None


class EmailScoreResult(BaseModel):
    email: str = ""
    email_quality: EmailQuality = "no_email"
    score: int = 0
    reasons: List[str] = Field(default_factory=list)


class FinalLeadAuditResult(BaseModel):
    business_name: str = ""
    business_category: str = ""
    website: str = ""
    final_url: str = ""
    website_status: WebsiteStatus = "unknown_error"
    email: str = ""
    email_quality: EmailQuality = "no_email"
    website_opportunity_score: int = 0
    visual_score: int = 0
    technical_issue_score: int = 0
    conversion_issue_score: int = 0
    lead_quality_score: int = 0
    outreach_priority: Priority = "low"
    next_best_action: NextBestAction = "manual_research_needed"
    recommended_pitch_type: PitchType = "skip_good_site"
    recommended_pitch_angle: str = ""
    contact_channels: List[str] = Field(default_factory=list)
    top_business_impact_issues: List[str] = Field(default_factory=list)
    top_verified_issues: List[str] = Field(default_factory=list)
    top_subjective_issues: List[str] = Field(default_factory=list)
    evidence_summary: str = ""
    screenshots_saved: List[str] = Field(default_factory=list)
    audit_status: Literal["completed", "failed", "partial"] = "completed"
    error_message: Optional[str] = None
    debug: Dict[str, Any] = Field(default_factory=dict)


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def model_to_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
