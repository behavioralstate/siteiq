"""Endpoint admin SiteIQ — monitoraggio consumo (Fase 5).

Solo lettura (protetti da auth): chi ha richiesto test, quando, su quale URL,
e quanto credito/token LLM è stato consumato. Ogni token valido è un admin e
vede i dati di tutti i client.
"""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app import leads
from app.auth import require_auth
from app.i18n import request_locale, t
from app.jobs import _resolve_reports_dir
from app.usage import list_requests, totals

router = APIRouter(dependencies=[Depends(require_auth)])

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@router.get("/api/admin/usage")
def usage_overview(client: str | None = Query(None),
                   caller: str = Depends(require_auth)) -> dict:
    """Riepilogo aggregato del consumo: tutti i client, o `?client=nome`."""
    return {"totals": totals(client), "client": client, "requested_by": caller}


@router.get("/api/admin/requests")
def requests(log: str | None = Query(None, description="filtra per nome client"),
             limit: int = Query(100, ge=1, le=1000)) -> dict:
    """Ultimi N test registrati (tutti, o per client con `?log=nome`)."""
    rows = list_requests(client=log, limit=limit)
    return {"requests": rows, "count": len(rows)}


@router.get("/api/admin/leads")
def leads_view(limit: int = Query(50, ge=1, le=500)) -> dict:
    """Lead raccolti dalla landing (email + url + stato conferma + scan usato)."""
    rows = leads.list_leads(limit=limit)
    return {"leads": rows, "count": len(rows)}


@router.get("/api/admin/reports")
def reports_list() -> dict:
    """Lista i report HTML salvati su disco (per la visualizzazione admin)."""
    files = sorted(_resolve_reports_dir().glob("*.html"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for f in files[:200]:
        st = f.stat()
        items.append({"job_id": f.stem, "path": f.name, "bytes": st.st_size,
                      "modified": datetime.fromtimestamp(st.st_mtime).isoformat()})
    return {"reports": items, "count": len(items)}


@router.get("/api/admin/report/{job_id}")
def report_page(job_id: str, request: Request):
    """Contenuto HTML della pagina report di un job (admin)."""
    f = _resolve_reports_dir() / f"{job_id}.html"
    if not JOB_ID_RE.match(job_id) or not f.is_file():
        raise HTTPException(status_code=404, detail=t(request_locale(request), "errors.api.report_not_found"))
    return HTMLResponse(content=f.read_text(encoding="utf-8"), status_code=200)
