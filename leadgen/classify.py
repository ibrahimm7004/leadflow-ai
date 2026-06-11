from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional

from .constants import (
    EXCLUDED_DOMAINS,
    EXTERNAL_PLATFORM_DOMAIN_MAP,
    EXTERNAL_PLATFORM_DOMAINS,
    SOCIAL_DOMAIN_MAP,
    SUBDOMAIN_ONLY,
)


def _get_domain(url: str) -> str:
    try:
        without_scheme = url.split("//", 1)[-1]
        host = without_scheme.split("/", 1)[0].lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def is_excluded_website(url: Optional[str]) -> bool:
    if not url:
        return True
    host = _get_domain(url)
    if not host:
        return True

    for domain in EXCLUDED_DOMAINS | EXTERNAL_PLATFORM_DOMAINS:
        if host == domain:
            if domain in SUBDOMAIN_ONLY:
                return False
            return True
        if host.endswith("." + domain):
            return True
    return False


def classify_website_uri(url: Optional[str]) -> str:
    if not url:
        return "none,"
    host = _get_domain(url)
    if not host:
        return "none,"
    for domain, label in SOCIAL_DOMAIN_MAP.items():
        if host == domain or host.endswith("." + domain):
            return f"{label},{url}"
    for domain, label in EXTERNAL_PLATFORM_DOMAIN_MAP.items():
        if host == domain or host.endswith("." + domain):
            return f"external_platform:{label},{url}"
    for domain in EXTERNAL_PLATFORM_DOMAINS:
        if host == domain or host.endswith("." + domain):
            return f"external_platform,{url}"
    return f"website,{url}"


def score_place(place: Dict[str, Any]) -> float:
    rating = float(place.get("rating") or 0)
    user_rating_count = int(place.get("userRatingCount") or 0)
    website_uri = place.get("websiteUri")
    social_bonus = 2.0 if is_excluded_website(website_uri) and website_uri else 0.0
    return math.log1p(user_rating_count) * 2.0 + rating * 1.5 + social_bonus


def serialize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    return str(value)


def extract_place_id(place: Dict[str, Any]) -> str:
    place_id = place.get("id")
    if place_id:
        return place_id
    name = place.get("name", "")
    if isinstance(name, str) and name.startswith("places/"):
        return name.split("/", 1)[1]
    return ""
