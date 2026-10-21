"""Job manager per l'analisi SiteIQ.

Esegue crawl + analisi LLM in un thread di background e tiene lo stato del job
(progress + risultato) in memoria. Il WebSocket (/ws/{job_id}) ascolta i
progress, doctor r infine il report.

Little design: job sono in-memory (volatili alla loss del processo). L'MVP
non persiste i report anonimi (privacy). Eventuale persistenza arriverà solo
per utenti identificati (fuori MVP).
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable

from app.crawl import crawl_site
from app.llm import BaseLlm, StubLlm
from app.checks import build_checks
from app.wpvuln import check_wordpress
from app.usage import log_request
import os
from pathlib import Path

# carica .env se presente (per REPORT_NOTIFY_EMAIL ecc. quando avviato da uvicorn)
from app.llm import _load_env as _load_dotenv
_load_dotenv()

REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", Path(__file__).resolve().parent.parent.parent / "reports"))


def _resolve_reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def _save_report_page(job_id: str, report: dict) -> str | None:
    """Salva la pagina HTML del report e ritorna il path, o None in errore."""
    try:
        from app.email_report import render_report_page
        path = _resolve_reports_dir() / f"{job_id}.html"
        path.write_text(render_report_page(report), encoding="utf-8")
        return str(path)
    except Exception:
        return None


def _send_report_email(email: str, report: dict) -> None:
    """Invia il report HTML al lead. Mailing in try/except nel chiamante."""
    from app.email_report import render_report_email
    from app.mailer import send_report
    subject, body = render_report_email(report)
    send_report(email, subject, body)


class Job:
    def __init__(self, url: str, llm: BaseLlm, max_pages: int = 15, client: str = "anon",
                 notify_email: str | None = None):
        self.id = uuid.uuid4().hex
        self.url = url
        self.max_pages = max_pages
        self.llm = llm
        self.client = client
        self.notify_email = notify_email
        self.status = "pending"          # pending | running | done | error
        self.progress = {"done": 0, "total": 1, "current": url}
        self.result = None                # final_report
        self.error = None
        self._lock = threading.Lock()
        self._listeners: list[Callable] = []
        # registra la richiesta all'avvio (per monitoraggio consumo)
        self.usage_id = log_request(client, url, model=getattr(llm, "model", llm.name),
                                    status="skipped" if isinstance(llm, StubLlm) else "running")

    def on_progress(self, cb):
        """Registra un listener di progress/status. cb(ketys_event: str, payload)."""
        self._listeners.append(cb)

    def _emit(self, kind: str, payload):
        for cb in list(self._listeners):
            try:
                cb(kind, payload)
            except Exception:
                pass

    def _progress_cb(self, done, total, current):
        with self._lock:
            self.progress = {"done": done, "total": total, "current": current}
            s = dict(self.progress)
        self._emit("progress", s)

    def run(self):
        self.status = "running"
        self._emit("status", {"status": "running"})
        usage = {}
        try:
            crawl = crawl_site(self.url, max_pages=self.max_pages, progress=self._progress_cb)
            self._emit("progress", {"done": 1, "total": 1,
                                    "current": "Report AI in generazione…"})
            result = self.llm.analyze(crawl)
            # consumi token/credito dal client LLM (ultima chiamata)
            usage = getattr(self.llm, "last_usage", {}) or {}
            evidence = [r.get("evidence_ref") for r in result.get("recommendations", [])
                        if r.get("evidence_ref")]
            # arricchisci il report con il dettaglio per-categoria (deterministico)
            result["checks"] = build_checks(crawl)
            # se è WordPress, consulta la WPVulnerability API (core + plugin)
            if crawl.get("pages") and any(p.get("wordpress", {}).get("is_wordpress") for p in crawl["pages"]):
                try:
                    fp = next((p.get("wordpress") for p in crawl["pages"]
                               if p.get("wordpress", {}).get("is_wordpress")), {})
                    result["wordpress_security"] = check_wordpress(fp or {})
                except Exception as wp_err:
                    result["wordpress_security"] = {"is_wordpress": True, "error": str(wp_err)}
            # salva una pagina HTML autonoma del report (per /admin)
            self.report_page = _save_report_page(self.id, result)
            with self._lock:
                self.result = result
                self.status = "done"
            self._emit("status", {"status": "done"})
            self._emit("result", result)
            self._finalize("ok", usage, evidence)
            # Invia il report via email:
            #   - SEMPRE al destinatario di notifica (REPORT_NOTIFY_EMAIL, es. lorenzo@…)
            #   - inoltre al lead che ha richiesto l'analisi (se presente)
            if result.get("checks"):
                recipients: set[str] = set()
                _notify = os.environ.get("REPORT_NOTIFY_EMAIL", "").strip()
                if _notify:
                    recipients.add(_notify)
                if self.notify_email:
                    recipients.add(self.notify_email)
                for rcpt in recipients:
                    try:
                        _send_report_email(rcpt, result)
                    except Exception as _mail_err:
                        self.report_email_error = f"{_mail_err} (-> {rcpt})"
        except Exception as e:
            with self._lock:
                self.error = str(e)
                self.status = "error"
            self._emit("status", {"status": "error", "error": str(e)})
            self._finalize("error", usage)

    def _finalize(self, status: str, usage: dict, evidence: list | None = None):
        """Aggiorna il record usage con esito + consumi reali."""
        from app.usage import _update_status
        _update_status(self.usage_id, status, usage, evidence)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, url: str, llm: BaseLlm, max_pages: int = 15, client: str = "anon",
               notify_email: str | None = None) -> Job:
        j = Job(url, llm, max_pages, client, notify_email)
        with self._lock:
            self._jobs[j.id] = j
        return j

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


store = JobStore()


def start_analysis(url: str, llm: BaseLlm, max_pages: int = 15, client: str = "anon",
                   notify_email: str | None = None) -> Job:
    job = store.create(url, llm, max_pages, client, notify_email)
    t = threading.Thread(target=job.run, daemon=True, name=f"siteiq-job-{job.id[:8]}")
    t.start()
    return job