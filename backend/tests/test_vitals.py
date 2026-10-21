"""Test module vitals (Task 9 — Core Web Vitals via CDP).

Serve tests_fixture/vitals e verifica che collect_vitals ritorni chiavi
presenti nel modello `vitals` (schema v1.0.0).
"""
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
from app.vitals import collect_vitals, collect_vitals_on_goto, read_vitals  # noqa: E402

FIXTURE = ROOT / "tests_fixture" / "vitals"
REQUIRED_KEYS = {"LCP_ms", "INP_or_TBT_ms", "CLS", "FCP_ms", "TTFB_ms"}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def vitals_server():
    handler = partial(QuietHandler, directory=str(FIXTURE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_vitals_has_all_schema_keys(vitals_server):
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            page = b.new_page()
            data = collect_vitals_on_goto(page, f"{vitals_server}/")
            assert REQUIRED_KEYS <= set(data.keys()), data
            assert isinstance(data["LCP_ms"], int)
            assert isinstance(data["CLS"], (int, float))
        finally:
            b.close()


def test_vitals_values_are_non_negative(vitals_server):
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            page = b.new_page()
            data = collect_vitals_on_goto(page, f"{vitals_server}/")
            for k in ("LCP_ms", "INP_or_TBT_ms", "FCP_ms", "TTFB_ms"):
                assert data[k] >= 0, f"{k} negativo: {data}"
        finally:
            b.close()


def test_lcp_fcp_really_captured(vitals_server):
    """Regressione osservata live: gli observer confrontavano entryType sbagliato
    (target 'LCP'/'FCP') → LCP/FCP restavano 0 su siti reali. Qui LCP/FCP devono
    essere >0 perché la fixture locale ha un paint misurabile."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page()
            pg.add_init_script(__import__("app.vitals", fromlist=["_OBSERVER_SCRIPT"])._OBSERVER_SCRIPT)
            resp = pg.goto(f"{vitals_server}/", wait_until="domcontentloaded")
            pg.wait_for_timeout(4000)
            d = read_vitals(pg)
            assert d["LCP_ms"] > 0, f"LCP non catturato (bug observer): {d}"
            assert d["FCP_ms"] > 0, f"FCP non catturato (bug observer): {d}"
        finally:
            b.close()