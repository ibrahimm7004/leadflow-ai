from __future__ import annotations

import sqlite3
import time
import calendar
import json
from typing import Any, Dict, List, Optional


def init_cache(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_place_ids (
            place_id TEXT PRIMARY KEY,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            times_seen INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS details_seen_place_ids (
            place_id TEXT PRIMARY KEY,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            times_seen INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS query_state (
            query TEXT PRIMARY KEY,
            last_run_utc TEXT,
            last_next_page_token TEXT,
            exhausted INTEGER,
            pages_fetched_total INTEGER,
            candidates_fetched_total INTEGER,
            last_requests_made INTEGER,
            last_pages_fetched INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_enrichment_cache (
            cache_key TEXT PRIMARY KEY,
            place_id TEXT,
            business_name TEXT,
            website_url TEXT,
            social_url TEXT,
            result_json TEXT,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            expires_utc TEXT,
            times_used INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            search_mode TEXT,
            params_json TEXT,
            headers_json TEXT,
            results_count INTEGER,
            created_utc TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_result_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            query TEXT,
            place_id TEXT,
            name TEXT,
            rating REAL,
                user_rating_count INTEGER,
                website_url TEXT,
                has_external_website INTEGER,
                google_maps_uri TEXT,
                row_json TEXT,
                created_utc TEXT,
            FOREIGN KEY(run_id) REFERENCES search_runs(run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_search_result_rows_query
        ON search_result_rows(query)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_search_result_rows_reviews
        ON search_result_rows(user_rating_count)
        """
    )
    _ensure_column(conn, "search_result_rows", "has_external_website", "INTEGER")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def load_seen_ids(conn: sqlite3.Connection, table: str = "seen_place_ids") -> set[str]:
    rows = conn.execute(f"SELECT place_id FROM {table}").fetchall()
    return {row[0] for row in rows}


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_epoch_from_iso(value: str) -> float:
    try:
        return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return 0.0


def get_query_state(conn: sqlite3.Connection, query_key: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT query, last_run_utc, last_next_page_token, exhausted,
               pages_fetched_total, candidates_fetched_total,
               last_requests_made, last_pages_fetched
        FROM query_state
        WHERE query = ?
        """,
        (query_key,),
    ).fetchone()
    if not row:
        return None
    return {
        "query": row[0],
        "last_run_utc": row[1],
        "last_next_page_token": row[2],
        "exhausted": bool(row[3]),
        "pages_fetched_total": row[4] or 0,
        "candidates_fetched_total": row[5] or 0,
        "last_requests_made": row[6] or 0,
        "last_pages_fetched": row[7] or 0,
    }


def upsert_query_state(
    conn: sqlite3.Connection,
    query_key: str,
    last_run_utc: str,
    last_next_page_token: Optional[str],
    exhausted: bool,
    pages_fetched_total_increment: int,
    candidates_fetched_total_increment: int,
    last_requests_made: int,
    last_pages_fetched: int,
) -> None:
    conn.execute(
        """
        INSERT INTO query_state(
            query, last_run_utc, last_next_page_token, exhausted,
            pages_fetched_total, candidates_fetched_total,
            last_requests_made, last_pages_fetched
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(query) DO UPDATE SET
            last_run_utc=excluded.last_run_utc,
            last_next_page_token=excluded.last_next_page_token,
            exhausted=excluded.exhausted,
            pages_fetched_total=query_state.pages_fetched_total + excluded.pages_fetched_total,
            candidates_fetched_total=query_state.candidates_fetched_total + excluded.candidates_fetched_total,
            last_requests_made=excluded.last_requests_made,
            last_pages_fetched=excluded.last_pages_fetched
        """,
        (
            query_key,
            last_run_utc,
            last_next_page_token,
            1 if exhausted else 0,
            pages_fetched_total_increment,
            candidates_fetched_total_increment,
            last_requests_made,
            last_pages_fetched,
        ),
    )
    conn.commit()


def upsert_seen_ids(conn: sqlite3.Connection, appended_place_ids: List[str], table: str = "seen_place_ids") -> None:
    now = _utc_now_iso()
    for place_id in appended_place_ids:
        conn.execute(
            f"""
            INSERT INTO {table}(place_id, first_seen_utc, last_seen_utc, times_seen)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(place_id) DO UPDATE SET
                last_seen_utc=excluded.last_seen_utc,
                times_seen={table}.times_seen + 1
            """,
            (place_id, now, now),
        )
    conn.commit()


def get_email_cache(conn: sqlite3.Connection, cache_key: str) -> Optional[str]:
    row = conn.execute(
        """
        SELECT result_json, expires_utc
        FROM email_enrichment_cache
        WHERE cache_key = ?
        """,
        (cache_key,),
    ).fetchone()
    if not row:
        return None
    result_json, expires_utc = row
    if expires_utc and _utc_epoch_from_iso(expires_utc) < time.time():
        return None
    now = _utc_now_iso()
    conn.execute(
        """
        UPDATE email_enrichment_cache
        SET last_seen_utc = ?, times_used = times_used + 1
        WHERE cache_key = ?
        """,
        (now, cache_key),
    )
    conn.commit()
    return result_json


def upsert_email_cache(
    conn: sqlite3.Connection,
    cache_key: str,
    place_id: str,
    business_name: str,
    website_url: str,
    social_url: str,
    result_json: str,
    ttl_days: int = 30,
) -> None:
    now = _utc_now_iso()
    expires_utc = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() + ttl_days * 24 * 60 * 60),
    )
    conn.execute(
        """
        INSERT INTO email_enrichment_cache(
            cache_key, place_id, business_name, website_url, social_url,
            result_json, first_seen_utc, last_seen_utc, expires_utc, times_used
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(cache_key) DO UPDATE SET
            place_id=excluded.place_id,
            business_name=excluded.business_name,
            website_url=excluded.website_url,
            social_url=excluded.social_url,
            result_json=excluded.result_json,
            last_seen_utc=excluded.last_seen_utc,
            expires_utc=excluded.expires_utc,
            times_used=email_enrichment_cache.times_used + 1
        """,
        (
            cache_key,
            place_id,
            business_name,
            website_url,
            social_url,
            result_json,
            now,
            now,
            expires_utc,
        ),
    )
    conn.commit()


def store_search_results(
    conn: sqlite3.Connection,
    query: str,
    search_mode: str,
    params: Dict[str, Any],
    headers: List[str],
    rows: List[Dict[str, Any]],
) -> int:
    now = _utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO search_runs(
            query, search_mode, params_json, headers_json, results_count, created_utc
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            query,
            search_mode,
            json.dumps(params, separators=(",", ":"), ensure_ascii=True),
            json.dumps(headers, separators=(",", ":"), ensure_ascii=True),
            len(rows),
            now,
        ),
    )
    run_id = int(cursor.lastrowid)
    for row in rows:
        conn.execute(
            """
            INSERT INTO search_result_rows(
                run_id, query, place_id, name, rating, user_rating_count,
                website_url, has_external_website, google_maps_uri, row_json, created_utc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                query,
                str(row.get("placeId") or ""),
                str(row.get("name") or ""),
                _safe_float(row.get("rating")),
                _safe_int(row.get("userRatingCount")),
                str(row.get("websiteUrl") or row.get("rawWebsiteUri") or row.get("websiteUri") or ""),
                1 if str(row.get("hasExternalWebsite") or "").lower() == "true" else 0,
                str(row.get("googleMapsUri") or ""),
                json.dumps(row, separators=(",", ":"), ensure_ascii=True),
                now,
            ),
        )
    conn.commit()
    return run_id


def _safe_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except Exception:
        return 0.0
