from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from .config import Settings
from .models import CrawlResult, PageAuditResult
from .playwright_compat import ensure_windows_playwright_loop
from .technical_checks import CTA_WORDS, check_broken_internal_links, classify_page_type, extract_page_metrics
from .url_utils import absolute_url, same_site


LogFn = Callable[[str, Dict], None]

PRIORITY_KEYWORDS = {
    "contact": 100,
    "book": 95,
    "booking": 95,
    "appointment": 95,
    "reservation": 92,
    "reserve": 92,
    "order": 90,
    "services": 82,
    "service": 82,
    "menu": 82,
    "treatments": 82,
    "products": 78,
    "about": 60,
}


def crawl_site(start_url: str, settings: Settings, emit: Optional[LogFn] = None) -> CrawlResult:
    emit = emit or (lambda _event, _payload: None)
    discovered: List[str] = []
    pages: List[PageAuditResult] = []
    screenshots: List[str] = []

    try:
        ensure_windows_playwright_loop()
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.headless)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=settings.user_agent,
                ignore_https_errors=True,
            )
            home_html, home_final, home_result = _visit_page(context, start_url, settings, "home", emit)
            if home_result:
                pages.append(home_result)
            discovered = _discover_priority_links(home_html, home_final or start_url)
            queue = [home_final or start_url] + discovered
            queue = list(dict.fromkeys([url for url in queue if url and same_site(url, start_url)]))
            emit("crawl.discovered_links", {"urls": queue[: settings.max_pages_to_crawl]})

            for url in queue[1: settings.max_pages_to_crawl]:
                page_type = classify_page_type(url)
                _html, _final, result = _visit_page(context, url, settings, page_type, emit)
                if result:
                    pages.append(result)

            browser.close()
    except ImportError:
        return CrawlResult(
            pages=pages,
            discovered_urls=discovered,
            screenshots_saved=screenshots,
            error_message="Playwright is not installed. Run: pip install -r requirements.txt && python -m playwright install chromium",
        )
    except PlaywrightError as exc:
        return CrawlResult(pages=pages, discovered_urls=discovered, screenshots_saved=screenshots, error_message=str(exc))
    except Exception as exc:
        return CrawlResult(pages=pages, discovered_urls=discovered, screenshots_saved=screenshots, error_message=str(exc))

    for page in pages:
        if page.screenshot_path_mobile:
            screenshots.append(page.screenshot_path_mobile)
        if page.screenshot_path_desktop:
            screenshots.append(page.screenshot_path_desktop)
    return CrawlResult(pages=pages, discovered_urls=discovered, screenshots_saved=screenshots)


def _visit_page(context, url: str, settings: Settings, page_type: str, emit: LogFn) -> Tuple[str, str, Optional[PageAuditResult]]:
    page = context.new_page()
    console_errors: List[str] = []
    network_errors: List[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text[:300]) if msg.type == "error" else None)
    page.on("requestfailed", lambda req: network_errors.append(f"{req.url} - {req.failure.get('errorText') if req.failure else 'failed'}"[:500]))

    emit("crawl.visit", {"url": url, "page_type": page_type})
    response = None
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=settings.playwright_timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=min(settings.playwright_timeout_ms, 8000))
        except Exception:
            pass
        html = page.content()
        final_url = page.url
        metrics = extract_page_metrics(html, final_url)
        viewport_checks = _run_viewport_checks(page)
        broken_images = _count_broken_images(page)
        broken_links = check_broken_internal_links(metrics.pop("internal_link_urls", []), settings)
        result = PageAuditResult(
            url=url,
            final_url=final_url,
            page_type=page_type,
            http_status=response.status if response else None,
            console_errors=console_errors[:10],
            network_errors=network_errors[:10],
            broken_internal_links=broken_links[:10],
            broken_image_count=broken_images,
            **metrics,
            **viewport_checks,
        )
        emit("crawl.page_metrics", result.model_dump() if hasattr(result, "model_dump") else result.dict())
        page.close()
        return html, final_url, result
    except Exception as exc:
        emit("crawl.page_error", {"url": url, "error": str(exc)})
        page.close()
        return "", url, PageAuditResult(url=url, final_url=url, page_type=page_type, notes=[str(exc)])


def _discover_priority_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    scored: List[tuple[int, str]] = []
    for tag in soup.select("nav a[href], header a[href], footer a[href], a[href]"):
        href = str(tag.get("href") or "")
        url = absolute_url(base_url, href)
        if not url or not same_site(url, base_url):
            continue
        label = f"{tag.get_text(' ', strip=True)} {href}".lower()
        score = 0
        for keyword, value in PRIORITY_KEYWORDS.items():
            if keyword in label:
                score += value
        if score:
            scored.append((score, url))
    return list(dict.fromkeys(url for _score, url in sorted(scored, key=lambda item: item[0], reverse=True)))


def _run_viewport_checks(page) -> Dict:
    return page.evaluate(
        """
        () => {
          const body = document.body;
          const doc = document.documentElement;
          const vw = Math.max(doc.clientWidth || 0, window.innerWidth || 0);
          const ctaWords = %s;
          const elements = Array.from(document.querySelectorAll('a, button, input[type=button], input[type=submit]'));
          const ctaElements = elements.filter(el => {
            const rect = el.getBoundingClientRect();
            const text = ((el.innerText || el.value || '') + ' ' + (el.href || '')).toLowerCase();
            return rect.top >= 0 && rect.top < 650 && rect.width > 20 && rect.height > 15 && ctaWords.some(w => text.includes(w));
          });
          const aboveFold = ctaElements.length > 0;
          const cookiePanels = Array.from(document.querySelectorAll('body *')).filter(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width < 120 || rect.height < 40) return false;
            const text = (el.innerText || '').toLowerCase();
            const style = window.getComputedStyle(el);
            const fixedLike = ['fixed', 'sticky'].includes(style.position) || rect.bottom > window.innerHeight - 5;
            return fixedLike && text.includes('cookie') && (text.includes('accept') || text.includes('privacy'));
          });
          const overlaps = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
          const cookieBlocksCta = ctaElements.some(cta => {
            const ctaRect = cta.getBoundingClientRect();
            return cookiePanels.some(panel => overlaps(ctaRect, panel.getBoundingClientRect()));
          });
          const smallTapTargets = elements.filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
          }).length;
          const smallFonts = Array.from(document.querySelectorAll('body *')).filter(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return false;
            const size = parseFloat(window.getComputedStyle(el).fontSize || '16');
            return size > 0 && size < 12;
          }).length;
          return {
            visible_cta_above_fold: aboveFold,
            cookie_banner_blocks_cta: cookieBlocksCta,
            mobile_horizontal_overflow: Math.max(body.scrollWidth, doc.scrollWidth) > vw + 4,
            small_tap_targets: smallTapTargets,
            small_font_elements: smallFonts
          };
        }
        """
        % list(CTA_WORDS)
    )


def _count_broken_images(page) -> int:
    return int(
        page.evaluate(
            """
            () => Array.from(document.images).filter(img => !img.complete || img.naturalWidth === 0).length
            """
        )
    )
