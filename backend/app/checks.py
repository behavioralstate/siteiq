"""Verifiche per categoria (Fase 6 — dettaglio tipo GooUX).

Calcolate in post-processing DETERMINISTICO dal crawl_report: sono fatti
oggettivi (header presente/assente, lunghezza title, vitals oltre soglia), quindi
non vengono affidati al LLM — zero allucinazioni, zero spend di token extra.

Output: dict {category: [ {id, label, status: ok|warn|error, detail?} ]}, con label
e detail nella lingua richiesta (locales/<locale>.json, sezione "checks").
Le categorie rispecchiano i 5 reparti: development, seo, security, accessibility,
performance.

Severity map per il frontend: ok=verde, warn=ambra, error=rosso. Ogni check ha
una evidenza nel crawl_report (no assunzioni).
"""
from __future__ import annotations

from collections import Counter

from app.i18n import DEFAULT_LOCALE, Translator

# Threshold Core Web Vitals (dalla skill pagespeed-insights)
# (px, good_max, poor_min): sotto good = good; tra good e poor = warn; sopra = error
CWV = {
    "LCP_ms":  ("LCP",  2500, 4000),
    "FCP_ms":  ("FCP",  1800, 3000),
    "CLS":     ("CLS",  0.10, 0.25),
    "TTFB_ms": ("TTFB", 800,  1800),
    "INP_or_TBT_ms": ("INP/TBT", 200, 500),
}


def _sev(value, good, poor):
    return "ok" if value < good else ("warn" if value < poor else "error")


SECURITY_HEADERS = (
    ("strict-transport-security", "Strict-Transport-Security (HSTS)"),
    ("content-security-policy", "Content-Security-Policy (CSP)"),
    ("x-frame-options", "X-Frame-Options"),
    ("x-content-type-options", "X-Content-Type-Options"),
    ("referrer-policy", "Referrer-Policy"),
    ("permissions-policy", "Permissions-Policy"),
)


def build_checks(crawl: dict, locale: str = DEFAULT_LOCALE) -> dict:
    """Ritorna {category: [checks]} per il report, con i testi nel `locale`.
    Usa SOLO pagine ok; gli altri dati reali (error/skipped) vengono accorpati
    in un check diagnostico. Funzione pura: ricalcolabile in un altro locale."""
    tr = Translator(locale)
    pages = crawl.get("pages", [])
    ok_pages = [p for p in pages if p.get("status") == "ok"]
    non_ok = [p for p in pages if p.get("status") != "ok"]

    checks = {k: [] for k in ("development", "seo", "security", "accessibility", "performance")}

    def ck(cid: str, status: str, detail: str = "", label: str | None = None) -> dict:
        key = cid if label is None else None
        return _ck(cid, label if label is not None else tr(f"checks.{key}.label"), status, detail)

    # --- Sviluppo Web ---
    dev = checks["development"]
    if not ok_pages:
        dev.append(_ck("http", tr("checks.http_unreachable.label"), "error",
                       tr("checks.http_unreachable.detail")))
    else:
        p0 = ok_pages[0]
        st = p0.get("http_status", 0)
        dev.append(ck("http", "ok" if st == 200 else "warn" if st < 400 else "error",
                      tr("checks.http.detail", status=st)))
        hops = len(p0.get("redirect_chain", []) or [])
        dev.append(ck("redirect", "ok" if not hops else "warn" if hops <= 5 else "error",
                      tr("checks.redirect.too_many" if hops > 5 else "checks.redirect.detail",
                         count=hops)))
        charset_ok = p0.get("charset_ok")
        dev.append(ck("charset", "ok" if charset_ok else "error",
                      tr("checks.charset.present" if charset_ok else "checks.charset.missing")))

    # --- SEO ---
    seo = checks["seo"]
    if ok_pages:
        s = ok_pages[0].get("seo", {})
        title = s.get("title") or None
        tl = s.get("title_length") or 0
        seo.append(ck("title", "ok" if title and 10 <= tl <= 70 else "warn" if title else "error",
                      tr("checks.text_with_length", text=title[:60], count=tl) if title
                      else tr("checks.missing")))
        desc = s.get("meta_description") or None
        dl = len(desc) if desc else 0
        seo.append(ck("meta_description", "ok" if desc and 50 <= dl <= 160 else "warn" if desc else "error",
                      tr("checks.text_with_length", text=desc[:60], count=dl) if desc
                      else tr("checks.missing")))
        h1 = s.get("headings", {}).get("h1", 0)
        seo.append(ck("h1", "ok" if h1 == 1 else "warn" if h1 > 1 else "error",
                      tr("checks.h1.detail", count=h1)))
        seo.append(ck("canonical", "ok" if s.get("canonical") else "warn",
                      s.get("canonical") or tr("checks.canonical.missing")))
        # hreflang: informativo. Assente è corretto per un sito monolingua,
        # presente indica versioni linguistiche dichiarate: nessuno dei due è un errore.
        hrefl = s.get("hreflang_count", 0)
        seo.append(ck("hreflang", "ok",
                      tr("checks.hreflang.detail", count=hrefl) if hrefl else tr("checks.hreflang.none")))
        jsonld = s.get("schema_jsonld", []) or []
        seo.append(ck("schema", "ok" if jsonld else "warn",
                      tr("checks.schema.detail", count=len(jsonld)) if jsonld else tr("checks.schema.none")))

    # --- Sicurezza ---
    sec = checks["security"]
    if ok_pages:
        h = ok_pages[0].get("http_headers", {}) or {}
        for hid, label in SECURITY_HEADERS:
            present = bool(h.get(hid))
            sec.append(ck(hid.replace("-", "_"), "ok" if present else "warn",
                          tr("checks.header.present" if present else "checks.header.missing"),
                          label=label))

    # --- Accessibilità ---
    acc = checks["accessibility"]
    for p in ok_pages:
        a11y = p.get("accessibility", {})
        viol = a11y.get("violations", []) or []
        alt_missing = p.get("images_missing_alt", 0)
        acc.append(ck("alt", "ok" if alt_missing == 0 else "warn",
                      tr("checks.alt.detail", count=alt_missing)))
        contrast = a11y.get("contrast_violations", 0)
        acc.append(ck("contrast", "ok" if contrast == 0 else "error",
                      tr("checks.contrast.detail", count=contrast)))
        # raggruppa violazioni axe per regola
        grouped = Counter(v.get("rule") or "unknown" for v in viol)
        for rule, count in grouped.items():
            acc.append(ck("axe_" + rule, "error", tr("checks.axe.detail", count=count),
                          label=tr("checks.axe.label", rule=rule)))

    # --- Performance ---
    perf = checks["performance"]
    if ok_pages:
        v = ok_pages[0].get("vitals") or {}
        if not any(v.get(k) for k in CWV):
            perf.append(ck("vitals", "warn", tr("checks.vitals.detail")))
        for key, (label, good, poor) in CWV.items():
            val = v.get(key)
            if val is None or val == 0:
                continue
            valtxt = (tr.number(val, 2) if key == "CLS"
                      else tr("checks.milliseconds", value=tr.number(val, 0)))
            perf.append(ck(key.lower().replace("_", "."), _sev(val, good, poor), valtxt, label=label))

    # diagnostica: se ci sono pagine non-ok, accorpale (info, non severità)
    if non_ok:
        n_err = sum(1 for p in non_ok if p.get("status") == "error")
        n_skip = len(non_ok) - n_err
        detail = tr("checks.scan.detail", count=len(non_ok), errors=n_err, skipped=n_skip)
        if n_skip:
            detail = tr("checks.scan.with_robots", detail=detail,
                        robots=tr("checks.scan.robots", count=n_skip))
        checks["development"].insert(0, ck("scan", "error" if n_err else "warn", detail))

    # pulisci check vuoti (categorie senza pagina ok e senza diagnostica)
    return {k: v for k, v in checks.items() if v}


def _ck(cid: str, label: str, status: str, detail: str = "") -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail}
