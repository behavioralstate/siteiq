"""Verifiche per categoria (Fase 6 — dettaglio tipo GooUX).

Calcolate in post-processing DETERMINISTICO dal crawl_report: sono fatti
oggettivi (header presente/assente, lunghezza title, vitals oltre soglia), quindi
non vengono affidati al LLM — zero allucinazioni, zero spend di token extra.

Output: dict {category: [ {id, label, status: ok|warn|error, detail?} ]}
Le categorie rispecchiano i 5 reparti: development, seo, security, accessibility,
performance.

Severity map per il frontend: ok=verde, warn=ambra, error=rosso. Ogni check ha
una evidenza nel crawl_report (no assunzioni).
"""
from __future__ import annotations

from collections import Counter

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


def build_checks(crawl: dict) -> dict:
    """Ritorna {category: [checks]} per il report. Usa SOLO pagine ok; gli
    altri dati reali (error/skipped) vengono accorpati in un check diagnostico."""
    pages = crawl.get("pages", [])
    ok_pages = [p for p in pages if p.get("status") == "ok"]
    non_ok = [p for p in pages if p.get("status") != "ok"]
    meta = crawl.get("scan_meta", {})

    checks = {k: [] for k in ("development", "seo", "security", "accessibility", "performance")}

    # --- Sviluppo Web ---
    dev = checks["development"]
    if not ok_pages:
        dev.append(_ck("http", "Pagina raggiungibile (HTTP 200)", "error",
                       "Nessuna pagina OK analizzata — controlla che l'URL sia pubblico e raggiungibile."))
    else:
        p0 = ok_pages[0]
        st = p0.get("http_status", 0)
        dev.append(_ck("http", "HTTP status", "ok" if st == 200 else "warn" if st < 400 else "error",
                       f"HTTP {st}"))
        chain = p0.get("redirect_chain", []) or []
        dev.append(_ck("redirect", "Catena di redirect", "ok" if not chain else "warn" if len(chain) <= 5 else "error",
                       f"{len(chain)} hop" + (" (troppi: >5)" if len(chain) > 5 else "")))
        dev.append(_ck("charset", "Codifica caratteri dichiarata",
                       "ok" if p0.get("charset_ok") else "error", "Meta charset presente o assente"))
        dev.append(_ck("robots", "robots.txt rispettato", "ok" if p0.get("robots_respected", True) else "warn"))

    # --- SEO ---
    seo = checks["seo"]
    if ok_pages:
        p0 = ok_pages[0]
        s = p0.get("seo", {})
        title = s.get("title") or None
        tl = s.get("title_length") or 0
        seo.append(_ck("title", "Title tag", "ok" if title and 10 <= tl <= 70
                       else "warn" if title else "error",
                       f"{(title or 'Mancante')[:60]}" + (f" ({tl} caratteri)" if title else "")))
        desc = s.get("meta_description") or None
        dl = len(desc) if desc else 0
        seo.append(_ck("meta_description", "Meta description", "ok" if desc and 50 <= dl <= 160
                       else "warn" if desc else "error",
                       f"{(desc or 'Mancante')[:60]}" + (f" ({dl} caratteri)" if desc else "")))
        h1 = s.get("headings", {}).get("h1", 0)
        seo.append(_ck("h1", "H1 unico", "ok" if h1 == 1 else "warn" if h1 > 1 else "error",
                       f"{h1} elemento/i H1"))
        seo.append(_ck("canonical", "Canonical", "ok" if s.get("canonical") else "warn",
                       s.get("canonical") or "mancante"))
        hrefl = s.get("hreflang_count", 0)
        seo.append(_ck("hreflang", "Tag hreflang", "warn" if hrefl else "ok",
                       f"{hrefl} alternat(e) lingue"))
        jsonld = s.get("schema_jsonld", []) or []
        seo.append(_ck("schema", "Dati strutturati (schema.org)", "ok" if jsonld else "warn",
                       f"{len(jsonld)} blocco/i JSON-LD" if jsonld else "assenti"))

    # --- Sicurezza ---
    sec = checks["security"]
    if ok_pages:
        h = ok_pages[0].get("http_headers", {}) or {}
        for hid, label in (
            ("strict-transport-security", "Strict-Transport-Security (HSTS)"),
            ("content-security-policy", "Content-Security-Policy (CSP)"),
            ("x-frame-options", "X-Frame-Options"),
            ("x-content-type-options", "X-Content-Type-Options"),
            ("referrer-policy", "Referrer-Policy"),
            ("permissions-policy", "Permissions-Policy"),
        ):
            val = h.get(hid)
            sec.append(_ck(hid.replace("-", "_"), label, "ok" if val else "warn",
                           ("presente" if val else "header mancante")))

    # --- Accessibilità ---
    acc = checks["accessibility"]
    if ok_pages:
        for p in ok_pages:
            a11y = p.get("accessibility", {})
            viol = a11y.get("violations", []) or []
            # ALT mancanti
            alt_missing = p.get("images_missing_alt", 0)
            acc.append(_ck("alt", "Immagini con ALT", "ok" if alt_missing == 0 else "warn",
                           f"{alt_missing} immagine/i senza alt"))
            contrast = a11y.get("contrast_violations", 0)
            acc.append(_ck("contrast", "Contrasto colore (WCAG 1.4.3)", "ok" if contrast == 0 else "error",
                           f"{contrast} violazione/i"))
            # raggruppa violazioni axe per regola
            grouped = Counter(v.get("rule", "sconosciuta") for v in viol)
            for rule, count in grouped.items():
                acc.append(_ck("axe_" + rule, f"Violazione axe: {rule}", "error",
                               f"{count} nodo/i"))

    # --- Performance ---
    perf = checks["performance"]
    if ok_pages:
        v = ok_pages[0].get("vitals") or {}
        measured = any(v.get(k) for k in CWV)
        if not measured:
            perf.append(_ck("vitals", "Core Web Vitals misurati", "warn",
                            "Nessuna metrica misurata (ambiente headless o pagina non renderizzata)."))
        for key, (label, good, poor) in CWV.items():
            val = v.get(key)
            if val is None or val == 0:
                continue
            sev = _sev(val, good, poor)
            unit = "ms" if key != "CLS" else ""
            valtxt = f"{val:.0f}{unit}" if key != "CLS" else f"{val:.2f}"
            perf.append(_ck(key.lower().replace("_", "."), label, sev, valtxt))

    # diagnostica: se ci sono pagine non-ok, accorpale (info, non severità)
    if non_ok:
        n_err = sum(1 for p in non_ok if p.get("status") == "error")
        checks["development"].insert(0, _ck(
            "scan", "Integrità scansione",
            "error" if n_err else "ok",
            f"{len(non_ok)} pagina/e non analizzabile/i (err={n_err}, skip={len(non_ok)-n_err})",
        ))

    # pulisci check vuoti (categorie senza pagina ok e senza diagnostica)
    return {k: v for k, v in checks.items() if v}


def _ck(cid: str, label: str, status: str, detail: str = "") -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail}