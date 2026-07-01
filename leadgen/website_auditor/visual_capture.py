from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import Settings
from .models import PageAuditResult
from .playwright_compat import ensure_windows_playwright_loop
from .url_utils import slugify


LogFn = Callable[[str, Dict], None]


def capture_minimal_screenshots(
    business_name: str,
    home_url: str,
    pages: List[PageAuditResult],
    settings: Settings,
    emit: Optional[LogFn] = None,
) -> List[str]:
    emit = emit or (lambda _event, _payload: None)
    if not home_url:
        return []

    lead_slug = slugify(business_name or home_url)
    lead_dir = settings.screenshots_dir / lead_slug
    lead_dir.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []

    contact_or_booking = next((p for p in pages if p.page_type in {"contact", "booking"}), None)
    should_capture_conversion = _should_capture_conversion_path(pages)

    targets = [
        ("mobile_home_above_fold", home_url, {"width": 390, "height": 844}, lead_dir / "mobile_home.png"),
        ("desktop_home_above_fold", home_url, {"width": 1440, "height": 900}, lead_dir / "desktop_home.png"),
    ]
    if should_capture_conversion and contact_or_booking:
        targets.append(
            (
                "mobile_contact_or_booking_page",
                contact_or_booking.final_url or contact_or_booking.url,
                {"width": 390, "height": 844},
                lead_dir / "mobile_contact_or_booking.png",
            )
        )

    try:
        ensure_windows_playwright_loop()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.headless)
            for label, url, viewport, path in targets:
                emit("screenshot.capture", {"label": label, "url": url, "path": str(path)})
                page = browser.new_page(viewport=viewport, user_agent=settings.user_agent, ignore_https_errors=True)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=settings.playwright_timeout_ms)
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        pass
                    page.screenshot(path=str(path), full_page=False)
                    saved.append(str(path))
                except Exception as exc:
                    emit("screenshot.error", {"label": label, "url": url, "error": str(exc)})
                finally:
                    page.close()
            browser.close()
    except ImportError as exc:
        emit(
            "screenshot.error",
            {"error": f"Playwright is not installed. Run: pip install -r requirements.txt && python -m playwright install chromium ({exc})"},
        )
    return saved


def _should_capture_conversion_path(pages: List[PageAuditResult]) -> bool:
    home = next((page for page in pages if page.page_type == "home"), pages[0] if pages else None)
    if not home:
        return False
    homepage_is_decent_or_borderline = home.word_count >= 80 and not home.mobile_horizontal_overflow
    conversion_path_exists = any(page.page_type in {"contact", "booking"} for page in pages)
    cta_exists = any(page.cta_buttons_present or page.visible_cta_above_fold for page in pages)
    return homepage_is_decent_or_borderline and conversion_path_exists and cta_exists
