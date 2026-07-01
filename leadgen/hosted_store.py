from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .env import get_project_env


DEFAULT_SETTINGS: Dict[str, Any] = {
    "notificationEmail": "ibrahim.m7004@gmail.com",
    "emailNotificationsEnabled": True,
    "dailyAutomationEnabled": True,
    "weekendsOff": False,
    "defaultSearch": {
        "businessType": "barber",
        "location": "Boston, MA",
        "numLeads": 25,
        "searchMode": "all_businesses",
        "minRating": 3.5,
        "maxUserReviews": 300,
        "enabled": True,
    },
    "calendarOverrides": {},
    "visibleColumns": [
        "name",
        "bestEmail",
        "phone",
        "address",
        "websiteUrl",
        "rating",
        "userRatingCount",
        "googleMapsUri",
    ],
}

DEFAULT_SCHEDULE: List[Dict[str, Any]] = [
    {
        "dayOfWeek": index,
        "businessType": "barber",
        "location": "Boston, MA",
        "numLeads": 25,
        "searchMode": "all_businesses",
        "minRating": 3.5,
        "maxUserReviews": 300,
        "enabled": True,
    }
    for index in range(7)
]

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class HostedStoreError(RuntimeError):
    pass


def configured() -> bool:
    return bool(_base_url() and _service_key())


def status() -> Dict[str, Any]:
    return {
        "configured": configured(),
        "supabaseUrlLoaded": bool(_base_url()),
        "supabaseServiceKeyLoaded": bool(_service_key()),
    }


def _base_url() -> str:
    return get_project_env("SUPABASE_URL").rstrip("/")


def _service_key() -> str:
    return get_project_env("SUPABASE_SERVICE_ROLE_KEY")


def _headers(prefer: str = "") -> Dict[str, str]:
    key = _service_key()
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _table_url(table: str) -> str:
    base = _base_url()
    if not base or not _service_key():
        raise HostedStoreError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env.")
    return f"{base}/rest/v1/{table}"


def _request(method: str, table: str, *, params: Optional[Dict[str, Any]] = None, json_body: Any = None, prefer: str = "") -> Any:
    response = requests.request(
        method,
        _table_url(table),
        headers=_headers(prefer),
        params={key: value for key, value in (params or {}).items() if value not in (None, "")},
        json=json_body,
        timeout=30,
    )
    if response.status_code >= 400:
        raise HostedStoreError(f"Supabase {table} {method} failed: {response.status_code} {response.text}")
    if not response.text:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _json_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _email_updates_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    updates = {
        "best_email": row.get("bestEmail") or None,
        "best_email_type": row.get("bestEmailType") or None,
        "best_email_confidence": row.get("bestEmailConfidence") or None,
        "best_email_source_url": row.get("bestEmailSourceUrl") or None,
        "best_email_evidence": row.get("bestEmailEvidence") or None,
        "contact_name": row.get("contactName") or None,
        "contact_title": row.get("contactTitle") or None,
        "all_emails_json": _json_value(row.get("allEmailsJson")),
        "email_scrape_status": row.get("emailScrapeStatus") or None,
        "email_scrape_error": row.get("emailScrapeError") or None,
        "email_selection_method": row.get("emailSelectionMethod") or None,
        "email_pages_fetched": _int(row.get("emailPagesFetched")),
        "email_candidate_count": _int(row.get("emailCandidateCount")),
    }
    return updates


def _audit_updates_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    audit = _json_value(row.get("auditResult"))
    updates = {
        "audit_result_json": audit,
        "audit_status": row.get("auditStatus") or None,
        "audit_website_status": row.get("auditWebsiteStatus") or None,
        "audit_lead_quality_score": _int(row.get("auditLeadQualityScore")),
        "audit_website_opportunity_score": _int(row.get("auditWebsiteOpportunityScore")),
        "audit_outreach_priority": row.get("auditOutreachPriority") or None,
        "audit_next_best_action": row.get("auditNextBestAction") or None,
        "audit_recommended_pitch_type": row.get("auditRecommendedPitchType") or None,
        "audit_recommended_pitch_angle": row.get("auditRecommendedPitchAngle") or None,
        "audited_at": row.get("auditedAt") or None,
    }
    return updates


def lead_payload(
    row: Dict[str, Any],
    *,
    lead_date: str,
    run_id: Optional[str],
    business_type: str,
    location: str,
    query: str,
) -> Dict[str, Any]:
    payload = {
        "lead_date": lead_date,
        "search_run_id": run_id,
        "search_query": query,
        "business_type": business_type,
        "search_location": location,
        "place_id": row.get("placeId") or None,
        "name": row.get("name") or "",
        "phone": row.get("phone") or row.get("nationalPhoneNumber") or None,
        "address": row.get("address") or row.get("formattedAddress") or row.get("shortFormattedAddress") or None,
        "website_url": row.get("websiteUrl") or None,
        "raw_website_uri": row.get("rawWebsiteUri") or row.get("websiteUri") or None,
        "google_maps_uri": row.get("googleMapsUri") or None,
        "rating": _num(row.get("rating")),
        "user_rating_count": _int(row.get("userRatingCount")),
        "website_kind": row.get("websiteKind") or None,
        "social_platform": row.get("socialPlatform") or None,
        "social_url": row.get("socialUrl") or None,
        "has_external_website": _bool(row.get("hasExternalWebsite")),
        "external_website_url": row.get("externalWebsiteUrl") or None,
        "raw_data": row,
    }
    payload.update(_email_updates_from_row(row))
    payload.update(_audit_updates_from_row(row))
    return payload


def to_app_row(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
    all_emails = row.get("all_emails_json")
    if isinstance(all_emails, (dict, list)):
        all_emails_json = json.dumps(all_emails, separators=(",", ":"), ensure_ascii=True)
    else:
        all_emails_json = all_emails or ""
    return {
        **raw,
        "id": row.get("id"),
        "leadDate": row.get("lead_date"),
        "searchRunId": row.get("search_run_id"),
        "searchQuery": row.get("search_query"),
        "businessType": row.get("business_type"),
        "searchLocation": row.get("search_location"),
        "placeId": row.get("place_id") or raw.get("placeId") or "",
        "name": row.get("name") or raw.get("name") or "",
        "phone": row.get("phone") or raw.get("phone") or "",
        "address": row.get("address") or raw.get("address") or "",
        "websiteUrl": row.get("website_url") or raw.get("websiteUrl") or "",
        "rawWebsiteUri": row.get("raw_website_uri") or raw.get("rawWebsiteUri") or "",
        "googleMapsUri": row.get("google_maps_uri") or raw.get("googleMapsUri") or "",
        "rating": row.get("rating") if row.get("rating") is not None else raw.get("rating", ""),
        "userRatingCount": row.get("user_rating_count") if row.get("user_rating_count") is not None else raw.get("userRatingCount", ""),
        "websiteKind": row.get("website_kind") or raw.get("websiteKind") or "",
        "socialPlatform": row.get("social_platform") or raw.get("socialPlatform") or "",
        "socialUrl": row.get("social_url") or raw.get("socialUrl") or "",
        "hasExternalWebsite": "true" if row.get("has_external_website") else "false",
        "externalWebsiteUrl": row.get("external_website_url") or raw.get("externalWebsiteUrl") or "",
        "ticked": bool(row.get("ticked")),
        "tickedAt": row.get("ticked_at") or "",
        "bestEmail": row.get("best_email") or "",
        "bestEmailType": row.get("best_email_type") or "",
        "bestEmailConfidence": row.get("best_email_confidence") or "",
        "bestEmailSourceUrl": row.get("best_email_source_url") or "",
        "bestEmailEvidence": row.get("best_email_evidence") or "",
        "contactName": row.get("contact_name") or "",
        "contactTitle": row.get("contact_title") or "",
        "allEmailsJson": all_emails_json,
        "emailScrapeStatus": row.get("email_scrape_status") or "",
        "emailScrapeError": row.get("email_scrape_error") or "",
        "emailSelectionMethod": row.get("email_selection_method") or "",
        "emailPagesFetched": row.get("email_pages_fetched") or 0,
        "emailCandidateCount": row.get("email_candidate_count") or 0,
        "emailDebugJson": row.get("email_debug_json") or {},
        "auditResult": row.get("audit_result_json") or {},
        "auditStatus": row.get("audit_status") or "",
        "auditWebsiteStatus": row.get("audit_website_status") or "",
        "auditLeadQualityScore": row.get("audit_lead_quality_score") or 0,
        "auditWebsiteOpportunityScore": row.get("audit_website_opportunity_score") or 0,
        "auditOutreachPriority": row.get("audit_outreach_priority") or "",
        "auditNextBestAction": row.get("audit_next_best_action") or "",
        "auditRecommendedPitchType": row.get("audit_recommended_pitch_type") or "",
        "auditRecommendedPitchAngle": row.get("audit_recommended_pitch_angle") or "",
        "auditedAt": row.get("audited_at") or "",
        "createdAt": row.get("created_at") or "",
        "updatedAt": row.get("updated_at") or "",
    }


def create_search_run(*, run_date: str, query: str, business_type: str, location: str, params: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "run_date": run_date,
        "search_query": query,
        "business_type": business_type,
        "search_location": location,
        "params": params,
        "meta": meta,
    }
    rows = _request("POST", "search_runs", json_body=payload, prefer="return=representation")
    return rows[0] if rows else {}


def upsert_leads(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    result = _request(
        "POST",
        "leads",
        params={"on_conflict": "place_id"},
        json_body=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )
    return [to_app_row(row) for row in (result or [])]


def find_existing_place_ids(place_ids: List[str]) -> set[str]:
    ids = [str(place_id).strip() for place_id in place_ids if str(place_id or "").strip()]
    if not ids:
        return set()
    safe = ",".join(f'"{place_id}"' for place_id in ids)
    rows = _request("GET", "leads", params={"select": "place_id", "place_id": f"in.({safe})"}) or []
    return {str(row.get("place_id") or "").strip() for row in rows if str(row.get("place_id") or "").strip()}


def update_search_run(run_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    rows = _request("PATCH", "search_runs", params={"id": f"eq.{run_id}"}, json_body=updates, prefer="return=representation") or []
    if not rows:
        raise HostedStoreError("Search run not found")
    return rows[0]


def latest_search_run(*, run_date: str = "", query: str = "") -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "select": "*",
        "order": "created_at.desc",
        "limit": 1,
    }
    if run_date:
        params["run_date"] = f"eq.{run_date}"
    if query:
        params["search_query"] = f"eq.{query}"
    rows = _request("GET", "search_runs", params=params) or []
    return rows[0] if rows else None


def search_progress(query: str) -> Dict[str, Any]:
    run = latest_search_run(query=query)
    meta = run.get("meta") if isinstance(run, dict) and isinstance(run.get("meta"), dict) else {}
    previous_deepest = int(meta.get("deepestHistoricalPage") or meta.get("deepestPageReached") or meta.get("pages_fetched") or 0)
    return {
        "query": query,
        "runId": run.get("id") if run else "",
        "deepestHistoricalPage": previous_deepest,
        "exhausted": bool(meta.get("exhausted")) if run else False,
        "lastRunMeta": meta,
        "lastRunAt": run.get("created_at") if run else "",
    }


def search_run_summary(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not row:
        return {}
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return {
        "id": row.get("id") or "",
        "date": row.get("run_date") or "",
        "query": row.get("search_query") or "",
        "businessType": row.get("business_type") or "",
        "location": row.get("search_location") or "",
        "createdAt": row.get("created_at") or "",
        "pagesFetched": int(meta.get("pages_fetched") or 0),
        "requestsMade": int(meta.get("requests_made") or 0),
        "candidatesFetched": int(meta.get("candidates_fetched") or 0),
        "resultsReturned": int(meta.get("resultsReturned") or 0),
        "storedCount": int(meta.get("storedCount") or 0),
        "duplicatesRemoved": int(meta.get("duplicatesRemoved") or 0),
        "previousDeepestPage": int(meta.get("previousDeepestPage") or 0),
        "deepestPageReached": int(meta.get("deepestPageReached") or 0),
        "deepestHistoricalPage": int(meta.get("deepestHistoricalPage") or 0),
        "targetMaxPages": int(meta.get("targetMaxPages") or 0),
        "resumeFromPage": int(meta.get("resumeFromPage") or 1),
        "exhausted": bool(meta.get("exhausted")),
        "pageResumeSupported": bool(meta.get("pageResumeSupported", False)),
        "pageResumeNote": str(meta.get("pageResumeNote") or ""),
    }


def list_leads(
    *,
    lead_date: Optional[str] = None,
    limit: int = 250,
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    ticked: str = "",
    has_email: str = "",
    min_rating: str = "",
    max_reviews: str = "",
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "select": "*",
        "limit": min(max(limit, 1), 1000),
        "order": "lead_date.desc,ticked.asc,user_rating_count.asc.nullslast,name.asc",
    }
    if lead_date:
        params["lead_date"] = f"eq.{lead_date}"
        params["order"] = "ticked.asc,user_rating_count.asc.nullslast,name.asc"
    if date_from:
        params["lead_date"] = f"gte.{date_from}"
    if date_to:
        params["lead_date"] = f"lte.{date_to}" if "lead_date" not in params else params["lead_date"]
        if date_from:
            params["and"] = f"(lead_date.gte.{date_from},lead_date.lte.{date_to})"
            params.pop("lead_date", None)
    if q:
        safe = q.replace("*", "").replace(",", " ")
        params["or"] = f"(name.ilike.*{safe}*,address.ilike.*{safe}*,search_query.ilike.*{safe}*,best_email.ilike.*{safe}*)"
    if ticked in {"true", "false"}:
        params["ticked"] = f"eq.{ticked}"
    if has_email == "true":
        params["best_email"] = "not.is.null"
    elif has_email == "false":
        params["best_email"] = "is.null"
    if min_rating:
        params["rating"] = f"gte.{min_rating}"
    if max_reviews:
        params["user_rating_count"] = f"lte.{max_reviews}"
    rows = _request("GET", "leads", params=params) or []
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for row in rows:
        place_id = str(row.get("place_id") or "").strip()
        key = place_id or f"name:{str(row.get('name') or '').strip().lower()}|addr:{str(row.get('address') or '').strip().lower()}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(to_app_row(row))
    return deduped


def list_outreach_leads(limit: int = 500) -> List[Dict[str, Any]]:
    rows = _request(
        "GET",
        "leads",
        params={
            "select": "*",
            "audit_result_json": "not.is.null",
            "limit": min(max(limit, 1), 1000),
            "order": "audit_lead_quality_score.desc.nullslast,audited_at.desc",
        },
    ) or []
    return [to_app_row(row) for row in rows]


def get_lead(lead_id: str) -> Dict[str, Any]:
    rows = _request("GET", "leads", params={"select": "*", "id": f"eq.{lead_id}", "limit": 1}) or []
    if not rows:
        raise HostedStoreError("Lead not found")
    return to_app_row(rows[0])


def update_lead(lead_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    allowed = {
        "ticked": "ticked",
        "tickedAt": "ticked_at",
        "bestEmail": "best_email",
        "bestEmailType": "best_email_type",
        "bestEmailConfidence": "best_email_confidence",
        "bestEmailSourceUrl": "best_email_source_url",
        "bestEmailEvidence": "best_email_evidence",
        "contactName": "contact_name",
        "contactTitle": "contact_title",
        "allEmailsJson": "all_emails_json",
        "emailScrapeStatus": "email_scrape_status",
        "emailScrapeError": "email_scrape_error",
        "emailSelectionMethod": "email_selection_method",
        "emailPagesFetched": "email_pages_fetched",
        "emailCandidateCount": "email_candidate_count",
        "emailDebugJson": "email_debug_json",
        "auditResult": "audit_result_json",
        "auditStatus": "audit_status",
        "auditWebsiteStatus": "audit_website_status",
        "auditLeadQualityScore": "audit_lead_quality_score",
        "auditWebsiteOpportunityScore": "audit_website_opportunity_score",
        "auditOutreachPriority": "audit_outreach_priority",
        "auditNextBestAction": "audit_next_best_action",
        "auditRecommendedPitchType": "audit_recommended_pitch_type",
        "auditRecommendedPitchAngle": "audit_recommended_pitch_angle",
        "auditedAt": "audited_at",
    }
    payload: Dict[str, Any] = {}
    for app_key, db_key in allowed.items():
        if app_key not in updates:
            continue
        value = updates[app_key]
        if app_key == "allEmailsJson":
            value = _json_value(value)
        if app_key == "auditResult":
            value = _json_value(value)
        if app_key == "tickedAt" and not value:
            value = None
        payload[db_key] = value
    if "ticked" in updates and "tickedAt" not in updates:
        payload["ticked_at"] = _now_iso() if updates.get("ticked") else None
    if not payload:
        return get_lead(lead_id)
    rows = _request("PATCH", "leads", params={"id": f"eq.{lead_id}"}, json_body=payload, prefer="return=representation") or []
    if not rows:
        raise HostedStoreError("Lead not found")
    return to_app_row(rows[0])


def get_settings() -> Dict[str, Any]:
    rows = _request("GET", "app_settings", params={"select": "*"}) or []
    settings = {
        **DEFAULT_SETTINGS,
        "defaultSearch": dict(DEFAULT_SETTINGS["defaultSearch"]),
        "calendarOverrides": {},
        "visibleColumns": list(DEFAULT_SETTINGS["visibleColumns"]),
    }
    for row in rows:
        settings[row.get("key")] = row.get("value")
    settings["defaultSearch"] = normalize_search_config(settings.get("defaultSearch"), DEFAULT_SETTINGS["defaultSearch"])
    settings["calendarOverrides"] = settings.get("calendarOverrides") if isinstance(settings.get("calendarOverrides"), dict) else {}
    settings["visibleColumns"] = settings.get("visibleColumns") if isinstance(settings.get("visibleColumns"), list) else list(DEFAULT_SETTINGS["visibleColumns"])
    return settings


def update_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    rows = [{"key": key, "value": value} for key, value in settings.items()]
    if rows:
        _request("POST", "app_settings", json_body=rows, prefer="resolution=merge-duplicates,return=minimal")
    return get_settings()


def get_schedule() -> List[Dict[str, Any]]:
    rows = _request("GET", "weekly_schedule", params={"select": "*", "order": "day_of_week.asc"}) or []
    if not rows:
        return DEFAULT_SCHEDULE
    return [
        {
            "dayOfWeek": row.get("day_of_week"),
            "dayName": DAY_NAMES[int(row.get("day_of_week") or 0)],
            "businessType": row.get("business_type") or "",
            "location": row.get("location") or "",
            "numLeads": row.get("num_leads") or 25,
            "searchMode": row.get("search_mode") or "all_businesses",
            "minRating": row.get("min_rating") if row.get("min_rating") is not None else 3.5,
            "maxUserReviews": row.get("max_user_reviews") if row.get("max_user_reviews") is not None else 300,
            "enabled": bool(row.get("enabled")),
        }
        for row in rows
    ]


def update_schedule(schedule: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in schedule:
        rows.append(
            {
                "day_of_week": int(item.get("dayOfWeek")),
                "business_type": str(item.get("businessType") or "barber"),
                "location": str(item.get("location") or "Boston, MA"),
                "num_leads": int(item.get("numLeads") or 25),
                "search_mode": str(item.get("searchMode") or "all_businesses"),
                "min_rating": float(item.get("minRating") or 3.5),
                "max_user_reviews": int(item.get("maxUserReviews") or 300),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    _request("POST", "weekly_schedule", json_body=rows, prefer="resolution=merge-duplicates,return=minimal")
    return get_schedule()


def schedule_for_weekday(day_of_week: int) -> Dict[str, Any]:
    schedule = get_schedule()
    by_day = {int(item["dayOfWeek"]): item for item in schedule if item.get("enabled", True)}
    for offset in range(7):
        day = (day_of_week - offset) % 7
        if day in by_day:
            return by_day[day]
    return DEFAULT_SCHEDULE[day_of_week]


def normalize_search_config(value: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = dict(fallback or DEFAULT_SETTINGS["defaultSearch"])
    if isinstance(value, dict):
        base.update({key: item for key, item in value.items() if item is not None})
    return {
        "businessType": str(base.get("businessType") or "barber"),
        "location": str(base.get("location") or "Boston, MA"),
        "numLeads": int(base.get("numLeads") or 25),
        "searchMode": str(base.get("searchMode") or "all_businesses"),
        "minRating": float(base.get("minRating") if base.get("minRating") not in (None, "") else 3.5),
        "maxUserReviews": int(base.get("maxUserReviews") if base.get("maxUserReviews") not in (None, "") else 300),
        "enabled": bool(base.get("enabled", True)),
    }


def search_config_for_date(run_date: date) -> Dict[str, Any]:
    settings = get_settings()
    default_config = normalize_search_config(settings.get("defaultSearch"))
    overrides = settings.get("calendarOverrides") if isinstance(settings.get("calendarOverrides"), dict) else {}
    date_key = run_date.isoformat()
    has_override = date_key in overrides and isinstance(overrides.get(date_key), dict)
    config = normalize_search_config(overrides.get(date_key) if has_override else {}, default_config)
    if settings.get("weekendsOff") and run_date.weekday() >= 5 and not has_override:
        config["enabled"] = False
    return config


def effective_search_preview_for_date(run_date: date) -> Dict[str, Any]:
    settings = get_settings()
    default_config = normalize_search_config(settings.get("defaultSearch"))
    overrides = settings.get("calendarOverrides") if isinstance(settings.get("calendarOverrides"), dict) else {}
    date_key = run_date.isoformat()
    has_override = date_key in overrides and isinstance(overrides.get(date_key), dict)
    config = normalize_search_config(overrides.get(date_key) if has_override else {}, default_config)
    weekends_off_applied = bool(settings.get("weekendsOff") and run_date.weekday() >= 5 and not has_override)
    if weekends_off_applied:
        config["enabled"] = False
    business_type = str(config.get("businessType") or "barber")
    location = str(config.get("location") or "Boston, MA")
    return {
        "date": date_key,
        "enabled": bool(config.get("enabled", True)),
        "query": f"{business_type} in {location}",
        "source": "override" if has_override else "default",
        "weekendsOffApplied": weekends_off_applied,
        "config": config,
    }
