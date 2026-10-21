"""Test del modulo llm (Task 13) — stub deterministico conforme allo schema."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent.parent
from app.llm import StubLlm, make_llm  # noqa: E402

FINAL_SCHEMA = json.load(open(ROOT / "schema" / "final_report.schema.json"))


def _crawl_ok():
    return {
        "schema_version": "1.0.0",
        "url": "https://example.com/",
        "scanned_at": "2026-10-06T16:00:00Z",
        "scan_meta": {"pages_requested": 5, "pages_returned": 2, "truncated": False},
        "pages": [
            {
                "id": "p001", "url": "https://example.com/", "status": "ok",
                "http_status": 200, "redirect_chain": [],
                "accessibility": {"violations": [], "contrast_violations": 0},
                "seo": {"title": "x"}, "http_headers": {},
                "images_missing_alt": 3, "charset_ok": True,
            },
            {
                "id": "p002", "url": "https://example.com/about", "status": "ok",
                "http_status": 200, "redirect_chain": [],
                "accessibility": {"violations": [
                    {"id": "a0001", "rule": "color-contrast", "impact": "serious", "nodes": []}
                ], "contrast_violations": 1},
                "seo": {"title": "y"}, "http_headers": {},
                "images_missing_alt": 0, "charset_ok": True,
            },
        ],
    }


def test_stub_conforms_to_final_schema():
    report = StubLlm().analyze(_crawl_ok())
    errs = list(Draft202012Validator(FINAL_SCHEMA).iter_errors(report))
    assert errs == [], errs[:5]


def test_make_llm_stub_default():
    llm = make_llm(stub=True)
    assert isinstance(llm, StubLlm)
    assert llm.name == "stub"


def test_stub_flag_counts_violations():
    llm = StubLlm()
    rep = llm.analyze(_crawl_ok())
    assert rep["url"] == "https://example.com/"
    assert rep["scores"]["accessibility"]["value"] < 100  # c'È una violazione
    # alt mancanti -> recommendation P1
    assert any(r["title"].startswith("Aggiungi") for r in rep["recommendations"])


def test_normalize_glossary_dict_from_llm():
    """Regressione: l'LLM ha emesso glossary come dict {term: definition} invece
    di array -> report non conforme. _normalize deve convertirlo in array."""
    from app.llm import OpenRouterLlm
    llm = OpenRouterLlm()
    rep = {
        "schema_version": "1.0.0", "url": "https://x.it",
        "generated_at": "2026-10-07T00:00:00Z",
        "summary": {"verdict": "ok", "highlights": [], "most_urgent": ""},
        "scores": {"development": {"value": 80, "grade": "B"},
                   "seo": {"value": 80, "grade": "B"}, "security": {"value": 80, "grade": "B"},
                   "accessibility": {"value": 80, "grade": "B"},
                   "performance": {"value": 80, "grade": "B"}},
        "priorities": [], "recommendations": [],
        # errore esatto segnalato: glossary come dict
        "glossary": {"LCP": "Largest Contentful Paint - tempo di caricamento",
                     "CLS": "Cumulative Layout Shift - movimenti", "H1": "Titolo principale"},
    }
    llm._normalize(rep)
    g = rep["glossary"]
    assert isinstance(g, list)
    assert isinstance(g[0], dict) and "term" in g[0] and "definition" in g[0]
    # ora deve validare senza errori
    llm._validate(rep)  # non deve lanciare RuntimeError


def test_extract_json_handles_preambolo_and_truncation():
    """_extract_json deve gestire JSON con testo attorno e JSON troncato."""
    from app.llm import OpenRouterLlm
    llm = OpenRouterLlm()
    # preambolo di testo
    raw = 'Ecco il report:\n{"a": 1, "b": 2}\n\nFine.'
    assert llm._extract_json(raw) == {"a": 1, "b": 2}
    # JSON valido + testo dopo (trailing garbage) -> estrae solo l'oggetto
    raw2 = '{"a": 1, "b": [1,2]} ... e il testo dopo'
    assert llm._extract_json(raw2) == {"a": 1, "b": [1, 2]}
    # JSON irrecuperabile (oggetto MAI chiuso) -> deve lanciare (retry gestirà)
    import pytest as _p
    with _p.raises(Exception):
        llm._extract_json('{"a": 1, "b": 2')  # noqa: RUF100