"""Localizzazione: coerenza dei cataloghi, uso delle chiavi, resa nelle due lingue."""
import json
import re
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.i18n import SUPPORTED, catalog, negotiate, t
from app.main import app

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND = ROOT / "frontend"
HTML_PAGES = ("index.html", "admin.html", "report_viewer.html")
EN = {"Accept-Language": "en-GB"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# chiavi letterali nei punti di chiamata (quelle composte a runtime sono
# coperte dai test di comportamento qui sotto)
PY_KEY_CALLS = (
    re.compile(r"""\bt\(\s*[\w.]+\s*,\s*["']([\w.]+)["']"""),             # t(locale, "k")
    re.compile(r"""\btr(?:\.optional|\.list)?\(\s*["']([\w.]+)["']"""),     # tr("k")
)
PY_BEST_MSGS = (
    re.compile(r'BestError\(\s*\d+,\s*"[A-Z_]+",\s*"(\w+)"'),              # messaggio BEST
    re.compile(r'_invalid\(\s*[\w"]+,\s*"(\w+)"'),
)
JS_KEY_CALLS = re.compile(r"""(?:I18N\.t|I18N\.optional|\bt|\btr)\(\s*["']([\w.]+)["']""")
HTML_KEYS = re.compile(r"""data-i18n(?:-html)?="([\w.]+)"|:\s*([\w.]+)(?=[;"])""")


def _placeholders(value) -> set:
    if isinstance(value, dict):
        return set().union(*(_placeholders(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(set(), *(_placeholders(v) for v in value))
    return set(PLACEHOLDER.findall(value))


# --------------------------------------------------------------- catalogs --

def test_catalogs_have_the_same_keys_and_shapes():
    it, en = catalog("it-IT"), catalog("en-GB")
    assert set(it) == set(en), sorted(set(it) ^ set(en))
    for key in it:
        assert type(it[key]) is type(en[key]), key
        if isinstance(it[key], dict):
            assert set(it[key]) == set(en[key]), key


def test_catalogs_use_the_same_placeholders():
    it, en = catalog("it-IT"), catalog("en-GB")
    mismatched = [k for k in it if _placeholders(it[k]) != _placeholders(en[k])]
    assert not mismatched, mismatched


def test_every_key_used_in_code_exists():
    known = catalog("it-IT")
    used = set()
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for rx in PY_KEY_CALLS:
            used |= {(path.name, k) for k in rx.findall(text)}
        for rx in PY_BEST_MSGS:
            used |= {(path.name, "best.errors." + m) for m in rx.findall(text)}
    for path in FRONTEND.glob("*.js"):
        used |= {(path.name, k) for k in JS_KEY_CALLS.findall(path.read_text(encoding="utf-8"))}
    for page in HTML_PAGES:
        for a, b in HTML_KEYS.findall((FRONTEND / page).read_text(encoding="utf-8")):
            if (a or b).count("."):
                used.add((page, a or b))
    assert len(used) > 200, "lo scanner non trova più le chiavi: controlla le regex"
    missing = sorted(f"{name}: {key}" for name, key in used
                     if "." in key and not key.endswith((".", "_")) and key not in known)
    assert not missing, missing


class _InlineText(HTMLParser):
    """Testo italiano scritto nell'HTML per ogni data-i18n (fallback senza JS)."""
    VOID = {"meta", "link", "input", "br", "img", "hr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.stack = {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for pair in (a.get("data-i18n-attr") or "").split(";"):
            if ":" in pair:
                attr, key = (s.strip() for s in pair.split(":", 1))
                self.found.setdefault(key, set()).add(a.get(attr, ""))
        if self.stack and self.stack[-1][2] == "html":
            self.stack[-1][3].append(self.get_starttag_text())
        if tag in self.VOID:
            return
        key = a.get("data-i18n") or a.get("data-i18n-html")
        mode = "text" if "data-i18n" in a else "html" if "data-i18n-html" in a else None
        self.stack.append([tag, key, mode, []])

    def handle_endtag(self, tag):
        if tag in self.VOID or not self.stack:
            return
        _, key, _, parts = self.stack.pop()
        if key:
            self.found.setdefault(key, set()).add("".join(parts).strip())

    def handle_data(self, data):
        for frame in self.stack:
            if frame[1]:
                frame[3].append(data)


def test_html_inline_text_matches_the_italian_catalog():
    it = catalog("it-IT")
    for page in HTML_PAGES:
        parser = _InlineText()
        parser.feed((FRONTEND / page).read_text(encoding="utf-8"))
        for key, values in parser.found.items():
            assert values == {it[key]}, f"{page}: {key} = {values} != {it[key]!r}"


# ------------------------------------------------------------- resolution --

@pytest.mark.parametrize("header, expected", [
    ("en-GB", "en-GB"), ("en-US,en;q=0.9", "en-GB"), ("fr-FR, it;q=0.5", "it-IT"),
    ("de-DE", "it-IT"), ("", "it-IT"), (None, "it-IT"), ("en;q=0, it;q=0.1", "it-IT"),
    ("it-CH;q=0.4, en;q=0.8", "en-GB"), ("*", "it-IT"),
])
def test_accept_language_negotiation(header, expected):
    assert negotiate(header) == expected


def test_plurals_and_number_formats():
    assert t("it-IT", "checks.h1.detail", count=1) == "1 elemento H1"
    assert t("it-IT", "checks.h1.detail", count=2) == "2 elementi H1"
    assert t("en-GB", "checks.h1.detail", count=1) == "1 H1 element"
    assert t("en-GB", "checks.h1.detail", count=0) == "0 H1 elements"
    assert i18n.format_number("it-IT", 2345.6, 0) == "2.346"
    assert i18n.format_number("en-GB", 2345.6, 0) == "2,346"
    assert i18n.format_number("it-IT", 0.125, 2) == "0,12" or i18n.format_number("it-IT", 0.125, 2) == "0,13"


def test_missing_key_falls_back_to_the_key(caplog):
    assert t("en-GB", "nope.not.here") == "nope.not.here"
    assert t("xx-XX", "checks.missing") == t("it-IT", "checks.missing")


# ------------------------------------------------------------------ HTTP --

def test_locale_catalogs_are_served(client=None):
    c = TestClient(app)
    assert c.get("/locales/en-GB.json").json()["meta"]["html_lang"] == "en-GB"
    assert c.get("/locales/fr-FR.json").status_code == 404


def test_api_errors_follow_accept_language():
    c = TestClient(app)
    it = c.post("/api/lead", json={"email": "not-an-email", "url": "https://example.com"})
    en = c.post("/api/lead", json={"email": "not-an-email", "url": "https://example.com"}, headers=EN)
    assert it.json()["detail"] == "email non valida"
    assert en.json()["detail"] == "invalid email address"
    assert en.headers["content-language"] == "en-GB"
    assert "Accept-Language" in en.headers["vary"]


def test_confirmation_email_and_link_use_the_request_locale(monkeypatch):
    sent = []
    monkeypatch.setattr("app.routers.lead.send_confirmation",
                        lambda email, url, locale=None: sent.append((url, locale)))
    r = TestClient(app).post("/api/lead", json={"email": f"en{time.time_ns()}@example.com",
                                                "url": "https://example.com"}, headers=EN)
    assert r.json()["message"] == "check your email to confirm"
    url, locale = sent[0]
    assert locale == "en-GB" and "lang=en-GB" in url


def test_confirmation_email_text_is_localized(monkeypatch):
    from app import mailer
    captured = {}
    monkeypatch.setattr(mailer, "_send", lambda msg: captured.setdefault("msg", msg))
    mailer.send_confirmation("a@example.com", "https://x/?token=1", "en-GB")
    assert captured["msg"]["Subject"] == "Confirm your email — SiteIQ"
    assert "https://x/?token=1" in captured["msg"].get_content()


def test_best_errors_follow_accept_language():
    c = TestClient(app)
    assert c.get("/best/nothing").json()["error"]["message"].startswith("Nessuna route BEST")
    en = c.get("/best/nothing", headers=EN).json()["error"]
    assert en["code"] == "NOT_FOUND" and en["message"].startswith("No BEST route")


def test_best_findings_are_rendered_in_the_query_locale(monkeypatch):
    from app import jobs
    from app.best import service
    crawl = {"url": "https://example.com", "pages": [{
        "status": "ok", "http_status": 200, "redirect_chain": [], "charset_ok": True,
        "seo": {"title": None, "headings": {"h1": 2}}, "http_headers": {},
        "images_missing_alt": 0, "accessibility": {"violations": [], "contrast_violations": 0}}]}
    job = jobs.store.create("https://example.com", None, origin="best")
    job.crawl, job.result, job.status = crawl, {"url": "https://example.com"}, "done"
    c = TestClient(app)
    params = {"analysisId": job.id, "category": "seo"}
    it = {f["id"]: f for f in c.get("/best/queries/get-findings", params=params).json()["findings"]}
    en = {f["id"]: f for f in c.get("/best/queries/get-findings", params=params, headers=EN).json()["findings"]}
    assert it["seo.h1"]["detail"] == "2 elementi H1"
    assert en["seo.h1"]["detail"] == "2 H1 elements"
    assert it.keys() == en.keys()
    assert service.finding_counts(list(it.values())) == service.finding_counts(list(en.values()))


# ------------------------------------------------------- report and LLM --

def _report():
    from app.llm import StubLlm
    return StubLlm().analyze({"url": "https://example.com/", "pages": [
        {"status": "ok", "images_missing_alt": 2, "accessibility": {"violations": []}}]}, locale="en-GB")


def test_report_page_and_email_in_english():
    from html import unescape
    from app.email_report import render_report_email, render_report_page
    rep = _report()
    page = unescape(render_report_page(rep, "en-GB"))
    subject, body = render_report_email(rep, "en-GB")
    assert '<html lang="en-GB">' in page
    for text in ("Final verdict", "Action plan", "The 17 areas examined", "Ease of use",
                 "Business/positioning", "At least 2 images without an alt attribute."):
        assert text in page, text
    assert subject == "Analysis of your website https://example.com/ — SiteIQ"
    assert "What to fix first" in unescape(body)
    assert "Giudizio" not in page and "Piano" not in page


def test_report_labels_come_from_ids_not_from_llm_text():
    from html import unescape
    from app.email_report import render_report_page
    rep = _report()  # testi inglesi, ma etichette di area/macro dagli id
    page = unescape(render_report_page(rep, "it-IT"))
    assert "Business/posizionamento" in page and "Facilità d'uso" in page


def test_prompt_asks_for_the_locale_language_and_ids():
    from app.prompt import AREA_IDS, MACRO_IDS, get_system_prompt
    en = get_system_prompt("en-GB")
    assert "in British English" in en
    assert all(f'"{a}"' in en for a in AREA_IDS) and all(f'"{m}"' in en for m in MACRO_IDS)
    assert "in italiano" in get_system_prompt("it-IT")


# ------------------------------------------------- frontend (real browser) --

@pytest.fixture(scope="module")
def live_server():
    import socket as _socket

    import uvicorn
    with _socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(timeout=5)


def test_landing_switches_language_and_remembers_it(live_server):
    from playwright.sync_api import sync_playwright
    en = catalog("en-GB")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(locale="it-IT")
            page.goto(f"{live_server}/")
            page.wait_for_function("document.documentElement.lang === 'it'")
            assert page.locator("h1").inner_text().startswith("Capire il tuo sito")

            page.click("[data-set-locale='en-GB']")
            page.wait_for_function("document.documentElement.lang === 'en-GB'")
            assert page.locator("h1").inner_text().replace("\n", " ") == "Understand your website, on one page."
            assert page.title() == en["web.landing.page_title"]
            assert page.get_attribute("#lead-email", "placeholder") == en["web.landing.email_placeholder"]
            assert page.get_attribute("[data-set-locale='en-GB']", "aria-pressed") == "true"

            page.reload()  # la scelta resta salvata
            page.wait_for_function("document.documentElement.lang === 'en-GB'")

            page.fill("#lead-url", "not a url")
            page.click("#lead-form button[type=submit]")
            assert page.locator("#lead-error").inner_text() == en["web.app.url_invalid"]
        finally:
            browser.close()


def test_browser_language_picks_english_and_lang_param_wins(live_server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context(locale="en-US").new_page()
            page.goto(f"{live_server}/admin")
            page.wait_for_function("document.documentElement.lang === 'en-GB'")
            assert page.locator("h1").inner_text() == "Admin panel"
            page.goto(f"{live_server}/admin?lang=it-IT")
            page.wait_for_function("document.documentElement.lang === 'it'")
            assert page.locator("h1").inner_text() == "Pannello admin"
        finally:
            browser.close()
