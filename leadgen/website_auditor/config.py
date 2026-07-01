from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    max_pages_to_crawl: int = 6
    request_timeout_seconds: int = 12
    playwright_timeout_ms: int = 20000
    enable_llm_visual_audit: bool = False
    enable_pagespeed: bool = False
    openai_api_key: str = ""
    openai_visual_model: str = "gpt-4o-mini"
    output_dir: Path = BASE_DIR / "outputs"
    screenshot_mode: str = "minimal"
    headless: bool = True
    max_broken_links_to_check: int = 20
    user_agent: str = "Mozilla/5.0 (compatible; LeadWebsiteAuditor/0.1)"

    @property
    def screenshots_dir(self) -> Path:
        return self.output_dir / "screenshots"


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    output_dir = Path(os.getenv("OUTPUT_DIR", str(BASE_DIR / "outputs"))).expanduser()
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir
    return Settings(
        max_pages_to_crawl=_int_env("MAX_PAGES_TO_CRAWL", 6),
        request_timeout_seconds=_int_env("REQUEST_TIMEOUT_SECONDS", 12),
        playwright_timeout_ms=_int_env("PLAYWRIGHT_TIMEOUT_MS", 20000),
        enable_llm_visual_audit=_bool_env("ENABLE_LLM_VISUAL_AUDIT", False),
        enable_pagespeed=_bool_env("ENABLE_PAGESPEED", False),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_visual_model=os.getenv("OPENAI_VISUAL_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        output_dir=output_dir,
        screenshot_mode=os.getenv("SCREENSHOT_MODE", "minimal").strip().lower() or "minimal",
        headless=_bool_env("HEADLESS", True),
        max_broken_links_to_check=_int_env("MAX_BROKEN_LINKS_TO_CHECK", 20),
        user_agent=os.getenv("USER_AGENT", "Mozilla/5.0 (compatible; LeadWebsiteAuditor/0.1)").strip(),
    )
