import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from leadgen.local_scrape_suite import crawl_site, write_report


class FakeResponse:
    def __init__(self, url, text="", status_code=200, content_type="text/html"):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, **kwargs):
        if url in self.pages:
            return FakeResponse(url, self.pages[url])
        return FakeResponse(url, "", status_code=404)


class LocalScrapeSuiteTests(unittest.TestCase):
    def test_crawls_nested_same_domain_pages_and_extracts_context_sets(self):
        pages = {
            "https://localbiz.com/sitemap.xml": """
            <urlset>
              <url><loc>https://localbiz.com/team</loc></url>
            </urlset>
            """,
            "https://localbiz.com/": """
            <html><head><title>Local Biz</title></head><body>
              <h1>Local Biz Home</h1>
              <a href="/about">About</a>
              <a href="/contact">Contact</a>
              <a href="https://external.com/contact">External</a>
              <a href="/brochure.pdf">PDF</a>
            </body></html>
            """,
            "https://localbiz.com/about": """
            <html><body>
              <h1>About Us</h1>
              <p>We are owned by Maria Lopez.</p>
              <a href="/team">Team</a>
            </body></html>
            """,
            "https://localbiz.com/contact": """
            <html><body>
              <h1>Contact</h1>
              <h2>Office</h2>
              <p>For general requests, email info@localbiz.com.</p>
            </body></html>
            """,
            "https://localbiz.com/team": """
            <html><head><title>Team Page</title></head><body>
              <h1>Leadership</h1>
              <section>
                <h2>Owner</h2>
                <p>Maria Lopez, owner and operator, can be reached at
                <a href="mailto:maria@localbiz.com">maria@localbiz.com</a>.</p>
                <p>Partnerships: partner [at] localbiz [dot] com</p>
              </section>
            </body></html>
            """,
        }

        with patch("leadgen.local_scrape_suite.requests.Session", return_value=FakeSession(pages)):
            report = crawl_site("https://localbiz.com", max_pages=20, max_depth=4)

        self.assertEqual(
            {"info@localbiz.com", "maria@localbiz.com", "partner@localbiz.com"},
            set(report.unique_emails),
        )
        self.assertTrue(any(page.url == "https://localbiz.com/team" for page in report.pages))
        self.assertTrue(any("external.com" in url for url in report.skipped_external))
        maria_sets = [item for item in report.evidence_sets if item.email == "maria@localbiz.com"]
        self.assertTrue(maria_sets)
        self.assertEqual("Leadership", maria_sets[0].page_header)
        self.assertTrue(any("owner" in line.lower() for line in maria_sets[0].nearby_lines))

    def test_writes_txt_report(self):
        pages = {
            "https://localbiz.com/sitemap.xml": "",
            "https://localbiz.com/": "<html><body><h1>Contact</h1><p>Email hello@localbiz.com</p></body></html>",
        }

        with patch("leadgen.local_scrape_suite.requests.Session", return_value=FakeSession(pages)):
            report = crawl_site("localbiz.com", max_pages=5, max_depth=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_report(report, Path(tmpdir))
            text = path.read_text(encoding="utf-8")

        self.assertIn("hello@localbiz.com", text)
        self.assertIn("EMAIL + DATA SETS FOR AI", text)


if __name__ == "__main__":
    unittest.main()
