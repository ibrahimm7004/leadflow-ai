import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import leadgen.web_api as web_api


class SearchStorageTests(unittest.TestCase):
    def test_search_filters_sorts_and_stores_rows(self):
        places = [
            {
                "id": "high",
                "_place_id": "high",
                "displayName": {"text": "High Reviews"},
                "formattedAddress": "1 Main St",
                "rating": 4.7,
                "userRatingCount": 250,
                "websiteUri": "https://high.example",
                "googleMapsUri": "https://maps.example/high",
            },
            {
                "id": "low",
                "_place_id": "low",
                "displayName": {"text": "Low Reviews"},
                "formattedAddress": "2 Main St",
                "rating": 4.2,
                "userRatingCount": 40,
                "websiteUri": "https://www.low.example/contact/team?utm_source=maps",
                "googleMapsUri": "https://maps.example/low",
            },
            {
                "id": "platform",
                "_place_id": "platform",
                "displayName": {"text": "Platform Site"},
                "formattedAddress": "4 Main St",
                "rating": 4.4,
                "userRatingCount": 20,
                "websiteUri": "https://booksy.com/en-us/12345_platform_site",
                "googleMapsUri": "https://maps.example/platform",
            },
            {
                "id": "too-many",
                "_place_id": "too-many",
                "displayName": {"text": "Too Many Reviews"},
                "formattedAddress": "3 Main St",
                "rating": 4.9,
                "userRatingCount": 700,
                "websiteUri": "https://many.example",
                "googleMapsUri": "https://maps.example/many",
            },
        ]

        def fake_build_results(*args, **kwargs):
            candidate_filter = kwargs["candidate_filter_fn"]
            filtered = [place for place in places if candidate_filter(place)]
            return filtered, places, {
                "query": args[1],
                "pages_fetched": 1,
                "requests_made": 1,
                "candidates_fetched": len(places),
                "start_page_token": None,
                "end_next_page_token": None,
                "exhausted": True,
                "per_page": [],
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "leads_cache.sqlite3"
            client = TestClient(web_api.app)
            with patch.dict("os.environ", {"LEADS_CACHE_PATH": str(db_path)}), patch(
                "leadgen.web_api._api_key", return_value="test-key"
            ), patch("leadgen.web_api.build_results", side_effect=fake_build_results):
                response = client.post(
                    "/api/search",
                    json={
                        "businessType": "barber",
                        "location": "Boston, MA",
                        "numLeads": 10,
                        "searchMode": "all_businesses",
                        "minRating": 3.5,
                        "maxUserReviews": 300,
                    },
                )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual([row["name"] for row in data["results"]], ["Platform Site", "Low Reviews", "High Reviews"])
            self.assertEqual(data["results"][0]["websiteUrl"], "")
            self.assertEqual(data["results"][0]["hasExternalWebsite"], "true")
            self.assertEqual(data["results"][1]["websiteUrl"], "https://www.low.example/")
            self.assertEqual(data["meta"]["storedRunId"], 1)

            conn = sqlite3.connect(db_path)
            run = conn.execute("SELECT query, results_count FROM search_runs").fetchone()
            rows = conn.execute(
                "SELECT name, user_rating_count, website_url, has_external_website FROM search_result_rows ORDER BY user_rating_count ASC"
            ).fetchall()
            conn.close()

        self.assertEqual(run, ("barber in Boston, MA", 3))
        self.assertEqual(rows, [
            ("Platform Site", 20, "https://booksy.com/en-us/12345_platform_site", 1),
            ("Low Reviews", 40, "https://www.low.example/", 0),
            ("High Reviews", 250, "https://high.example/", 0),
        ])


if __name__ == "__main__":
    unittest.main()
