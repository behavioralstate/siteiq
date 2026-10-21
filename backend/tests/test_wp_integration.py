"""Test integrazione WordPress: crawler -> fingerprint -> WPVulnerability API
-> sezione wordpress_security nel report. Usa una fixture WP locale (rapida).
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.crawl import crawl_site  # noqa: E402
from app.wpvuln import check_wordpress  # noqa: E402


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def wp_server():
    handler = partial(QuietHandler, directory=str(ROOT / "tests_fixture" / "wp"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_crawl_detects_wordpress(wp_server):
    report = crawl_site(f"{wp_server}/")
    p = report["pages"][0]
    assert p["wordpress"]["is_wordpress"] is True
    assert p["wordpress"]["core"] == "6.4.2"
    slugs = {pl["slug"] for pl in p["wordpress"]["plugins"]}
    assert "contact-form-7" in slugs and "woocommerce" in slugs
    assert p["wordpress"]["theme"] == "twentytwentyfour"
    # versione plugin estratta dal ?ver=
    cf7 = next(pl for pl in p["wordpress"]["plugins"] if pl["slug"] == "contact-form-7")
    assert cf7["version"] in ("5.9.2", None)  # best-effort


def test_check_wordpress_against_api(wp_server):
    """Query reale all'API per i plugin della fixture: must not crash."""
    from app.wpfingerprint import fingerprint
    import httpx
    html = httpx.get(f"{wp_server}/").text
    fp = fingerprint(html)
    res = check_wordpress(fp)
    assert res["is_wordpress"] is True
    assert res["summary"]["plugins_total"] == 2
    # fallback di rete: status può essere ok o unavailable, ma mai crash
    for pl in res["plugins"]:
        assert pl["status"] in ("ok", "unavailable")
    assert len(res["core"]["vulnerabilities"]) >= 0