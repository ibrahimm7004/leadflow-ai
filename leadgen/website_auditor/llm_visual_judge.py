from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import BASE_DIR, Settings
from .models import PageAuditResult, VisualAuditResult


LogFn = Callable[[str, Dict], None]


def run_visual_audit(
    business_name: str,
    business_category: str,
    screenshots: List[str],
    pages: List[PageAuditResult],
    settings: Settings,
    emit: Optional[LogFn] = None,
) -> VisualAuditResult:
    emit = emit or (lambda _event, _payload: None)
    prompt = _build_prompt(business_name, business_category, pages)
    if not settings.enable_llm_visual_audit:
        return VisualAuditResult(
            visual_score=_heuristic_visual_score(pages),
            design_status="unknown",
            mobile_usability_score=_heuristic_mobile_score(pages),
            conversion_score=_heuristic_conversion_score(pages),
            pitch_confidence="low",
            recommended_visual_pitch_angle="LLM visual audit disabled; using automated checks only.",
            llm_prompt=prompt,
        )
    if not settings.openai_api_key:
        return VisualAuditResult(
            visual_score=_heuristic_visual_score(pages),
            design_status="unknown",
            mobile_usability_score=_heuristic_mobile_score(pages),
            conversion_score=_heuristic_conversion_score(pages),
            pitch_confidence="low",
            recommended_visual_pitch_angle="OPENAI_API_KEY missing; using automated checks only.",
            llm_prompt=prompt,
            llm_error="OPENAI_API_KEY missing",
        )
    if not screenshots:
        return VisualAuditResult(
            visual_score=_heuristic_visual_score(pages),
            design_status="unknown",
            mobile_usability_score=_heuristic_mobile_score(pages),
            conversion_score=_heuristic_conversion_score(pages),
            pitch_confidence="low",
            recommended_visual_pitch_angle="No screenshots captured; using automated checks only.",
            llm_prompt=prompt,
        )

    content = [{"type": "input_text", "text": prompt}]
    for path in screenshots[:3]:
        image = _image_data_url(Path(path))
        if image:
            content.append({"type": "input_image", "image_url": image})

    emit(
        "llm.request",
        {
            "model": settings.openai_visual_model,
            "prompt": prompt,
            "screenshots": screenshots[:3],
            "note": "Image payload sent as base64 data URLs; app displays screenshot files instead of dumping large base64 strings.",
        },
    )
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=settings.openai_visual_model,
            input=[{"role": "user", "content": content}],
            max_output_tokens=1400,
        )
        raw = getattr(response, "output_text", "") or ""
        emit("llm.response", {"model": settings.openai_visual_model, "raw_response": raw})
        data = _parse_json(raw)
        result = VisualAuditResult(**data)
        result.llm_model = settings.openai_visual_model
        result.llm_prompt = prompt
        result.llm_raw_response = raw
        return result
    except Exception as exc:
        emit("llm.error", {"error": str(exc)})
        return VisualAuditResult(
            visual_score=_heuristic_visual_score(pages),
            design_status="unknown",
            mobile_usability_score=_heuristic_mobile_score(pages),
            conversion_score=_heuristic_conversion_score(pages),
            pitch_confidence="low",
            recommended_visual_pitch_angle="LLM visual audit failed; using automated checks only.",
            llm_model=settings.openai_visual_model,
            llm_prompt=prompt,
            llm_error=str(exc),
        )


def _build_prompt(business_name: str, business_category: str, pages: List[PageAuditResult]) -> str:
    prompt_path = BASE_DIR / "prompts" / "visual_audit_prompt.txt"
    base = prompt_path.read_text(encoding="utf-8")
    page_findings = [
        {
            "url": page.final_url or page.url,
            "page_type": page.page_type,
            "title": page.title,
            "word_count": page.word_count,
            "meta_description_present": page.meta_description_present,
            "images_missing_alt": page.images_missing_alt,
            "broken_image_count": page.broken_image_count,
            "console_error_count": len(page.console_errors),
            "network_error_count": len(page.network_errors),
            "broken_internal_links": page.broken_internal_links[:5],
            "forms_present": page.forms_present,
            "generic_contact_form": page.generic_contact_form,
            "phone_links_present": page.phone_links_present,
            "email_links_present": page.email_links_present,
            "phone_numbers": page.phone_numbers,
            "email_addresses": page.email_addresses,
            "social_links": page.social_links,
            "cta_labels": page.cta_labels,
            "cta_hrefs": page.cta_hrefs,
            "booking_cta_links": page.booking_cta_links,
            "brand_candidates": page.brand_candidates,
            "trust_signals": page.trust_signals,
            "cta_buttons_present": page.cta_buttons_present,
            "visible_cta_above_fold": page.visible_cta_above_fold,
            "cookie_banner_blocks_cta": page.cookie_banner_blocks_cta,
            "mobile_horizontal_overflow": page.mobile_horizontal_overflow,
            "small_tap_targets": page.small_tap_targets,
            "small_font_elements": page.small_font_elements,
            "contact_info_present": page.contact_info_present,
        }
        for page in pages
    ]
    return base.replace("{{business_name}}", business_name or "Unknown business").replace(
        "{{business_category}}", business_category or "Unknown category"
    ).replace("{{structured_findings_json}}", json.dumps(page_findings, indent=2, ensure_ascii=True))


def _image_data_url(path: Path) -> str:
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except OSError:
        return ""


def _parse_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _heuristic_visual_score(pages: List[PageAuditResult]) -> int:
    home = pages[0] if pages else None
    if not home:
        return 0
    score = 70
    if home.mobile_horizontal_overflow:
        score -= 20
    if home.small_font_elements > 15:
        score -= 8
    if home.small_tap_targets > 20:
        score -= 8
    if not home.visible_cta_above_fold:
        score -= 10
    if home.word_count < 80:
        score -= 10
    return max(0, min(100, score))


def _heuristic_mobile_score(pages: List[PageAuditResult]) -> int:
    home = pages[0] if pages else None
    if not home:
        return 0
    score = 80
    if home.mobile_horizontal_overflow:
        score -= 35
    score -= min(20, home.small_tap_targets // 2)
    score -= min(15, home.small_font_elements // 3)
    return max(0, min(100, score))


def _heuristic_conversion_score(pages: List[PageAuditResult]) -> int:
    score = 45
    if any(page.visible_cta_above_fold for page in pages):
        score += 20
    if any(page.forms_present for page in pages):
        score += 10
    if any(page.phone_links_present or page.email_links_present for page in pages):
        score += 15
    if any(page.page_type in {"contact", "booking"} for page in pages):
        score += 10
    return max(0, min(100, score))
