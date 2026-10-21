"""Test del modulo checks (Fase 6 — dettaglio per-categoria)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.checks import build_checks  # noqa: E402


def _crawl():
    return {
        "scan_meta": {"pages_requested": 1, "pages_returned": 1},
        "pages": [{
            "status": "ok", "http_status": 200, "redirect_chain": [],
            "charset_ok": True, "robots_respected": True,
            "seo": {"title": "Titolo", "title_length": 6, "meta_description": "x"*140,
                    "headings": {"h1": 1}, "canonical": None, "hreflang_count": 0,
                    "schema_jsonld": []},
            "http_headers": {"strict-transport-security": "presente"},
            "images_missing_alt": 2,
            "accessibility": {"violations": [{"rule": "color-contrast", "id": "a0001"}],
                              "contrast_violations": 1},
            "vitals": {"LCP_ms": 3200, "CLS": 0.05, "FCP_ms": 900, "TTFB_ms": 400,
                       "INP_or_TBT_ms": 150},
        }],
    }


def test_checks_has_all_five_categories():
    checks = build_checks(_crawl())
    assert set(checks.keys()) == {"development", "seo", "security", "accessibility", "performance"}


def test_security_headers_lists_present_and_missing():
    checks = build_checks(_crawl())
    sec = checks["security"]
    ids = {c["id"] for c in sec}
    assert "strict_transport_security" in ids
    assert all(c["status"] == ("ok" if c["id"] == "strict_transport_security" else "warn")
               for c in sec)


def test_performance_categorizes_by_threshold():
    checks = build_checks(_crawl())
    perf = {c["id"]: c["status"] for c in checks["performance"]}
    assert perf["lcp.ms"] == "warn"          # 3200ms: warn (2500-4000)
    assert perf["fcp.ms"] == "ok"            # 900ms: good
    assert perf["ttfb.ms"] == "ok"           # 400ms: good


def test_accessibility_flags_contrast_and_axe():
    checks = build_checks(_crawl())
    acc = checks["accessibility"]
    contrast = next(c for c in acc if c["id"] == "contrast")
    assert contrast["status"] == "error"
    assert any(c["id"] == "axe_color-contrast" for c in acc)


def test_error_pages_add_diagnostic_check():
    crawl = _crawl()
    crawl["pages"][0]["status"] = "error"
    crawl["pages"][0]["http_status"] = 0
    crawl["pages"].append({"status": "skipped", "url": "x"})
    checks = build_checks(crawl)
    dev = checks["development"]
    assert any(c["id"] == "scan" and c["status"] == "error" for c in dev)