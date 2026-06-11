import os
import sqlite3
import tempfile
import unittest

from leadgen.ai_email_enrichment import (
    clean_email,
    extract_emails_from_html,
    load_leads_from_db,
    valid_owned_website,
)


class AiEmailEnrichmentTests(unittest.TestCase):
    def test_extracts_plain_mailto_and_obfuscated_emails(self):
        html = """
        <html><head><title>Team</title></head><body>
          <a href="mailto:owner@localbiz.com">Email Jane Owner</a>
          Contact support@localbiz.com
          Sales: sales [at] localbiz [dot] com
        </body></html>
        """

        emails, _ = extract_emails_from_html(html, "https://localbiz.com/team", "localbiz.com")
        found = {item.email for item in emails}

        self.assertEqual(
            {"owner@localbiz.com", "support@localbiz.com", "sales@localbiz.com"},
            found,
        )

    def test_owner_context_beats_generic_contact(self):
        html = """
        <html><body>
          For questions, email info@localbiz.com.
          Maria Lopez, owner and operator, can be reached at maria@localbiz.com.
        </body></html>
        """

        emails, signals = extract_emails_from_html(html, "https://localbiz.com/about", "localbiz.com")

        self.assertEqual("maria@localbiz.com", emails[0].email)
        self.assertEqual("owner", emails[0].local_type)
        self.assertTrue(any("owner" in signal.lower() for signal in signals))

    def test_filters_sentence_fragment_false_positive(self):
        self.assertEqual("", clean_email("showers@once.tankless"))

    def test_external_platform_is_not_owned_website(self):
        self.assertEqual("", valid_owned_website("https://booksy.com/en-us/12345_barber"))
        self.assertEqual("https://examplebiz.com/", valid_owned_website("https://examplebiz.com/contact?utm=maps"))

    def test_loader_ignores_placeholder_websites_before_limit(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.execute(
                """
                CREATE TABLE search_result_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    query TEXT,
                    place_id TEXT,
                    name TEXT,
                    rating REAL,
                    user_rating_count INTEGER,
                    website_url TEXT,
                    google_maps_uri TEXT,
                    row_json TEXT,
                    created_utc TEXT
                )
                """
            )
            rows = [
                ("No Site 1", "none,"),
                ("No Site 2", ""),
                ("Real Site", "example.com"),
            ]
            for name, website in rows:
                conn.execute(
                    """
                    INSERT INTO search_result_rows(
                        run_id, query, place_id, name, rating, user_rating_count,
                        website_url, google_maps_uri, row_json, created_utc
                    )
                    VALUES (1, 'query', '', ?, 4.5, 1, ?, '', '{}', '')
                    """,
                    (name, website),
                )
            conn.commit()
            conn.close()

            leads = load_leads_from_db(path, limit=1)

            self.assertEqual(1, len(leads))
            self.assertEqual("Real Site", leads[0]["name"])
            self.assertEqual("https://example.com/", leads[0]["website_url"])
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
