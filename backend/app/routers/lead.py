"""Endpoint pubblici per il flusso lead -> conferma email -> 1 scansione (Fase 5.5).

- POST /api/lead {email,url}   -> salva lead, invia email di conferma
- GET  /api/confirm?token=X    -> conferma l'email (double opt-in)
- POST /api/scan  {token}      -> esegue 1 scansione (1 pagina) se diritto attivo

Queste API sono PUBBLICHE (nessun admin token): la "protezione" è il diritto
limitato — 1 scansione per email confermata. Da dietro firewall/nginx in prod.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import leads
from app.jobs import start_analysis
from app.llm import make_llm
from app.mailer import build_confirm_url, send_confirmation

router = APIRouter()

URL_RE = re.compile(r"^https?://", re.I)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class LeadRequest(BaseModel):
    email: str = Field(min_length=3)
    url: str = Field(min_length=4)


class ScanRequest(BaseModel):
    token: str = Field(min_length=8)


@router.post("/api/lead")
def request_lead(req: LeadRequest) -> dict:
    url = req.url.strip()
    if not URL_RE.match(url):
        raise HTTPException(status_code=422, detail="URL non valido (serve http:// o https://)")
    if not EMAIL_RE.match(req.email.strip()):
        raise HTTPException(status_code=422, detail="email non valida")
    lead = leads.create_lead(req.email.strip(), url)
    # base url per il link di conferma (env o fallback localhost)
    base = __import__("os").environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    confirm_url = build_confirm_url(base, lead["token"])
    try:
        send_confirmation(req.email, confirm_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"impossibile inviare l'email di conferma: {e}")
    return {"status": "pending", "message": "controlla la tua email per confermare"}


@router.get("/api/confirm")
def confirm(token: str) -> dict:
    lead = leads.confirm_lead(token)
    if lead is None:
        raise HTTPException(status_code=404, detail="link di conferma non valido")
    return {"status": "confirmed", "email": lead["email"], "url": lead["url"]}


@router.post("/api/scan")
def scan(req: ScanRequest) -> dict:
    if not leads.can_scan(req.token):
        raise HTTPException(
            status_code=403,
            detail="email non confermata o scansione gratuita già utilizzata",
        )
    lead = leads.get_lead_by_token(req.token)
    if lead is None:
        raise HTTPException(status_code=403, detail="lead non trovato")
    url = lead["url"]
    # usa sempre l'LLM reale per il prodotto (1 scansione per email, costo contenuto)
    llm = make_llm(stub=False)
    job = start_analysis(url, llm, max_pages=1, client=f"lead:{lead['email']}",
                         notify_email=lead["email"])
    leads.mark_scan_used(req.token)
    return {"job_id": job.id, "status": "pending", "url": url}


@router.get("/api/scan/{job_id}")
def scan_status(job_id: str) -> dict:
    """Polling per l'utente lead (pubblico ma minimale: solo stato del proprio job)."""
    from app.jobs import store
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    return {
        "job_id": job.id,
        "status": job.status,
        "error": job.error,
        "result": job.result,
    }