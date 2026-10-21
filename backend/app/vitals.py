"""Core Web Vitals via Playwright CDP (nessuna dipendenza npm/Node).

Poiché la macchina non ha Node, non usiamo Lighthouse CLI. Raccogliamo LCP,
CLS, FCP via PerformanceObserver iniettato con add_init_script (prima del
caricamento), e TTFB dalla Navigation Timing API. INP/TBT reale richiede
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


def read_vitals(page: Page) -> dict:
    """Legge i vitals raccolti dagli observer installati PRIMA della navigazione
    (add_init_script). TTFB dalla Navigation Timing API (responseStart rispetto
    all'inizio della navigazione, redirect inclusi, come web-vitals)."""
    try:
        d = page.evaluate(
            """() => {
                const V = window.__siteiqVitals || {};
                const nav = performance.getEntriesByType('navigation')[0];
                const ttfb = nav ? nav.responseStart - (nav.activationStart || 0) : 0;
                return {
                  LCP_ms: V.LCP ? Math.round(V.LCP) : 0,
                  CLS: Math.round((V.CLS||0) * 100) / 100,
                  FCP_ms: V.FCP ? Math.round(V.FCP) : 0,
                  TBT_ms: Math.round(V.TBT||0),
                  TTFB_ms: Math.max(0, Math.round(ttfb)),
                };
            }"""
        )
    except Exception:
        d = {"LCP_ms": 0, "CLS": 0, "FCP_ms": 0, "TBT_ms": 0, "TTFB_ms": 0}
    d["INP_or_TBT_ms"] = d.pop("TBT_ms")
    return d
