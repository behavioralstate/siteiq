"""Query alla WPVulnerability API (pubblica, senza API key) e confronto versioni.

API (documentata su wpvulnerability.com — funziona su .net):
  GET https://www.wpvulnerability.net/core/<versione>  -> data.vulnerability[]
  GET https://www.wpvulnerability.net/plugin/<slug>     -> data.vulnerability[] con operator.+source[]

Ogni vulnerability ha:
  - operator: {min_version, min_operator, max_version, max_operator}
  - source: [{id, name, link, description}]

Confrontiamo la versione installata con operator usando un parser semver.
Fallback: se l'API non risponde, stato 'unavailable' — non blocchiamo il report.
"""
from __future__ import annotations

import httpx
from packaging.version import Version

API_BASE = "https://www.wpvulnerability.net"
TIMEOUT = 15

_OP_FN = {
    "lt": lambda v, x: v < x,
    "lte": lambda v, x: v <= x,
    "le": lambda v, x: v <= x,   # alias usato dall'API (max_operator "le")
    "gt": lambda v, x: v > x,
    "gte": lambda v, x: v >= x,
    "ge": lambda v, x: v >= x,   # alias
    "eq": lambda v, x: v == x,
    "=": lambda v, x: v == x,
}


def _to_version(s: str | None) -> Version | None:
    if not s:
        return None
    try:
        return Version(s.strip())
    except Exception:
        return None


def _matches(ver: Version, boundary: Version, op_name: str | None) -> bool:
    op = _OP_FN.get(op_name or "eq", _OP_FN["eq"])
    return op(ver, boundary)


def _vuln_applies(ver: Version, op: dict) -> bool:
    """True se la versione installata rispetta i vincoli min/max dell'operator."""
    min_v = _to_version(op.get("min_version"))
    max_v = _to_version(op.get("max_version"))
    if min_v is not None and not _matches(ver, min_v, op.get("min_operator", "gte")):
        return False
    if max_v is not None and not _matches(ver, max_v, op.get("max_operator", "lt")):
        return False
    return True


def _fmt_vulns(raw: list[dict]) -> list[dict]:
    out = []
    for v in raw:
        sources = [
            {"id": (s.get("id") or s.get("name")), "link": s.get("link")}
            for s in (v.get("source") or [])
        ]
        out.append({
            "id": v.get("uuid", ""),
            "title": v.get("name", ""),
            "cve": ", ".join(s["id"] for s in sources if s["id"]),
            "impact": v.get("impact"),
            "sources": sources,
        })
    return out


def fetch_core_vulns(core_version: str) -> dict:
    """Vuln note per una specifica versione di WordPress core."""
    url = f"{API_BASE}/core/{core_version}"
    try:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            return {"status": "ok", "vulnerabilities": []}
        vulns = (j.get("data") or {}).get("vulnerability", []) or []
        return {"status": "ok", "vulnerabilities": _fmt_vulns(vulns)}
    except Exception as e:
        return {"status": "unavailable", "error": str(e), "vulnerabilities": []}


def fetch_plugin_vulns(slug: str, version: str | None) -> dict:
    """Vuln del plugin, filtrate per versione installata.

    Regola anti-falso-positivo: se `version` è None (versione non rilevata dal
    crawler), NON possiamo affermare che il plugin sia vulnerabile. Restituiamo
    version_unknown=True e vulnerabilities vuote (lo stato lo decide il chiamante:
    "non verificabile", non "vulnerabile").
    """
    url = f"{API_BASE}/plugin/{slug}"
    try:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            return {"status": "ok", "vulnerabilities": [], "version_unknown": version is None}
        data = j.get("data") or {}
        all_vulns = data.get("vulnerability", []) or []
        ver = _to_version(version)
        if ver is None:
            # versione sconosciuta: non è un giudizio di vulnerabilità.
            return {
                "status": "ok",
                "vulnerabilities": [],
                "total_found": len(all_vulns),
                "version_checked": None,
                "version_unknown": True,
            }
        applicable = [v for v in all_vulns if _vuln_applies(ver, v.get("operator") or {})]
        return {
            "status": "ok",
            "vulnerabilities": _fmt_vulns(applicable),
            "total_found": len(all_vulns),
            "version_checked": version,
            "version_unknown": False,
        }
    except Exception as e:
        return {"status": "unavailable", "error": str(e), "vulnerabilities": []}


def check_wordpress(fp: dict) -> dict:
    """Check completo per un fingerprint WP (core + plugin). Riepilogo riportabile."""
    result = {"is_wordpress": fp.get("is_wordpress", False)}
    if not result["is_wordpress"]:
        return result

    if fp.get("core"):
        core_res = fetch_core_vulns(fp["core"])
        result["core"] = {"version": fp["core"], **core_res}

    plugins = []
    for p in fp.get("plugins", []):
        slug = p["slug"]
        res = fetch_plugin_vulns(slug, p.get("version"))
        v_unknown = res.get("version_unknown", False)
        if v_unknown:
            # versione non rilevata: non è un verdetto di vulnerabilità
            plugins.append({
                "slug": slug,
                "version": None,
                "status": "unknown",
                "vulnerable": False,
                "vulnerabilities": [],
                "total_known": res.get("total_found", 0),
                "error": None,
            })
            continue
        plugins.append({
            "slug": slug,
            "version": p.get("version"),
            "status": res["status"],
            "vulnerable": len(res.get("vulnerabilities", [])) > 0,
            "vulnerabilities": res.get("vulnerabilities", []),
            "total_known": res.get("total_found", 0),
            "error": res.get("error"),
        })
    result["plugins"] = plugins

    vulnerable_plugins = [p for p in plugins if p["vulnerable"]]
    result["summary"] = {
        "plugins_total": len(plugins),
        "plugins_vulnerable": len(vulnerable_plugins),
        "plugins_unknown": sum(1 for p in plugins if p["status"] == "unknown"),
        "core_vulnerable": bool(fp.get("core") and result.get("core", {}).get("vulnerabilities")),
        "unavailable": sum(1 for p in plugins if p["status"] == "unavailable"),
    }
    return result