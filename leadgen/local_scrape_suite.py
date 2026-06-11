from __future__ import annotations

import argparse
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .ai_email_enrichment import (
    EMAIL_RE,
    clean_email,
    compact_text,
    decode_cfemail,
    host_for,
    normalize_obfuscated,
    valid_owned_website,
)


OUTPUT_DIR = Path("local_scrape_runs")

BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "dd",
    "div",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
    "td",
    "th",
}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

SKIP_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".otf",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rss",
    ".svg",
    ".tar",
    ".tif",
    ".tiff",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}

TECHNICAL_PATH_PARTS = (
    "/wp-json",
    "/xmlrpc",
    "/cdn-cgi/",
    "/feed",
    "/comments/",
)


@dataclass
class TextLine:
    text: str
    tag: str
    heading: str


@dataclass
class EmailEvidenceSet:
    email: str
    source_url: str
    page_title: str
    page_header: str
    section_header: str
    matched_line: str
    nearby_lines: List[str]
    source_kind: str


@dataclass
class PageRecord:
    url: str
    depth: int
    status: str
    http_status: int = 0
    title: str = ""
    page_header: str = ""
    links_found: int = 0
    internal_links_queued: int = 0
    emails_found: int = 0
    error: str = ""


@dataclass
class CrawlReport:
    root_url: str
    host: str
    pages: List[PageRecord] = field(default_factory=list)
    evidence_sets: List[EmailEvidenceSet] = field(default_factory=list)
    skipped_external: Set[str] = field(default_factory=set)
    skipped_assets: Set[str] = field(default_factory=set)
    stopped_reason: str = "completed"
    duration_seconds: float = 0.0

    @property
    def unique_emails(self) -> List[str]:
        return sorted({item.email for item in self.evidence_sets})


def canonicalize_url(url: str, base_url: str = "") -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if base_url:
        value = urljoin(base_url, value)
    if value.startswith(("mailto:", "tel:", "javascript:", "sms:")):
        return ""
    parsed = urlparse(value)
    if not parsed.scheme:
        value = "https://" + value
        parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            unquote(path),
            "",
            "",
            "",
        )
    )


def _path_has_skipped_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


def _path_is_technical(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(part in path for part in TECHNICAL_PATH_PARTS)


def is_allowed_internal_url(url: str, root_host: str, allow_subdomains: bool = False) -> bool:
    host = host_for(url)
    if host == root_host:
        return True
    return allow_subdomains and host.endswith("." + root_host)


def should_queue_url(url: str, root_host: str, allow_subdomains: bool = False) -> Tuple[bool, str]:
    if not url:
        return False, "empty"
    if not is_allowed_internal_url(url, root_host, allow_subdomains=allow_subdomains):
        return False, "external"
    if _path_has_skipped_extension(url):
        return False, "asset"
    if _path_is_technical(url):
        return False, "technical"
    return True, ""


def fetch_html(session: requests.Session, url: str, timeout: int) -> Tuple[str, str, int, str]:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; LeadsGeneratorLocalScrapeSuite/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.8,*/*;q=0.5",
        },
    )
    final_url = canonicalize_url(response.url or url)
    content_type = response.headers.get("content-type", "").lower()
    response.raise_for_status()
    if content_type and "text/html" not in content_type and "text/plain" not in content_type:
        return "", final_url, response.status_code, content_type
    return response.text or "", final_url, response.status_code, content_type


def page_title_and_header(soup: BeautifulSoup) -> Tuple[str, str]:
    title = ""
    if soup.title and soup.title.string:
        title = compact_text(soup.title.string, 160)
    first_heading = soup.find(["h1", "h2"])
    header = compact_text(first_heading.get_text(" ", strip=True), 180) if first_heading else ""
    return title, header


def clean_soup(soup: BeautifulSoup) -> None:
    for tag in soup.select("script, style, noscript, svg, canvas, iframe"):
        tag.decompose()


def _dedupe_lines(lines: Iterable[TextLine]) -> List[TextLine]:
    seen: Set[str] = set()
    result: List[TextLine] = []
    for line in lines:
        key = line.text.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(line)
    return result


def extract_text_lines(soup: BeautifulSoup) -> List[TextLine]:
    lines: List[TextLine] = []
    current_heading = ""
    for tag in soup.find_all(list(BLOCK_TAGS)):
        name = (tag.name or "").lower()
        text = compact_text(tag.get_text(" ", strip=True), 900)
        if not text:
            continue
        if name in HEADING_TAGS:
            current_heading = text
            lines.append(TextLine(text=text, tag=name, heading=current_heading))
            continue
        lines.append(TextLine(text=text, tag=name, heading=current_heading))
    return _dedupe_lines(lines)


def _nearby_lines(lines: List[TextLine], index: int, radius: int = 3) -> List[str]:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return [lines[position].text for position in range(start, end)]


def _add_evidence(
    evidence_sets: List[EmailEvidenceSet],
    seen: Set[Tuple[str, str, str]],
    email: str,
    source_url: str,
    page_title: str,
    page_header: str,
    section_header: str,
    matched_line: str,
    nearby_lines: List[str],
    source_kind: str,
) -> None:
    clean = clean_email(email)
    if not clean:
        return
    key = (clean, source_url, matched_line[:160].lower())
    if key in seen:
        return
    seen.add(key)
    evidence_sets.append(
        EmailEvidenceSet(
            email=clean,
            source_url=source_url,
            page_title=page_title,
            page_header=page_header,
            section_header=section_header,
            matched_line=compact_text(matched_line, 700),
            nearby_lines=[compact_text(line, 700) for line in nearby_lines if line],
            source_kind=source_kind,
        )
    )


def extract_email_evidence(html: str, source_url: str) -> Tuple[List[EmailEvidenceSet], List[str], str, str]:
    soup = BeautifulSoup(html or "", "html.parser")
    clean_soup(soup)
    page_title, page_header = page_title_and_header(soup)
    lines = extract_text_lines(soup)
    evidence_sets: List[EmailEvidenceSet] = []
    seen: Set[Tuple[str, str, str]] = set()

    for index, line in enumerate(lines):
        normalized = normalize_obfuscated(unescape(line.text))
        for match in EMAIL_RE.finditer(normalized):
            email = match.group(1)
            _add_evidence(
                evidence_sets,
                seen,
                email,
                source_url,
                page_title,
                page_header,
                line.heading,
                line.text,
                _nearby_lines(lines, index),
                "visible_text",
            )

    for tag in soup.select("a[href^='mailto:']"):
        href = str(tag.get("href") or "")
        raw_email = href.split(":", 1)[-1].split("?", 1)[0]
        parent = tag.find_parent(list(BLOCK_TAGS)) or tag.parent or tag
        parent_text = compact_text(parent.get_text(" ", strip=True), 900)
        heading = _closest_previous_heading(tag)
        _add_evidence(
            evidence_sets,
            seen,
            raw_email,
            source_url,
            page_title,
            page_header,
            heading,
            parent_text or tag.get_text(" ", strip=True) or raw_email,
            [parent_text] if parent_text else [raw_email],
            "mailto",
        )

    for tag in soup.select("[data-cfemail]"):
        decoded = decode_cfemail(str(tag.get("data-cfemail") or ""))
        if decoded:
            parent = tag.find_parent(list(BLOCK_TAGS)) or tag.parent or tag
            parent_text = compact_text(parent.get_text(" ", strip=True), 900)
            _add_evidence(
                evidence_sets,
                seen,
                decoded,
                source_url,
                page_title,
                page_header,
                _closest_previous_heading(tag),
                parent_text or decoded,
                [parent_text] if parent_text else [decoded],
                "cloudflare",
            )

    links = extract_internal_links(html, source_url)
    return evidence_sets, links, page_title, page_header


def _closest_previous_heading(tag) -> str:
    for previous in tag.find_all_previous(list(HEADING_TAGS), limit=5):
        text = compact_text(previous.get_text(" ", strip=True), 220)
        if text:
            return text
    return ""


def extract_internal_links(html: str, source_url: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    links: List[str] = []
    for tag in soup.select("a[href]"):
        url = canonicalize_url(str(tag.get("href") or ""), source_url)
        if url and url not in links:
            links.append(url)
    return links


def sitemap_urls(session: requests.Session, root_url: str, root_host: str, timeout: int, allow_subdomains: bool) -> List[str]:
    parsed = urlparse(root_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml"]
    found: List[str] = []
    seen_sitemaps: Set[str] = set()
    loc_re = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)

    def fetch_sitemap(sitemap_url: str, depth: int = 0) -> None:
        if sitemap_url in seen_sitemaps or depth > 2:
            return
        seen_sitemaps.add(sitemap_url)
        try:
            response = session.get(sitemap_url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code >= 400:
                return
        except requests.RequestException:
            return
        for match in loc_re.finditer(response.text or ""):
            url = canonicalize_url(unescape(match.group(1)))
            if urlparse(url).path.lower().endswith(".xml"):
                fetch_sitemap(url, depth + 1)
                continue
            allowed, reason = should_queue_url(url, root_host, allow_subdomains=allow_subdomains)
            if allowed and url not in found:
                found.append(url)
            elif reason == "asset":
                continue

    for sitemap_url in candidates:
        fetch_sitemap(sitemap_url)
    return found


def crawl_site(
    website_url: str,
    max_pages: int = 100,
    max_depth: int = 5,
    timeout: int = 8,
    max_seconds: int = 180,
    allow_subdomains: bool = False,
) -> CrawlReport:
    started = time.monotonic()
    root_url = valid_owned_website(website_url)
    if not root_url:
        return CrawlReport(root_url="", host="", stopped_reason="invalid website URL")

    root_host = host_for(root_url)
    report = CrawlReport(root_url=root_url, host=root_host)
    session = requests.Session()
    queue: Deque[Tuple[str, int]] = deque([(root_url, 0)])
    queued: Set[str] = {root_url}
    visited: Set[str] = set()

    for sitemap_url in sitemap_urls(session, root_url, root_host, timeout, allow_subdomains):
        if sitemap_url not in queued:
            queue.append((sitemap_url, 1))
            queued.add(sitemap_url)

    evidence_seen: Set[Tuple[str, str, str]] = set()
    while queue:
        if len(visited) >= max_pages:
            report.stopped_reason = f"max_pages reached ({max_pages})"
            break
        if time.monotonic() - started > max_seconds:
            report.stopped_reason = f"max_seconds reached ({max_seconds})"
            break

        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        allowed, reason = should_queue_url(url, root_host, allow_subdomains=allow_subdomains)
        if not allowed:
            if reason == "external":
                report.skipped_external.add(url)
            elif reason == "asset":
                report.skipped_assets.add(url)
            continue

        record = PageRecord(url=url, depth=depth, status="fetched")
        try:
            html, final_url, status_code, content_type = fetch_html(session, url, timeout)
            record.http_status = status_code
            if final_url and final_url != url:
                final_allowed, final_reason = should_queue_url(final_url, root_host, allow_subdomains=allow_subdomains)
                if not final_allowed:
                    record.status = "skipped_after_redirect"
                    record.error = final_reason
                    report.pages.append(record)
                    continue
                record.url = final_url
            if not html:
                record.status = "skipped_non_html"
                record.error = content_type
                report.pages.append(record)
                continue
        except requests.RequestException as exc:
            record.status = "error"
            record.error = str(exc)
            report.pages.append(record)
            continue

        evidence, links, title, header = extract_email_evidence(html, record.url)
        record.title = title
        record.page_header = header
        record.links_found = len(links)
        record.emails_found = len({item.email for item in evidence})
        for item in evidence:
            key = (item.email, item.source_url, item.matched_line[:160].lower())
            if key not in evidence_seen:
                evidence_seen.add(key)
                report.evidence_sets.append(item)

        if depth < max_depth:
            queued_before = len(queued)
            for link in links:
                allowed, reason = should_queue_url(link, root_host, allow_subdomains=allow_subdomains)
                if not allowed:
                    if reason == "external" and len(report.skipped_external) < 100:
                        report.skipped_external.add(link)
                    elif reason == "asset" and len(report.skipped_assets) < 100:
                        report.skipped_assets.add(link)
                    continue
                if link not in visited and link not in queued:
                    queue.append((link, depth + 1))
                    queued.add(link)
            record.internal_links_queued = len(queued) - queued_before

        report.pages.append(record)

    report.duration_seconds = round(time.monotonic() - started, 2)
    return report


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")
    return cleaned[:90] or "site"


def write_report(report: CrawlReport, output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{stamp}_{safe_filename(report.host)}.txt"
    lines: List[str] = []
    lines.append("LOCAL WEBSITE EMAIL SCRAPE REPORT")
    lines.append("=" * 80)
    lines.append(f"Root URL: {report.root_url}")
    lines.append(f"Host: {report.host}")
    lines.append(f"Duration: {report.duration_seconds}s")
    lines.append(f"Stopped Reason: {report.stopped_reason}")
    lines.append(f"Pages Visited: {len(report.pages)}")
    lines.append(f"Unique Emails: {len(report.unique_emails)}")
    lines.append("")
    lines.append("UNIQUE EMAILS")
    lines.append("-" * 80)
    for email in report.unique_emails:
        lines.append(email)
    if not report.unique_emails:
        lines.append("(none)")
    lines.append("")
    lines.append("PAGES VISITED")
    lines.append("-" * 80)
    for index, page in enumerate(report.pages, start=1):
        lines.append(f"{index}. [{page.status}] depth={page.depth} status={page.http_status} emails={page.emails_found} links={page.links_found} queued={page.internal_links_queued}")
        lines.append(f"   URL: {page.url}")
        if page.title:
            lines.append(f"   Title: {page.title}")
        if page.page_header:
            lines.append(f"   Header: {page.page_header}")
        if page.error:
            lines.append(f"   Error: {page.error}")
    lines.append("")
    lines.append("EMAIL + DATA SETS FOR AI")
    lines.append("-" * 80)
    if not report.evidence_sets:
        lines.append("(none)")
    for index, item in enumerate(report.evidence_sets, start=1):
        lines.append(f"SET {index}")
        lines.append(f"Email: {item.email}")
        lines.append(f"Source URL: {item.source_url}")
        lines.append(f"Source Kind: {item.source_kind}")
        lines.append(f"Page Title: {item.page_title}")
        lines.append(f"Page Header: {item.page_header}")
        lines.append(f"Section/Header Near Email: {item.section_header}")
        lines.append(f"Matched Line: {item.matched_line}")
        lines.append("Nearby Lines:")
        for nearby in item.nearby_lines:
            lines.append(f"- {nearby}")
        lines.append("")
    lines.append("SKIPPED EXTERNAL LINKS SAMPLE")
    lines.append("-" * 80)
    for url in sorted(report.skipped_external)[:50]:
        lines.append(url)
    if not report.skipped_external:
        lines.append("(none)")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_summary(report: CrawlReport, output_path: Path) -> None:
    print(f"Root: {report.root_url}")
    print(f"Pages visited: {len(report.pages)}")
    print(f"Unique emails found: {len(report.unique_emails)}")
    if report.unique_emails:
        print("Emails:")
        for email in report.unique_emails:
            print(f"  - {email}")
    else:
        print("Emails: none")
    print(f"Evidence sets: {len(report.evidence_sets)}")
    print(f"Report: {output_path}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Local same-domain website email scraping test suite.")
    parser.add_argument("website", help="Website URL or domain to crawl.")
    parser.add_argument("--max-pages", type=int, default=100, help="Maximum HTML pages to fetch.")
    parser.add_argument("--max-depth", type=int, default=5, help="Maximum internal link depth.")
    parser.add_argument("--timeout", type=int, default=8, help="Per-request timeout in seconds.")
    parser.add_argument("--max-seconds", type=int, default=180, help="Whole-crawl time cap in seconds.")
    parser.add_argument("--allow-subdomains", action="store_true", help="Allow subdomains under the starting host.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Directory for text reports.")
    args = parser.parse_args(argv)

    report = crawl_site(
        args.website,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        timeout=args.timeout,
        max_seconds=args.max_seconds,
        allow_subdomains=args.allow_subdomains,
    )
    output_path = write_report(report, Path(args.output_dir))
    print_summary(report, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
