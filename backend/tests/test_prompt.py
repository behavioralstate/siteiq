"""Test del prompt di orchestrazione (Task 14) e del loader .env.

Non chiama il LLM reale (network). Verifica:
  - il prompt di sistema menziona le 3 skill e la regola evidence_ref;
  - build_user_prompt produce testo che contiene l'URL e le statistiche;
  - _minify riduce la size dei nodi DOM di axe (per non gonfiare il context).
"""
from pathlib import Path

from app.prompt import SYSTEM_PROMPT, build_user_prompt, get_system_prompt


def _crawl():
    return {
        "url": "https://example.com/",
        "pages": [
            {
                "status": "ok",
                "accessibility": {"violations": [
                    {"rule": "color-contrast", "impact": "serious",
                     "nodes": [{"html": "<span>c</span>"} for _ in range(10)]}
                ], "contrast_violations": 1},
                "vitals": {"LCP_ms": 3200, "CLS": 0.02},
            },
            {"status": "error"},
            {"status": "skipped"},
        ],
    }


def test_system_prompt_mentions_three_skills():
    p = get_system_prompt()
    for s in ("pagespeed-insights", "impeccable", "accessibility"):
        assert s.replace("pagespeed-insights", "pagespeed-insights") in p


def test_system_prompt_forbids_unreferenced_advice():
    p = get_system_prompt()
    assert "ANTI-ALLUCINAZIONE" in p
    assert "evidence_ref" in p
    assert "non ha dati a supporto" in p or "NON scriverlo" in p


def test_user_prompt_has_stats_and_url():
    crawl = _crawl()
    prompt = build_user_prompt(crawl)
    assert "example.com" in prompt
    assert "Pagine totali: 3" in prompt
    assert "ok=1" in prompt
    assert "error=1" in prompt
    assert "skipped=1" in prompt
    assert "<span>c</span>" in prompt  # HTML del nodo visibile (a risiko del context)


def test_minify_limits_dom_nodes():
    crawl = _crawl()
    ok_page = next(p for p in crawl["pages"] if p.get("status") == "ok")
    big = sum(len(v["nodes"]) for v in ok_page["accessibility"]["violations"])
    assert big == 10  # prima di minify
    import json
    from app.prompt import _minify
    text = _minify(crawl)
    # dopo minify: max 3 nodi per violazione
    d = json.loads(text)
    n = d["pages"][0]["accessibility"]["violations"][0]["nodes"]
    assert len(n) <= 3


def test_env_loader_ignores_comments_and_quotes(tmp_path):
    import os
    from app.config import load_env
    (tmp_path / ".env").write_text("# commento\nKEY=value\nQUOTED=\"ciao mondo\"\n")
    load_env(str(tmp_path / ".env"))
    assert os.environ["KEY"] == "value"
    assert os.environ["QUOTED"] == "ciao mondo"