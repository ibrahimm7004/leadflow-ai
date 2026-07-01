from __future__ import annotations

import math
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import requests
from openai import OpenAI

from .classify import (
    classify_website_uri,
    extract_place_id,
    is_excluded_website,
    score_place,
    serialize_value,
)
from .constants import LEADS_FIELDS, OUTPUT_FIELDS
from .env import ENV_PATH, get_project_env, load_project_env
from . import cache as cache_module
from .email_scraper import (
    EMAIL_FIELDS,
    ScraperConfig,
    blank_result,
    cache_json_for_result,
    cache_key_for_row,
    email_result_from_cache_json,
    scrape_business_email,
)
from .ai_email_enrichment import (
    EmailEvidence,
    MODEL as AI_EMAIL_MODEL,
    ScrapeResult as AiScrapeResult,
    build_email_decision_prompt,
    choose_best_email_with_gpt,
    choose_local_best,
    clean_email,
    classify_and_score,
    store_result as store_ai_email_result,
    valid_owned_website,
    host_for,
)
from .local_scrape_suite import (
    CrawlReport,
    EmailEvidenceSet,
    crawl_site,
)
from .places import PlacesApiError, build_results
from . import hosted_store
from .hosted_store import HostedStoreError
from .notifier import send_daily_ready_email

load_project_env()

def _allowed_origins() -> List[str]:
    raw = get_project_env("ALLOWED_ORIGINS")
    if not raw:
        return []
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _allow_origin_regex() -> Optional[str]:
    return r"https://([a-z0-9-]+\.)*vercel\.app|http://(localhost|127\.0\.0\.1):\d+"


def _scheduler_enabled() -> bool:
    in_process = get_project_env("RUN_IN_PROCESS_SCHEDULER", "").strip().lower() == "true"
    legacy = get_project_env("ENABLE_DAILY_AUTOMATION", "false").strip().lower() == "true"
    app_env = get_project_env("APP_ENV", "").strip().lower()
    if in_process:
        return True
    if legacy and app_env != "production":
        return True
    return False

WEB_SEARCH_PROMPT_TEMPLATE = """For the business {business} find the best possible email to reach out to for a pitch. {website_instruction}I want you to look for provided emails and people, and decide which single person would be the best for reaching out to make a pitch to improve the business's website; I found some flaws in the website and want to reach out to a real person or the next best bet, so I can help them improve their business! It is typically best to reach out to the owner, manager, ceo, but if you find a better fit for this specific business to email, let me know. Return the single best email address only; ensure the email is one provided within the info and not an erroneous or dummy one. If absolutely no email exists, return nothing."""

app = FastAPI(title="Leads Generator API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_origin_regex=_allow_origin_regex(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    businessType: str = Field(default="barber")
    location: str = Field(default="Cambridge, MA")
    numLeads: int = Field(default=25, ge=1, le=1000)
    searchMode: Literal["qualified_no_website", "all_businesses"] = "all_businesses"
    noRealWebsiteOnly: bool = True

    includedType: Optional[str] = None
    strictTypeFiltering: Optional[bool] = None
    rankPreference: Optional[Literal["RELEVANCE", "DISTANCE"]] = None
    openNow: Optional[bool] = None
    minRating: float = Field(default=3.5, ge=0, le=5)
    maxUserReviews: Optional[int] = Field(default=300, ge=0, le=10000000)
    priceLevels: List[
        Literal[
            "PRICE_LEVEL_FREE",
            "PRICE_LEVEL_INEXPENSIVE",
            "PRICE_LEVEL_MODERATE",
            "PRICE_LEVEL_EXPENSIVE",
            "PRICE_LEVEL_VERY_EXPENSIVE",
        ]
    ] = Field(default_factory=list)
    languageCode: Optional[str] = None
    regionCode: Optional[str] = None
    includePureServiceAreaBusinesses: Optional[bool] = None
    includeFutureOpeningBusinesses: Optional[bool] = None
    pageSize: int = Field(default=20, ge=1, le=20)
    maxPages: Optional[int] = Field(default=None, ge=1, le=50)

    locationBias: Optional[Dict[str, Any]] = None
    locationRestriction: Optional[Dict[str, Any]] = None
    evOptions: Optional[Dict[str, Any]] = None
    routingParameters: Optional[Dict[str, Any]] = None
    searchAlongRouteParameters: Optional[Dict[str, Any]] = None

    @field_validator("businessType", "location")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Required")
        return value

    @field_validator("minRating")
    @classmethod
    def _rating_step(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return value
        return math.ceil(value * 2) / 2


class EmailEnrichmentRequest(BaseModel):
    rows: List[Dict[str, Any]]
    headers: List[str] = Field(default_factory=list)
    enrichmentMode: Literal["ai_decision", "local_only", "gpt_web_search", "legacy_scraper"] = "ai_decision"
    maxPagesPerBusiness: int = Field(default=100, ge=1, le=300)
    maxDepth: int = Field(default=5, ge=1, le=12)
    businessConcurrency: int = Field(default=2, ge=1, le=8)
    requestTimeoutSeconds: int = Field(default=8, ge=2, le=30)
    businessTimeoutSeconds: int = Field(default=180, ge=5, le=600)
    allowSubdomains: bool = False
    maxOpenAiCalls: Optional[int] = Field(default=None, ge=0, le=1000)
    useCache: bool = False
    storeResults: bool = True


class LeadUpdateRequest(BaseModel):
    ticked: Optional[bool] = None
    tickedAt: Optional[str] = None
    bestEmail: Optional[str] = None
    bestEmailType: Optional[str] = None
    bestEmailConfidence: Optional[str] = None
    bestEmailSourceUrl: Optional[str] = None
    bestEmailEvidence: Optional[str] = None
    contactName: Optional[str] = None
    contactTitle: Optional[str] = None
    allEmailsJson: Optional[Any] = None
    emailScrapeStatus: Optional[str] = None
    emailScrapeError: Optional[str] = None
    emailSelectionMethod: Optional[str] = None
    emailPagesFetched: Optional[int] = None
    emailCandidateCount: Optional[int] = None
    emailDebugJson: Optional[Any] = None


class OneLeadEnrichmentRequest(BaseModel):
    enrichmentMode: Literal["ai_decision", "local_only", "gpt_web_search"] = "ai_decision"
    maxPagesPerBusiness: int = Field(default=100, ge=1, le=300)
    maxDepth: int = Field(default=5, ge=1, le=12)
    requestTimeoutSeconds: int = Field(default=8, ge=2, le=30)
    businessTimeoutSeconds: int = Field(default=180, ge=5, le=600)
    maxOpenAiCalls: int = Field(default=1, ge=0, le=1)
    storeResults: bool = True


class OneLeadAuditRequest(BaseModel):
    enableVisualAudit: bool = True
    storeResults: bool = True


class SettingsRequest(BaseModel):
    settings: Dict[str, Any]


class ScheduleDayRequest(BaseModel):
    dayOfWeek: int = Field(ge=0, le=6)
    businessType: str
    location: str
    numLeads: int = Field(default=25, ge=1, le=1000)
    searchMode: Literal["qualified_no_website", "all_businesses"] = "all_businesses"
    minRating: float = Field(default=3.5, ge=0, le=5)
    maxUserReviews: int = Field(default=300, ge=0, le=10000000)
    enabled: bool = True


class ScheduleRequest(BaseModel):
    schedule: List[ScheduleDayRequest]


class DailyRunRequest(BaseModel):
    runDate: Optional[str] = None
    notify: bool = True


AI_EMAIL_DEBUG_FIELDS = [
    "emailDebugId",
    "emailSelectionMethod",
    "emailPagesFetched",
    "emailCandidateCount",
]


def _api_key() -> str:
    api_key = get_project_env("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail=f"GOOGLE_MAPS_API_KEY is not set in {ENV_PATH}.")
    return api_key


def _search_params(payload: SearchRequest) -> Dict[str, Any]:
    return {
        "pageSize": payload.pageSize,
        "includedType": payload.includedType,
        "strictTypeFiltering": payload.strictTypeFiltering,
        "rankPreference": payload.rankPreference,
        "openNow": payload.openNow,
        "minRating": payload.minRating,
        "priceLevels": payload.priceLevels,
        "languageCode": payload.languageCode,
        "regionCode": payload.regionCode,
        "includePureServiceAreaBusinesses": payload.includePureServiceAreaBusinesses,
        "includeFutureOpeningBusinesses": payload.includeFutureOpeningBusinesses,
        "locationBias": payload.locationBias,
        "locationRestriction": payload.locationRestriction,
        "evOptions": payload.evOptions,
        "routingParameters": payload.routingParameters,
        "searchAlongRouteParameters": payload.searchAlongRouteParameters,
    }


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _matches_search_filters(place: Dict[str, Any], payload: SearchRequest) -> bool:
    if payload.minRating is not None and _safe_float(place.get("rating")) < payload.minRating:
        return False
    if payload.maxUserReviews is not None and _safe_int(place.get("userRatingCount")) > payload.maxUserReviews:
        return False
    return True


def _sort_by_low_reviews(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            _safe_int(row.get("userRatingCount")),
            -_safe_float(row.get("rating")),
            str(row.get("name") or "").lower(),
        ),
    )


def _max_pages(payload: SearchRequest) -> int:
    if payload.maxPages:
        return payload.maxPages
    minimum_pages = math.ceil(payload.numLeads / payload.pageSize)
    multiplier = 3 if payload.searchMode == "qualified_no_website" or payload.maxUserReviews is not None else 1
    return min(50, max(1, minimum_pages * multiplier))


def _split_website(value: Optional[str]) -> Dict[str, str]:
    classified = classify_website_uri(value)
    kind, _, url = classified.partition(",")
    display_url = valid_owned_website(url) if kind == "website" else url
    has_external = kind.startswith("external_platform")
    return {
        "websiteKind": kind,
        "websiteUrl": display_url if not has_external else "",
        "websiteDisplay": classified,
        "socialPlatform": kind if kind not in {"none", "website"} and not has_external else "",
        "socialUrl": url if kind not in {"none", "website"} and not has_external else "",
        "hasExternalWebsite": "true" if has_external else "false",
        "externalWebsiteUrl": url if has_external else "",
    }


def _lead_row_for_place(place: Dict[str, Any]) -> List[str]:
    return [
        f"{place.get('score', 0):.2f}",
        (place.get("displayName") or {}).get("text", ""),
        place.get("nationalPhoneNumber", ""),
        place.get("formattedAddress", ""),
        classify_website_uri(place.get("websiteUri")),
        serialize_value(place.get("rating")),
        serialize_value(place.get("userRatingCount")),
        serialize_value(place.get("googleMapsUri")),
        serialize_value(place.get("photos")),
        serialize_value(place.get("primaryType")),
        serialize_value(place.get("regularOpeningHours")),
    ]


def _detail_row_for_place(place: Dict[str, Any]) -> List[str]:
    return [
        (place.get("displayName") or {}).get("text", ""),
        place.get("nationalPhoneNumber", ""),
        place.get("formattedAddress", ""),
        classify_website_uri(place.get("websiteUri")),
        serialize_value(place.get("rating")),
        serialize_value(place.get("userRatingCount")),
        serialize_value(place.get("googleMapsUri")),
        serialize_value(place.get("accessibilityOptions")),
        serialize_value(place.get("addressComponents")),
        serialize_value(place.get("addressDescriptor")),
        serialize_value(place.get("adrFormatAddress")),
        serialize_value(place.get("businessStatus")),
        serialize_value(place.get("containingPlaces")),
        serialize_value(place.get("googleMapsLinks")),
        serialize_value(place.get("iconBackgroundColor")),
        serialize_value(place.get("iconMaskBaseUri")),
        serialize_value(place.get("location")),
        serialize_value(place.get("photos")),
        serialize_value(place.get("plusCode")),
        serialize_value(place.get("postalAddress")),
        serialize_value(place.get("primaryType")),
        serialize_value(place.get("primaryTypeDisplayName")),
        serialize_value(place.get("pureServiceAreaBusiness")),
        serialize_value(place.get("shortFormattedAddress")),
        serialize_value(place.get("subDestinations")),
        serialize_value(place.get("types")),
        serialize_value(place.get("utcOffsetMinutes")),
        serialize_value(place.get("viewport")),
        serialize_value(place.get("currentOpeningHours")),
        serialize_value(place.get("currentSecondaryOpeningHours")),
        serialize_value(place.get("internationalPhoneNumber")),
        serialize_value(place.get("priceLevel")),
        serialize_value(place.get("priceRange")),
        serialize_value(place.get("regularOpeningHours")),
        serialize_value(place.get("regularSecondaryOpeningHours")),
        serialize_value(place.get("name")),
        serialize_value(place.get("attributions")),
        serialize_value(place.get("_place_id") or extract_place_id(place)),
    ]


def _result_for_place(place: Dict[str, Any]) -> Dict[str, Any]:
    row = _lead_row_for_place(place)
    result = dict(zip(LEADS_FIELDS, row))
    result.update(
        {
            "placeId": place.get("_place_id") or extract_place_id(place),
            "rawWebsiteUri": place.get("websiteUri") or "",
            "businessStatus": serialize_value(place.get("businessStatus")),
            "primaryTypeDisplayName": serialize_value(place.get("primaryTypeDisplayName")),
            "shortFormattedAddress": serialize_value(place.get("shortFormattedAddress")),
            "internationalPhoneNumber": serialize_value(place.get("internationalPhoneNumber")),
            "priceLevel": serialize_value(place.get("priceLevel")),
            "priceRange": serialize_value(place.get("priceRange")),
            "types": serialize_value(place.get("types")),
        }
    )
    result.update(_split_website(place.get("websiteUri")))
    return result


def _detail_result_for_place(place: Dict[str, Any]) -> Dict[str, Any]:
    row = _detail_row_for_place(place)
    result = dict(zip(OUTPUT_FIELDS, row))
    result["rawWebsiteUri"] = place.get("websiteUri") or ""
    result.update(_split_website(place.get("websiteUri")))
    return result


def _execute_search(payload: SearchRequest) -> Dict[str, Any]:
    query = f"{payload.businessType} in {payload.location}"
    qualified_mode = payload.searchMode == "qualified_no_website"
    include_fn = is_excluded_website if qualified_mode else (lambda _url: True)
    base_max_pages = _max_pages(payload)
    progress = hosted_store.search_progress(query) if hosted_store.configured() else {}
    previous_deepest_page = int(progress.get("deepestHistoricalPage") or 0)
    previous_exhausted = bool(progress.get("exhausted")) if progress else False
    target_max_pages = base_max_pages
    if previous_deepest_page and not previous_exhausted:
        target_max_pages = min(50, max(base_max_pages, previous_deepest_page + base_max_pages))
    resume_from_page = previous_deepest_page + 1 if previous_deepest_page and not previous_exhausted else 1

    try:
        leads, details, meta = build_results(
            _api_key(),
            query,
            payload.numLeads,
            target_max_pages,
            set(),
            set(),
            search_params=_search_params(payload),
            candidate_filter_fn=lambda place: _matches_search_filters(place, payload),
            is_excluded_website_fn=include_fn,
            score_place_fn=score_place,
            extract_place_id_fn=extract_place_id,
            existing_place_ids_fn=hosted_store.find_existing_place_ids if hosted_store.configured() else None,
        )
    except PlacesApiError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"Google Places API error: {exc.message}",
        ) from exc

    result_builder = _result_for_place if qualified_mode else _detail_result_for_place
    results = _sort_by_low_reviews([result_builder(place) for place in leads])
    headers = (
        [
            *LEADS_FIELDS,
            "websiteKind",
            "websiteUrl",
            "socialPlatform",
            "socialUrl",
            "hasExternalWebsite",
            "externalWebsiteUrl",
            "placeId",
            "rawWebsiteUri",
            "businessStatus",
            "primaryTypeDisplayName",
            "shortFormattedAddress",
            "internationalPhoneNumber",
            "priceLevel",
            "priceRange",
            "types",
        ]
        if qualified_mode
        else [
            *OUTPUT_FIELDS,
            "rawWebsiteUri",
            "websiteKind",
            "websiteUrl",
            "socialPlatform",
            "socialUrl",
            "hasExternalWebsite",
            "externalWebsiteUrl",
        ]
    )
    conn = cache_module.init_cache(os.getenv("LEADS_CACHE_PATH", "leads_cache.sqlite3"))
    try:
        local_run_id = cache_module.store_search_results(
            conn,
            query,
            payload.searchMode,
            payload.model_dump(),
            headers,
            results,
        )
    finally:
        conn.close()

    return {
        "query": query,
        "requested": payload.model_dump(),
        "headers": headers,
        "results": results,
        "detailsColumns": OUTPUT_FIELDS,
        "meta": {
            **meta,
            "detailsReturned": len(details),
            "resultsReturned": len(results),
            "maxPagesUsed": target_max_pages,
            "baseMaxPages": base_max_pages,
            "targetMaxPages": target_max_pages,
            "previousDeepestPage": previous_deepest_page,
            "resumeFromPage": resume_from_page,
            "deepestPageReached": int(meta.get("pages_fetched") or 0),
            "deepestHistoricalPage": max(previous_deepest_page, int(meta.get("pages_fetched") or 0)),
            "duplicatesRemoved": int(meta.get("duplicates_removed") or 0),
            "pageResumeSupported": False,
            "pageResumeNote": "Google Places page tokens cannot be resumed across runs. Earlier pages are re-queried and previously stored businesses are removed before storage and display.",
            "storedRunId": local_run_id,
        },
    }


def _hosted_payload_for_result(search_data: Dict[str, Any], run_date: str) -> Dict[str, Any]:
    requested = search_data.get("requested") or {}
    query = str(search_data.get("query") or "")
    business_type = str(requested.get("businessType") or "")
    location = str(requested.get("location") or "")
    run = hosted_store.create_search_run(
        run_date=run_date,
        query=query,
        business_type=business_type,
        location=location,
        params=requested,
        meta=search_data.get("meta") or {},
    )
    run_id = run.get("id")
    rows = [
        hosted_store.lead_payload(
            row,
            lead_date=run_date,
            run_id=run_id,
            business_type=business_type,
            location=location,
            query=query,
        )
        for row in search_data.get("results", [])
    ]
    stored = hosted_store.upsert_leads(rows)
    meta = dict(search_data.get("meta") or {})
    meta["storedCount"] = len(stored)
    if run_id:
        run = hosted_store.update_search_run(run_id, {"meta": meta})
    return {"run": run, "stored": stored, "runSummary": hosted_store.search_run_summary(run)}


def _today_est() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _date_string(value: Optional[str] = None) -> str:
    return value or _today_est().isoformat()


def _hosted_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


def _audit_settings(enable_visual_audit: bool) -> Any:
    from .website_auditor.config import Settings as AuditSettings, load_settings as load_audit_settings

    base = load_audit_settings()
    api_key = get_project_env("OPENAI_API_KEY").strip() or base.openai_api_key
    visual_model = get_project_env("OPENAI_VISUAL_MODEL", base.openai_visual_model).strip() or base.openai_visual_model
    return AuditSettings(
        **{
            **base.__dict__,
            "enable_llm_visual_audit": bool(enable_visual_audit and api_key),
            "openai_api_key": api_key,
            "openai_visual_model": visual_model,
        }
    )


def _audit_input_from_app_row(row: Dict[str, Any]) -> Any:
    from .website_auditor.models import LeadInput as AuditLeadInput

    return AuditLeadInput(
        business_name=str(row.get("name") or ""),
        business_category=str(row.get("businessType") or row.get("searchQuery") or ""),
        address=str(row.get("address") or ""),
        phone=str(row.get("phone") or ""),
        website=str(row.get("websiteUrl") or row.get("externalWebsiteUrl") or row.get("rawWebsiteUri") or ""),
        google_rating=_safe_float(row.get("rating")) or None,
        review_count=_safe_int(row.get("userRatingCount")) or None,
        google_maps_url=str(row.get("googleMapsUri") or ""),
        email=str(row.get("bestEmail") or ""),
        email_source=str(row.get("bestEmailSourceUrl") or ""),
        email_contact_type=str(row.get("bestEmailType") or ""),
        email_contact_name=str(row.get("contactName") or ""),
        email_contact_title=str(row.get("contactTitle") or ""),
        email_recent_activity_signal=str(row.get("emailRecentActivitySignal") or ""),
    )


def _audit_update_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "auditResult": result,
        "auditStatus": result.get("audit_status") or "",
        "auditWebsiteStatus": result.get("website_status") or "",
        "auditLeadQualityScore": int(result.get("lead_quality_score") or 0),
        "auditWebsiteOpportunityScore": int(result.get("website_opportunity_score") or 0),
        "auditOutreachPriority": result.get("outreach_priority") or "",
        "auditNextBestAction": result.get("next_best_action") or "",
        "auditRecommendedPitchType": result.get("recommended_pitch_type") or "",
        "auditRecommendedPitchAngle": result.get("recommended_pitch_angle") or "",
        "auditedAt": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/api/config-status")
def config_status() -> Dict[str, Any]:
    openai_key = get_project_env("OPENAI_API_KEY").strip()
    maps_key = get_project_env("GOOGLE_MAPS_API_KEY").strip()
    return {
        "envPath": str(ENV_PATH),
        "envFileExists": ENV_PATH.exists(),
        "openAiKeyLoaded": bool(openai_key),
        "openAiKeyPrefix": openai_key[:7] if openai_key else "",
        "openAiModel": get_project_env("OPENAI_MODEL", "gpt-5.5"),
        "googleMapsKeyLoaded": bool(maps_key),
        "hostedDb": hosted_store.status(),
    }


@app.post("/api/search")
def search(payload: SearchRequest) -> Dict[str, Any]:
    return _execute_search(payload)


@app.get("/api/app/bootstrap")
def app_bootstrap() -> Dict[str, Any]:
    db_status = hosted_store.status()
    settings = dict(hosted_store.DEFAULT_SETTINGS)
    schedule = hosted_store.DEFAULT_SCHEDULE
    latest_run: Dict[str, Any] = {}
    effective_search = {
        "today": hosted_store.effective_search_preview_for_date(_today_est()),
        "tomorrow": hosted_store.effective_search_preview_for_date(_today_est() + timedelta(days=1)),
    } if db_status["configured"] else {}
    if db_status["configured"]:
        try:
            settings = hosted_store.get_settings()
            schedule = hosted_store.get_schedule()
            latest_run = hosted_store.search_run_summary(hosted_store.latest_search_run(run_date=_today_est().isoformat()))
            effective_search = {
                "today": hosted_store.effective_search_preview_for_date(_today_est()),
                "tomorrow": hosted_store.effective_search_preview_for_date(_today_est() + timedelta(days=1)),
            }
        except HostedStoreError as exc:
            return {
                "hostedDb": db_status,
                "settings": settings,
                "schedule": schedule,
                "effectiveSearch": effective_search,
                "setupError": str(exc),
            }
    return {
        "hostedDb": db_status,
        "settings": settings,
        "schedule": schedule,
        "today": _today_est().isoformat(),
        "latestRun": latest_run,
        "effectiveSearch": effective_search,
    }


@app.get("/api/app/leads/today")
def app_today_leads() -> Dict[str, Any]:
    try:
        today = _today_est().isoformat()
        rows = hosted_store.list_leads(lead_date=today, limit=500)
        latest_run = hosted_store.latest_search_run(run_date=today)
        return {"date": today, "rows": rows, "runSummary": hosted_store.search_run_summary(latest_run)}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.get("/api/app/leads")
def app_all_leads(
    q: str = "",
    dateFrom: str = "",
    dateTo: str = "",
    ticked: str = "",
    hasEmail: str = "",
    minRating: str = "",
    maxReviews: str = "",
    limit: int = 500,
) -> Dict[str, Any]:
    try:
        rows = hosted_store.list_leads(
            limit=limit,
            q=q,
            date_from=dateFrom,
            date_to=dateTo,
            ticked=ticked,
            has_email=hasEmail,
            min_rating=minRating,
            max_reviews=maxReviews,
        )
        return {"rows": rows}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.patch("/api/app/leads/{lead_id}")
def app_update_lead(lead_id: str, payload: LeadUpdateRequest) -> Dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    try:
        row = hosted_store.update_lead(lead_id, updates)
        return {"row": row}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.get("/api/app/outreach")
def app_outreach_leads(limit: int = 500) -> Dict[str, Any]:
    try:
        return {"rows": hosted_store.list_outreach_leads(limit=limit)}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.post("/api/app/leads/{lead_id}/audit")
def app_audit_one_lead(lead_id: str, payload: OneLeadAuditRequest) -> Dict[str, Any]:
    try:
        from .website_auditor.main import audit_lead as run_website_audit
        from .website_auditor.models import model_to_dict as audit_model_to_dict

        row = hosted_store.get_lead(lead_id)
        audit_input = _audit_input_from_app_row(row)
        settings = _audit_settings(payload.enableVisualAudit)
        result = run_website_audit(audit_input, settings)
        result_data = audit_model_to_dict(result)
        updates = _audit_update_payload(result_data)
        stored_row = hosted_store.update_lead(lead_id, updates) if payload.storeResults else row
        return {"row": stored_row, "audit": result_data}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Website audit failed: {exc}") from exc


@app.get("/api/app/settings")
def app_get_settings() -> Dict[str, Any]:
    try:
        return {"settings": hosted_store.get_settings()}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.put("/api/app/settings")
def app_update_settings(payload: SettingsRequest) -> Dict[str, Any]:
    try:
        settings = hosted_store.update_settings(payload.settings)
        today = _today_est()
        return {
            "settings": settings,
            "effectiveSearch": {
                "today": hosted_store.effective_search_preview_for_date(today),
                "tomorrow": hosted_store.effective_search_preview_for_date(today + timedelta(days=1)),
            },
        }
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.get("/api/app/effective-search")
def app_effective_search(runDate: str = "") -> Dict[str, Any]:
    try:
        target_date = date.fromisoformat(runDate) if runDate else _today_est()
        return hosted_store.effective_search_preview_for_date(target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid runDate. Expected YYYY-MM-DD.") from exc
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.get("/api/app/schedule")
def app_get_schedule() -> Dict[str, Any]:
    try:
        return {"schedule": hosted_store.get_schedule()}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


@app.put("/api/app/schedule")
def app_update_schedule(payload: ScheduleRequest) -> Dict[str, Any]:
    try:
        return {"schedule": hosted_store.update_schedule([item.model_dump() for item in payload.schedule])}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


def _daily_payload_for(run_date: date) -> Optional[SearchRequest]:
    schedule = hosted_store.search_config_for_date(run_date)
    if not schedule.get("enabled", True):
        return None
    return SearchRequest(
        businessType=schedule.get("businessType") or "barber",
        location=schedule.get("location") or "Boston, MA",
        numLeads=int(schedule.get("numLeads") or 25),
        searchMode=schedule.get("searchMode") or "all_businesses",
        noRealWebsiteOnly=(schedule.get("searchMode") == "qualified_no_website"),
        minRating=float(schedule.get("minRating") if schedule.get("minRating") is not None else 3.5),
        maxUserReviews=int(schedule.get("maxUserReviews") if schedule.get("maxUserReviews") is not None else 300),
    )


def run_daily_lead_job(run_date_value: Optional[str] = None, notify: bool = True) -> Dict[str, Any]:
    if not hosted_store.configured():
        raise HostedStoreError("Supabase is not configured. Daily automation needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")
    run_date = date.fromisoformat(run_date_value) if run_date_value else _today_est()
    payload = _daily_payload_for(run_date)
    if payload is None:
        return {
            "date": run_date.isoformat(),
            "query": "",
            "requested": {},
            "meta": {"skipped": True, "reason": "Calendar day is disabled"},
            "storedCount": 0,
            "rows": [],
            "notification": {"sent": False, "reason": "Calendar day is disabled"},
        }
    search_data = _execute_search(payload)
    stored = _hosted_payload_for_result(search_data, run_date.isoformat())
    settings = hosted_store.get_settings()

    notification = {"sent": False, "reason": "Disabled"}
    if notify and settings.get("emailNotificationsEnabled", True):
        try:
            notification = send_daily_ready_email(
                str(settings.get("notificationEmail") or "ibrahim.m7004@gmail.com"),
                {
                    "date": run_date.isoformat(),
                    "query": search_data.get("query"),
                    "stored": len(stored["stored"]),
                    "apiCalls": (search_data.get("meta") or {}).get("requests_made", 0),
                },
            )
        except Exception as exc:
            notification = {"sent": False, "reason": str(exc)}

    return {
        "date": run_date.isoformat(),
        "query": search_data.get("query"),
        "requested": search_data.get("requested"),
        "meta": search_data.get("meta"),
        "storedCount": len(stored["stored"]),
        "rows": stored["stored"],
        "runSummary": stored.get("runSummary") or {},
        "notification": notification,
    }


@app.post("/api/app/run-daily")
def app_run_daily(payload: DailyRunRequest) -> Dict[str, Any]:
    try:
        return run_daily_lead_job(payload.runDate, payload.notify)
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


def _has_scrape_source(row: Dict[str, Any]) -> bool:
    return bool(_row_website_url(row))


def _merge_email_result(row: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(row)
    for field in EMAIL_FIELDS:
        merged[field] = result.get(field, "")
    return merged


def _row_website_url(row: Dict[str, Any]) -> str:
    for key in ("websiteUrl", "rawWebsiteUri", "websiteUri"):
        url = valid_owned_website(str(row.get(key) or ""))
        if url:
            return url
    return ""


def _confidence_from_local_score(score: int) -> str:
    if score >= 100:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _evidence_text_for_candidate(item: EmailEvidenceSet) -> str:
    parts = [
        f"Source kind: {item.source_kind}",
        f"Page title: {item.page_title}",
        f"Page header: {item.page_header}",
        f"Section/header near email: {item.section_header}",
        f"Matched line: {item.matched_line}",
    ]
    if item.nearby_lines:
        parts.append("Nearby lines: " + " / ".join(item.nearby_lines[:5]))
    return " | ".join(part for part in parts if part and not part.endswith(": "))


def _people_signals_from_report(report: CrawlReport) -> List[str]:
    keywords = (
        "owner",
        "founder",
        "co-founder",
        "ceo",
        "president",
        "principal",
        "partner",
        "operator",
        "manager",
        "director",
    )
    signals: List[str] = []
    for item in report.evidence_sets:
        candidates = [item.section_header, item.matched_line, *item.nearby_lines]
        for text in candidates:
            compacted = " ".join(str(text or "").split())
            if not compacted:
                continue
            if any(keyword in compacted.lower() for keyword in keywords) and compacted not in signals:
                signals.append(compacted[:420])
            if len(signals) >= 12:
                return signals
    return signals


def _scrape_result_from_report(report: CrawlReport) -> AiScrapeResult:
    by_email: Dict[str, EmailEvidence] = {}
    for item in report.evidence_sets:
        evidence = _evidence_text_for_candidate(item)
        score, local_type = classify_and_score(
            item.email,
            [evidence, item.section_header, item.matched_line, *item.nearby_lines],
            item.source_url,
            report.host,
        )
        current = by_email.get(item.email)
        if not current or score > current.score:
            by_email[item.email] = EmailEvidence(
                email=item.email,
                source_url=item.source_url,
                page_title=item.page_title,
                evidence=[evidence],
                score=score,
                local_type=local_type,
            )
        elif current and evidence not in current.evidence and len(current.evidence) < 8:
            current.evidence.append(evidence)

    emails = sorted(by_email.values(), key=lambda item: item.score, reverse=True)
    has_fetch_errors = any(page.status == "error" for page in report.pages)
    if emails:
        status = "found"
    elif report.stopped_reason == "invalid website URL":
        status = "skipped"
    elif has_fetch_errors and not report.pages:
        status = "error"
    else:
        status = "not_found"
    error_parts = []
    if report.stopped_reason != "completed":
        error_parts.append(report.stopped_reason)
    error_parts.extend(page.error for page in report.pages if page.status == "error" and page.error)
    return AiScrapeResult(
        website_url=report.root_url,
        pages_fetched=len([page for page in report.pages if page.status == "fetched"]),
        emails=emails,
        people_signals=_people_signals_from_report(report),
        status=status,
        error="; ".join(error_parts[:4]),
    )


def _candidate_payloads(scrape: AiScrapeResult) -> List[Dict[str, Any]]:
    return [
        {
            "email": email.email,
            "sourceUrl": email.source_url,
            "pageTitle": email.page_title,
            "evidence": email.evidence,
            "localScore": email.score,
            "localType": email.local_type,
        }
        for email in scrape.emails
    ]


def _report_payload(report: Optional[CrawlReport]) -> Dict[str, Any]:
    if not report:
        return {
            "rootUrl": "",
            "host": "",
            "stoppedReason": "",
            "durationSeconds": 0,
            "uniqueEmails": [],
            "pages": [],
            "skippedExternalSample": [],
            "skippedAssetsSample": [],
            "rawEvidenceSets": [],
        }
    return {
        "rootUrl": report.root_url,
        "host": report.host,
        "stoppedReason": report.stopped_reason,
        "durationSeconds": report.duration_seconds,
        "uniqueEmails": report.unique_emails,
        "pages": [
            {
                "url": page.url,
                "depth": page.depth,
                "status": page.status,
                "httpStatus": page.http_status,
                "title": page.title,
                "pageHeader": page.page_header,
                "linksFound": page.links_found,
                "internalLinksQueued": page.internal_links_queued,
                "emailsFound": page.emails_found,
                "error": page.error,
            }
            for page in report.pages
        ],
        "skippedExternalSample": sorted(report.skipped_external)[:50],
        "skippedAssetsSample": sorted(report.skipped_assets)[:50],
        "rawEvidenceSets": [
            {
                "email": item.email,
                "sourceUrl": item.source_url,
                "sourceKind": item.source_kind,
                "pageTitle": item.page_title,
                "pageHeader": item.page_header,
                "sectionHeader": item.section_header,
                "matchedLine": item.matched_line,
                "nearbyLines": item.nearby_lines,
            }
            for item in report.evidence_sets
        ],
    }


def _ai_detail_payload(
    row: Dict[str, Any],
    scrape: AiScrapeResult,
    llm_input: str,
    llm_raw_response: str,
    usage: Dict[str, Any],
    error: str,
    report: Optional[CrawlReport] = None,
) -> Dict[str, Any]:
    return {
        "business": {
            "name": row.get("name") or "",
            "address": row.get("address") or row.get("formattedAddress") or "",
            "phone": row.get("phone") or row.get("nationalPhoneNumber") or "",
            "website": scrape.website_url or _row_website_url(row),
            "googleMapsUri": row.get("googleMapsUri") or "",
            "rating": row.get("rating") or "",
            "userRatingCount": row.get("userRatingCount") or "",
        },
        "scrape": {
            "status": scrape.status,
            "error": scrape.error,
            "pagesFetched": scrape.pages_fetched,
            "peopleSignals": scrape.people_signals,
            "emailCandidates": _candidate_payloads(scrape),
            "crawlReport": _report_payload(report),
        },
        "ai": {
            "model": AI_EMAIL_MODEL,
            "input": llm_input,
            "rawResponse": llm_raw_response,
            "usage": usage,
            "error": error,
        },
    }


def _result_from_ai_scrape(
    row: Dict[str, Any],
    scrape: AiScrapeResult,
    best_email: str,
    local_best_email: str,
    llm_used: bool,
    llm_raw_response: str,
    usage: Dict[str, Any],
    error: str,
    debug_id: str,
    stored_result_id: str = "",
) -> Dict[str, Any]:
    matched = next((email for email in scrape.emails if email.email == best_email), None)
    status = "found" if best_email else scrape.status
    if scrape.status == "error" and not best_email:
        status = "error"
    selection_method = "ai" if llm_used and best_email else "local"
    if not scrape.emails:
        selection_method = "none"
    if llm_used and not best_email and local_best_email:
        selection_method = "local_fallback"

    result = {
        "bestEmail": best_email,
        "bestEmailType": matched.local_type if matched else "unknown",
        "bestEmailConfidence": _confidence_from_local_score(matched.score) if matched else "low",
        "bestEmailSourceUrl": matched.source_url if matched else "",
        "bestEmailEvidence": " | ".join((matched.evidence if matched else [])[:3]),
        "contactName": "",
        "contactTitle": "",
        "allEmailsJson": json.dumps(_candidate_payloads(scrape), separators=(",", ":"), ensure_ascii=True),
        "emailScrapeStatus": status,
        "emailScrapeError": error or scrape.error,
        "emailDebugId": debug_id,
        "emailSelectionMethod": selection_method,
        "emailPagesFetched": scrape.pages_fetched,
        "emailCandidateCount": len(scrape.emails),
        "emailStoredResultId": stored_result_id,
    }
    return result


def _lead_from_row_for_ai(row: Dict[str, Any], website_url: str) -> Dict[str, Any]:
    return {
        "id": row.get("id") or row.get("sourceRowId") or "",
        "run_id": row.get("runId") or row.get("run_id") or "",
        "place_id": row.get("placeId") or "",
        "name": row.get("name") or "",
        "query": row.get("query") or "",
        "address": row.get("address") or row.get("formattedAddress") or row.get("shortFormattedAddress") or "",
        "rating": row.get("rating") or "",
        "user_rating_count": row.get("userRatingCount") or "",
        "website_url": website_url,
    }


def _store_ai_result_in_db(
    row: Dict[str, Any],
    scrape: AiScrapeResult,
    best_email: str,
    local_best: str,
    llm_used: bool,
    llm_raw_response: str,
    usage: Dict[str, Any],
    status: str,
    error: str,
) -> str:
    db_path = os.getenv("LEADS_CACHE_PATH", "leads_cache.sqlite3")
    lead = _lead_from_row_for_ai(row, scrape.website_url)
    result_id = store_ai_email_result(
        db_path,
        lead,
        scrape,
        best_email,
        local_best,
        llm_used,
        llm_raw_response,
        usage,
        status,
        error,
    )
    return str(result_id)


def _merge_ai_email_result(row: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(row)
    for field in [*EMAIL_FIELDS, *AI_EMAIL_DEBUG_FIELDS, "emailStoredResultId"]:
        merged[field] = result.get(field, "")
    return merged


def _extract_openai_output_text(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    parts: List[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _extract_openai_sources(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    sources = data.get("sources")
    if isinstance(sources, list):
        return sources
    found: List[Dict[str, Any]] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            annotations = content.get("annotations") or []
            for annotation in annotations:
                if isinstance(annotation, dict) and annotation.get("url"):
                    found.append(annotation)
    return found


def _count_openai_web_search_calls(data: Dict[str, Any]) -> int:
    count = 0
    for item in data.get("output", []) or []:
        if item.get("type") == "web_search_call":
            count += 1
    return count


def _row_location_text(row: Dict[str, Any]) -> str:
    return " ".join(
        str(
            row.get("address")
            or row.get("formattedAddress")
            or row.get("shortFormattedAddress")
            or row.get("location")
            or ""
        ).split()
    )


def _business_search_label(row: Dict[str, Any]) -> str:
    name = " ".join(str(row.get("name") or row.get("displayName") or "").split())
    location = _row_location_text(row)
    if name and location:
        return f"{name} in {location}"
    return name or location or "this business"


def _gpt_web_search_prompt(row: Dict[str, Any], website_url: str) -> str:
    if website_url:
        website_instruction = (
            f"Use the verified private website {website_url} and all its webpages, "
            "as well as other digital info you may find including socials, directories, and public webpages. "
        )
    else:
        website_instruction = (
            "Use all digital info you may find, including public webpages, directories, socials, and business profiles. "
        )
    return WEB_SEARCH_PROMPT_TEMPLATE.format(
        business=_business_search_label(row),
        website_instruction=website_instruction,
    )


def _call_gpt_web_search(row: Dict[str, Any], website_url: str, api_key: str) -> tuple[str, str, Dict[str, Any], List[Dict[str, Any]], int]:
    prompt = _gpt_web_search_prompt(row, website_url)
    model = get_project_env("OPENAI_MODEL", "gpt-5.5")
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        input=prompt,
    )
    data = response.model_dump() if hasattr(response, "model_dump") else {}
    output_text = _extract_openai_output_text(data)
    if not output_text and hasattr(response, "output_text"):
        output_text = str(response.output_text or "").strip()
    parsed_email = _parse_best_email(output_text)
    return parsed_email, output_text, data.get("usage", {}), _extract_openai_sources(data), _count_openai_web_search_calls(data)


def _parse_best_email(value: str) -> str:
    if not value:
        return ""
    for match in re.finditer(r"(?<![A-Z0-9_%+-])([A-Z0-9._%+-]{1,64}@[A-Z0-9.-]+\.[A-Z]{2,24})(?![A-Z0-9_%+-])", value, re.IGNORECASE):
        email = match.group(1).strip().strip(".,;:()[]{}<>\"'")
        cleaned = clean_email(email)
        if cleaned:
            return cleaned
    return ""


def _enrich_emails_with_ai(payload: EmailEnrichmentRequest) -> Dict[str, Any]:
    started = time.monotonic()
    rows = [dict(row) for row in payload.rows]
    headers = list(dict.fromkeys([*payload.headers, *EMAIL_FIELDS, *AI_EMAIL_DEBUG_FIELDS]))
    api_key = get_project_env("OPENAI_API_KEY").strip()
    use_gpt = payload.enrichmentMode == "ai_decision"
    max_openai_calls = payload.maxOpenAiCalls if payload.maxOpenAiCalls is not None else len(rows)
    debug_details: Dict[str, Any] = {}
    results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
    website_jobs: List[tuple[int, Dict[str, Any], str]] = []
    businesses_without_urls = 0
    errors = 0

    for index, row in enumerate(rows):
        website_url = _row_website_url(row)
        if not website_url:
            businesses_without_urls += 1
            scrape = AiScrapeResult("", 0, [], [], "skipped", "No owned website URL")
            debug_id = f"row-{index}"
            debug_details[debug_id] = _ai_detail_payload(row, scrape, "", "", {}, "")
            result = _result_from_ai_scrape(row, scrape, "", "", False, "", {}, "", debug_id)
            results[index] = _merge_ai_email_result(row, result)
        else:
            website_jobs.append((index, row, website_url))

    def scrape_one(item: tuple[int, Dict[str, Any], str]) -> tuple[int, Dict[str, Any], AiScrapeResult, Optional[CrawlReport]]:
        index, row, website_url = item
        try:
            report = crawl_site(
                website_url,
                max_pages=payload.maxPagesPerBusiness,
                max_depth=payload.maxDepth,
                timeout=payload.requestTimeoutSeconds,
                max_seconds=payload.businessTimeoutSeconds,
                allow_subdomains=payload.allowSubdomains,
            )
            scrape = _scrape_result_from_report(report)
        except Exception as exc:
            report = None
            scrape = AiScrapeResult(website_url, 0, [], [], "error", str(exc))
        return index, row, scrape, report

    scraped_items: List[tuple[int, Dict[str, Any], AiScrapeResult, Optional[CrawlReport]]] = []
    with ThreadPoolExecutor(max_workers=payload.businessConcurrency) as executor:
        future_map = {executor.submit(scrape_one, item): item for item in website_jobs}
        for future in as_completed(future_map):
            scraped_items.append(future.result())

    openai_calls = 0
    pages_fetched = 0
    businesses_enriched = 0
    stored_results = 0

    for index, row, scrape, report in sorted(scraped_items, key=lambda item: item[0]):
        pages_fetched += scrape.pages_fetched
        local_best = choose_local_best(scrape)
        best_email = local_best
        llm_used = False
        llm_raw = ""
        usage: Dict[str, Any] = {}
        error = scrape.error
        llm_input = build_email_decision_prompt(_lead_from_row_for_ai(row, scrape.website_url), scrape) if scrape.emails else ""

        if scrape.status == "error":
            errors += 1
        if use_gpt and scrape.emails:
            if not api_key:
                error = (error + "; " if error else "") + f"OPENAI_API_KEY is not set in {ENV_PATH}; used local best"
            elif openai_calls >= max_openai_calls:
                error = (error + "; " if error else "") + "Max OpenAI calls reached; used local best"
            else:
                try:
                    chosen, llm_raw, usage = choose_best_email_with_gpt(
                        _lead_from_row_for_ai(row, scrape.website_url),
                        scrape,
                        api_key,
                    )
                    openai_calls += 1
                    llm_used = True
                    if chosen:
                        best_email = chosen
                    elif local_best:
                        error = (error + "; " if error else "") + "GPT returned no valid candidate; used local best"
                except Exception as exc:
                    openai_calls += 1
                    llm_used = True
                    errors += 1
                    error = (error + "; " if error else "") + f"OpenAI API error: {exc}"

        if best_email:
            businesses_enriched += 1

        debug_id = f"row-{index}"
        debug_details[debug_id] = _ai_detail_payload(row, scrape, llm_input, llm_raw, usage, error, report)
        result = _result_from_ai_scrape(
            row,
            scrape,
            best_email,
            local_best,
            llm_used,
            llm_raw,
            usage,
            error,
            debug_id,
        )
        if payload.storeResults:
            try:
                stored_id = _store_ai_result_in_db(
                    row,
                    scrape,
                    best_email,
                    local_best,
                    llm_used,
                    llm_raw,
                    usage,
                    result["emailScrapeStatus"],
                    error,
                )
                if stored_id:
                    stored_results += 1
                    result["emailStoredResultId"] = stored_id
            except Exception as exc:
                result["emailScrapeError"] = (result.get("emailScrapeError") + "; " if result.get("emailScrapeError") else "") + f"DB store error: {exc}"
        results[index] = _merge_ai_email_result(row, result)

    final_rows = [
        row if row is not None else _merge_ai_email_result(rows[index], _result_from_ai_scrape(rows[index], AiScrapeResult("", 0, [], [], "error", "Unknown enrichment failure"), "", "", False, "", {}, "Unknown enrichment failure", f"row-{index}"))
        for index, row in enumerate(results)
    ]

    return {
        "headers": headers,
        "results": final_rows,
        "details": debug_details,
        "meta": {
            "enrichmentMode": payload.enrichmentMode,
            "businessesAttempted": len(rows) - businesses_without_urls,
            "businessesEnriched": businesses_enriched,
            "businessesCached": 0,
            "businessesWithoutUrls": businesses_without_urls,
            "externalWebsiteSkipped": 0,
            "pagesFetched": pages_fetched,
            "socialPagesFetched": 0,
            "emailCandidatesFound": sum(len(detail["scrape"]["emailCandidates"]) for detail in debug_details.values()),
            "openAiCalls": openai_calls,
            "storedResults": stored_results,
            "errors": errors,
            "durationSeconds": round(time.monotonic() - started, 2),
        },
    }


def _enrich_emails_with_gpt_web_search(payload: EmailEnrichmentRequest) -> Dict[str, Any]:
    started = time.monotonic()
    rows = [dict(row) for row in payload.rows]
    headers = list(dict.fromkeys([*payload.headers, *EMAIL_FIELDS, *AI_EMAIL_DEBUG_FIELDS]))
    api_key = get_project_env("OPENAI_API_KEY").strip()
    max_openai_calls = payload.maxOpenAiCalls if payload.maxOpenAiCalls is not None else len(rows)
    results: List[Dict[str, Any]] = []
    debug_details: Dict[str, Any] = {}
    businesses_without_urls = 0
    businesses_enriched = 0
    openai_calls = 0
    web_search_calls = 0
    stored_results = 0
    errors = 0

    for index, row in enumerate(rows):
        debug_id = f"row-{index}"
        website_url = _row_website_url(row)
        has_business_signal = bool(str(row.get("name") or row.get("displayName") or "").strip() or _row_location_text(row))
        best_email = ""
        raw_response = ""
        usage: Dict[str, Any] = {}
        sources: List[Dict[str, Any]] = []
        error = ""
        selection_method = "gpt_web_search"
        prompt = _gpt_web_search_prompt(row, website_url)

        if not has_business_signal:
            businesses_without_urls += 1
            selection_method = "none"
            error = "No business name or location available for web search"
        elif not api_key:
            errors += 1
            selection_method = "none"
            error = f"OPENAI_API_KEY is not set in {ENV_PATH}"
        elif openai_calls >= max_openai_calls:
            selection_method = "none"
            error = "Max OpenAI calls reached"
        else:
            try:
                best_email, raw_response, usage, sources, web_calls = _call_gpt_web_search(row, website_url, api_key)
                openai_calls += 1
                web_search_calls += web_calls or 1
            except Exception as exc:
                openai_calls += 1
                errors += 1
                selection_method = "error"
                error = f"OpenAI web search error: {exc}"

        if best_email:
            businesses_enriched += 1
        source_url = ""
        if sources:
            first_source = sources[0]
            if isinstance(first_source, dict):
                source_url = str(first_source.get("url") or "")

        scrape_for_store = AiScrapeResult(
            website_url=website_url,
            pages_fetched=0,
            emails=[
                EmailEvidence(
                    email=best_email,
                    source_url=source_url,
                    page_title="GPT Web Search",
                    evidence=[raw_response],
                    score=55,
                    local_type="unknown",
                )
            ]
            if best_email
            else [],
            people_signals=[],
            status="found" if best_email else ("error" if error else "not_found"),
            error=error,
        )
        stored_result_id = ""
        if payload.storeResults:
            try:
                stored_result_id = _store_ai_result_in_db(
                    row,
                    scrape_for_store,
                    best_email,
                    best_email,
                    bool(openai_calls),
                    raw_response,
                    usage,
                    scrape_for_store.status,
                    error,
                )
                if stored_result_id:
                    stored_results += 1
            except Exception as exc:
                error = (error + "; " if error else "") + f"DB store error: {exc}"

        result = {
            "bestEmail": best_email,
            "bestEmailType": "unknown" if best_email else "unknown",
            "bestEmailConfidence": "medium" if best_email else "low",
            "bestEmailSourceUrl": source_url,
            "bestEmailEvidence": raw_response,
            "contactName": "",
            "contactTitle": "",
            "allEmailsJson": json.dumps(
                [{"email": best_email, "source": "gpt_web_search", "rawResponse": raw_response}] if best_email else [],
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            "emailScrapeStatus": "found" if best_email else ("error" if error and selection_method == "error" else "not_found"),
            "emailScrapeError": error,
            "emailDebugId": debug_id,
            "emailSelectionMethod": selection_method,
            "emailPagesFetched": 0,
            "emailCandidateCount": 1 if best_email else 0,
            "emailStoredResultId": stored_result_id,
        }
        merged = _merge_ai_email_result(row, result)
        results.append(merged)

        debug_details[debug_id] = {
            "business": {
                "name": row.get("name") or "",
                "address": row.get("address") or row.get("formattedAddress") or "",
                "phone": row.get("phone") or row.get("nationalPhoneNumber") or "",
                "website": website_url,
                "googleMapsUri": row.get("googleMapsUri") or "",
                "rating": row.get("rating") or "",
                "userRatingCount": row.get("userRatingCount") or "",
            },
            "scrape": {
                "status": result["emailScrapeStatus"],
                "error": error,
                "pagesFetched": 0,
                "peopleSignals": [],
                "emailCandidates": (
                    [
                        {
                            "email": best_email,
                            "sourceUrl": "",
                            "pageTitle": "GPT Web Search",
                            "evidence": [raw_response],
                            "localScore": 0,
                            "localType": "unknown",
                        }
                    ]
                    if best_email
                    else []
                ),
                "crawlReport": {
                    "rootUrl": website_url,
                    "host": host_for(website_url) if website_url else "",
                    "stoppedReason": "gpt_web_search",
                    "durationSeconds": 0,
                    "uniqueEmails": [best_email] if best_email else [],
                    "pages": [],
                    "skippedExternalSample": [],
                    "skippedAssetsSample": [],
                    "rawEvidenceSets": [],
                },
            },
            "ai": {
                "model": get_project_env("OPENAI_MODEL", "gpt-5.5"),
                "input": prompt,
                "rawResponse": raw_response,
                "usage": usage,
                "error": error,
                "sources": sources,
                "webSearchCalls": web_search_calls,
            },
        }

    return {
        "headers": headers,
        "results": results,
        "details": debug_details,
        "meta": {
            "enrichmentMode": payload.enrichmentMode,
            "businessesAttempted": len(rows) - businesses_without_urls,
            "businessesEnriched": businesses_enriched,
            "businessesCached": 0,
            "businessesWithoutUrls": businesses_without_urls,
            "externalWebsiteSkipped": 0,
            "pagesFetched": 0,
            "socialPagesFetched": 0,
            "emailCandidatesFound": businesses_enriched,
            "openAiCalls": openai_calls,
            "webSearchCalls": web_search_calls,
            "storedResults": stored_results,
            "errors": errors,
            "durationSeconds": round(time.monotonic() - started, 2),
        },
    }


@app.post("/api/enrich-emails")
def enrich_emails(payload: EmailEnrichmentRequest) -> Dict[str, Any]:
    if payload.enrichmentMode == "gpt_web_search":
        return _enrich_emails_with_gpt_web_search(payload)
    if payload.enrichmentMode in {"ai_decision", "local_only"}:
        return _enrich_emails_with_ai(payload)

    started = time.monotonic()
    rows = [dict(row) for row in payload.rows]
    headers = list(dict.fromkeys([*payload.headers, *EMAIL_FIELDS]))
    config = ScraperConfig(
        max_pages_per_business=payload.maxPagesPerBusiness,
        request_timeout_seconds=payload.requestTimeoutSeconds,
        business_timeout_seconds=payload.businessTimeoutSeconds,
    )

    results: List[Optional[Dict[str, Any]]] = [None] * len(rows)
    scrape_queue: List[tuple[int, Dict[str, Any], str]] = []
    businesses_cached = 0
    businesses_without_urls = 0
    pages_fetched = 0
    social_pages_fetched = 0
    errors = 0

    conn = cache_module.init_cache(os.getenv("LEADS_CACHE_PATH", "leads_cache.sqlite3"))
    try:
        for index, row in enumerate(rows):
            if not _has_scrape_source(row):
                businesses_without_urls += 1
                results[index] = _merge_email_result(row, blank_result("skipped"))
                continue

            key = cache_key_for_row(row)
            if payload.useCache and key:
                cached_json = cache_module.get_email_cache(conn, key)
                if cached_json:
                    cached_result = email_result_from_cache_json(cached_json)
                    businesses_cached += 1
                    if cached_result.get("emailScrapeStatus") == "error":
                        errors += 1
                    results[index] = _merge_email_result(row, cached_result)
                    continue
            scrape_queue.append((index, row, key))

        def scrape_one(item: tuple[int, Dict[str, Any], str]) -> tuple[int, Dict[str, Any], str]:
            index, row, key = item
            try:
                return index, scrape_business_email(row, config), key
            except Exception as exc:
                return index, blank_result("error", str(exc)), key

        with ThreadPoolExecutor(max_workers=payload.businessConcurrency) as executor:
            future_map = {executor.submit(scrape_one, item): item for item in scrape_queue}
            for future in as_completed(future_map):
                index, email_result, key = future.result()
                pages_fetched += int(email_result.get("pagesFetched") or 0)
                social_pages_fetched += int(email_result.get("socialPagesFetched") or 0)
                if email_result.get("emailScrapeStatus") == "error":
                    errors += 1
                row = rows[index]
                results[index] = _merge_email_result(row, email_result)

                if payload.useCache and key and email_result.get("emailScrapeStatus") != "error":
                    cache_module.upsert_email_cache(
                        conn,
                        key,
                        str(row.get("placeId") or ""),
                        str(row.get("name") or ""),
                        str(row.get("websiteUrl") or row.get("rawWebsiteUri") or row.get("websiteUri") or ""),
                        str(row.get("socialUrl") or ""),
                        cache_json_for_result(email_result),
                    )
    finally:
        conn.close()

    final_rows = [row if row is not None else _merge_email_result(rows[index], blank_result("error", "Unknown enrichment failure")) for index, row in enumerate(results)]
    businesses_enriched = sum(1 for row in final_rows if row.get("emailScrapeStatus") in {"found", "cached"} and row.get("bestEmail"))

    return {
        "headers": headers,
        "results": final_rows,
        "meta": {
            "businessesAttempted": len(rows) - businesses_without_urls,
            "businessesEnriched": businesses_enriched,
            "businessesCached": businesses_cached,
            "businessesWithoutUrls": businesses_without_urls,
            "pagesFetched": pages_fetched,
            "socialPagesFetched": social_pages_fetched,
            "errors": errors,
            "durationSeconds": round(time.monotonic() - started, 2),
        },
    }


@app.post("/api/app/leads/{lead_id}/enrich")
def app_enrich_one_lead(lead_id: str, payload: OneLeadEnrichmentRequest) -> Dict[str, Any]:
    try:
        row = hosted_store.get_lead(lead_id)
        request = EmailEnrichmentRequest(
            rows=[row],
            headers=list(row.keys()),
            enrichmentMode=payload.enrichmentMode,
            maxPagesPerBusiness=payload.maxPagesPerBusiness,
            maxDepth=payload.maxDepth,
            businessConcurrency=1,
            requestTimeoutSeconds=payload.requestTimeoutSeconds,
            businessTimeoutSeconds=payload.businessTimeoutSeconds,
            maxOpenAiCalls=0 if payload.enrichmentMode == "local_only" else payload.maxOpenAiCalls,
            useCache=False,
            storeResults=payload.storeResults,
        )
        enriched = enrich_emails(request)
        enriched_row = enriched.get("results", [{}])[0]
        debug_id = enriched_row.get("emailDebugId") or "row-0"
        debug = (enriched.get("details") or {}).get(debug_id) or {}
        update_payload = {
            "bestEmail": enriched_row.get("bestEmail") or "",
            "bestEmailType": enriched_row.get("bestEmailType") or "",
            "bestEmailConfidence": enriched_row.get("bestEmailConfidence") or "",
            "bestEmailSourceUrl": enriched_row.get("bestEmailSourceUrl") or "",
            "bestEmailEvidence": enriched_row.get("bestEmailEvidence") or "",
            "contactName": enriched_row.get("contactName") or "",
            "contactTitle": enriched_row.get("contactTitle") or "",
            "allEmailsJson": enriched_row.get("allEmailsJson") or "[]",
            "emailScrapeStatus": enriched_row.get("emailScrapeStatus") or "",
            "emailScrapeError": enriched_row.get("emailScrapeError") or "",
            "emailSelectionMethod": enriched_row.get("emailSelectionMethod") or "",
            "emailPagesFetched": int(enriched_row.get("emailPagesFetched") or 0),
            "emailCandidateCount": int(enriched_row.get("emailCandidateCount") or 0),
            "emailDebugJson": debug,
        }
        stored_row = hosted_store.update_lead(lead_id, update_payload)
        return {"row": stored_row, "details": debug, "meta": enriched.get("meta") or {}}
    except HostedStoreError as exc:
        raise _hosted_error(exc) from exc


_DAILY_JOB_LOCK = threading.Lock()
_DAILY_SCHEDULER_STARTED = False


def _seconds_until_next_daily_run(now: Optional[datetime] = None) -> float:
    tz = ZoneInfo("America/New_York")
    current = now or datetime.now(tz)
    target = current.replace(hour=5, minute=0, second=0, microsecond=0)
    if current >= target:
        target = target + timedelta(days=1)
    return max(1.0, (target - current).total_seconds())


def _daily_scheduler_loop() -> None:
    while True:
        time.sleep(_seconds_until_next_daily_run())
        try:
            settings = hosted_store.get_settings() if hosted_store.configured() else {}
            if settings.get("dailyAutomationEnabled", True):
                with _DAILY_JOB_LOCK:
                    run_daily_lead_job(notify=True)
        except Exception as exc:
            print(f"Daily lead automation failed: {exc}")


@app.on_event("startup")
def start_daily_scheduler() -> None:
    global _DAILY_SCHEDULER_STARTED
    enabled = _scheduler_enabled()
    if not enabled or _DAILY_SCHEDULER_STARTED:
        return
    _DAILY_SCHEDULER_STARTED = True
    thread = threading.Thread(target=_daily_scheduler_loop, daemon=True)
    thread.start()
