from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from .config import Settings, load_settings
from .crawler import crawl_site
from .email_scoring import score_email
from .lead_scoring import score_final_lead
from .llm_visual_judge import run_visual_audit
from .models import CrawlResult, FinalLeadAuditResult, LeadInput, WebsiteStatusResult, model_to_dict
from .output_writer import write_outputs
from .visual_capture import capture_minimal_screenshots
from .website_status import check_website_status


LogFn = Callable[[str, Dict], None]


def audit_lead(lead: LeadInput, settings: Settings, emit: Optional[LogFn] = None) -> FinalLeadAuditResult:
    emit = emit or (lambda _event, _payload: None)
    emit("lead.start", model_to_dict(lead))
    try:
        status = check_website_status(lead.website, settings)
        emit("status.result", model_to_dict(status))

        email_score = score_email(lead)
        emit("email.score", model_to_dict(email_score))

        crawl = CrawlResult()
        visual = None
        if status.website_status in {"live", "thin_site"}:
            crawl = crawl_site(status.final_url or status.normalized_url, settings, emit)
            home_url = crawl.pages[0].final_url if crawl.pages else status.final_url
            screenshots = []
            if not crawl.error_message or crawl.pages:
                screenshots = capture_minimal_screenshots(lead.business_name, home_url, crawl.pages, settings, emit)
            crawl.screenshots_saved = screenshots
            emit("screenshot.saved", {"paths": screenshots})
            visual = run_visual_audit(lead.business_name, lead.business_category, screenshots, crawl.pages, settings, emit)
            emit("visual.result", model_to_dict(visual))
        else:
            visual = run_visual_audit(lead.business_name, lead.business_category, [], [], settings, emit)
            emit("visual.skipped", {"reason": f"Website status is {status.website_status}", "heuristic_result": model_to_dict(visual)})

        result = score_final_lead(lead, status, crawl, visual, email_score)
        emit("lead.result", model_to_dict(result))
        return result
    except Exception as exc:
        emit("lead.error", {"error": str(exc)})
        fallback_status = WebsiteStatusResult(input_url=lead.website, normalized_url=lead.website, website_status="unknown_error", error_message=str(exc))
        result = FinalLeadAuditResult(
            business_name=lead.business_name,
            business_category=lead.business_category,
            website=lead.website,
            final_url="",
            website_status=fallback_status.website_status,
            email=lead.email,
            audit_status="failed",
            error_message=str(exc),
        )
        return result


def load_leads(path: Path) -> List[LeadInput]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("leads", [])
        return [LeadInput.from_row(row) for row in data]
    frame = pd.read_csv(path).fillna("")
    return [LeadInput.from_row(row.to_dict()) for _idx, row in frame.iterrows()]


def audit_file(input_path: Path, output_csv: Path, settings: Settings, emit: Optional[LogFn] = None) -> List[FinalLeadAuditResult]:
    leads = load_leads(input_path)
    results: List[FinalLeadAuditResult] = []
    for index, lead in enumerate(leads, start=1):
        if emit:
            emit("batch.progress", {"index": index, "total": len(leads), "business_name": lead.business_name})
        results.append(audit_lead(lead, settings, emit))
    write_outputs(results, output_csv)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit business websites and score outreach opportunity.")
    parser.add_argument("--input", default="data/input_leads.csv", help="CSV or JSON input file.")
    parser.add_argument("--output", default="outputs/audit_results.csv", help="Output CSV path. JSON is written beside it.")
    parser.add_argument("--enable-llm", action="store_true", help="Enable OpenAI vision audit for screenshots.")
    parser.add_argument("--no-llm", action="store_true", help="Disable OpenAI vision audit even if env enables it.")
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.enable_llm:
        settings = Settings(**{**settings.__dict__, "enable_llm_visual_audit": True})
    if args.no_llm:
        settings = Settings(**{**settings.__dict__, "enable_llm_visual_audit": False})

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    def print_log(event: str, payload: Dict) -> None:
        if event in {"lead.start", "status.result", "email.score", "crawl.visit", "crawl.page_error", "screenshot.capture", "llm.request", "llm.response", "lead.result", "batch.progress"}:
            print(json.dumps({"event": event, "payload": payload}, ensure_ascii=True, default=str))

    results = audit_file(input_path, output_path, settings, print_log)
    print(f"Wrote {len(results)} result(s) to {output_path} and {output_path.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
