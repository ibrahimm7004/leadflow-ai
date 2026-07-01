from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse


SOCIAL_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "pinterest.com",
}

EXTERNAL_PLATFORM_DOMAINS = {
    "yelp.com",
    "linktr.ee",
    "linktree.com",
    "square.site",
    "toasttab.com",
    "clover.com",
    "doordash.com",
    "ubereats.com",
    "grubhub.com",
    "opentable.com",
    "resy.com",
    "vagaro.com",
    "schedulicity.com",
    "booksy.com",
    "glossgenius.com",
    "wixsite.com",
    "godaddysites.com",
}


def normalize_url(value: str) -> str:
    url = (value or "").strip()
    if "," in url and url.split(",", 1)[0].strip().lower() in {
        "website",
        "instagram",
        "facebook",
        "linkedin",
        "x",
        "twitter",
        "tiktok",
        "youtube",
    }:
        url = url.split(",", 1)[1].strip()
    if not url or url.lower() in {"none", "null", "n/a", "na", "-"}:
        return ""
    if url.startswith("www."):
        url = "https://" + url
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def root_url(value: str) -> str:
    url = normalize_url(value)
    if not url:
        return ""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc.lower(), "/", "", "", ""))


def host_for(value: str) -> str:
    host = urlparse(normalize_url(value) or value).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, base_url: str) -> bool:
    return bool(host_for(url) and host_for(url) == host_for(base_url))


def is_domain_match(host: str, domains: set[str]) -> bool:
    normalized = host.lower()
    return any(normalized == domain or normalized.endswith("." + domain) for domain in domains)


def is_social_url(url: str) -> bool:
    return is_domain_match(host_for(url), SOCIAL_DOMAINS)


def is_external_platform_url(url: str) -> bool:
    return is_domain_match(host_for(url), EXTERNAL_PLATFORM_DOMAINS)


def absolute_url(base_url: str, href: str) -> str:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return ""
    return normalize_url(urljoin(base_url, href))


def slugify(value: str, fallback: str = "lead") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:80] or fallback
