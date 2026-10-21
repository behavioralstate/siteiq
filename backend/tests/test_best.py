"""Superficie BEST: discovery, comandi, eventi (log + SSE), query.

Le analisi girano davvero (crawler Playwright) contro la fixture statica su
127.0.0.1, ammessa in test da SITEIQ_ALLOW_PRIVATE_TARGETS=1 (conftest).
"""
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.best import catalogue, service
from app.best.eventlog import log as event_log
from app.main import app

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "tests_fixture" / "site"
CE = {"Content-Type": "application/cloudevents+json"}
TERMINAL = {"SiteAnalysisCompleted", "SiteAnalysisFailed"}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(FIXTURE)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture()
def client():
    return TestClient(app)


def _path(url: str) -> str:
    """URI assoluto del catalogo -> path per il TestClient."""
    return "/best" + url.split("/best", 1)[1]


def command(url: str, **overrides) -> dict:
    entry = catalogue.get("commands", "analyze-site", "1.0")
    env = {
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": "https://agents.example.com/test",
        "type": "AnalyzeSite",
        "datacontenttype": "application/json",
        "dataschema": catalogue.dataschema(entry),
        "time": datetime.now(timezone.utc).isoformat(),
        "data": {"url": url},
    }
    env.update(overrides)
    return env


def wait_for_outcome(client, correlation_id: str, timeout: float = 90) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = client.get("/best/events", params={"correlationId": correlation_id}).json()["events"]
        if any(e["type"] in TERMINAL for e in events):
            return events
        time.sleep(0.5)
    raise AssertionError(f"nessun esito per {correlation_id}")


def assert_best_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# --------------------------------------------------------------- discovery --

def test_manifest_is_public_and_structural(client):
    r = client.get("/.well-known/best")
    assert r.status_code == 200
    m = r.json()["best"]
    assert m["version"] == "0.9.17"
    service_id = catalogue.service_id()
    assert service_id == "local.siteiq.analysis"  # PUBLIC_BASE_URL di default: 127.0.0.1
    svc = m["services"][service_id]
    assert svc["authentication"] == {"type": "none"}
    assert svc["http"]["endpoint"] == catalogue.endpoint()
    names = {c["name"] for c in m["capabilities"]}
    assert names == {"io.best.agents.commands", "io.best.agents.events", "io.best.agents.queries"}
    for cap in m["capabilities"]:
        assert cap["service"] == service_id
        assert cap["endpoints"]
    # manifest discipline: descrizioni brevi, senza URL o header
    for desc in [svc["description"]] + [c["description"] for c in m["capabilities"]]:
        assert len(desc) <= 500 and "http" not in desc and "/" not in desc


@pytest.mark.parametrize("base, expected", [
    ("https://siteiq.example.org", "org.example.siteiq.analysis"),
    ("https://Analisi.Example.COM:8443/app/", "com.example.analisi.analysis"),
    ("https://www.esempio.it", "it.esempio.www.analysis"),
    ("https://bücher.example", "example.xn--bcher-kva.analysis"),
    ("http://127.0.0.1:8000", "local.siteiq.analysis"),
    ("http://[::1]:8000", "local.siteiq.analysis"),
    ("http://localhost:8000", "local.siteiq.analysis"),
    ("http://app.localhost", "local.siteiq.analysis"),
])
def test_service_id_is_the_reversed_public_host(monkeypatch, client, base, expected):
    monkeypatch.setenv("PUBLIC_BASE_URL", base)
    assert catalogue.service_id() == expected
    m = client.get("/.well-known/best").json()["best"]
    assert list(m["services"]) == [expected]
    assert {c["service"] for c in m["capabilities"]} == {expected}


def test_best_routes_are_not_in_openapi(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/best") or "well-known" in p]


def test_landing_links_the_manifest(client):
    assert 'href="/.well-known/best"' in client.get("/").text


# --------------------------------------------------------------- catalogue --

def test_command_catalogue_and_schema_document(client):
    cmds = client.get("/best/commands").json()["commands"]
    assert [c["commandType"] for c in cmds] == ["AnalyzeSite"]
    doc = client.get(_path(cmds[0]["dataschema"]))
    assert doc.status_code == 200
    assert doc.headers["content-type"].startswith("application/schema+json")
    body = doc.json()
    assert body["commandType"] == "AnalyzeSite"
    assert body["produces"] == ["SiteAnalysisStarted", "SiteCrawled",
                                "SiteAnalysisCompleted", "SiteAnalysisFailed"]
    Draft202012Validator.check_schema(body)


def test_query_catalogue_and_schema_documents(client):
    queries = client.get("/best/queries").json()["queries"]
    assert {q["schema"] for q in queries} == {"get-analysis", "get-findings", "get-crawl-report"}
    for q in queries:
        doc = client.get(_path(q["dataschema"])).json()
        assert set(doc) <= {"description", "parameters", "response", "workflows"}
        Draft202012Validator.check_schema(doc["parameters"])
        Draft202012Validator.check_schema(doc["response"])


def test_unknown_schema_and_route_use_best_errors(client):
    assert_best_error(client.get("/best/commands/nope/1.0"), 404, "SCHEMA_NOT_FOUND")
    assert_best_error(client.get("/best/events/nope/1.0"), 404, "SCHEMA_NOT_FOUND")
    assert_best_error(client.get("/best/nothing-here"), 404, "NOT_FOUND")


# ------------------------------------------------------- happy path e2e --

def _validate_event(client, ev: dict, correlation_id: str):
    assert ev["specversion"] == "1.0"
    assert ev["correlationid"] == correlation_id
    assert ev["datacontenttype"] == "application/json"
    schema = client.get(_path(ev["dataschema"])).json()
    assert not list(Draft202012Validator(schema).iter_errors(ev["data"])), ev


def test_analyze_site_end_to_end(client, site, monkeypatch):
    from app import jobs
    mails = []
    monkeypatch.setattr(jobs, "_send_report_email", lambda rcpt, rep, loc: mails.append(rcpt))
    monkeypatch.setenv("REPORT_NOTIFY_EMAIL", "notify@example.com")

    env = command(f"{site}/")
    r = client.post("/best/commands", content=json.dumps(env), headers=CE)
    assert r.status_code == 202, r.text
    assert r.json() == {"id": env["id"], "correlationId": env["id"]}

    events = wait_for_outcome(client, env["id"])
    assert [e["type"] for e in events] == ["SiteAnalysisStarted", "SiteCrawled", "SiteAnalysisCompleted"]
    for ev in events:
        _validate_event(client, ev, env["id"])
    analysis_id = events[-1]["data"]["analysisId"]
    assert events[1]["data"]["pageStatus"] == "ok"

    a = client.get("/best/queries/get-analysis", params={"analysisId": analysis_id}).json()
    assert a["status"] == "completed" and a["failure"] is None
    assert a["findingCounts"] == events[-1]["data"]["findingCounts"]

    f = client.get("/best/queries/get-findings", params={"analysisId": analysis_id}).json()
    ids = {x["id"] for x in f["findings"]}
    assert "security.content-security-policy" in ids
    assert "seo.title" in ids
    sec = client.get("/best/queries/get-findings",
                     params={"analysisId": analysis_id, "category": "security"}).json()["findings"]
    assert sec and all(x["category"] == "security" for x in sec)

    crawl = client.get("/best/queries/get-crawl-report", params={"analysisId": analysis_id}).json()
    assert crawl["crawlReport"]["pages"][0]["status"] == "ok"

    # superficie pubblica deterministica: niente LLM, niente email
    assert service.best_job(analysis_id).llm is None
    assert mails == []


def test_caller_correlation_id_is_kept(client, site):
    env = command(f"{site}/", correlationid="process-42")
    r = client.post("/best/commands", content=json.dumps(env), headers=CE)
    assert r.json()["correlationId"] == "process-42"
    events = wait_for_outcome(client, "process-42")
    assert all(e["correlationid"] == "process-42" for e in events)


def test_sse_stream_delivers_events_until_outcome(client, site):
    env = command(f"{site}/about.html")
    client.post("/best/commands", content=json.dumps(env), headers=CE)
    received = []
    with client.stream("GET", "/best/events/stream", params={"correlationId": env["id"]},
                       headers={"Accept": "text/event-stream"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        current_id = None
        for line in r.iter_lines():
            if line.startswith("id: "):
                current_id = line[4:]
            elif line.startswith("data: "):
                ev = json.loads(line[6:])
                assert ev["id"] == current_id
                received.append(ev["type"])
    # lo stream si chiude da solo all'esito; Started può precedere l'iscrizione
    assert received[-1] == "SiteAnalysisCompleted"
    assert "SiteCrawled" in received


# --------------------------------------------------------------- failures --

def test_robots_disallowed_page_fails_with_reason(client, site):
    env = command(f"{site}/private.html")
    client.post("/best/commands", content=json.dumps(env), headers=CE)
    events = wait_for_outcome(client, env["id"])
    failed = events[-1]
    assert failed["type"] == "SiteAnalysisFailed"
    assert failed["data"]["reason"] == "ROBOTS_DISALLOWED"
    _validate_event(client, failed, env["id"])
    aid = failed["data"]["analysisId"]
    a = client.get("/best/queries/get-analysis", params={"analysisId": aid}).json()
    assert a["status"] == "failed" and a["failure"]["reason"] == "ROBOTS_DISALLOWED"
    f = client.get("/best/queries/get-findings", params={"analysisId": aid}).json()
    assert f == {"analysisId": aid, "status": "failed", "findings": []}


def test_unreachable_site_fails_without_internal_details(client):
    env = command("http://127.0.0.1:9/")
    client.post("/best/commands", content=json.dumps(env), headers=CE)
    failed = wait_for_outcome(client, env["id"])[-1]
    assert failed["data"]["reason"] == "TARGET_UNREACHABLE"
    assert "Error" not in failed["data"]["message"]


# ------------------------------------------------------------ ingestion --

def test_command_rejections(client, monkeypatch):
    ok = command("https://example.com/")
    post = lambda body, headers=CE: client.post("/best/commands", content=body, headers=headers)
    assert_best_error(post(json.dumps(ok), {"Content-Type": "text/plain"}), 415, "UNSUPPORTED_MEDIA_TYPE")
    assert_best_error(post("{not json"), 400, "INVALID_JSON")
    assert_best_error(post(json.dumps({**ok, "specversion": "0.3"})), 400, "INVALID_ENVELOPE")
    no_source = {k: v for k, v in ok.items() if k != "source"}
    assert_best_error(post(json.dumps(no_source)), 400, "INVALID_ENVELOPE")
    assert_best_error(post(json.dumps({**ok, "type": "DeleteEverything"})), 400, "UNKNOWN_COMMAND_TYPE")
    assert_best_error(post(json.dumps({**ok, "dataschema": "https://evil.example/x"})), 400, "DATASCHEMA_MISMATCH")
    assert_best_error(post(json.dumps({**ok, "data": {"url": "ftp://example.com"}})), 400, "INVALID_DATA")
    assert_best_error(post(json.dumps({**ok, "data": {"url": "https://a.it", "x": 1}})), 400, "INVALID_DATA")
    assert_best_error(post("x" * (65 * 1024)), 413, "PAYLOAD_TOO_LARGE")
    monkeypatch.setenv("SITEIQ_ALLOW_PRIVATE_TARGETS", "0")
    private = command("http://169.254.169.254/latest/meta-data/")
    assert_best_error(post(json.dumps(private)), 400, "TARGET_NOT_ALLOWED")


def test_plain_json_content_type_is_accepted(client, monkeypatch):
    monkeypatch.setattr(service, "submit_analysis", lambda url, corr, **k: None)
    r = client.post("/best/commands", content=json.dumps(command("https://example.com/")),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 202


def test_command_id_is_an_idempotency_key(client, monkeypatch):
    started = []
    monkeypatch.setattr(service, "submit_analysis", lambda url, corr, **k: started.append(url))
    env = command("https://example.com/")
    first = client.post("/best/commands", content=json.dumps(env), headers=CE)
    again = client.post("/best/commands", content=json.dumps(env), headers=CE)
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    assert started == ["https://example.com/"]
    changed = {**env, "data": {"url": "https://example.org/"}}
    assert_best_error(client.post("/best/commands", content=json.dumps(changed), headers=CE),
                      409, "DUPLICATE_COMMAND_ID")


def test_commands_are_rate_limited_per_client(client, monkeypatch):
    from app.best import router
    monkeypatch.setattr(service, "submit_analysis", lambda url, corr, **k: None)
    monkeypatch.setattr(router.command_limiter, "limit", 2)
    codes = [client.post("/best/commands", content=json.dumps(command("https://example.com/")),
                         headers=CE).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_queue_full_is_503_and_frees_the_id(client, monkeypatch):
    from app import jobs
    monkeypatch.setattr(jobs, "MAX_QUEUED_JOBS", 0)
    env = command("https://example.com/")
    r = client.post("/best/commands", content=json.dumps(env), headers=CE)
    assert_best_error(r, 503, "QUEUE_FULL")
    assert r.headers["retry-after"] == "60"
    monkeypatch.setattr(service, "submit_analysis", lambda url, corr, **k: None)
    assert client.post("/best/commands", content=json.dumps(env), headers=CE).status_code == 202


# ----------------------------------------------------------- events/queries --

def test_event_log_paging_and_filters(client):
    event_log.clear()
    for i in range(3):
        service._publish("SiteAnalysisStarted", f"page-{i}", {"analysisId": "0" * 32, "url": "https://a.it"})
    first = client.get("/best/events", params={"limit": 2}).json()
    assert len(first["events"]) == 2 and "nextCursor" in first
    rest = client.get("/best/events", params={"limit": 2, "after": first["nextCursor"]}).json()
    assert [e["correlationid"] for e in rest["events"]] == ["page-2"]
    assert "nextCursor" not in rest
    only = client.get("/best/events", params={"correlationId": "page-1"}).json()["events"]
    assert [e["correlationid"] for e in only] == ["page-1"]
    assert client.get("/best/events", params={"type": "SiteCrawled"}).json()["events"] == []
    assert_best_error(client.get("/best/events", params={"from": "yesterday"}), 400, "INVALID_PARAMETERS")


def test_query_parameter_errors(client):
    assert_best_error(client.get("/best/queries/nope"), 404, "SCHEMA_NOT_FOUND")
    assert_best_error(client.get("/best/queries/get-analysis"), 400, "INVALID_PARAMETERS")
    assert_best_error(client.get("/best/queries/get-analysis", params={"analysisId": "x"}),
                      400, "INVALID_PARAMETERS")
    assert_best_error(client.get("/best/queries/get-analysis", params={"analysisId": "a" * 32}),
                      404, "ANALYSIS_NOT_FOUND")


def test_non_best_analyses_are_not_visible(client):
    from app import jobs
    from app.llm import StubLlm
    job = jobs.store.create("https://example.com", StubLlm(), origin="lead")
    assert_best_error(client.get("/best/queries/get-analysis", params={"analysisId": job.id}),
                      404, "ANALYSIS_NOT_FOUND")


def test_wordpress_findings_projection():
    result = {"checks": {}, "wordpress_security": {
        "is_wordpress": True,
        "core": {"version": "6.4.2", "status": "ok", "vulnerabilities": []},
        "plugins": [
            {"slug": "contact-form-7", "version": "5.9.2", "status": "ok",
             "vulnerabilities": [{"cve": "CVE-2024-1, CVE-2024-2"}]},
            {"slug": "woo_commerce", "version": None, "status": "unknown", "vulnerabilities": []},
        ]}}
    by_id = {f["id"]: f for f in service.project_findings(result)}
    assert by_id["wordpress.core"]["status"] == "ok"
    cf7 = by_id["wordpress.plugin.contact-form-7"]
    assert cf7["status"] == "error" and cf7["references"] == ["CVE-2024-1", "CVE-2024-2"]
    assert by_id["wordpress.plugin.woo-commerce"]["status"] == "warn"
