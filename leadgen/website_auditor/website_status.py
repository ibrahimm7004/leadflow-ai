from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .models import WebsiteStatusResult
from .url_utils import host_for, is_external_platform_url, is_social_url, normalize_url


PARKED_PHRASES = (
    "domain for sale",
    "buy this domain",
    "parked free",
    "this domain is parked",
    "sedo domain parking",
    "godaddy.com/domainsearch",
)

PLACEHOLDER_PHRASES = (
    "coming soon",
    "under construction",
    "website coming soon",
    "future home of",
    "site not found",
    "account suspended",
    "this site is temporarily unavailable",
    "launching soon",
)


def check_website_status(url: str, settings: Settings) -> WebsiteStatusResult:
    normalized = normalize_url(url)
    if not normalized:
        return WebsiteStatusResult(input_url=url or "", website_status="no_website", detected_reasons=["Missing website URL"])

    if is_social_url(normalized):
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=normalized,
            website_status="social_only",
            detected_reasons=["Website field points to a social profile"],
        )
    if is_external_platform_url(normalized):
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=normalized,
            website_status="external_platform_only",
            detected_reasons=["Website field points to a third-party platform"],
        )

    session = requests.Session()
    headers = {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml,*/*"}
    try:
        response = session.get(
            normalized,
            headers=headers,
            timeout=settings.request_timeout_seconds,
            allow_redirects=True,
        )
    except requests.exceptions.SSLError as exc:
        return WebsiteStatusResult(input_url=url, normalized_url=normalized, website_status="broken", error_message=f"SSL error: {exc}")
    except requests.exceptions.ConnectTimeout as exc:
        return WebsiteStatusResult(input_url=url, normalized_url=normalized, website_status="broken", error_message=f"Connection timeout: {exc}")
    except requests.exceptions.ConnectionError as exc:
        return WebsiteStatusResult(input_url=url, normalized_url=normalized, website_status="broken", error_message=f"Connection/DNS error: {exc}")
    except requests.RequestException as exc:
        return WebsiteStatusResult(input_url=url, normalized_url=normalized, website_status="unknown_error", error_message=str(exc))

    chain = [item.url for item in response.history] + [response.url]
    final_url = normalize_url(response.url)
    title, text = _extract_title_text(response.text)
    reasons: list[str] = []

    if response.status_code >= 500:
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=final_url,
            website_status="broken",
            http_status=response.status_code,
            redirect_chain=chain,
            title=title,
            text_snippet=text[:500],
            detected_reasons=["Server returned 5xx status"],
        )
    if response.status_code >= 400:
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=final_url,
            website_status="broken",
            http_status=response.status_code,
            redirect_chain=chain,
            title=title,
            text_snippet=text[:500],
            detected_reasons=["Server returned 4xx status"],
        )

    final_host = host_for(final_url)
    original_host = host_for(normalized)
    if final_host and original_host and final_host != original_host:
        if is_social_url(final_url):
            return WebsiteStatusResult(
                input_url=url,
                normalized_url=normalized,
                final_url=final_url,
                website_status="social_only",
                http_status=response.status_code,
                redirect_chain=chain,
                title=title,
                text_snippet=text[:500],
                detected_reasons=["Website redirects to a social profile"],
            )
        if is_external_platform_url(final_url):
            return WebsiteStatusResult(
                input_url=url,
                normalized_url=normalized,
                final_url=final_url,
                website_status="external_platform_only",
                http_status=response.status_code,
                redirect_chain=chain,
                title=title,
                text_snippet=text[:500],
                detected_reasons=["Website redirects to a third-party platform"],
            )
        if not (final_host.endswith(original_host) or original_host.endswith(final_host)):
            reasons.append(f"Redirected from {original_host} to {final_host}")

    combined = f"{title} {text}".lower()
    parked_hits = [phrase for phrase in PARKED_PHRASES if phrase in combined]
    if parked_hits:
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=final_url,
            website_status="parked_domain",
            http_status=response.status_code,
            redirect_chain=chain,
            title=title,
            text_snippet=text[:500],
            detected_reasons=[f"Parked-domain phrase: {parked_hits[0]}"],
        )

    placeholder_hits = [phrase for phrase in PLACEHOLDER_PHRASES if phrase in combined]
    if placeholder_hits:
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=final_url,
            website_status="placeholder",
            http_status=response.status_code,
            redirect_chain=chain,
            title=title,
            text_snippet=text[:500],
            detected_reasons=[f"Placeholder phrase: {placeholder_hits[0]}"],
        )

    word_count = len(text.split())
    if word_count < 45:
        return WebsiteStatusResult(
            input_url=url,
            normalized_url=normalized,
            final_url=final_url,
            website_status="thin_site",
            http_status=response.status_code,
            redirect_chain=chain,
            title=title,
            text_snippet=text[:500],
            detected_reasons=[f"Very low text content ({word_count} words)"],
        )

    if reasons:
        status = "redirected_unrelated"
    else:
        status = "live"
    return WebsiteStatusResult(
        input_url=url,
        normalized_url=normalized,
        final_url=final_url,
        website_status=status,
        http_status=response.status_code,
        redirect_chain=chain,
        title=title,
        text_snippet=text[:500],
        detected_reasons=reasons,
    )


def _extract_title_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    return title[:180], text
