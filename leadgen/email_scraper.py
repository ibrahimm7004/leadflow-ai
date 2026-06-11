from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


EMAIL_FIELDS = [
    "bestEmail",
    "bestEmailType",
    "bestEmailConfidence",
    "bestEmailSourceUrl",
    "bestEmailEvidence",
    "contactName",
    "contactTitle",
    "allEmailsJson",
    "emailScrapeStatus",
    "emailScrapeError",
]

LIKELY_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/staff",
    "/leadership",
    "/owners",
    "/our-story",
    "/menu",
    "/careers",
]

DISCOVERY_KEYWORDS = (
    "contact",
    "about",
    "team",
    "staff",
    "leadership",
    "owner",
    "owners",
    "founder",
    "story",
    "people",
)

OWNER_KEYWORDS = (
    "owner",
    "founder",
    "co-founder",
    "cofounder",
    "ceo",
    "president",
    "principal",
    "proprietor",
    "operator",
)

PERSON_KEYWORDS = (
    "manager",
    "general manager",
    "director",
    "chef",
    "executive chef",
    "partner",
    "operations",
)

ROLE_PREFIXES = {
    "sales",
    "hello",
    "contact",
    "office",
    "bookings",
    "booking",
    "reservations",
    "events",
}

GENERIC_PREFIXES = {
    "info",
    "help",
    "support",
    "admin",
    "service",
    "customerservice",
    "no-reply",
    "noreply",
}

SKIP_PREFIXES = {
    "example",
    "test",
    "privacy",
    "abuse",
    "postmaster",
    "webmaster",
}

SKIP_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "domain.com",
    "email.com",
    "yourdomain.com",
}

SOCIAL_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
    "pinterest.com",
)

EMAIL_RE = re.compile(
    r"(?<![A-Z0-9._%+-])([A-Z0-9._%+-]{1,64}@[A-Z0-9.-]+\.[A-Z]{2,24})(?![A-Z0-9._%+-])",
    re.IGNORECASE,
)
OBFUSCATED_RE = re.compile(
    r"([A-Z0-9._%+-]{1,64})\s*(?:\[at\]|\(at\)|\sat\s)\s*([A-Z0-9.-]+?)\s*(?:\[dot\]|\(dot\)|\sdot\s)\s*([A-Z]{2,24})",
    re.IGNORECASE,
)
NAME_TITLE_RE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}).{0,80}?(owner|founder|co-founder|ceo|president|principal|manager|director|chef|operator)",
    re.IGNORECASE,
)


@dataclass
class ScraperConfig:
    max_pages_per_business: int = 12
    request_timeout_seconds: int = 8
    business_timeout_seconds: int = 45


@dataclass
class EmailCandidate:
    email: str
    source_url: str
    evidence: str
    score: int
    email_type: str
    confidence: str
    contact_name: str = ""
    contact_title: str = ""


def blank_result(status: str = "not_found", error: str = "") -> Dict[str, str]:
    return {
        "bestEmail": "",
        "bestEmailType": "unknown",
        "bestEmailConfidence": "low",
        "bestEmailSourceUrl": "",
        "bestEmailEvidence": "",
        "contactName": "",
        "contactTitle": "",
        "allEmailsJson": "[]",
        "emailScrapeStatus": status,
        "emailScrapeError": error,
    }


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _canonical_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, flags=re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", "", "", ""))


def _is_social_url(url: str) -> bool:
    host = _host(url)
    return any(host == domain or host.endswith("." + domain) for domain in SOCIAL_DOMAINS)


def _owned_url_from_row(row: Dict[str, Any]) -> str:
    for key in ("websiteUrl", "rawWebsiteUri", "websiteUri"):
        url = _canonical_url(str(row.get(key) or ""))
        if url and not _is_social_url(url):
            return url
    return ""


def _social_urls_from_row(row: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for key in ("socialUrl", "websiteUrl", "rawWebsiteUri", "websiteUri"):
        url = _canonical_url(str(row.get(key) or ""))
        if url and _is_social_url(url) and url not in urls:
            urls.append(url)
    return urls


def cache_key_for_row(row: Dict[str, Any]) -> str:
    website_url = _owned_url_from_row(row)
    if website_url:
        return "domain:" + _host(website_url)
    socials = _social_urls_from_row(row)
    if socials:
        return "social:" + socials[0]
    place_id = str(row.get("placeId") or "")
    if place_id:
        return "place:" + place_id
    return ""


def _decode_cfemail(value: str) -> str:
    try:
        key = int(value[:2], 16)
        chars = [
            chr(int(value[i : i + 2], 16) ^ key)
            for i in range(2, len(value), 2)
        ]
        return "".join(chars)
    except Exception:
        return ""


def _normalize_obfuscated(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group(1)}@{match.group(2)}.{match.group(3)}"

    return OBFUSCATED_RE.sub(repl, text)


def _valid_email(email: str) -> str:
    email = unquote(unescape(email)).strip().strip(".,;:()[]{}<>\"'").lower()
    match = EMAIL_RE.fullmatch(email)
    if not match:
        return ""
    local, domain = email.rsplit("@", 1)
    if local in SKIP_PREFIXES or domain in SKIP_DOMAINS:
        return ""
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")):
        return ""
    if ".." in domain or domain.startswith("-") or domain.endswith("-"):
        return ""
    return email


def _context_for_email(text: str, email: str, window: int = 180) -> str:
    index = text.lower().find(email.lower())
    if index < 0:
        return text[:window].strip()
    start = max(0, index - window // 2)
    end = min(len(text), index + len(email) + window // 2)
    return " ".join(text[start:end].split())


def extract_email_candidates(html: str, source_url: str) -> List[EmailCandidate]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: List[Tuple[str, str]] = []

    for tag in soup.select("a[href^='mailto:']"):
        href = str(tag.get("href") or "")
        mailto = href.split(":", 1)[-1].split("?", 1)[0]
        candidates.append((mailto, tag.get_text(" ", strip=True) or "mailto link"))

    for tag in soup.select("[data-cfemail]"):
        decoded = _decode_cfemail(str(tag.get("data-cfemail") or ""))
        if decoded:
            candidates.append((decoded, "cloudflare protected email"))

    text = soup.get_text(" ", strip=True)
    normalized_text = _normalize_obfuscated(text)
    for match in EMAIL_RE.finditer(normalized_text):
        email = match.group(1)
        candidates.append((email, _context_for_email(normalized_text, email)))

    by_email: Dict[str, EmailCandidate] = {}
    for raw_email, evidence in candidates:
        email = _valid_email(raw_email)
        if not email:
            continue
        ranked = rank_email(email, evidence, source_url)
        previous = by_email.get(email)
        if not previous or ranked.score > previous.score:
            by_email[email] = ranked
    return sorted(by_email.values(), key=lambda item: item.score, reverse=True)


def rank_email(email: str, evidence: str, source_url: str) -> EmailCandidate:
    local, domain = email.split("@", 1)
    evidence_l = (evidence or "").lower()
    path_l = urlparse(source_url).path.lower()
    score = 0
    email_type = "unknown"

    if any(keyword in evidence_l for keyword in OWNER_KEYWORDS):
        score += 120
        email_type = "owner"
    elif any(keyword in evidence_l for keyword in PERSON_KEYWORDS):
        score += 90
        email_type = "person"
    elif local not in ROLE_PREFIXES and local not in GENERIC_PREFIXES and "." in local:
        score += 75
        email_type = "person"
    elif local not in ROLE_PREFIXES and local not in GENERIC_PREFIXES and len(local) > 2:
        score += 60
        email_type = "person"
    elif local in ROLE_PREFIXES:
        score += 40
        email_type = "role"
    elif local in GENERIC_PREFIXES:
        score += 20
        email_type = "generic"

    if any(keyword in path_l for keyword in ("team", "staff", "about", "owner", "leadership")):
        score += 18
    if any(keyword in path_l for keyword in ("contact", "reservation", "booking")):
        score += 8
    if domain in source_url.lower():
        score += 10
    if local in {"noreply", "no-reply"}:
        score -= 80

    confidence = "high" if score >= 100 else "medium" if score >= 60 else "low"
    contact_name, contact_title = _extract_contact(evidence)
    return EmailCandidate(
        email=email,
        source_url=source_url,
        evidence=evidence[:240],
        score=score,
        email_type=email_type,
        confidence=confidence,
        contact_name=contact_name,
        contact_title=contact_title,
    )


def _extract_contact(evidence: str) -> Tuple[str, str]:
    match = NAME_TITLE_RE.search(evidence or "")
    if not match:
        return "", ""
    name = " ".join(match.group(1).split())
    title = " ".join(match.group(2).split()).title()
    return name, title


def _fetch(url: str, timeout: int) -> Tuple[str, str]:
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LeadsGeneratorEmailBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        allow_redirects=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type and content_type:
        return "", response.url
    return response.text, response.url


def _same_host(url: str, base_host: str) -> bool:
    host = _host(url)
    return host == base_host


def _discover_links(html: str, base_url: str, base_host: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links: List[Tuple[int, str]] = []
    for tag in soup.select("a[href]"):
        href = str(tag.get("href") or "")
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = _canonical_url(urljoin(base_url, href))
        if not url or not _same_host(url, base_host):
            continue
        label = f"{href} {tag.get_text(' ', strip=True)}".lower()
        if not any(keyword in label for keyword in DISCOVERY_KEYWORDS):
            continue
        score = sum(1 for keyword in DISCOVERY_KEYWORDS if keyword in label)
        links.append((score, url))
    ordered = [url for _, url in sorted(links, key=lambda item: item[0], reverse=True)]
    return list(dict.fromkeys(ordered))


def _website_queue(home_url: str, html: str) -> List[str]:
    parsed = urlparse(home_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    base_host = _host(home_url)
    urls = [home_url]
    urls.extend(_canonical_url(urljoin(base, path)) for path in LIKELY_PATHS)
    urls.extend(_discover_links(html, home_url, base_host))
    return [url for url in dict.fromkeys(urls) if url]


def _candidate_payload(candidate: EmailCandidate) -> Dict[str, Any]:
    return {
        "email": candidate.email,
        "type": candidate.email_type,
        "confidence": candidate.confidence,
        "sourceUrl": candidate.source_url,
        "evidence": candidate.evidence,
        "contactName": candidate.contact_name,
        "contactTitle": candidate.contact_title,
        "score": candidate.score,
    }


def scrape_business_email(row: Dict[str, Any], config: Optional[ScraperConfig] = None) -> Dict[str, Any]:
    config = config or ScraperConfig()
    started = time.monotonic()
    website_url = _owned_url_from_row(row)
    social_urls = _social_urls_from_row(row)
    if not website_url and not social_urls:
        result = blank_result("skipped")
        result.update({"pagesFetched": 0, "socialPagesFetched": 0})
        return result

    candidates: Dict[str, EmailCandidate] = {}
    pages_fetched = 0
    social_pages_fetched = 0

    try:
        if website_url:
            html, final_url = _fetch(website_url, config.request_timeout_seconds)
            if html:
                pages_fetched += 1
                for candidate in extract_email_candidates(html, final_url):
                    candidates[candidate.email] = candidate
                queue = _website_queue(final_url, html)
            else:
                queue = []

            for url in queue[1:]:
                if pages_fetched >= config.max_pages_per_business:
                    break
                if time.monotonic() - started > config.business_timeout_seconds:
                    break
                try:
                    page_html, page_url = _fetch(url, config.request_timeout_seconds)
                except requests.RequestException:
                    continue
                if not page_html:
                    continue
                pages_fetched += 1
                for candidate in extract_email_candidates(page_html, page_url):
                    previous = candidates.get(candidate.email)
                    if not previous or candidate.score > previous.score:
                        candidates[candidate.email] = candidate
                for social_url in _social_links_from_html(page_html, page_url):
                    if social_url not in social_urls:
                        social_urls.append(social_url)

        for social_url in social_urls[:5]:
            if time.monotonic() - started > config.business_timeout_seconds:
                break
            try:
                social_html, final_social_url = _fetch(social_url, config.request_timeout_seconds)
            except requests.RequestException:
                continue
            if not social_html:
                continue
            social_pages_fetched += 1
            for candidate in extract_email_candidates(social_html, final_social_url):
                previous = candidates.get(candidate.email)
                if not previous or candidate.score > previous.score:
                    candidates[candidate.email] = candidate
    except requests.RequestException as exc:
        result = blank_result("error", str(exc))
        result.update({"pagesFetched": pages_fetched, "socialPagesFetched": social_pages_fetched})
        return result

    ranked = sorted(candidates.values(), key=lambda item: item.score, reverse=True)
    if not ranked:
        result = blank_result("not_found")
        result.update({"pagesFetched": pages_fetched, "socialPagesFetched": social_pages_fetched})
        return result

    best = ranked[0]
    result = {
        "bestEmail": best.email,
        "bestEmailType": best.email_type,
        "bestEmailConfidence": best.confidence,
        "bestEmailSourceUrl": best.source_url,
        "bestEmailEvidence": best.evidence,
        "contactName": best.contact_name,
        "contactTitle": best.contact_title,
        "allEmailsJson": json.dumps([_candidate_payload(candidate) for candidate in ranked], separators=(",", ":")),
        "emailScrapeStatus": "found",
        "emailScrapeError": "",
        "pagesFetched": pages_fetched,
        "socialPagesFetched": social_pages_fetched,
    }
    return result


def _social_links_from_html(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: List[str] = []
    for tag in soup.select("a[href]"):
        url = _canonical_url(urljoin(base_url, str(tag.get("href") or "")))
        if url and _is_social_url(url) and url not in urls:
            urls.append(url)
    return urls


def email_result_from_cache_json(result_json: str) -> Dict[str, Any]:
    try:
        result = json.loads(result_json)
        if isinstance(result, dict):
            result["emailScrapeStatus"] = "cached"
            return result
    except Exception:
        pass
    return blank_result("error", "Invalid cached email enrichment payload")


def cache_json_for_result(result: Dict[str, Any]) -> str:
    payload = {key: value for key, value in result.items() if key not in {"emailScrapeStatus"}}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
