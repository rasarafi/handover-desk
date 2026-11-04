"""audit.py against two local sites: one with planted problems, one clean.

Run: python3 -m unittest discover -s tests
"""
import functools
import http.server
import pathlib
import sys
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "audit"))
import audit  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
HOME = {"/", "/index.html"}  # the start page may be reported under either name


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(directory):
    handler = functools.partial(QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


class PlantedSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = serve(FIXTURES / "planted-site")
        cls.report = audit.run(cls.url)
        cls.by_check = {}
        for f in cls.report["findings"]:
            cls.by_check.setdefault(f["check"], []).append(f)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def pages(self, check):
        return {loc["page"] for f in self.by_check.get(check, []) for loc in f["locations"]}

    def evidence(self, check):
        return " ".join(
            f"{loc['page']} {loc['evidence']}" for f in self.by_check.get(check, []) for loc in f["locations"]
        )

    def test_site_is_up(self):
        self.assertNotIn("alive", self.by_check)
        self.assertEqual(self.report["pages_checked"], 2)

    def test_lorem_ipsum(self):
        self.assertTrue(self.pages("placeholder-text") & HOME)
        self.assertIn("Lorem ipsum", self.evidence("placeholder-text"))

    def test_test_account_on_both_pages(self):
        ev = self.evidence("test-data")
        self.assertIn("test@test.com", ev)
        self.assertTrue(self.pages("test-data") & HOME)
        self.assertIn("/dashboard.html", self.pages("test-data"))

    def test_dead_link(self):
        ev = self.evidence("broken-link")
        self.assertIn("pricing.html", ev)
        self.assertIn("404", ev)
        self.assertEqual(len(self.by_check["broken-link"]), 1, "one finding per dead URL, not per page")

    def test_dev_url_in_js(self):
        ev = self.evidence("dev-url")
        self.assertIn("localhost:3000", ev)
        self.assertIn("app.js", ev)

    def test_metadata(self):
        ev = self.evidence("metadata")
        self.assertIn("Untitled", ev)
        self.assertIn("favicon", ev)
        self.assertIn("og:", ev)

    def test_findings_are_numbered_from_one(self):
        ids = [f["id"] for f in self.report["findings"]]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_markdown_lists_every_finding(self):
        md = audit.to_markdown(self.report)
        for f in self.report["findings"]:
            self.assertIn(f"{f['id']}. ", md)


class CleanSite(unittest.TestCase):
    def test_no_findings(self):
        server, url = serve(FIXTURES / "clean-site")
        try:
            report = audit.run(url)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(report["findings"], [], audit.to_markdown(report))
        self.assertEqual(report["pages_checked"], 3)


class DeadSite(unittest.TestCase):
    def test_unreachable_is_one_alive_finding(self):
        report = audit.run("http://127.0.0.1:9/")
        self.assertEqual([f["check"] for f in report["findings"]], ["alive"])


class DevUrlRules(unittest.TestCase):
    def test_own_origin_is_not_a_dev_url(self):
        hits = audit.find_dev_urls('fetch("http://127.0.0.1:8093/api")', own_netloc="127.0.0.1:8093")
        self.assertEqual(hits, [])

    def test_other_local_port_is(self):
        hits = audit.find_dev_urls('fetch("http://127.0.0.1:5173/api")', own_netloc="127.0.0.1:8093")
        self.assertEqual(hits, ["http://127.0.0.1:5173/api"])

    def test_staging_host(self):
        hits = audit.find_dev_urls('a href="https://staging.acme.io/x"', own_netloc="acme.io")
        self.assertEqual(hits, ["https://staging.acme.io/x"])


class TestDataRules(unittest.TestCase):
    def test_real_looking_email_is_fine(self):
        self.assertEqual(audit.find_test_data("Contact hello@tidewell.co.uk"), [])

    def test_known_fakes(self):
        hits = audit.find_test_data("by John Doe, mail foo@example.com or asdf@mailinator.com")
        self.assertEqual(sorted(hits), ["John Doe", "asdf@mailinator.com", "foo@example.com"])


if __name__ == "__main__":
    unittest.main()
