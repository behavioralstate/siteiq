"""Endpoint admin SiteIQ — monitoraggio consumo (Fase 5).

Solo lettura (protetti da auth): chi ha richiesto test, quando, su quale URL,
e quanto credito/token LLM è stato consumato.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_auth
from app.usage import list_requests, totals

router = APIRouter()


@router.get("/api/admin/usage", dependencies=[Depends(require_auth)])
def usage_overview(client: str = Depends(require_auth)) -> dict:
    """Riepilogo aggregato del consumo. `?client=fabio` filtra per utente."""
    return {
        "totals": totals(client),
        "n_scans_per_client": None,  # estensione futura
        "requested_by": client,
    }


@router.get("/api/admin/requests", dependencies=[Depends(require_auth)])
def requests(log: str = Query("fabio"), limit: int = Query(100, ge=1, le=1000),
             client: str = Depends(require_auth)) -> dict:
    """Ultimi N test registrati (per client o tutti). Log accessibile solo ad admin."""
    rows = list_requests(client=log, limit=limit)
    return {"requests": rows, "count": len(rows)}


@router.get("/api/admin/leads", dependencies=[Depends(require_auth)])
def leads_view(limit: int = Query(50, ge=1, le=500),
               client: str = Depends(require_auth)) -> dict:
    """Lead raccolti dalla landing (email + url + stato conferma + scan usato)."""
    from app import leads as _leads
    rows = _leads.list_leads(limit=limit)
    return {"leads": rows, "count": len(rows)}


@router.get("/api/admin/reports", dependencies=[Depends(require_auth)])
def reports_list(client: str = Depends(require_auth)) -> dict:
    """Lista i report HTML salvati su disco (per la visualizzazione admin)."""
    from app.jobs import _resolve_reports_dir
    d = _resolve_reports_dir()
    files = sorted(d.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for f in files[:200]:
        items.append({"job_id": f.stem, "path": f.name, "bytes": f.stat().st_size,
                      "modified": __import__("datetime").datetime.fromtimestamp(
                          f.stat().st_mtime).isoformat()})
    return {"reports": items, "count": len(items)}


@router.get("/api/admin/report/{job_id}")
def report_page(job_id: str, client: str = Depends(require_auth)):
    """Ritorna il contenuto HTML della pagina report di un job (admin)."""
    from app.jobs import _resolve_reports_dir
    from fastapi.responses import HTMLResponse
    f = _resolve_reports_dir() / f"{job_id}.html"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="report non trovato")
    return HTMLResponse(content=f.read_text(encoding="utf-8"), status_code=200)