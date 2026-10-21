"""Test crawler (single-URL, decisione 2026-10-07).

Serve la fixture statica in tests_fixture/site via http.server su una porta
effimera, lancia crawl_site() sull'URL inserito, e valida l'output contro
crawl_report.schema.json. Il crawler scansiona SOLO l'URL dato (niente BFS).

Esegui:
  cd backend && python3 -m pytest tests/test_crawler.py -v
"""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.crawl import crawl_site  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.load(open(ROOT / "schema" / "crawl_report.schema.json"))
FIXTURE = ROOT / "tests_fixture" / "site"


class QuietHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if not self.path.endswith("/robots.txt"):
            self.send_header("Content-Security-Policy", "default-src 'self'")
            self.send_header("Strict-Transport-Security", "max-age=63072000")
        super().end_headers()

    def log_message(self, *args, **kwargs):  # silenzia i log di http.server
        pass


@pytest.fixture(scope="module")
def fixture_server():
    handler = partial(QuietHandler, directory=str(FIXTURE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_crawl_fixture_conforms_to_schema(fixture_server):
    report = crawl_site(f"{fixture_server}/")
    errs = list(Draft202012Validator(SCHEMA).iter_errors(report))
    assert errs == [], f"report non conforme: {errs[:5]}"


def test_crawl_scans_only_the_given_url(fixture_server):
    """Single-URL: il report contiene SOLO l'URL inserito, non le pagine linkate."""
    report = crawl_site(f"{fixture_server}/")
    assert len(report["pages"]) == 1
    assert report["pages"][0]["url"].rstrip("/") == f"{fixture_server}"
    # about.html è linkato ma NON deve essere scoperto (niente BFS)
    assert not any("about.html" in p["url"] for p in report["pages"])


def test_crawl_detects_missing_alt(fixture_server):
    report = crawl_site(f"{fixture_server}/")
    ok_pages = [p for p in report["pages"] if p["status"] == "ok"]
    assert ok_pages, "nessuna pagina ok"
    assert any(p["images_missing_alt"] >= 1 for p in ok_pages)


def test_crawl_skipped_when_robots_disallows(fixture_server):
    # private.html è Disallow da robots.txt: se lo scansioniamo direttamente -> skipped
    report = crawl_site(f"{fixture_server}/private.html")
    assert report["pages"][0]["status"] == "skipped"


def test_scan_meta_single_page(fixture_server):
    report = crawl_site(f"{fixture_server}/")
    assert report["scan_meta"]["pages_requested"] == 1
    assert report["scan_meta"]["pages_returned"] == 1
    assert report["scan_meta"]["truncated"] is False


def test_crawl_collects_security_headers(fixture_server):
    report = crawl_site(f"{fixture_server}/")
    ok_pages = [p for p in report["pages"] if p["status"] == "ok"]
    assert ok_pages
    headers = ok_pages[0].get("http_headers", {})
    assert "content-security-policy" in headers
    assert "strict-transport-security" in headers


def test_crawl_collects_vitals_on_ok_pages(fixture_server):
    report = crawl_site(f"{fixture_server}/")
    for p in report["pages"]:
        if p["status"] == "ok":
            v = p.get("vitals")
            assert v is not None, "pagina ok senza vitals"
            assert {"LCP_ms", "INP_or_TBT_ms", "CLS", "FCP_ms", "TTFB_ms"} <= set(v)