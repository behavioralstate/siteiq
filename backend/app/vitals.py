"""Core Web Vitals via Playwright CDP (nessuna dipendenza npm/Node).

Poiché la macchina non ha Node, non usiamo Lighthouse CLI. Raccogliamo LCP,
CLS, FCP via PerformanceObserver iniettato con add_init_script (prima del
caricamento), e TTFB via CDP Network.responseReceived. INP/TBT reale richiede
interazioni; per MVP usiamo i Long Tasks come proxy TBT (come da schema:
INP_or_TBT_ms).

Nota MVP onesta: LCP/CLS migliori vengono da run reali di Lighthouse/PSI.
Questo modulo dà segnali orientativi sufficienti per il report.
"""
from __future__ import annotations

from playwright.sync_api import Page

_OBSERVER_SCRIPT = r"""
window.__siteiqVitals = { LCP: null, CLS: 0, FCP: null, TBT: 0 };
(function () {
  const V = window.__siteiqVitals;
  try {
    // LCP: entryType 'largest-contentful-paint' (prendi il massimo startTime)
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.entryType === 'largest-contentful-paint' && e.startTime) V.LCP = e.startTime;
      }
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    // FCP: entryType 'paint' con name 'first-contentful-paint'
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.entryType === 'paint' && e.name === 'first-contentful-paint' && e.startTime && V.FCP === null) V.FCP = e.startTime;
      }
    }).observe({ type: 'paint', buffered: true });
    const cls = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (!e.hadRecentInput) V.CLS += e.value;
      }
    });
    cls.observe({ type: 'layout-shift', buffered: true });
    const long = new PerformanceObserver((list) => {
      for (const e of list.getEntries()) V.TBT += Math.max(0, e.duration - 50);
    });
    long.observe({ type: 'longtask', buffered: true });
  } catch (e) { /* observer non disponibili: lascia i default */ }
})();
"""


def _observe(page: Page, nav_start: float) -> dict:
    page.wait_for_timeout(6000)  # finestra di osservazione performance
    return page.evaluate(
        """(navStart) => {
            const V = window.__siteiqVitals;
            return {
              LCP_ms: V.LCP ? Math.round(V.LCP) : 0,
              CLS: Math.round(V.CLS * 100) / 100,
              FCP_ms: V.FCP ? Math.round(V.FCP) : 0,
              TBT_ms: Math.round(V.TBT),
            };
        }""",
        nav_start,
    )


def collect_vitals(page: Page) -> dict:
    """Raccoglie vitals sulla pagina GIÀ caricata in `page`.

    NB: usa page.evaluate (non add_init_script) perché la pagina è già stata
    navigata dal crawler; add_init_script gira solo su nuove navigazioni.
    """
    try:
        page.evaluate(_OBSERVER_SCRIPT)
    except Exception:
        pass  # observer non disponibili: restituisce zeri
    d = _observe(page, 0.0)
    d["INP_or_TBT_ms"] = d.pop("TBT_ms")  # schema v1.0.0
    d["TTFB_ms"] = 0
    return d


def read_vitals(page: Page, ttfb_ms: int = 0) -> dict:
    """Legge i vitals raccolti da observer installati PRIMA della navigazione
    (add_init_script). Non re-installa: presume __siteiqVitals già popolato.
    Aggiunge TTFB passato (misurato via CDP)."""
    try:
        d = page.evaluate(
            """() => {
                const V = window.__siteiqVitals || {};
                return {
                  LCP_ms: V.LCP ? Math.round(V.LCP) : 0,
                  CLS: Math.round((V.CLS||0) * 100) / 100,
                  FCP_ms: V.FCP ? Math.round(V.FCP) : 0,
                  TBT_ms: Math.round(V.TBT||0),
                };
            }"""
        )
    except Exception:
        d = {"LCP_ms": 0, "CLS": 0, "FCP_ms": 0, "TBT_ms": 0}
    d["INP_or_TBT_ms"] = d.pop("TBT_ms")
    d["TTFB_ms"] = int(ttfb_ms or 0)
    return d


def collect_vitals_on_goto(page: Page, url: str, timeout: int = 20000) -> dict:
    """Esegue goto con observer attivi e restituisce vitals. TTFB via CDP."""
    page.add_init_script(_OBSERVER_SCRIPT)

    ttfb = 0.0
    cdp = page.context.new_cdp_session(page)
    cdp.send("Performance.enable")

    def _ttfb(event):
        nonlocal ttfb
        if event.get("type") == "Document" and event.get("response", {}):
            ttfb = event.get("response", {}).get("timing", {}).get("requestTime", 0)

    cdp.on("Network.responseReceived", _ttfb)

    page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    data = page.evaluate(
        """() => {
            const V = window.__siteiqVitals;
            return {
              LCP_ms: V.LCP ? Math.round(V.LCP) : 0,
              CLS: Math.round(V.CLS * 100) / 100,
              FCP_ms: V.FCP ? Math.round(V.FCP) : 0,
              INP_or_TBT_ms: Math.round(V.TBT),
            };
        }"""
    )
    data["TTFB_ms"] = int(ttfb)
    return data