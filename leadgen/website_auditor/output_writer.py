from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from .models import FinalLeadAuditResult, model_to_dict


def write_outputs(results: Iterable[FinalLeadAuditResult], output_csv: Path) -> tuple[Path, Path]:
    full_rows = [model_to_dict(result) for result in results]
    csv_rows = [_flatten(row) for row in full_rows]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_json = output_csv.with_suffix(".json")
    pd.DataFrame(csv_rows).to_csv(output_csv, index=False)
    output_json.write_text(json.dumps(full_rows, indent=2, ensure_ascii=True), encoding="utf-8")
    return output_csv, output_json


def _flatten(row: dict) -> dict:
    flattened = dict(row)
    for key in ("top_verified_issues", "top_subjective_issues", "screenshots_saved"):
        flattened[key] = json.dumps(flattened.get(key) or [], ensure_ascii=True)
    flattened["debug"] = json.dumps(flattened.get("debug") or {}, ensure_ascii=True)
    return flattened
