"""Job manager per l'analisi SiteIQ.

Esegue crawl + analisi LLM in un pool di thread limitato e tiene lo stato del job
(progress + risultato) in memoria. Il WebSocket (/ws/{job_id}) ascolta i
progress e infine il report.

Scelte di progetto:
  - job in memoria (persi al riavvio): l'MVP non persiste i report anonimi
    (privacy); resta su disco solo la pagina HTML del report per /admin.
  - un solo processo uvicorn: con più worker lo store non è condiviso.
  - concorrenza limitata (SITEIQ_MAX_CONCURRENT_JOBS, default 2): ogni job apre
    un Chromium e può chiamare l'LLM a pagamento. Oltre SITEIQ_MAX_QUEUED_JOBS
    job in attesa, le nuove richieste vengono rifiutate (QueueFull -> 503).
  - i job conclusi vengono rimossi dopo SITEIQ_JOB_TTL_S secondi (default 1h).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from app.checks import build_checks
from app.config import REPO_ROOT, env_int, env_str
from app.crawl import crawl_site
from app.email_report import render_report_email, render_report_page
from app.i18n import DEFAULT_LOCALE, t
from app.llm import BaseLlm
from app.mailer import send_report
from app.usage import log_request, update_status
from app.wpvuln import check_wordpress

log = logging.getLogger(__name__)

REPORTS_DIR = Path(env_str("REPORTS_DIR") or REPO_ROOT / "reports")
MAX_CONCURRENT_JOBS = env_int("SITEIQ_MAX_CONCURRENT_JOBS", 2)
MAX_QUEUED_JOBS = env_int("SITEIQ_MAX_QUEUED_JOBS", 20)
JOB_TTL_S = env_int("SITEIQ_JOB_TTL_S", 3600)



class QueueFull(RuntimeError):
    """Troppi job in attesa: il chiamante deve riprovare più tardi."""


class AnalysisFailed(RuntimeError):
    """Esito negativo atteso di un'analisi deterministica, con codice macchina."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def _save_report_page(job_id: str, report: dict, locale: str = DEFAULT_LOCALE) -> str | None:
    """Salva la pagina HTML del report e ritorna il path, o None in errore."""
    try:
        path = _resolve_reports_dir() / f"{job_id}.html"
        path.write_text(render_report_page(report, locale), encoding="utf-8")
        return str(path)
    except Exception:
        log.exception("salvataggio pagina report fallito (job %s)", job_id)
        return None


def _send_report_email(email: str, report: dict, locale: str = DEFAULT_LOCALE) -> None:
    subject, body = render_report_email(report, locale)
    send_report(email, subject, body)


class Job:
    """Un'analisi. Con `llm=None` è solo deterministica (crawl, check, WordPress):
    nessun costo LLM, nessuna pagina report HTML, nessuna email."""

    def __init__(self, url: str, llm: BaseLlm | None, max_pages: int = 1, client: str = "anon",
                 notify_email: str | None = None, origin: str = "api",
                 locale: str = DEFAULT_LOCALE):
        self.id = uuid.uuid4().hex
        self.url = url
        self.max_pages = max_pages
        self.llm = llm
        self.client = client
        self.notify_email = notify_email
        self.origin = origin              # api | lead | best: chi ha avviato il job
        self.locale = locale              # lingua di check, report AI ed email
        self.status = "pending"          # pending | running | done | error
        self.progress = {"done": 0, "total": 1, "current": url}
        self.crawl = None                 # crawl_report grezzo
        self.result = None                # final_report (o solo check se deterministico)
        self.error = None                 # dettaglio interno (solo admin/log)
        self.failure_reason: str | None = None  # codice macchina dell'errore
        self.report_email_errors: list[str] = []
        self.created_at = _utc_now()
        self.completed_at: str | None = None
        self.finished_at: float | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable] = []
        # registra la richiesta all'avvio (per monitoraggio consumo)
        model = getattr(llm, "model", llm.name) if llm else None
        self.usage_id = log_request(client, url, model=model,
                                    status="skipped" if llm and llm.is_stub else "running")

    def public_error(self, locale: str) -> str | None:
        """Messaggio di errore mostrabile a utenti anonimi (niente dettagli interni)."""
        return t(locale, "errors.api.analysis_failed") if self.status == "error" else None

    def on_progress(self, cb: Callable) -> None:
        """Registra un listener cb(kind: str, payload)."""
        with self._lock:
            self._listeners.append(cb)

    def off_progress(self, cb: Callable) -> None:
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)

    def _emit(self, kind: str, payload):
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(kind, payload)
            except Exception:
                log.debug("listener di progress fallito", exc_info=True)

    def _progress_cb(self, done, total, current):
        with self._lock:
            self.progress = {"done": done, "total": total, "current": current}
            s = dict(self.progress)
        self._emit("progress", s)

    def run(self):
        self.status = "running"
        self._emit("status", {"status": "running"})
        try:
            crawl = crawl_site(self.url, max_pages=self.max_pages, progress=self._progress_cb)
            self.crawl = crawl
            self._emit("crawled", crawl)
            if self.llm is None:
                _require_ok_page(crawl)
                result = {"url": crawl.get("url", self.url)}
                evidence = []
            else:
                self._emit("progress", {"done": 1, "total": 1,
                                        "current": t(self.locale, "jobs.progress_ai")})
                result = self.llm.analyze(crawl, locale=self.locale)
                evidence = [r.get("evidence_ref") for r in result.get("recommendations", [])
                            if r.get("evidence_ref")]
            # dettaglio per-categoria (deterministico, non dal LLM)
            result["checks"] = build_checks(crawl, self.locale)
            wp_page = next((p for p in crawl.get("pages", [])
                            if (p.get("wordpress") or {}).get("is_wordpress")), None)
            if wp_page:
                try:
                    result["wordpress_security"] = check_wordpress(wp_page["wordpress"])
                except Exception as wp_err:
                    log.warning("verifica WordPress fallita: %s", wp_err)
                    result["wordpress_security"] = {"is_wordpress": True, "error": str(wp_err)}
            # la pagina HTML del report presuppone le sezioni scritte dall'LLM
            self.report_page = _save_report_page(self.id, result, self.locale) if self.llm else None
            with self._lock:
                self.result = result
                self.status = "done"
                self.completed_at = _utc_now()
                self.finished_at = time.monotonic()
            self._emit("status", {"status": "done"})
            self._emit("result", result)
            self._finalize("ok", evidence)
            self._send_emails(result)
        except Exception as e:
            log.exception("job %s fallito (%s)", self.id, self.url)
            with self._lock:
                self.error = f"{type(e).__name__}: {e}"
                self.failure_reason = getattr(e, "reason", "INTERNAL")
                self.status = "error"
                self.completed_at = _utc_now()
                self.finished_at = time.monotonic()
            self._emit("status", {"status": "error", "error": self.public_error(self.locale)})
            self._finalize("error")

    def _send_emails(self, result: dict) -> None:
        """Report via email al destinatario fisso (REPORT_NOTIFY_EMAIL) e al lead.
        Mai senza LLM o con lo stub: non c'è un report da inviare."""
        if self.llm is None or self.llm.is_stub:
            return
        recipients: set[str] = set()
        notify = env_str("REPORT_NOTIFY_EMAIL")
        if notify:
            recipients.add(notify)
        if self.notify_email:
            recipients.add(self.notify_email)
        for rcpt in sorted(recipients):
            try:
                _send_report_email(rcpt, result, self.locale)
            except Exception as mail_err:
                log.warning("invio report a %s fallito: %s", rcpt, mail_err)
                self.report_email_errors.append(f"{mail_err} (-> {rcpt})")

    def _finalize(self, status: str, evidence: list | None = None):
        """Aggiorna il record usage con esito + consumi reali."""
        usage = getattr(self.llm, "last_usage", {}) or {}
        update_status(self.usage_id, status, usage, evidence)


def _require_ok_page(crawl: dict) -> None:
    """Senza LLM non ha senso "analizzare" una pagina non scaricata: esito negativo."""
    page = (crawl.get("pages") or [{}])[0]
    if page.get("status") == "skipped":
        raise AnalysisFailed("ROBOTS_DISALLOWED", "robots.txt del sito esclude la pagina")
    if page.get("status") != "ok":
        status = page.get("http_status") or 0
        if status:
            raise AnalysisFailed("TARGET_HTTP_ERROR", f"il sito ha risposto HTTP {status}")
        raise AnalysisFailed("TARGET_UNREACHABLE",
                             page.get("error_detail") or "sito non raggiungibile")


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [jid for jid, j in self._jobs.items()
                   if j.finished_at is not None and now - j.finished_at > JOB_TTL_S]
        for jid in expired:
            del self._jobs[jid]

    def create(self, url: str, llm: BaseLlm | None, max_pages: int = 1, client: str = "anon",
               notify_email: str | None = None, origin: str = "api",
               locale: str = DEFAULT_LOCALE) -> Job:
        with self._lock:
            self._evict_expired()
            pending = sum(1 for j in self._jobs.values() if j.status in ("pending", "running"))
            if pending >= MAX_QUEUED_JOBS:
                raise QueueFull()
        j = Job(url, llm, max_pages, client, notify_email, origin, locale)
        with self._lock:
            self._jobs[j.id] = j
        return j

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


store = JobStore()
_executor = ThreadPoolExecutor(max_workers=max(1, MAX_CONCURRENT_JOBS),
                               thread_name_prefix="siteiq-job")


def start_analysis(url: str, llm: BaseLlm | None, max_pages: int = 1, client: str = "anon",
                   notify_email: str | None = None, origin: str = "api",
                   on_event: Callable | None = None, locale: str = DEFAULT_LOCALE) -> Job:
    """Crea il job e lo accoda al pool. Solleva QueueFull se la coda è piena.
    `on_event(job, kind, payload)` è registrato PRIMA dell'avvio: non perde eventi."""
    job = store.create(url, llm, max_pages, client, notify_email, origin, locale)
    if on_event is not None:
        job.on_progress(partial(on_event, job))
    _executor.submit(job.run)
    return job
