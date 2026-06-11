import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from leadgen import cache
from leadgen.email_scraper import (
    ScraperConfig,
    cache_json_for_result,
    extract_email_candidates,
    rank_email,
    scrape_business_email,
)
import leadgen.web_api as web_api


class FakeResponse:
    def __init__(self, url, text, status_code=200, content_type="text/html"):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class EmailScraperTests(unittest.TestCase):
    def test_extracts_mailto_plain_and_obfuscated_emails(self):
        html = """
        <a href="mailto:Owner@ExampleRestaurant.com">Email owner</a>
        <p>General: info@example-restaurant.com</p>
        <p>Chef Nina founder nina [at] example-restaurant [dot] com</p>
        """
        emails = {candidate.email for candidate in extract_email_candidates(html, "https://example-restaurant.com/team")}
        self.assertIn("owner@examplerestaurant.com", emails)
        self.assertIn("info@example-restaurant.com", emails)
        self.assertIn("nina@example-restaurant.com", emails)

    def test_filters_placeholder_email(self):
        html = "<p>Use test@example.com or hello@realrestaurant.com</p>"
        emails = {candidate.email for candidate in extract_email_candidates(html, "https://realrestaurant.com")}
        self.assertNotIn("test@example.com", emails)
        self.assertIn("hello@realrestaurant.com", emails)

    def test_owner_rank_beats_generic(self):
        owner = rank_email("alex@restaurant.com", "Alex Morgan, founder and owner", "https://restaurant.com/team")
        generic = rank_email("info@restaurant.com", "Contact us", "https://restaurant.com/contact")
        self.assertGreater(owner.score, generic.score)
        self.assertEqual(owner.email_type, "owner")

    def test_crawler_fetches_homepage_and_contact_page(self):
        pages = {
            "https://restaurant.com/": '<a href="/contact">Contact</a>',
            "https://restaurant.com/contact": "<p>Owner Maria maria@restaurant.com</p>",
        }

        def fake_get(url, **kwargs):
            return FakeResponse(url, pages.get(url, ""))

        with patch("leadgen.email_scraper.requests.get", side_effect=fake_get):
            result = scrape_business_email(
                {"name": "Restaurant", "websiteUrl": "https://restaurant.com"},
                ScraperConfig(max_pages_per_business=3, request_timeout_seconds=2, business_timeout_seconds=10),
            )

        self.assertEqual(result["bestEmail"], "maria@restaurant.com")
        self.assertEqual(result["emailScrapeStatus"], "found")
        self.assertGreaterEqual(result["pagesFetched"], 2)

    def test_email_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "cache.sqlite3"
            conn = cache.init_cache(str(db))
            result = {"bestEmail": "owner@restaurant.com", "emailScrapeStatus": "found"}
            cache.upsert_email_cache(
                conn,
                "domain:restaurant.com",
                "place-1",
                "Restaurant",
                "https://restaurant.com",
                "",
                cache_json_for_result(result),
            )
            cached = cache.get_email_cache(conn, "domain:restaurant.com")
            conn.close()

        self.assertIsNotNone(cached)
        self.assertEqual(json.loads(cached)["bestEmail"], "owner@restaurant.com")

    def test_api_enrichment_keeps_row_level_errors(self):
        def fake_scrape(row, config):
            if row["name"] == "Bad":
                raise RuntimeError("boom")
            return {
                "bestEmail": "owner@good.com",
                "bestEmailType": "owner",
                "bestEmailConfidence": "high",
                "bestEmailSourceUrl": "https://good.com/contact",
                "bestEmailEvidence": "owner",
                "contactName": "",
                "contactTitle": "",
                "allEmailsJson": "[]",
                "emailScrapeStatus": "found",
                "emailScrapeError": "",
                "pagesFetched": 1,
                "socialPagesFetched": 0,
            }

        client = TestClient(web_api.app)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"LEADS_CACHE_PATH": str(Path(tmpdir) / "cache.sqlite3")}), patch(
            "leadgen.web_api.scrape_business_email", side_effect=fake_scrape
        ):
            response = client.post(
                "/api/enrich-emails",
                json={
                    "headers": ["name", "websiteUrl"],
                    "enrichmentMode": "legacy_scraper",
                    "rows": [
                        {"name": "Good", "websiteUrl": "https://good.com"},
                        {"name": "Bad", "websiteUrl": "https://bad.com"},
                    ],
                    "useCache": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"][0]["bestEmail"], "owner@good.com")
        self.assertEqual(data["results"][1]["emailScrapeStatus"], "error")
        self.assertEqual(data["meta"]["errors"], 1)

    def test_api_ai_local_enrichment_returns_debug_details(self):
        client = TestClient(web_api.app)
        fake_report = web_api.CrawlReport(
            root_url="https://good.com/",
            host="good.com",
            evidence_sets=[
                web_api.EmailEvidenceSet(
                    email="owner@good.com",
                    source_url="https://good.com/about",
                    page_title="About",
                    page_header="About",
                    section_header="Leadership",
                    matched_line="Maria Owner can be reached at owner@good.com",
                    nearby_lines=["Maria Owner founded Good Co."],
                    source_kind="visible_text",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"LEADS_CACHE_PATH": str(Path(tmpdir) / "cache.sqlite3")}), patch(
            "leadgen.web_api.crawl_site", return_value=fake_report
        ):
            response = client.post(
                "/api/enrich-emails",
                json={
                    "headers": ["name", "websiteUrl"],
                    "enrichmentMode": "local_only",
                    "rows": [{"name": "Good", "websiteUrl": "https://good.com"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"][0]["bestEmail"], "owner@good.com")
        self.assertEqual(data["results"][0]["emailSelectionMethod"], "local")
        self.assertEqual(data["meta"]["openAiCalls"], 0)
        self.assertIn("row-0", data["details"])
        self.assertEqual(data["details"]["row-0"]["scrape"]["emailCandidates"][0]["email"], "owner@good.com")
        self.assertEqual(data["details"]["row-0"]["scrape"]["crawlReport"]["rawEvidenceSets"][0]["sectionHeader"], "Leadership")

    def test_api_gpt_web_search_enrichment_returns_debug_details(self):
        client = TestClient(web_api.app)

        def fake_web_search(row, website_url, api_key):
            return (
                "owner@good.com",
                "owner@good.com",
                {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                [{"url": "https://good.com/contact"}],
                1,
            )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "leadgen.web_api._call_gpt_web_search", side_effect=fake_web_search
        ):
            response = client.post(
                "/api/enrich-emails",
                json={
                    "headers": ["name", "websiteUrl"],
                    "enrichmentMode": "gpt_web_search",
                    "storeResults": False,
                    "rows": [{"name": "Good", "websiteUrl": "https://good.com"}],
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"][0]["bestEmail"], "owner@good.com")
        self.assertEqual(data["results"][0]["emailSelectionMethod"], "gpt_web_search")
        self.assertEqual(data["meta"]["openAiCalls"], 1)
        self.assertEqual(data["meta"]["webSearchCalls"], 1)
        self.assertIn("For the business Good", data["details"]["row-0"]["ai"]["input"])
        self.assertIn("verified private website https://good.com/", data["details"]["row-0"]["ai"]["input"])
        self.assertEqual(data["details"]["row-0"]["ai"]["sources"][0]["url"], "https://good.com/contact")

    def test_api_gpt_web_search_runs_without_website(self):
        client = TestClient(web_api.app)

        def fake_web_search(row, website_url, api_key):
            self.assertEqual(website_url, "")
            return (
                "owner@good.com",
                "owner@good.com",
                {"total_tokens": 12},
                [],
                1,
            )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "leadgen.web_api._call_gpt_web_search", side_effect=fake_web_search
        ):
            response = client.post(
                "/api/enrich-emails",
                json={
                    "headers": ["name", "address", "websiteUrl"],
                    "enrichmentMode": "gpt_web_search",
                    "storeResults": False,
                    "rows": [{"name": "Good", "address": "Cambridge, MA", "websiteUrl": ""}],
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"][0]["bestEmail"], "owner@good.com")
        self.assertEqual(data["meta"]["openAiCalls"], 1)
        self.assertEqual(data["meta"]["businessesWithoutUrls"], 0)
        self.assertIn("For the business Good in Cambridge, MA", data["details"]["row-0"]["ai"]["input"])
        self.assertIn("Use all digital info you may find", data["details"]["row-0"]["ai"]["input"])

    def test_gpt_web_search_uses_sdk_like_standalone_script(self):
        class FakeResponse:
            output_text = "owner@good.com"

            def model_dump(self):
                return {
                    "output": [
                        {"type": "web_search_call"},
                        {"type": "message", "content": [{"text": "owner@good.com", "annotations": []}]},
                    ],
                    "usage": {"total_tokens": 12},
                }

        class FakeResponses:
            def __init__(self):
                self.kwargs = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                return FakeResponse()

        fake_responses = FakeResponses()

        class FakeOpenAI:
            def __init__(self, api_key):
                self.responses = fake_responses

        with patch.dict("os.environ", {"OPENAI_MODEL": "gpt-5.5"}), patch("leadgen.web_api.OpenAI", FakeOpenAI):
            email, raw, usage, sources, calls = web_api._call_gpt_web_search(
                {"name": "Good"},
                "https://good.com/",
                "test-key",
            )

        self.assertEqual(email, "owner@good.com")
        self.assertEqual(raw, "owner@good.com")
        self.assertEqual(usage["total_tokens"], 12)
        self.assertEqual(calls, 1)
        self.assertEqual(fake_responses.kwargs["model"], "gpt-5.5")
        self.assertEqual(fake_responses.kwargs["tools"], [{"type": "web_search"}])
        self.assertEqual(fake_responses.kwargs["tool_choice"], "required")
        self.assertIn("For the business Good", fake_responses.kwargs["input"])
        self.assertIn("verified private website https://good.com/", fake_responses.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
