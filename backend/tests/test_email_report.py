"""Test del report email (render + invio via mailer monkeypatch)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import os
os.environ.setdefault("AUTH_CLIENTS", "fabio=test")


def _report():
    return {
        "url": "https://example.com/",
        "summary": {"verdict": "attention", "most_urgent": "Contrasto colore insufficiente.",
                    "highlights": ["x"]},
        "scores": {"development": {"value": 60, "grade": "D"},
                   "seo": {"value": 85, "grade": "B"},
                   "security": {"value": 90, "grade": "A"},
                   "accessibility": {"value": 45, "grade": "F"},
                   "performance": {"value": 70, "grade": "C"}},
        "checks": {"security": [
            {"id": "hsts", "label": "Strict-Transport-Security", "status": "ok", "detail": "presente"},
            {"id": "csp", "label": "Content-Security-Policy", "status": "warn", "detail": "header mancante"},
        ]},
        "wordpress_security": {"is_wordpress": True,
                               "core": {"version": "6.4.2", "vulnerabilities": [{"cve": "CVE-1"}]},
                               "plugins": [
                                   {"slug": "contact-form-7", "version": "5.9.2", "status": "ok",
                                    "vulnerable": True, "vulnerabilities": [{"cve": "CVE-2024-4704"}]},
                                   {"slug": "woo", "version": "8.1.0", "status": "ok",
                                    "vulnerable": False, "vulnerabilities": []}]},
        "recommendations": [{"priority": "P0", "title": "Contrasto", "detail": "porta a 4.5:1",
                             "evidence_ref": "x", "effort": "low"},
                            {"priority": "P1", "title": "Alt", "detail": "aggiungi alt",
                             "evidence_ref": "y", "effort": "low"}],
        "areas": [
            {"name": "Business/posizionamento", "score10": 7,
             "analysis": "Comunicazione chiara.", "strengths": ["Posizionamento"],
             "weaknesses": ["Stelle non dichiarate"], "evidence_ref": None},
            {"name": "Sicurezza", "score10": 4,
             "analysis": "Header assenti.", "strengths": ["HTTPS valido"],
             "weaknesses": ["Header mancanti"], "evidence_ref": "pages[0].http_headers"},
        ],
        "overall": {"score10": 5, "verdict": "Problemi da sistemare.",
                    "macro_areas": {"Business": 7, "Velocità": 4, "Marketing": 7}},
        "action_plan": {"immediate_0_30": ["Inserire H1"],
                        "medium_30_90": ["Ottimizzare immagini"],
                        "long_90_365": ["Integrare booking"]},
        "opportunities": [{"title": "Perf", "benefit": "Velocità", "priority": "High"}],
        "glossary": [{"term": "LCP", "definition": "Contenuto visibile"}],
        "commercial_proposal": None,
    }


def test_render_html_balanced_and_contains_sections():
    from app.email_report import render_report_email
    subj, body = render_report_email(_report())
    assert "SiteIQ" in subj
    for tag in ("<table", "<tr", "<td", "</table", "</tr>", "</td>"):
        assert tag in body
    assert "Sicurezza WordPress" in body
    assert "contact-form-7" in body
    assert "Punteggi per area" in body


def test_send_report_builds_multipart(monkeypatch):
    import smtplib as _smtplib
    from app import mailer as _mailer

    captured = {}
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): captured["msg"] = msg

    monkeypatch.setattr(_smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(_mailer, "smtp_config",
                        lambda: {"host": "smtp.x", "port": 587, "user": "u", "password": "p",
                                 "sender": "siteiq@example.com"})

    from app.mailer import send_report
    from app.email_report import render_report_email
    subj, body = render_report_email(_report())
    send_report("pippo@esempio.it", subj, body)

    msg = captured["msg"]
    assert msg["To"] == "pippo@esempio.it"
    assert msg.is_multipart() is True


_MINI_CRAWL = {
    "url": "https://x.it", "scan_meta": {},
    "pages": [{"status": "ok", "http_status": 200, "redirect_chain": [],
               "seo": {"title": "t", "title_length": 1, "meta_description": "m",
                       "headings": {}, "canonical": None, "hreflang_count": 0,
                       "schema_jsonld": []}, "http_headers": {},
               "images_missing_alt": 0, "charset_ok": True, "robots_respected": True}],
}


def _run_job(monkeypatch, tmp_path, llm, **job_kwargs):
    from app import jobs
    monkeypatch.setattr(jobs, "REPORTS_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(jobs, "_send_report_email", lambda rcpt, rep, loc: sent.append(rcpt))
    # crawl stub: evita Playwright
    monkeypatch.setattr(jobs, "crawl_site", lambda url, max_pages=1, progress=None: _MINI_CRAWL)
    job = jobs.Job("https://x.it", llm, **job_kwargs)
    job.run()
    assert job.status == "done", job.error
    return sent


def _real_like_llm():
    """LLM finto ma NON stub: si comporta come OpenRouter ai fini delle email."""
    from app.llm import StubLlm

    class FakeRealLlm(StubLlm):
        name = "fake-real"
        is_stub = False

    return FakeRealLlm()


def test_job_notifies_both_notify_address_and_lead(monkeypatch, tmp_path):
    """A fine job, il report va a REPORT_NOTIFY_EMAIL E al lead."""
    monkeypatch.setenv("REPORT_NOTIFY_EMAIL", "notify@example.com")
    sent = _run_job(monkeypatch, tmp_path, _real_like_llm(),
                    client="lead:utente@esempio.it", notify_email="utente@esempio.it")
    assert sorted(sent) == ["notify@example.com", "utente@esempio.it"]


def test_job_notifies_address_even_without_lead(monkeypatch, tmp_path):
    """Anche senza lead, se configurato, il report va a REPORT_NOTIFY_EMAIL."""
    monkeypatch.setenv("REPORT_NOTIFY_EMAIL", "notify@example.com")
    sent = _run_job(monkeypatch, tmp_path, _real_like_llm(), client="admin")
    assert sent == ["notify@example.com"]


def test_stub_job_never_sends_email(monkeypatch, tmp_path):
    """Il report dello stub è testo fisso di esempio: non va mai spedito."""
    from app.llm import StubLlm
    monkeypatch.setenv("REPORT_NOTIFY_EMAIL", "notify@example.com")
    sent = _run_job(monkeypatch, tmp_path, StubLlm(), client="admin",
                    notify_email="utente@esempio.it")
    assert sent == []


def test_render_page_is_full_html_styled():
    """La pagina report e' HTML5 autonomo, con CSS e sezioni (per /admin)."""
    from html import unescape
    from app.email_report import render_report_page
    page = unescape(render_report_page(_report()))
    assert "<!doctype html>" in page
    assert "SiteIQ" in page
    assert ".score-card" in page or ".scores" in page
    assert "example.com" in page  # il dominio del sito analizzato è evidenziato
    assert "title-site" in page
    assert "Sicurezza WordPress" in page
    assert "contact-form-7" in page
    assert "<style>" in page
    assert "VULNERABILE" in page
    assert "aree esaminate" in page
    assert "Business/posizionamento" in page
    assert "Giudizio finale" in page
    assert "Piano d'azione" in page
    assert "Le opportunità principali" in page
    assert "Glossario" in page


def test_email_contains_new_sections():
    """L'email ora include 17 aree, giudizio, piano, opportunità e glossario."""
    from html import unescape
    from app.email_report import render_report_email
    _, body = render_report_email(_report())
    body = unescape(body)
    assert "aree esaminate" in body
    assert "Business/posizionamento" in body
    assert "Giudizio finale" in body
    assert "Piano d'azione" in body
    assert "Le opportunità principali" in body
    assert "Glossario" in body
    assert "LCP" in body


def test_save_report_page_writes_file(monkeypatch, tmp_path):
    """_save_report_page scrive il file HTML del report su disco."""
    from app import jobs
    monkeypatch.setattr(jobs, "REPORTS_DIR", tmp_path)
    path = jobs._save_report_page("jobtest123", _report())
    assert path is not None
    assert (tmp_path / "jobtest123.html").is_file()
    content = (tmp_path / "jobtest123.html").read_text(encoding="utf-8")
    assert "Punteggi per area" in content