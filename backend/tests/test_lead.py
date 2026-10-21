"""Test flusso lead -> conferma email -> 1 scansione (Fase 5.5).

Evita l'SMTP reale: monkeypatch di app.mailer.send_confirmation.
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

os.environ["AUTH_CLIENTS"] = "fabio=test-token-fabio"
os.environ["USAGE_DB"] = "/home/fabio/siteiq/test_lead_usage.db"

from app.main import app  # noqa: E402


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@pytest.fixture(scope="module")
def fixture_server():
    handler = partial(QuietHandler, directory=str(Path(__file__).resolve().parent.parent.parent / "tests_fixture" / "site"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture()
def client(monkeypatch):
    # blocca l'invio email reale; cattura il token per i passi successivi
    captured = {}
    def fake_send(email, confirm_url):
        from urllib.parse import parse_qs, urlparse
        captured["url"] = confirm_url
        captured["token"] = parse_qs(urlparse(confirm_url).query)["token"][0]
    monkeypatch.setattr("app.routers.lead.send_confirmation", fake_send)
    return captured


def test_lead_flow_email_no_confirmation_no_scan(client):
    c = TestClient(app)
    email = f"utente-{int(time.time())}@esempio.it"
    # 1) crea lead: deve restare pending e NON dare diritto allo scan
    r = c.post("/api/lead", json={"email": email, "url": "https://esempio.it"})
    assert r.status_code == 200, r.text
    token = client["token"]
    assert token

    # senza conferma, lo scan è vietato
    r = c.post("/api/scan", json={"token": token})
    assert r.status_code == 403


def test_lead_reuse_same_email_is_idempotent(client):
    """Richiedere di nuovo con la stessa email non deve andare in errore (500):
    riusa il lead esistente e ritorna un token valido."""
    from app.leads import create_lead
    email = f"idemp-{int(time.time())}@esempio.it"
    l1 = create_lead(email, "https://a.it")
    l2 = create_lead(email, "https://b.it")
    assert l1 and l1["token"] == l2["token"], "stessa email deve riusare lo stesso token"
    assert l2["url"] == "https://b.it"


def test_confirm_lead_idempotent(client):
    """Confermare due volte lo stesso token non deve fallire (già confermato)."""
    from app.leads import create_lead, confirm_lead
    email = f"conf-{int(time.time())}@esempio.it"
    lead = create_lead(email, "https://x.it")
    assert lead is not None
    first = confirm_lead(lead["token"])
    second = confirm_lead(lead["token"])
    assert first and first["status"] == "confirmed"
    assert second and second["status"] == "confirmed"  # idempotente


def test_lead_flow_full_confirmation_enables_scan(client, fixture_server):
    c = TestClient(app)
    url = f"{fixture_server}/"
    email = f"utente2-{int(time.time())}@esempio.it"
    r = c.post("/api/lead", json={"email": email, "url": url})
    assert r.status_code == 200
    token = client["token"]

    # conferma email
    r = c.get(f"/api/confirm?token={token}")
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # ora lo scan è permesso (con stub LLM: veloce, offline, senza costo)
    import app.routers.lead as lead_router
    from app.llm import StubLlm
    lead_router.make_llm = lambda stub=False: StubLlm()

    r = c.post("/api/scan", json={"token": token})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    # attende il completamento (polling pubblico /api/scan/{id})
    deadline = time.time() + 90
    state = result = err = None
    while time.time() < deadline:
        j = c.get(f"/api/scan/{job_id}").json()
        state, result, err = j["status"], j.get("result"), j.get("error")
        if state in ("done", "error"):
            break
        time.sleep(1)
    assert state == "done", f"job: {state}, err {err}"
    assert result is not None

    # seconda scansione: vietata (1 sola per email)
    r = c.post("/api/scan", json={"token": token})
    assert r.status_code == 403