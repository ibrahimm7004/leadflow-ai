from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .constants import EXTERNAL_PLATFORM_DOMAINS
from .env import get_project_env, load_project_env


MODEL = "gpt-5.4-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

LIKELY_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/staff",
    "/leadership",
    "/owners",
    "/owner",
    "/our-story",
    "/company",
    "/management",
]

LINK_KEYWORDS = (
    "contact",
    "about",
    "team",
    "staff",
    "leadership",
    "owner",
    "founder",
    "management",
    "company",
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
    "partner",
    "operator",
)

PERSON_KEYWORDS = (
    "manager",
    "general manager",
    "director",
    "operations",
    "chef",
    "office manager",
    "administrator",
)

USEFUL_ROLE_PREFIXES = {
    "sales",
    "hello",
    "contact",
    "office",
    "service",
    "services",
    "booking",
    "bookings",
    "reservations",
    "events",
    "customerservice",
}

GENERIC_PREFIXES = {
    "info",
    "help",
    "support",
    "admin",
    "webmaster",
}

BAD_PREFIXES = {
    "example",
    "test",
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "privacy",
    "abuse",
    "postmaster",
}

BAD_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "sentry.io",
}

COMMON_EMAIL_TLDS = {
    "academy",
    "accountants",
    "agency",
    "ai",
    "app",
    "attorney",
    "biz",
    "business",
    "ca",
    "care",
    "center",
    "cleaning",
    "clinic",
    "co",
    "com",
    "company",
    "consulting",
    "contractors",
    "dental",
    "design",
    "dev",
    "digital",
    "directory",
    "edu",
    "email",
    "engineering",
    "enterprises",
    "estate",
    "events",
    "expert",
    "finance",
    "fitness",
    "global",
    "group",
    "guru",
    "health",
    "help",
    "homes",
    "info",
    "io",
    "law",
    "legal",
    "life",
    "live",
    "llc",
    "marketing",
    "media",
    "net",
    "network",
    "org",
    "photography",
    "plumbing",
    "pro",
    "properties",
    "realty",
    "repair",
    "restaurant",
    "services",
    "shop",
    "site",
    "social",
    "solutions",
    "store",
    "studio",
    "support",
    "systems",
    "tech",
    "today",
    "tools",
    "training",
    "us",
    "ventures",
    "website",
    "works",
    "world",
}

EMAIL_RE = re.compile(
    r"(?<![A-Z0-9_%+-])([A-Z0-9._%+-]{1,64}@[A-Z0-9.-]+\.[A-Z]{2,24})(?![A-Z0-9_%+-])",
    re.IGNORECASE,
)
EMAIL_VALID_RE = re.compile(
    r"^[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]+\.[A-Z]{2,24}$",
    re.IGNORECASE,
)

OBFUSCATED_RE = re.compile(
    r"([A-Z0-9._%+-]{1,64})\s*(?:\[at\]|\(at\)|\sat\s| at )\s*"
    r"([A-Z0-9.-]+?)\s*(?:\[dot\]|\(dot\)|\sdot\s| dot |\.)\s*([A-Z]{2,24})",
    re.IGNORECASE,
)

PERSON_SIGNAL_RE = re.compile(
    r"(?P<context>.{0,120}\b(?:owner|founder|co-founder|ceo|president|principal|"
    r"manager|director|operator|partner)\b.{0,160})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class EmailEvidence:
    email: str
    source_url: str
    page_title: str
    evidence: List[str] = field(default_factory=list)
    score: int = 0
    local_type: str = "unknown"


@dataclass
class ScrapeResult:
    website_url: str
    pages_fetched: int
    emails: List[EmailEvidence]
    people_signals: List[str]
    status: str
    error: str = ""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical_url(url: str) -> str:
    value = (url or "").strip()
    if "," in value and value.split(",", 1)[0].lower() in {"website", "instagram", "facebook", "linkedin", "x", "twitter", "tiktok", "youtube", "pinterest"}:
        value = value.split(",", 1)[1].strip()
    if not value or value.lower() in {"none", "none,", "null", "n/a", "na"}:
        return ""
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            "",
            "",
        )
    )


def root_url(url: str) -> str:
    canonical = canonical_url(url)
    if not canonical:
        return ""
    parsed = urlparse(canonical)
    if not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc.lower(), "/", "", "", ""))


def host_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def valid_owned_website(url: str) -> str:
    canonical = root_url(url)
    if not canonical:
        return ""
    host = host_for(canonical)
    social_hosts = (
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "youtube.com",
    )
    if any(host == domain or host.endswith("." + domain) for domain in social_hosts):
        return ""
    if any(host == domain or host.endswith("." + domain) for domain in EXTERNAL_PLATFORM_DOMAINS):
        return ""
    return canonical


def decode_cfemail(value: str) -> str:
    try:
        key = int(value[:2], 16)
        return "".join(
            chr(int(value[index : index + 2], 16) ^ key)
            for index in range(2, len(value), 2)
        )
    except Exception:
        return ""


def normalize_obfuscated(text: str) -> str:
    return OBFUSCATED_RE.sub(
        lambda match: f"{match.group(1)}@{match.group(2)}.{match.group(3)}",
        text,
    )


def clean_email(raw_email: str) -> str:
    email = unquote(unescape(raw_email or "")).strip().strip(".,;:()[]{}<>\"'").lower()
    if not EMAIL_VALID_RE.fullmatch(email):
        return ""
    local, domain = email.rsplit("@", 1)
    tld = domain.rsplit(".", 1)[-1]
    if local in BAD_PREFIXES or domain in BAD_DOMAINS:
        return ""
    if tld not in COMMON_EMAIL_TLDS:
        return ""
    if domain.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")):
        return ""
    if ".." in domain or domain.startswith("-") or domain.endswith("-"):
        return ""
    if len(local) <= 1:
        return ""
    return email


def compact_text(value: str, limit: int = 500) -> str:
    return " ".join((value or "").split())[:limit]


def context_for(text: str, needle: str, window: int = 360) -> str:
    lower = text.lower()
    index = lower.find(needle.lower())
    if index < 0:
        return compact_text(text, window)
    start = max(0, index - window // 2)
    end = min(len(text), index + len(needle) + window // 2)
    return compact_text(text[start:end], window)


def page_title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return compact_text(soup.title.string, 120)
    heading = soup.find(["h1", "h2"])
    return compact_text(heading.get_text(" ", strip=True), 120) if heading else ""


def classify_and_score(email: str, evidence: Iterable[str], source_url: str, website_host: str) -> Tuple[int, str]:
    local, domain = email.split("@", 1)
    evidence_blob = " ".join(evidence).lower()
    path = urlparse(source_url).path.lower()
    score = 0
    email_type = "unknown"

    if local in GENERIC_PREFIXES:
        score += 22
        email_type = "generic"
    elif local in USEFUL_ROLE_PREFIXES:
        score += 42
        email_type = "role"
    elif any(keyword in evidence_blob for keyword in OWNER_KEYWORDS):
        score += 140
        email_type = "owner"
    elif any(keyword in evidence_blob for keyword in PERSON_KEYWORDS):
        score += 95
        email_type = "person"
    elif local not in USEFUL_ROLE_PREFIXES and local not in GENERIC_PREFIXES:
        score += 70 if "." in local or "_" in local or "-" in local else 58
        email_type = "person"

    if any(keyword in path for keyword in ("team", "staff", "owner", "leadership", "about")):
        score += 20
    if "contact" in path:
        score += 10
    if domain == website_host or domain.endswith("." + website_host):
        score += 18
    elif website_host.endswith(domain):
        score += 10
    else:
        score -= 12

    return score, email_type


def extract_emails_from_html(html: str, source_url: str, website_host: str) -> Tuple[List[EmailEvidence], List[str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = page_title(soup)
    text = soup.get_text(" ", strip=True)
    searchable = normalize_obfuscated(unescape(text + " " + html))
    evidence_by_email: Dict[str, EmailEvidence] = {}

    def add(raw_email: str, snippet: str) -> None:
        email = clean_email(raw_email)
        if not email:
            return
        item = evidence_by_email.get(email)
        if not item:
            item = EmailEvidence(email=email, source_url=source_url, page_title=title)
            evidence_by_email[email] = item
        compact = compact_text(snippet, 420)
        if compact and compact not in item.evidence:
            item.evidence.append(compact)

    for tag in soup.select("a[href^='mailto:']"):
        href = str(tag.get("href") or "")
        raw = href.split(":", 1)[-1].split("?", 1)[0]
        label = tag.get_text(" ", strip=True)
        add(raw, label or context_for(searchable, raw))

    for tag in soup.select("[data-cfemail]"):
        decoded = decode_cfemail(str(tag.get("data-cfemail") or ""))
        if decoded:
            add(decoded, "Cloudflare protected email on page")

    for match in EMAIL_RE.finditer(searchable):
        add(match.group(1), context_for(searchable, match.group(1)))

    for item in evidence_by_email.values():
        item.score, item.local_type = classify_and_score(
            item.email, item.evidence, item.source_url, website_host
        )

    people_signals = []
    for match in PERSON_SIGNAL_RE.finditer(text):
        signal = compact_text(match.group("context"), 320)
        if signal and signal not in people_signals:
            people_signals.append(signal)
        if len(people_signals) >= 8:
            break

    return sorted(evidence_by_email.values(), key=lambda item: item.score, reverse=True), people_signals


def fetch_html(session: requests.Session, url: str, timeout: int) -> Tuple[str, str]:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LeadsGeneratorContactBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if content_type and "text/html" not in content_type and "text/plain" not in content_type:
        return "", response.url
    return response.text, response.url


def discover_links(html: str, base_url: str, website_host: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    scored: List[Tuple[int, str]] = []
    for tag in soup.select("a[href]"):
        href = str(tag.get("href") or "")
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = canonical_url(urljoin(base_url, href))
        if not url or host_for(url) != website_host:
            continue
        label = f"{href} {tag.get_text(' ', strip=True)}".lower()
        if not any(keyword in label for keyword in LINK_KEYWORDS):
            continue
        score = sum(1 for keyword in LINK_KEYWORDS if keyword in label)
        if any(keyword in label for keyword in ("owner", "founder", "team", "staff", "leadership")):
            score += 4
        elif "contact" in label:
            score += 3
        elif "about" in label:
            score += 2
        scored.append((score, url))
    return list(dict.fromkeys(url for _, url in sorted(scored, key=lambda pair: pair[0], reverse=True)))


def crawl_website(
    website_url: str,
    max_pages: int = 12,
    request_timeout: int = 8,
    business_timeout: int = 45,
) -> ScrapeResult:
    start = time.monotonic()
    root_url = valid_owned_website(website_url)
    if not root_url:
        return ScrapeResult("", 0, [], [], "skipped", "No valid owned website URL")

    session = requests.Session()
    website_host = host_for(root_url)
    fetched = 0
    errors: List[str] = []
    all_emails: Dict[str, EmailEvidence] = {}
    people_signals: List[str] = []

    try:
        home_html, final_home_url = fetch_html(session, root_url, request_timeout)
    except requests.RequestException as exc:
        return ScrapeResult(root_url, 0, [], [], "error", str(exc))

    queue = [final_home_url]
    if home_html:
        fetched += 1
        home_emails, signals = extract_emails_from_html(home_html, final_home_url, website_host)
        for email in home_emails:
            all_emails[email.email] = email
        people_signals.extend(signal for signal in signals if signal not in people_signals)
        parsed = urlparse(final_home_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        queue.extend(canonical_url(urljoin(base, path)) for path in LIKELY_PATHS)
        queue.extend(discover_links(home_html, final_home_url, website_host))

    seen = {final_home_url}
    for url in [value for value in dict.fromkeys(queue) if value]:
        if url in seen:
            continue
        seen.add(url)
        if fetched >= max_pages or time.monotonic() - start > business_timeout:
            break
        try:
            html, final_url = fetch_html(session, url, request_timeout)
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
            continue
        if not html:
            continue
        fetched += 1
        page_emails, signals = extract_emails_from_html(html, final_url, website_host)
        for email in page_emails:
            previous = all_emails.get(email.email)
            if not previous or email.score > previous.score:
                all_emails[email.email] = email
            elif previous:
                for snippet in email.evidence:
                    if snippet not in previous.evidence and len(previous.evidence) < 4:
                        previous.evidence.append(snippet)
        for signal in signals:
            if signal not in people_signals and len(people_signals) < 12:
                people_signals.append(signal)

    ranked = sorted(all_emails.values(), key=lambda item: item.score, reverse=True)
    status = "found" if ranked else "not_found"
    return ScrapeResult(root_url, fetched, ranked, people_signals, status, "; ".join(errors[:3]))


def load_leads_from_db(
    db_path: str,
    run_id: Optional[int] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = "WHERE website_url IS NOT NULL AND website_url != ''"
    params: List[Any] = []
    if run_id is not None:
        where += " AND run_id = ?"
        params.append(run_id)
    rows = conn.execute(
        f"""
        SELECT id, run_id, query, place_id, name, rating, user_rating_count,
               website_url, google_maps_uri, row_json
        FROM search_result_rows
        {where}
        ORDER BY run_id DESC, user_rating_count ASC, id ASC
        LIMIT ?
        """,
        (*params, max(limit * 5, limit)),
    ).fetchall()
    conn.close()

    leads = []
    for row in rows:
        website = valid_owned_website(row["website_url"])
        if not website:
            continue
        lead = dict(row)
        lead["website_url"] = website
        try:
            lead["row"] = json.loads(row["row_json"] or "{}")
        except Exception:
            lead["row"] = {}
        leads.append(lead)
        if len(leads) >= limit:
            break
    return leads


def build_llm_context(lead: Dict[str, Any], scrape: ScrapeResult, max_chars: int = 14000) -> str:
    payload = {
        "business": {
            "name": lead.get("name", ""),
            "query": lead.get("query", ""),
            "location": lead.get("address", "") or lead.get("formattedAddress", "") or lead.get("shortFormattedAddress", ""),
            "website": scrape.website_url,
            "rating": lead.get("rating", ""),
            "userRatingCount": lead.get("user_rating_count", ""),
        },
        "emailCandidates": [
            {
                "email": email.email,
                "localType": email.local_type,
                "localScore": email.score,
                "sourceUrl": email.source_url,
                "pageTitle": email.page_title,
                "evidence": email.evidence[:4],
            }
            for email in scrape.emails
        ],
        "peopleSignalsOnSite": scrape.people_signals[:12],
    }
    return json.dumps(payload, indent=2, ensure_ascii=True)[:max_chars]


def _business_prompt_label(lead: Dict[str, Any]) -> str:
    name = " ".join(str(lead.get("name") or "").split())
    location = " ".join(
        str(
            lead.get("address")
            or lead.get("formattedAddress")
            or lead.get("shortFormattedAddress")
            or lead.get("query")
            or ""
        ).split()
    )
    if name and location:
        return f"{name} in {location}"
    return name or location or "this business"


def build_email_decision_prompt(lead: Dict[str, Any], scrape: ScrapeResult) -> str:
    context = build_llm_context(lead, scrape)
    business = _business_prompt_label(lead)
    website = scrape.website_url or lead.get("website_url") or lead.get("website") or "the verified private website"
    return (
        f"For the business {business}, using the website {website}, choose the single best email address "
        "for outreach to pitch improving the business website. Prefer a real owner, founder, CEO, "
        "president, principal, partner, operator, or manager. If no real-person email exists, choose "
        "the best generic business email. You must choose only an email that appears in emailCandidates. "
        "Return exactly one email address and no other text. Return an empty string only if the "
        "candidate list is empty.\n\n"
        f"{context}"
    )


def choose_local_best(scrape: ScrapeResult) -> str:
    return scrape.emails[0].email if scrape.emails else ""


def parse_email_only(text: str) -> str:
    if not text:
        return ""
    match = EMAIL_RE.search(text.strip())
    return clean_email(match.group(1)) if match else ""


def choose_best_email_with_gpt(
    lead: Dict[str, Any],
    scrape: ScrapeResult,
    api_key: str,
    timeout: int = 45,
) -> Tuple[str, str, Dict[str, Any]]:
    allowed_emails = {email.email for email in scrape.emails}
    if not allowed_emails:
        return "", "", {}

    prompt = build_email_decision_prompt(lead, scrape)
    response = requests.post(
        OPENAI_RESPONSES_URL,
        timeout=timeout,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "input": [{"role": "user", "content": prompt}],
            "max_output_tokens": 40,
            "reasoning": {"effort": "none"},
        },
    )
    response.raise_for_status()
    data = response.json()
    output_text = extract_response_text(data)
    chosen = parse_email_only(output_text)
    if chosen not in allowed_emails:
        return "", output_text, data.get("usage", {})
    return chosen, output_text, data.get("usage", {})


def extract_response_text(data: Dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: List[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def init_result_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_email_enrichment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_row_id INTEGER,
            run_id INTEGER,
            place_id TEXT,
            business_name TEXT,
            website_url TEXT,
            best_email TEXT,
            local_best_email TEXT,
            llm_used INTEGER,
            llm_model TEXT,
            llm_raw_response TEXT,
            usage_json TEXT,
            status TEXT,
            error TEXT,
            pages_fetched INTEGER,
            all_emails_json TEXT,
            people_signals_json TEXT,
            created_utc TEXT
        )
        """
    )
    conn.commit()


def store_result(
    db_path: str,
    lead: Dict[str, Any],
    scrape: ScrapeResult,
    best_email: str,
    local_best_email: str,
    llm_used: bool,
    llm_raw_response: str,
    usage: Dict[str, Any],
    status: str,
    error: str,
) -> int:
    conn = sqlite3.connect(db_path)
    init_result_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO ai_email_enrichment_results (
            source_row_id, run_id, place_id, business_name, website_url,
            best_email, local_best_email, llm_used, llm_model, llm_raw_response,
            usage_json, status, error, pages_fetched, all_emails_json,
            people_signals_json, created_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead.get("id"),
            lead.get("run_id"),
            lead.get("place_id"),
            lead.get("name"),
            scrape.website_url,
            best_email,
            local_best_email,
            1 if llm_used else 0,
            MODEL if llm_used else "",
            llm_raw_response,
            json.dumps(usage, separators=(",", ":"), ensure_ascii=True),
            status,
            error,
            scrape.pages_fetched,
            json.dumps(
                [
                    {
                        "email": email.email,
                        "sourceUrl": email.source_url,
                        "pageTitle": email.page_title,
                        "evidence": email.evidence,
                        "localScore": email.score,
                        "localType": email.local_type,
                    }
                    for email in scrape.emails
                ],
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            json.dumps(scrape.people_signals, separators=(",", ":"), ensure_ascii=True),
            _utc_now(),
        ),
    )
    result_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    return result_id


def enrich_leads(
    db_path: str,
    run_id: Optional[int],
    limit: int,
    use_gpt: bool,
    max_api_calls: int,
    max_pages: int,
    store: bool,
) -> List[Dict[str, Any]]:
    load_project_env()
    api_key = get_project_env("OPENAI_API_KEY").strip()
    leads = load_leads_from_db(db_path, run_id=run_id, limit=limit)
    results: List[Dict[str, Any]] = []
    api_calls = 0

    for lead in leads:
        scrape = crawl_website(lead["website_url"], max_pages=max_pages)
        local_best = choose_local_best(scrape)
        best = local_best
        llm_raw = ""
        usage: Dict[str, Any] = {}
        llm_used = False
        status = scrape.status
        error = scrape.error

        if use_gpt and scrape.emails and api_key and api_calls < max_api_calls:
            try:
                best_from_gpt, llm_raw, usage = choose_best_email_with_gpt(lead, scrape, api_key)
                api_calls += 1
                llm_used = True
                if best_from_gpt:
                    best = best_from_gpt
                else:
                    error = (error + "; " if error else "") + "GPT returned no valid candidate; used local best"
            except requests.RequestException as exc:
                api_calls += 1
                llm_used = True
                error = (error + "; " if error else "") + f"OpenAI API error: {exc}"
        elif use_gpt and scrape.emails and not api_key:
            error = (error + "; " if error else "") + "OPENAI_API_KEY is missing; used local best"
        elif use_gpt and scrape.emails and api_calls >= max_api_calls:
            error = (error + "; " if error else "") + "Max API calls reached; used local best"

        if scrape.emails and best:
            status = "found"
        elif not scrape.emails:
            status = scrape.status

        row = {
            "rowId": lead.get("id"),
            "runId": lead.get("run_id"),
            "business": lead.get("name"),
            "website": scrape.website_url or lead.get("website_url"),
            "bestEmail": best,
            "localBestEmail": local_best,
            "llmUsed": llm_used,
            "status": status,
            "emailsFound": len(scrape.emails),
            "pagesFetched": scrape.pages_fetched,
            "error": error,
            "candidates": [email.email for email in scrape.emails],
        }
        results.append(row)

        if store:
            store_result(
                db_path,
                lead,
                scrape,
                best,
                local_best,
                llm_used,
                llm_raw,
                usage,
                status,
                error,
            )

    return results


def print_results(results: List[Dict[str, Any]]) -> None:
    if not results:
        print("No stored leads with usable websites were found.")
        return
    for result in results:
        print("-" * 88)
        print(f"Business:      {result['business']}")
        print(f"Website:       {result['website']}")
        print(f"Best email:    {result['bestEmail'] or '(none)'}")
        print(f"Local best:    {result['localBestEmail'] or '(none)'}")
        print(f"Status:        {result['status']} | emails={result['emailsFound']} | pages={result['pagesFetched']} | llm={result['llmUsed']}")
        if result["candidates"]:
            print(f"Candidates:    {', '.join(result['candidates'][:8])}")
        if result["error"]:
            print(f"Notes:         {result['error']}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standalone website-only email enrichment from stored SQLite lead rows."
    )
    parser.add_argument("--db", default="leads_cache.sqlite3", help="SQLite database path.")
    parser.add_argument("--run-id", type=int, default=None, help="Optional search run id.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum stored leads to inspect.")
    parser.add_argument("--max-pages", type=int, default=12, help="Maximum pages to fetch per website.")
    parser.add_argument("--max-api-calls", type=int, default=5, help="Safety cap for OpenAI calls.")
    parser.add_argument("--no-gpt", action="store_true", help="Only run local scraping/ranking.")
    parser.add_argument("--no-store", action="store_true", help="Do not store enrichment rows in SQLite.")
    args = parser.parse_args(argv)

    results = enrich_leads(
        db_path=args.db,
        run_id=args.run_id,
        limit=args.limit,
        use_gpt=not args.no_gpt,
        max_api_calls=args.max_api_calls,
        max_pages=args.max_pages,
        store=not args.no_store,
    )
    print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
