"""Test endpoint /api/analyze + auth + monitoraggio usage (Fase 5).

Esegue un'analisi reale sulla fixture (crawler vero) con lo stub LLM e
verifica: auth richiesta, job arriva a "done", e il consumo viene registrato.
"""
import json
import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "tests_fixture" / "site"

# token di test per l'auth (config via env, non tocca il .env di produzione)
TEST_TOKEN = "test-token-fabio"
os.environ["AUTH_CLIENTS"] = f"fabio={TEST_TOKEN}"
# DB usage isolato per i test
os.environ["USAGE_DB"] = str(ROOT / "test_usage.db")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
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


@pytest.fixture()
def client():
    return TestClient(app)


def _auth():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


def test_analyze_requires_auth(client, fixture_server):
    r = client.post("/api/analyze", json={"url": f"{fixture_server}/", "max_pages": 1})
    assert r.status_code in (401, 503)  # 401 se auth configurata, 503 se no


def test_analyze_rejects_bad_token(client, fixture_server):
    r = client.post("/api/analyze", json={"url": f"{fixture_server}/", "max_pages": 1},
                    headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_analyze_returns_job_id_and_reaches_done(client, fixture_server):
    url = f"{fixture_server}/"
    r = client.post("/api/analyze", json={"url": url, "max_pages": 1}, headers=_auth())
    assert r.status_code == 200
    assert r.json()["client"] == "fabio"
    job_id = r.json()["job_id"]
    assert job_id

    deadline = time.time() + 90
    state, result, err = None, None, None
    while time.time() < deadline:
        j = client.get(f"/api/analyze/{job_id}", headers=_auth()).json()
        state, result, err = j["status"], j.get("result"), j.get("error")
        if state in ("done", "error"):
            break
        time.sleep(1)
    assert state == "done", f"job mai completato: {state}, err {err}"
    assert result is not None


def test_usage_logged_after_analysis(client, fixture_server):
    """Dopo un'analisi, il log usage deve contenere la richiesta di fabio."""
    url = f"{fixture_server}/"
    r = client.post("/api/analyze", json={"url": url, "max_pages": 1}, headers=_auth())
    job_id = r.json()["job_id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        j = client.get(f"/api/analyze/{job_id}", headers=_auth()).json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(1)

    r = client.get("/api/admin/requests?log=fabio", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    assert any(req["url"].rstrip("/") == f"{fixture_server}" for req in data["requests"])


def test_admin_usage_requires_auth(client):
    r = client.get("/api/admin/usage")
    assert r.status_code in (401, 503)