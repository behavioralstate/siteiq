"""Crawler SiteIQ — scansiona SOLO l'URL inserito e produce un dict conforme a
schema/crawl_report.schema.json (versione 1.0.0).

Requirement (decisione 2026-10-07): l'URL da scansionare è SOLO quello che
l'utente inserisce. Niente BFS su link interni / discovery di pagine.

Per l'URL raccoglie: http_status + redirect chain, accessibilità (axe-core),
Core Web Vitals (CDP), header sicurezza, segnali SEO, alt mancanti, charset.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, sync_playwright

from app.egress_proxy import EgressProxy
from app.netguard import BlockedTarget, TargetGuard
from app.vitals import _OBSERVER_SCRIPT, read_vitals
from app.wpfingerprint import (core_version_from_feed, drop_core_versioned_plugins,
                               fingerprint, version_from_readme)

log = logging.getLogger(__name__)

SECURITY_HEADERS = ("strict-transport-security", "content-security-policy",
                    "x-frame-options", "x-content-type-options", "referrer-policy",
                    "permissions-policy")

SOCIAL_DOMAINS = {
    "facebook.com", "facebook.it", "fb.com", "instagram.com", "linkedin.com",
    "x.com", "twitter.com", "youtube.com", "tiktok.com", "pinterest.com",
    "whatsapp.com", "wa.me", "telegram.me", "t.me", "google.com/maps",
    "booking.com", "tripadvisor.com", "g.page", "gmb", "maps.google.com",
}


def _extract_qualitative(page: Page, url: str) -> dict:
    """Raccoglie i segnali qualitativi/commerciali per le 17 aree (PDF target):
    contenuti, contatti, canali social, tracker, booking engine, branding,
    placeholder (lorem ipsum), CTA, og:image. Restituisce sempre un dict completo.

    NOTA anti-allucinazione: qui raccogliamo SOLO ciò che è osservabile dal DOM;
    ciò che manca è assenza, non verdetto negativo.
    """
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)") if page.query_selector("a[href]") else []
    scripts = page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)") if page.query_selector("script[src]") else []
    iframes = page.eval_on_selector_all("iframe[src]", "els => els.map(e => e.src)") if page.query_selector("iframe[src]") else []

    # canali di contatto
    mailto = [h for h in hrefs if h.startswith("mailto:")]
    tel = [h for h in hrefs if h.startswith("tel:")]
    wa = [h for h in hrefs if "wa.me" in h or "whatsapp.com" in h]

    # canali social (da href + script/metatag)
    social = [h for h in hrefs if any(d in h for d in SOCIAL_DOMAINS)]
    meta_social = page.query_selector_all('meta[property^="og:"], meta[property^="twitter:"]')
    og = {}
    for m in meta_social:
        p = (m.get_attribute("property") or m.get_attribute("name") or "").strip()
        if p:
            og[p] = m.get_attribute("content") or ""

    # tracker
    sall = " ".join(scripts).lower()
    trackers = {
        "gtm": "googletagmanager" in sall,
        "ga4": "googletagmanager.com/gtag" in sall or "google-analytics" in sall,
        "fbpixel": "connect.facebook.net" in sall or "fbq" in " ".join(hrefs).lower(),
        "hotjar": "hotjar" in sall,
        "matomo": "matomo" in sall,
    }

    # booking engine esterno (booking platform integrati). Il booking engine può
    # apparire come <script>, <iframe> o come link esterno di prenotazione (<a>);
    # cerchiamo in tutti e tre.
    ext_hosts = []
    all_ext = " ".join(scripts + iframes + hrefs).lower()
    for host in ("ericsoft", "channelmanager", "booking", "softinn", "verssimo",
                 "travelclick", "blastness", "blastnessbooking"):
        if host in all_ext:
            ext_hosts.append(host)

    # branding: logo / favicon / colore brand / og:image
    logo = None
    for sel in ("img[alt*=logo i]", "img[src*=logo i]", ".logo img", "header img"):
        el = page.query_selector(sel)
        if el:
            logo = el.get_attribute("src") or el.get_attribute("alt") or sel
            break
    favicon = None
    fav = page.query_selector('link[rel~="icon"]')
    if fav:
        favicon = fav.get_attribute("href")
    brand_color = page.evaluate(
        "() => { const el = document.querySelector('h1,h2,a'); if(!el) return null;"
        " const c = getComputedStyle(el).color; return c.match(/\\d+/g) ? c.match(/\\d+/g).join(',') : c; }"
    )

    # CTA / form
    n_buttons = page.eval_on_selector_all("button, a.btn, a.button, [role=button]", "els => els.length") if page.query_selector("button, a.btn, a.button, [role=button]") else 0
    n_forms = page.eval_on_selector_all("form", "els => els.length") if page.query_selector("form") else 0

    # contenuti: estrai testo principale (per l'LLM per aree business/UX/contenuti)
    body_text = (page.inner_text("body") or "") if page.query_selector("body") else ""
    # rileva lorem ipsum segnaposto
    lorem = "lorem ipsum" in body_text.lower()

    # immagini totali vs con alt
    total_img = page.eval_on_selector_all("img", "els => els.length") if page.query_selector("img") else 0
    img_alt = page.eval_on_selector_all("img[alt]", "els => els.length") if page.query_selector("img[alt]") else 0

    return {
        "body_text_sample": body_text[:6000],
        "contact_channels": {
            "emails": mailto, "phones": tel, "whatsapp": wa,
            "n_contact_links": len(mailto) + len(tel) + len(wa),
            "n_forms": n_forms, "n_cta": n_buttons,
        },
        "social_channels": sorted(dict.fromkeys(social))[:10],
        "branding": {
            "logo": logo, "favicon": favicon,
            "og": og, "has_og_image": bool(og.get("og:image")),
            "has_twitter_card": bool(og.get("twitter:card")),
        },
        "tracking": trackers,
        "booking_external_hosts": ext_hosts,
        "content": {"lorem_ipsum": lorem, "body_text_words": len(body_text.split())},
        "media": {"total_images": total_img, "images_with_alt": img_alt,
                  "images_missing_alt": total_img - img_alt},
        "brand_color_css": brand_color,
    }


def _extract_seo(page: Page) -> dict:
    title_el = page.query_selector("title")
    meta_desc = page.query_selector('meta[name="description"]')
    canonical = page.query_selector('link[rel="canonical"]')
    headings = {
        f"h{i}": page.eval_on_selector_all(f"h{i}", "els => els.length")
        for i in range(1, 7)
    }
    jsonld = page.eval_on_selector_all(
        'script[type="application/ld+json"]',
        "els => els.map(e => { try { return JSON.parse(e.textContent) } "
        "catch { return null } }).filter(Boolean)",
    )
    title = title_el.inner_text() if title_el else None
    return {
        "title": title,
        "title_length": len(title) if title else None,
        "meta_description": meta_desc.get_attribute("content") if meta_desc else None,
        "headings": headings,
        "canonical": canonical.get_attribute("href") if canonical else None,
        "hreflang_count": page.eval_on_selector_all(
            'link[rel="alternate"][hreflang]', "els => els.length"
        ),
        "schema_jsonld": jsonld,
    }


def _axe_violations(page: Page) -> list[dict]:
    try:
        axres = Axe().run(page)
        out = []
        for i, v in enumerate(axres.response.get("violations", []), start=1):
            out.append({
                "id": f"a{i:04d}",
                "rule": v.get("id", ""),
                "impact": v.get("impact") or "minor",
                "nodes": v.get("nodes", []),
            })
        return out
    except Exception:
        return []


def _empty_report(pid: str, url: str, status: str, http_status: int) -> dict:
    return {
        "id": pid,
        "url": url,
        "status": status,
        "http_status": http_status,
        "redirect_chain": [],
        "accessibility": {"violations": [], "contrast_violations": 0},
        "seo": {"title": None, "title_length": None, "meta_description": None,
                "headings": {}, "canonical": None, "hreflang_count": 0,
                "schema_jsonld": []},
        "http_headers": {},
        "images_missing_alt": 0,
        "charset_ok": False,
        "robots_respected": True,
        "wordpress": {"is_wordpress": False},
        "qualitative": {
            "body_text_sample": "", "contact_channels": {"emails": [], "phones": [],
                "whatsapp": [], "n_contact_links": 0, "n_forms": 0, "n_cta": 0},
            "social_channels": [], "branding": {"logo": None, "favicon": None,
                "og": {}, "has_og_image": False, "has_twitter_card": False},
            "tracking": {"gtm": False, "ga4": False, "fbpixel": False,
                "hotjar": False, "matomo": False},
            "booking_external_hosts": [], "content": {"lorem_ipsum": False,
                "body_text_words": 0}, "media": {"total_images": 0,
                "images_with_alt": 0, "images_missing_alt": 0},
            "brand_color_css": None,
        },
    }


def _redirect_chain(resp) -> list[str]:
    chain: list[str] = []
    req = getattr(resp, "request", None)
    while req is not None and req.redirected_from is not None:
        chain.append(req.redirected_from.url)
        req = req.redirected_from
    chain.reverse()
    return chain


def _extract_security_headers(resp) -> dict:
    out = {}
    if resp is None:
        return out
    for name in SECURITY_HEADERS:
        val = resp.headers.get(name)
        if val is not None:
            out[name] = val
    return out


USER_AGENT = "SiteIQBot/0.1 (+SiteIQ analysis)"
ROBOTS_TIMEOUT_S = 10


def _robots_allows(url: str, guard: TargetGuard) -> bool:
    """robots.txt letto con timeout e con la protezione SSRF. Se non è
    leggibile (rete, 404, host bloccato) si assume consentito, come fanno i crawler."""
    rp = RobotFileParser()
    try:
        resp = guard.get(urljoin(url, "/robots.txt"), timeout=ROBOTS_TIMEOUT_S,
                         headers={"User-Agent": USER_AGENT})
    except Exception:
        return True
    if resp.status_code in (401, 403):
        return False
    if resp.status_code >= 400:
        return True
    rp.parse(resp.text.splitlines())
    return rp.can_fetch("SiteIQBot", url)


def _wordpress_enrich(report: dict, page_html: str, url: str, guard: TargetGuard) -> None:
    """Fingerprint WordPress + versione core dal feed + versioni plugin dal readme."""
    try:
        wp = fingerprint(page_html)
    except Exception:
        wp = {"is_wordpress": False}
    report["wordpress"] = wp
    if not wp.get("is_wordpress"):
        return

    base = urlparse(url)
    origin = f"{base.scheme}://{base.netloc}"
    headers = {"User-Agent": USER_AGENT}

    # Versione core non esposta nel DOM (meta generator rimosso): prova i feed.
    if not wp.get("core"):
        for feed_path in ("/feed/", "/?feed=rss2"):
            try:
                fr = guard.get(origin + feed_path, timeout=10, headers=headers)
            except Exception:
                continue
            if fr.status_code == 200:
                feed_core = core_version_from_feed(fr.text)
                if feed_core:
                    wp["core"] = feed_core
                    break

    # ?ver= uguale alla versione core = default di WordPress, non del plugin.
    drop_core_versioned_plugins(wp)

    # Plugin senza versione: readme.txt pubblico (Stable tag / Version).
    for pl in wp.get("plugins", []):
        if pl.get("version"):
            continue
        slug = quote(pl["slug"], safe="")
        try:
            rr = guard.get(f"{origin}/wp-content/plugins/{slug}/readme.txt",
                           timeout=8, headers=headers)
        except Exception:
            continue
        if rr.status_code == 200:
            v = version_from_readme(rr.text)
            if v:
                pl["version"] = v


def _scan_single(url: str, progress=None) -> dict:
    """Scansiona e popola il report della singola pagina."""
    if progress:
        progress(0, 1, url)

    guard = TargetGuard()
    try:
        guard.validate_url(url)
    except BlockedTarget as e:
        report = _empty_report("p001", url, "error", 0)
        report["error_detail"] = str(e)
        if progress:
            progress(1, 1, url)
        return report

    if not _robots_allows(url, guard):
        if progress:
            progress(1, 1, url)
        report = _empty_report("p001", url, "skipped", 0)
        report["error_detail"] = "pagina esclusa da robots.txt"
        return report

    # Tutto il traffico del browser passa dal proxy di uscita (SSRF).
    with EgressProxy(guard) as proxy, sync_playwright() as p:
        browser = p.chromium.launch(proxy={"server": proxy.url})
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            report = _empty_report("p001", url, "error", 0)
            try:
                # Observer vitals installati PRIMA della navigazione: su siti
                # lenti un evaluate post-hoc perde le metriche già emesse.
                page.add_init_script(_OBSERVER_SCRIPT)
                resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
                if resp is None:
                    raise RuntimeError("nessuna risposta HTTP")
                status = resp.status
                ok = status < 400
                report = _empty_report("p001", url, "ok" if ok else "error", status)
                report["redirect_chain"] = _redirect_chain(resp)
                report["http_headers"] = _extract_security_headers(resp)
                if ok:
                    page.wait_for_timeout(6000)  # finestra di osservazione performance
                    report["vitals"] = read_vitals(page)
                    report["seo"] = _extract_seo(page)
                    report["images_missing_alt"] = page.eval_on_selector_all(
                        "img:not([alt])", "els => els.length"
                    )
                    report["charset_ok"] = page.query_selector("meta[charset]") is not None
                    report["accessibility"]["violations"] = _axe_violations(page)
                    report["accessibility"]["contrast_violations"] = sum(
                        1 for v in report["accessibility"]["violations"]
                        if v["rule"] == "color-contrast"
                    )
                    report["qualitative"] = _extract_qualitative(page, url)
                    _wordpress_enrich(report, page.content(), url, guard)
            except Exception as e:
                log.warning("crawl fallito per %s: %s", url, e)
                report = _empty_report("p001", url, "error", 0)
                report["error_detail"] = f"{type(e).__name__}: {e}"[:500]
        finally:
            browser.close()

    if progress:
        progress(1, 1, url)
    return report


def crawl_site(start_url: str, max_pages: int = 1, progress=None) -> dict:
    """Scansiona SOLO `start_url` (single-URL) e ritorna un crawl_report (v1.0.0).

    `max_pages` è mantenuto per compatibilità interfaccia ma è ignorato: il
    crawler processa esclusivamente l'URL inserito.
    """
    page_report = _scan_single(start_url, progress=progress)
    return {
        "schema_version": "1.0.0",
        "url": start_url,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scan_meta": {"pages_requested": 1, "pages_returned": 1, "truncated": False},
        "pages": [page_report],
    }