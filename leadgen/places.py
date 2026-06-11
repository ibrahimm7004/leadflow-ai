from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import requests

from .constants import FIELD_MASK, PAGE_SIZE, PLACES_TEXT_SEARCH_URL


class PlacesApiError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _clean_search_params(search_params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not search_params:
        return {}
    return {
        key: value
        for key, value in search_params.items()
        if value not in (None, "", [], {})
    }


def _request_page(
    api_key: str,
    query: str,
    page_token: Optional[str],
    search_params: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    payload: Dict[str, Any] = {
        "textQuery": query,
        "pageSize": PAGE_SIZE,
        **_clean_search_params(search_params),
    }
    if page_token:
        payload["pageToken"] = page_token

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    response = requests.post(
        PLACES_TEXT_SEARCH_URL, headers=headers, data=json.dumps(payload), timeout=30)
    if response.status_code != 200:
        try:
            data = response.json()
            message = (data.get("error") or {}).get("message") or response.text
        except ValueError:
            message = response.text
        raise PlacesApiError(response.status_code, message)

    data = response.json()
    return data.get("places", []) or [], data.get("nextPageToken")


def build_results(
    api_key: str,
    query: str,
    limit: int,
    max_pages: int,
    leads_seen_ids: set[str],
    details_seen_ids: set[str],
    start_page_token: Optional[str] = None,
    search_params: Optional[Dict[str, Any]] = None,
    candidate_filter_fn=None,
    is_excluded_website_fn=None,
    score_place_fn=None,
    extract_place_id_fn=None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    leads_new: List[Dict[str, Any]] = []
    details_new: List[Dict[str, Any]] = []
    next_token: Optional[str] = start_page_token
    prev_next_token: Optional[str] = None
    fetched_count = 0
    pages_fetched = 0
    per_page: List[Dict[str, Any]] = []
    leads_ids_in_run: set[str] = set()
    details_ids_in_run: set[str] = set()

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break
        page_token_in = next_token
        places, next_token = _request_page(api_key, query, next_token, search_params)
        if not places:
            break
        pages_fetched += 1
        fetched_count += len(places)

        leads_valid_ids: List[str] = []
        details_valid_ids: List[str] = []
        leads_dup_count = 0
        details_dup_count = 0

        for place in places:
            place_id = extract_place_id_fn(place) if extract_place_id_fn else ""
            if not place_id:
                continue
            place["_place_id"] = place_id

            if place_id in details_seen_ids or place_id in details_ids_in_run:
                details_dup_count += 1
            else:
                details_ids_in_run.add(place_id)
                details_new.append(place)
                details_valid_ids.append(place_id)

            if candidate_filter_fn and not candidate_filter_fn(place):
                continue

            if is_excluded_website_fn and is_excluded_website_fn(place.get("websiteUri")):
                if place_id in leads_seen_ids or place_id in leads_ids_in_run:
                    leads_dup_count += 1
                else:
                    if score_place_fn:
                        place["score"] = score_place_fn(place)
                    leads_ids_in_run.add(place_id)
                    leads_new.append(place)
                    leads_valid_ids.append(place_id)

        per_page.append(
            {
                "page_index": pages_fetched,
                "page_token_in": page_token_in,
                "next_page_token_out": next_token,
                "candidates_count": len(places),
                "leads_valid_place_ids": leads_valid_ids,
                "details_new_place_ids": details_valid_ids,
                "leads_valid_count": len(leads_valid_ids),
                "details_new_count": len(details_valid_ids),
                "leads_duplicates_skipped_count": leads_dup_count,
                "details_duplicates_skipped_count": details_dup_count,
            }
        )

        if len(leads_new) >= limit:
            break
        if not next_token:
            break
        if prev_next_token and next_token == prev_next_token:
            break
        prev_next_token = next_token

    leads_new.sort(key=lambda p: p.get("score", 0), reverse=True)
    meta = {
        "query": query,
        "pages_fetched": pages_fetched,
        "requests_made": pages_fetched,
        "candidates_fetched": fetched_count,
        "start_page_token": start_page_token,
        "end_next_page_token": next_token,
        "exhausted": (not next_token) or (pages_fetched == 0),
        "per_page": per_page,
    }
    return leads_new, details_new, meta
