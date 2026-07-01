from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .config import Settings
from .url_utils import absolute_url, same_site


CTA_WORDS = (
    "book",
    "schedule",
    "reserve",
    "order",
    "call",
    "contact",
    "request",
    "quote",
    "appointment",
    "buy",
    "shop",
)

SOCIAL_HOSTS = ("instagram.com", "facebook.com", "tiktok.com", "youtube.com", "linkedin.com")
TRUST_SIGNAL_WORDS = (
    "review",
    "reviews",
    "testimonial",
    "testimonials",
    "gallery",
    "portfolio",
    "before",
    "after",
    "licensed",
    "insured",
    "award",
    "years",
    "established",
    "owner",
    "team",
    "staff",
)


def extract_page_metrics(html: str, url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    h1_tag = soup.find("h1")
    h1 = h1_tag.get_text(" ", strip=True) if h1_tag else ""
    text = " ".join(soup.get_text(" ", strip=True).split())
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    links = [absolute_url(url, str(tag.get("href") or "")) for tag in soup.select("a[href]")]
    links = [link for link in links if link]
    internal = [link for link in links if same_site(link, url)]
    external = [link for link in links if not same_site(link, url)]
    anchors = soup.select("a[href]")
    phone_numbers = _extract_phone_numbers(text, anchors)
    email_addresses = sorted(set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,24}", text, flags=re.I)))
    social_links = sorted({link for link in links if any(host in urlparse(link).netloc.lower() for host in SOCIAL_HOSTS)})
    ctas = _cta_items(soup, url)
    images = soup.select("img")
    missing_alt = [img for img in images if not str(img.get("alt") or "").strip()]
    forms = bool(soup.select("form, input, textarea, select"))
    phone_links = bool(soup.select("a[href^='tel:']"))
    email_links = bool(soup.select("a[href^='mailto:']"))
    cta_buttons = bool(ctas)
    contact_info = phone_links or email_links or bool(re.search(r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", text))
    return {
        "title": title[:180],
        "h1": h1[:180],
        "text_snippet": text[:1200],
        "word_count": len(text.split()),
        "meta_description_present": bool(meta and str(meta.get("content") or "").strip()),
        "internal_links": len(internal),
        "external_links": len(external),
        "images": len(images),
        "images_missing_alt": len(missing_alt),
        "forms_present": forms,
        "generic_contact_form": _has_generic_contact_form(soup),
        "phone_links_present": phone_links,
        "email_links_present": email_links,
        "phone_numbers": phone_numbers,
        "email_addresses": email_addresses[:10],
        "social_links": social_links[:10],
        "cta_labels": [item["label"] for item in ctas][:10],
        "cta_hrefs": [item["href"] for item in ctas if item["href"]][:10],
        "booking_cta_links": [item["href"] for item in ctas if item["is_booking"]][:10],
        "brand_candidates": _brand_candidates(soup, title, h1),
        "trust_signals": _trust_signals(text),
        "cta_buttons_present": cta_buttons,
        "contact_info_present": contact_info,
        "internal_link_urls": list(dict.fromkeys(internal)),
    }


def _cta_items(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for tag in soup.select("a, button, input[type='button'], input[type='submit']"):
        raw_label = " ".join([str(tag.get("value") or ""), tag.get_text(" ", strip=True), str(tag.get("aria-label") or "")])
        label = _compact_label(raw_label)
        text = label.lower()
        href = str(tag.get("href") or "").lower()
        if any(word in text or word in href for word in CTA_WORDS):
            items.append(
                {
                    "label": label or str(tag.get("value") or "").strip() or tag.name,
                    "href": absolute_url(base_url, str(tag.get("href") or "")) or str(tag.get("href") or ""),
                    "is_booking": any(word in text or word in href for word in ("book", "schedule", "appointment", "reserve", "reservation", "order")),
                }
            )
    return items


def _extract_phone_numbers(text: str, anchors) -> List[str]:
    values = set()
    for tag in anchors:
        href = str(tag.get("href") or "")
        if href.lower().startswith("tel:"):
            values.add(_normalize_phone(href.split(":", 1)[1]))
    for match in re.finditer(r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", text):
        values.add(_normalize_phone(match.group(0)))
    return sorted(value for value in values if value)


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def _has_generic_contact_form(soup: BeautifulSoup) -> bool:
    for form in soup.select("form"):
        text = form.get_text(" ", strip=True).lower()
        inputs = " ".join(
            " ".join(str(tag.get(attr) or "") for attr in ("name", "type", "placeholder", "value")).lower()
            for tag in form.select("input, textarea, select, button")
        )
        blob = f"{text} {inputs}"
        has_generic_words = any(word in blob for word in ("attach files", "attachment", "what services are you interested", "send"))
        has_booking_words = any(word in blob for word in ("date", "time", "appointment", "booking", "service requested"))
        if has_generic_words and not has_booking_words:
            return True
    return False


def _brand_candidates(soup: BeautifulSoup, title: str, h1: str) -> List[str]:
    candidates: List[str] = []
    meta_site = soup.find("meta", attrs={"property": re.compile("site_name$", re.I)})
    for value in (title, h1, str(meta_site.get("content") if meta_site else "")):
        value = _compact_label(value)
        if value:
            candidates.append(value)
    for tag in soup.select("header a, nav a, [class*='logo'], [class*='brand']"):
        label = _compact_label(tag.get_text(" ", strip=True))
        if label and len(label) <= 80:
            candidates.append(label)
    return list(dict.fromkeys(candidates))[:8]


def _trust_signals(text: str) -> List[str]:
    lower = text.lower()
    return [word for word in TRUST_SIGNAL_WORDS if re.search(rf"\b{re.escape(word)}\b", lower)][:10]


def _compact_label(value: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    text = " ".join(text.split())
    if not text:
        return ""
    # GoDaddy templates can duplicate logo text multiple times inside one anchor.
    for size in range(1, max(2, len(text.split()) // 2 + 1)):
        words = text.split()
        if len(words) >= size * 2 and len(words) % size == 0:
            chunk = words[:size]
            if all(words[index : index + size] == chunk for index in range(0, len(words), size)):
                text = " ".join(chunk)
                break
    phrase_match = re.match(r"^(.{3,40}?)\1+$", text, flags=re.I)
    if phrase_match:
        text = phrase_match.group(1).strip()
    return text[:120]


def check_broken_internal_links(urls: List[str], settings: Settings) -> List[str]:
    broken: List[str] = []
    session = requests.Session()
    headers = {"User-Agent": settings.user_agent}
    for url in list(dict.fromkeys(urls))[: settings.max_broken_links_to_check]:
        try:
            response = session.head(url, timeout=settings.request_timeout_seconds, allow_redirects=True, headers=headers)
            if response.status_code in {405, 403}:
                response = session.get(url, timeout=settings.request_timeout_seconds, allow_redirects=True, headers=headers)
            if response.status_code >= 400:
                broken.append(f"{url} returned HTTP {response.status_code}")
        except requests.RequestException as exc:
            broken.append(f"{url} failed: {exc.__class__.__name__}")
    return broken


def classify_page_type(url: str, label: str = "") -> str:
    blob = f"{urlparse(url).path} {label}".lower()
    if any(word in blob for word in ("contact", "location", "visit")):
        return "contact"
    if any(word in blob for word in ("book", "booking", "appointment", "reservation", "reserve", "order")):
        return "booking"
    if any(word in blob for word in ("service", "menu", "treatment", "product")):
        return "services"
    if any(word in blob for word in ("about", "team", "story")):
        return "about"
    return "home" if urlparse(url).path in {"", "/"} else "other"
