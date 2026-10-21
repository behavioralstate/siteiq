"""Regressioni di sicurezza: SSRF, limiti della scansione gratuita, XSS.

Le fixture HTTP girano su 127.0.0.1, quindi qui il blocco degli IP privati viene
riattivato in modo selettivo: si blocca il NOME "localhost" e si lascia passare
127.0.0.1, così si può verificare che un redirect/sotto-risorsa verso un host
bloccato non venga mai richiesto.
"""
import ipaddress
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import netguard
from app.main import app

AUTH = {"Authorization": "Bearer test-token-fabio"}


# ---------------------------------------------------------------- netguard --

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://0.0.0.0/", "http://localhost:8000/",
])
def test_guard_blocks_non_public_hosts(url):
    with pytest.raises(netguard.BlockedTarget):
        netguard.TargetGuard(allow_private=False).validate_url(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/",
    "https://example.com/<img src=x onerror=alert(1)>", "http://", "https://exa mple.com",
])
def test_guard_rejects_bad_schemes_and_characters(url):
    with pytest.raises(netguard.BlockedTarget):
        netguard.TargetGuard(allow_private=True).validate_url(url)


def test_guard_allows_public_ip_literal():
    assert netguard.TargetGuard(allow_private=False).validate_url("https://93.184.215.14/") \
        == "https://93.184.215.14/"
    assert netguard.is_public_ip(ipaddress.ip_address("8.8.8.8"))


# ------------------------------------------------------- crawler SSRF e2e --

class _Recorder(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):
        _Recorder.hits.append(self.path)
        port = self.server.server_address[1]
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/secret")
            self.end_headers()
            return
        if self.path == "/page":
            body = (f'<html><head><meta charset="utf-8"><title>Pagina pubblica</title></head>'
                    f'<body><h1>ok</h1><img alt="x" src="http://localhost:{port}/secret-img">'
                    f'</body></html>').encode()
        elif self.path == "/robots.txt":
            self.send_response(404)
            self.end_headers()
            return
        else:
            body = b"<html><body>SECRET</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def recorder_server():
    _Recorder.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture()
def block_localhost_name(monkeypatch):
    """Guard attivo, ma 127.0.0.1 resta ammesso: si blocca solo il nome localhost."""
    monkeypatch.setenv("SITEIQ_ALLOW_PRIVATE_TARGETS", "0")
    monkeypatch.setattr(netguard.TargetGuard, "_policy_reason", staticmethod(
        lambda host, ips: "not_public" if host == "localhost" else None))


def test_crawler_does_not_follow_redirect_to_blocked_host(recorder_server, block_localhost_name):
    from app.crawl import crawl_site
    report = crawl_site(f"{recorder_server}/redirect")
    page = report["pages"][0]
    assert "/secret" not in _Recorder.hits, _Recorder.hits
    assert page["status"] == "error"
    assert "SECRET" not in page["qualitative"]["body_text_sample"]


def test_crawler_blocks_subresources_to_blocked_host(recorder_server, block_localhost_name):
    from app.crawl import crawl_site
    report = crawl_site(f"{recorder_server}/page")
    assert report["pages"][0]["status"] == "ok"
    assert "/secret-img" not in _Recorder.hits, _Recorder.hits


def test_crawler_refuses_private_target_when_guard_on(recorder_server, monkeypatch):
    from app.crawl import crawl_site
    monkeypatch.setenv("SITEIQ_ALLOW_PRIVATE_TARGETS", "0")
    page = crawl_site(f"{recorder_server}/page")["pages"][0]
    assert page["status"] == "error"
    assert "non pubblico" in page["error_detail"]
    assert _Recorder.hits == []


# ------------------------------------------------------------- API layer --

@pytest.fixture()
def no_smtp(monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.lead.send_confirmation",
                        lambda email, url, locale=None: sent.append((email, url)))
    return sent


def test_lead_rejects_private_url(monkeypatch, no_smtp):
    monkeypatch.setenv("SITEIQ_ALLOW_PRIVATE_TARGETS", "0")
    r = TestClient(app).post("/api/lead", json={"email": "a@example.com",
                                                "url": "http://169.254.169.254/"})
    assert r.status_code == 422
    assert no_smtp == []


def test_lead_rejects_html_in_email(no_smtp):
    r = TestClient(app).post("/api/lead", json={"email": "<svg/onload=alert(1)>@x.yz",
                                                "url": "https://example.com"})
    assert r.status_code == 422


def test_lead_rate_limited_per_email(no_smtp):
    c = TestClient(app)
    codes = [c.post("/api/lead", json={"email": f"rl+{i}@example.com",
                                       "url": "https://example.com"}).status_code
             for i in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_email_variants_share_one_lead():
    from app.leads import create_lead
    stamp = int(time.time() * 1000)
    a = create_lead(f"Mario.{stamp}@Example.com", "https://a.it")
    b = create_lead(f"mario.{stamp}+promo@example.com", "https://b.it")
    assert a["token"] == b["token"]


def test_claim_scan_is_atomic():
    from app.leads import claim_scan, confirm_lead, create_lead
    lead = create_lead(f"race-{time.time_ns()}@example.com", "https://a.it")
    confirm_lead(lead["token"])
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(claim_scan(lead["token"]) is not None)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1


def test_scan_status_hides_internal_errors(monkeypatch):
    from app import jobs
    from app.llm import StubLlm

    def boom(*a, **k):
        raise RuntimeError("dettaglio interno: /srv/secret path")

    monkeypatch.setattr(jobs, "crawl_site", boom)
    job = jobs.store.create("https://example.com", StubLlm())
    job.run()
    body = TestClient(app).get(f"/api/scan/{job.id}").json()
    assert body["status"] == "error"
    assert "secret" not in body["error"]
    admin = TestClient(app).get(f"/api/analyze/{job.id}", headers=AUTH).json()
    assert "dettaglio interno" in admin["error"]


def test_analyze_rejects_file_url_and_unknown_engine():
    c = TestClient(app)
    assert c.post("/api/analyze", json={"url": "file:///etc/passwd"}, headers=AUTH).status_code == 422
    assert c.post("/api/analyze?llm=gpt", json={"url": "https://example.com"},
                  headers=AUTH).status_code == 422


def test_admin_report_rejects_non_hex_job_id():
    c = TestClient(app)
    assert c.get("/api/admin/report/..%5C..%5Cx", headers=AUTH).status_code == 404
    assert c.get("/api/admin/report/abc", headers=AUTH).status_code == 404


def test_queue_full_returns_503(monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "MAX_QUEUED_JOBS", 0)
    r = TestClient(app).post("/api/analyze", json={"url": "https://example.com"}, headers=AUTH)
    assert r.status_code == 503


# ------------------------------------------------------------------ auth --

def test_auth_accepts_comma_and_semicolon(monkeypatch):
    from app import auth
    monkeypatch.setenv("AUTH_CLIENTS", "anna=tok-a, bruno=tok-b;carla=tok-c")
    monkeypatch.setattr(auth, "_client_tokens", None)
    assert auth.token_client("tok-a") == "anna"
    assert auth.token_client("tok-b") == "bruno"
    assert auth.token_client("tok-c") == "carla"
    assert auth.token_client("tok-a, bruno=tok-b") is None


# ---------------------------------------------------------------- mailer --

def test_mailer_reads_documented_variable_names(monkeypatch):
    from app import mailer
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "s3cret")
    monkeypatch.setenv("SMTP_FROM", "from@example.com")
    cfg = mailer.smtp_config()
    assert cfg["password"] == "s3cret"
    assert cfg["sender"] == "from@example.com"


# ------------------------------------------------- XSS nel report e admin --

def test_report_page_escapes_llm_values():
    from app.email_report import render_report_email, render_report_page
    payload = '<img src=x onerror="alert(1)">'
    report = {
        "url": "https://example.com", "summary": {"verdict": "ok", "highlights": [], "most_urgent": ""},
        "scores": {}, "priorities": [], "recommendations": [],
        "overall": {"score10": payload, "verdict": "v",
                    "macro_areas": {"Business": payload, payload: 7}},
        "areas": [{"name": "a", "score10": payload, "analysis": "x",
                   "strengths": [], "weaknesses": []}],
        "opportunities": [{"title": "t", "benefit": "b", "priority": payload}],
    }
    for html in (render_report_page(report), render_report_email(report)[1]):
        assert "<img" not in html


def test_schema_rejects_non_numeric_macro_areas():
    from app.llm import _final_report_validator
    from app.llm import StubLlm
    rep = StubLlm().analyze({"url": "https://example.com", "pages": []})
    assert not list(_final_report_validator().iter_errors(rep))
    rep["overall"]["macro_areas"]["Business"] = "<img src=x>"
    assert list(_final_report_validator().iter_errors(rep))


# ------------------------------------------- admin panel XSS (end-to-end) --

@pytest.fixture()
def live_server():
    import socket as _socket

    import uvicorn
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def test_admin_panel_does_not_execute_stored_lead_payload(live_server):
    """Un lead salvato con HTML nell'email/URL (dati storici o bypass della
    validazione) deve comparire come testo nel pannello, mai eseguito."""
    from playwright.sync_api import sync_playwright

    from app.leads import create_lead
    payload = '<img src=x onerror="window.__pwned=1">'
    create_lead(f"xss{time.time_ns()}{payload}@example.com", f"https://example.com/{payload}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"{live_server}/admin")
            page.evaluate("localStorage.setItem('siteiq_admin_token', 'test-token-fabio')")
            page.reload()
            page.wait_for_selector("#leads-table tbody tr")
            page.wait_for_timeout(500)
            assert page.evaluate("window.__pwned") is None
            assert page.locator("#leads-table img").count() == 0
            assert payload in page.locator("#leads-table").inner_text()
        finally:
            browser.close()
