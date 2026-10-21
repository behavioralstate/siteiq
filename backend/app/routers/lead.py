"""Endpoint pubblici per il flusso lead -> conferma email -> 1 scansione (Fase 5.5).

- POST /api/lead {email,url}   -> salva lead, invia email di conferma
- GET  /api/confirm?token=X    -> conferma l'email (double opt-in)
- POST /api/scan  {token}      -> esegue 1 scansione (1 pagina) se diritto attivo
- GET  /api/scan/{job_id}      -> stato del job (senza dettagli interni)

Queste API sono PUBBLICHE (nessun admin token). Protezioni: 1 scansione per
casella confermata (consumata in modo atomico), rate limit per IP e per email,
URL limitati a host pubblici (netguard), coda di job limitata.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import leads
from app.config import env_int, env_str
from app.i18n import request_locale, t
from app.jobs import QueueFull, start_analysis, store
from app.llm import make_llm
from app.mailer import build_confirm_url, send_confirmation
from app.netguard import BlockedTarget, validate_target_url
from app.ratelimit import SlidingWindowLimiter

log = logging.getLogger(__name__)
router = APIRouter()

# niente spazi, virgolette o parentesi angolari: l'email finisce in HTML e header
EMAIL_RE = re.compile(r"^[^\s@<>\"'(),;:\\]+@[^\s@<>\"'(),;:\\]+\.[^\s@<>\"'(),;:\\]+$")
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")

lead_ip_limiter = SlidingWindowLimiter(env_int("SITEIQ_LEADS_PER_IP_PER_HOUR", 5), 3600)
lead_email_limiter = SlidingWindowLimiter(env_int("SITEIQ_LEADS_PER_EMAIL_PER_DAY", 3), 86400)
scan_ip_limiter = SlidingWindowLimiter(env_int("SITEIQ_SCANS_PER_IP_PER_HOUR", 5), 3600)


class LeadRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    url: str = Field(min_length=4, max_length=2048)


class ScanRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(loc: str) -> HTTPException:
    return HTTPException(status_code=429, detail=t(loc, "errors.api.too_many_requests"))


@router.post("/api/lead")
def request_lead(req: LeadRequest, request: Request) -> dict:
    loc = request_locale(request)
    email = req.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail=t(loc, "errors.api.email_invalid"))
    try:
        url = validate_target_url(req.url)
    except BlockedTarget as e:
        raise HTTPException(status_code=422, detail=t(loc, "errors.api.url_invalid", reason=e.localized(loc)))
    if not lead_ip_limiter.allow(_client_ip(request)):
        raise _too_many(loc)
    if not lead_email_limiter.allow(leads.normalize_email(email)[1]):
        raise _too_many(loc)

    lead = leads.create_lead(email, url, loc)
    base = env_str("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"
    try:
        send_confirmation(lead["email"], build_confirm_url(base, lead["token"], loc), loc)
    except Exception:
        log.exception("invio email di conferma fallito")
        raise HTTPException(status_code=502, detail=t(loc, "errors.api.confirmation_send_failed"))
    return {"status": "pending", "message": t(loc, "lead.check_email")}


@router.get("/api/confirm")
def confirm(token: str, request: Request) -> dict:
    lead = leads.confirm_lead(token)
    if lead is None:
        raise HTTPException(status_code=404, detail=t(request_locale(request), "errors.api.confirm_link_invalid"))
    return {"status": "confirmed", "email": lead["email"], "url": lead["url"]}


@router.post("/api/scan")
def scan(req: ScanRequest, request: Request) -> dict:
    loc = request_locale(request)
    if not scan_ip_limiter.allow(_client_ip(request)):
        raise _too_many(loc)
    lead = leads.get_lead_by_token(req.token)
    if lead is None or not leads.can_scan(req.token):
        raise HTTPException(status_code=403, detail=t(loc, "errors.api.scan_not_allowed"))
    # rivalida l'URL ora (il DNS può essere cambiato dopo la registrazione):
    # se non è ammesso, la scansione gratuita NON viene consumata
    try:
        url = validate_target_url(lead["url"])
    except BlockedTarget as e:
        raise HTTPException(status_code=422, detail=t(loc, "errors.api.url_invalid", reason=e.localized(loc)))
    if leads.claim_scan(req.token) is None:
        raise HTTPException(status_code=403, detail=t(loc, "errors.api.scan_already_used"))
    # sempre l'LLM reale per il prodotto (1 scansione per email, costo contenuto)
    try:
        job = start_analysis(url, make_llm(stub=False), max_pages=1,
                             client=f"lead:{lead['email']}", notify_email=lead["email"],
                             origin="lead", locale=loc)
    except QueueFull:
        leads.release_scan(req.token)
        raise HTTPException(status_code=503, detail=t(loc, "errors.api.queue_full"))
    return {"job_id": job.id, "status": "pending", "url": url}


@router.get("/api/scan/{job_id}")
def scan_status(job_id: str, request: Request) -> dict:
    """Polling per l'utente lead: solo stato e risultato, mai errori interni."""
    loc = request_locale(request)
    job = store.get(job_id) if JOB_ID_RE.match(job_id) else None
    if job is None:
        raise HTTPException(status_code=404, detail=t(loc, "errors.api.job_not_found"))
    return {
        "job_id": job.id,
        "status": job.status,
        "error": job.public_error(loc),
        "result": job.result,
    }
