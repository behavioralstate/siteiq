"""Test con jsonschema per i due schemi condivisi (Fase 1).

Esegui:  python -m venv venv && venv/bin/pip install jsonschema pytest
         venv/bin/pytest backend/tests/test_schemas.py -v
"""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent.parent / "schema"


def _load(name):
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def crawl_schema():
    return _load("crawl_report.schema.json")


@pytest.fixture(scope="module")
def final_schema():
    return _load("final_report.schema.json")


def _crawl_ok():
    return {
        "schema_version": "1.0.0",
        "url": "https://example.com/",
        "scanned_at": "2026-10-06T16:00:00Z",
        "scan_meta": {"pages_requested": 1, "pages_returned": 1, "truncated": False},
        "pages": [
            {
                "id": "p001",
                "url": "https://example.com/",
                "status": "ok",
                "http_status": 200,
                "vitals": {"LCP_ms": 2000, "INP_or_TBT_ms": 180, "CLS": 0.05},
                "accessibility": {"violations": [], "contrast_violations": 0},
                "seo": {
                    "title": "OK",
                    "title_length": 2,
                    "headings": {"h1": 1},
                    "canonical": "https://example.com/",
                },
                "images_missing_alt": 0,
                "charset_ok": True,
                "robots_respected": True,
            }
        ],
    }


def _final_ok():
    return {
        "schema_version": "1.0.0",
        "url": "https://example.com/",
        "generated_at": "2026-10-06T16:01:00Z",
        "summary": {"verdict": "ok", "highlights": ["x"], "most_urgent": "y"},
        "scores": {
            "development":    {"value": 90, "grade": "A"},
            "seo":            {"value": 80, "grade": "B"},
            "security":       {"value": 70, "grade": "C"},
            "accessibility":  {"value": 60, "grade": "D"},
            "performance":    {"value": 90, "grade": "A"},
        },
        "priorities": [
            {"level": "P0", "title": "Alt mancanti", "evidence_refs": ["p001.accessibility.violations"]}
        ],
        "recommendations": [
            {"priority": "P0", "title": "Aggiungi ALT", "detail": "...", "evidence_ref": "p001.images_missing_alt", "effort": "low"}
        ],
    }


def test_crawl_schema_is_valid(crawl_schema):
    Draft202012Validator.check_schema(crawl_schema)


def test_crawl_ok_passes(crawl_schema):
    errs = list(Draft202012Validator(crawl_schema).iter_errors(_crawl_ok()))
    assert errs == []


def test_crawl_schema_version_fixed(crawl_schema):
    bad = _crawl_ok(); bad["schema_version"] = "9.9.9"
    errs = list(Draft202012Validator(crawl_schema).iter_errors(bad))
    assert any("schema_version" in "/".join(p) for p in (e.absolute_path for e in errs))


def test_crawl_unknown_field_rejected(crawl_schema):
    bad = _crawl_ok(); bad["pages"][0]["surprise"] = 1
    errs = list(Draft202012Validator(crawl_schema).iter_errors(bad))
    assert errs


def test_final_schema_is_valid(final_schema):
    Draft202012Validator.check_schema(final_schema)


def test_final_ok_passes(final_schema):
    errs = list(Draft202012Validator(final_schema).iter_errors(_final_ok()))
    assert errs == []


def test_final_missing_evidence_ref_rejected(final_schema):
    bad = _final_ok(); bad["recommendations"][0].pop("evidence_ref")
    errs = list(Draft202012Validator(final_schema).iter_errors(bad))
    assert any("required" in e.message and "evidence_ref" in e.message for e in errs)


def test_final_bad_score_rejected(final_schema):
    bad = _final_ok(); bad["scores"]["performance"]["value"] = 999
    errs = list(Draft202012Validator(final_schema).iter_errors(bad))
    assert any("performance" in "/".join(str(p) for p in e.absolute_path) for e in errs)


def test_final_priority_requires_evidence(final_schema):
    bad = _final_ok(); bad["priorities"][0]["evidence_refs"] = []
    errs = list(Draft202012Validator(final_schema).iter_errors(bad))
    assert any("evidence_refs" in "/".join(str(p) for p in e.absolute_path) for e in errs)
