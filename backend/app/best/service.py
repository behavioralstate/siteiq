"""Ponte tra la superficie BEST e la pipeline esistente (jobs.py).

- AnalyzeSite avvia un job deterministico (llm=None, origin="best").
- I progressi del job diventano eventi BEST con il correlationid del comando.
- Le query leggono lo stato del job; solo i job nati da BEST sono visibili qui,
  mai quelli della landing o del pannello admin.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from functools import partial

from app.best import catalogue
from app.best.eventlog import log
from app.checks import build_checks
from app.config import env_int
from app.i18n import DEFAULT_LOCALE, Translator
from app.jobs import Job, start_analysis, store

ORIGIN = "best"
USAGE_CLIENT = "best"

# esiti pubblici: messaggi fissi dal catalogo (best.failure.<reason>), mai
# dettagli interni su una superficie pubblica
FAILURE_REASONS = ("TARGET_UNREACHABLE", "TARGET_HTTP_ERROR", "ROBOTS_DISALLOWED", "INTERNAL")

STATUS = {"pending": "pending", "running": "running", "done": "completed", "error": "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _publish(type_name: str, correlation_id: str, data: dict) -> None:
    entry = catalogue.by_type("events", type_name)
    log.publish({
        "specversion": "1.0",
        "id": str(uuid.uuid4()),
        "source": catalogue.endpoint(),
        "type": type_name,
        "datacontenttype": "application/json",
        "dataschema": catalogue.dataschema(entry),
        "correlationid": correlation_id,
        "time": _now(),
        "data": data,
    })


def failure(job: Job, locale: str) -> dict:
    reason = job.failure_reason if job.failure_reason in FAILURE_REASONS else "INTERNAL"
    return {"reason": reason, "message": Translator(locale)(f"best.failure.{reason}")}


def _on_job_event(correlation_id: str, locale: str, job: Job, kind: str, payload) -> None:
    """Traduce gli eventi interni del job in eventi di dominio BEST. I testi
    degli eventi sono nella lingua di chi ha inviato il comando."""
    base = {"analysisId": job.id, "url": job.url}
    if kind == "status" and payload.get("status") == "running":
        _publish("SiteAnalysisStarted", correlation_id, base)
    elif kind == "crawled":
        page = (payload.get("pages") or [{}])[0]
        _publish("SiteCrawled", correlation_id, {
            **base,
            "pageStatus": page.get("status", "error"),
            "httpStatus": page.get("http_status") or 0,
            "redirects": len(page.get("redirect_chain") or []),
            "isWordPress": bool((page.get("wordpress") or {}).get("is_wordpress")),
        })
    elif kind == "status" and payload.get("status") == "done":
        _publish("SiteAnalysisCompleted", correlation_id, {
            **base,
            "findingCounts": finding_counts(job_findings(job, locale)),
            "isWordPress": is_wordpress(job),
        })
    elif kind == "status" and payload.get("status") == "error":
        _publish("SiteAnalysisFailed", correlation_id, {**base, **failure(job, locale)})


def submit_analysis(url: str, correlation_id: str, locale: str = DEFAULT_LOCALE) -> Job:
    """Avvia l'analisi deterministica. Solleva QueueFull se la coda è piena."""
    return start_analysis(url, None, max_pages=1, client=USAGE_CLIENT, origin=ORIGIN,
                          on_event=partial(_on_job_event, correlation_id, locale), locale=locale)


def best_job(analysis_id: str) -> Job | None:
    job = store.get(analysis_id)
    return job if job is not None and job.origin == ORIGIN else None


# ------------------------------------------------------------- findings --

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _refs(vulns: list[dict]) -> list[str]:
    refs: list[str] = []
    for v in vulns:
        for ref in (v.get("cve") or v.get("title") or "").split(","):
            ref = ref.strip()
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def _wordpress_findings(wp: dict, tr: Translator) -> list[dict]:
    out = []
    if wp.get("error"):
        out.append({"id": "wordpress.check", "category": "wordpress", "status": "warn",
                    "label": tr("wordpress.check_label"), "detail": tr("wordpress.unavailable")})
    core = wp.get("core")
    if core:
        vulns = core.get("vulnerabilities") or []
        version = core.get("version")
        if vulns:
            status, detail = "error", tr("wordpress.known_vulns", version=version, count=len(vulns))
        elif core.get("status") == "unavailable":
            status, detail = "warn", tr("wordpress.version_unavailable", version=version)
        else:
            status, detail = "ok", tr("wordpress.no_known_vulns", version=version)
        out.append({"id": "wordpress.core", "category": "wordpress", "status": status,
                    "label": tr("wordpress.core_label"), "detail": detail, "references": _refs(vulns)})
    for pl in wp.get("plugins") or []:
        vulns = pl.get("vulnerabilities") or []
        version = pl.get("version")
        if pl.get("status") == "unknown":
            status, detail = "warn", tr("wordpress.version_unknown")
        elif pl.get("status") == "unavailable":
            status, detail = "warn", tr("wordpress.version_unavailable", version=version)
        elif vulns:
            status, detail = "error", tr("wordpress.known_vulns", version=version, count=len(vulns))
        else:
            status, detail = "ok", tr("wordpress.no_known_vulns", version=version)
        out.append({"id": f"wordpress.plugin.{_slug(pl['slug'])}", "category": "wordpress",
                    "status": status, "label": tr("wordpress.plugin_label", slug=pl["slug"]),
                    "detail": detail, "references": _refs(vulns)})
    return out


def project_findings(result: dict | None, locale: str = DEFAULT_LOCALE) -> list[dict]:
    """Check (già resi) + verifiche WordPress come lista piatta con id stabili."""
    if not result:
        return []
    findings = [
        {"id": f"{category}.{_slug(ck['id'])}", "category": category,
         "status": ck["status"], "label": ck["label"], "detail": ck.get("detail") or ""}
        for category, checks in (result.get("checks") or {}).items()
        for ck in checks
    ]
    wp = result.get("wordpress_security")
    if wp and wp.get("is_wordpress"):
        findings += _wordpress_findings(wp, Translator(locale))
    return findings


def job_findings(job: Job, locale: str) -> list[dict]:
    """Findings di un job concluso nella lingua richiesta: i check sono
    ricalcolati dal crawl (funzione pura), non tradotti a posteriori."""
    if job.status != "done" or not job.crawl:
        return []
    return project_findings({"checks": build_checks(job.crawl, locale),
                             "wordpress_security": (job.result or {}).get("wordpress_security")},
                            locale)


def finding_counts(findings: list[dict]) -> dict:
    c = Counter(f["status"] for f in findings)
    return {"ok": c["ok"], "warn": c["warn"], "error": c["error"]}


def is_wordpress(job: Job) -> bool:
    page = ((job.crawl or {}).get("pages") or [{}])[0]
    return bool((page.get("wordpress") or {}).get("is_wordpress"))


# --------------------------------------------------------------- queries --

def analysis_view(job: Job, locale: str) -> dict:
    status = STATUS[job.status]
    return {
        "analysisId": job.id,
        "url": job.url,
        "status": status,
        "requestedAt": job.created_at,
        "completedAt": job.completed_at,
        "findingCounts": finding_counts(job_findings(job, locale)) if status == "completed" else None,
        "failure": failure(job, locale) if status == "failed" else None,
    }


def findings_view(job: Job, locale: str, category: str | None, status: str | None) -> dict:
    findings = [f for f in job_findings(job, locale)
                if (category is None or f["category"] == category)
                and (status is None or f["status"] == status)]
    return {"analysisId": job.id, "status": STATUS[job.status], "findings": findings}


def crawl_view(job: Job) -> dict:
    return {"analysisId": job.id, "status": STATUS[job.status], "crawlReport": job.crawl}


# ---------------------------------------------------------- idempotency --

class IdempotencyStore:
    """id del comando -> (impronta del contenuto, correlationId), in memoria.

    Stesso id e stesso contenuto: si risponde come la prima volta senza
    rieseguire. Stesso id e contenuto diverso: conflitto (409)."""

    def __init__(self, ttl_s: int | None = None):
        self.ttl_s = ttl_s or env_int("SITEIQ_JOB_TTL_S", 3600)
        self._seen: dict[str, tuple[float, str, str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def fingerprint(envelope: dict) -> str:
        material = {k: envelope.get(k) for k in ("type", "data", "correlationid")}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def reserve(self, command_id: str, fingerprint: str,
                correlation_id: str) -> tuple[str, str] | None:
        """Atomico: registra l'id e ritorna None se è nuovo, altrimenti
        (impronta, correlationId) della prima richiesta con quell'id."""
        with self._lock:
            now = time.monotonic()
            for k in [k for k, v in self._seen.items() if now - v[0] > self.ttl_s]:
                del self._seen[k]
            hit = self._seen.get(command_id)
            if hit:
                return hit[1], hit[2]
            self._seen[command_id] = (now, fingerprint, correlation_id)
            return None

    def release(self, command_id: str) -> None:
        """Il comando non è partito (es. coda piena): l'id torna libero."""
        with self._lock:
            self._seen.pop(command_id, None)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


idempotency = IdempotencyStore()
