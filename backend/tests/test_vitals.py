"""Test module vitals (Task 9 — Core Web Vitals).

Serve tests_fixture/vitals e verifica che read_vitals (observer installati prima
della navigazione, come nel crawler) ritorni le chiavi del modello `vitals`
(schema v1.0.0) con valori plausibili.
"""
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
from app.vitals import _OBSERVER_SCRIPT, read_vitals  # noqa: E402

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


def _vitals_like_crawler(url: str) -> dict:
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            page = b.new_page()
            page.add_init_script(_OBSERVER_SCRIPT)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            return read_vitals(page)
        finally:
            b.close()


def test_vitals_has_all_schema_keys(vitals_server):
    data = _vitals_like_crawler(f"{vitals_server}/")
    assert REQUIRED_KEYS <= set(data.keys()), data
    assert isinstance(data["LCP_ms"], int)
    assert isinstance(data["CLS"], (int, float))


def test_vitals_values_are_non_negative(vitals_server):
    data = _vitals_like_crawler(f"{vitals_server}/")
    for k in ("LCP_ms", "INP_or_TBT_ms", "FCP_ms", "TTFB_ms"):
        assert data[k] >= 0, f"{k} negativo: {data}"


def test_ttfb_is_measured(vitals_server):
    """Regressione: TTFB veniva da un evento CDP mai abilitato -> sempre 0."""
    data = _vitals_like_crawler(f"{vitals_server}/")
    assert data["TTFB_ms"] > 0, data
    assert data["TTFB_ms"] < 30_000, data


def test_lcp_fcp_really_captured(vitals_server):
    """Regressione osservata live: gli observer confrontavano entryType sbagliato
    (target 'LCP'/'FCP') → LCP/FCP restavano 0 su siti reali. Qui LCP/FCP devono
    essere >0 perché la fixture locale ha un paint misurabile."""
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page()
            pg.add_init_script(_OBSERVER_SCRIPT)
            resp = pg.goto(f"{vitals_server}/", wait_until="domcontentloaded")
            pg.wait_for_timeout(4000)
            d = read_vitals(pg)
            assert d["LCP_ms"] > 0, f"LCP non catturato (bug observer): {d}"
            assert d["FCP_ms"] > 0, f"FCP non catturato (bug observer): {d}"
        finally:
            b.close()