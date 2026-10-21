"""SiteIQ backend — API per l'analisi web (crawler + report AI).

Architettura:
  POST /api/analyze -> avvia analisi in background
  GET  /health       -> healthcheck
  WS   /ws/{job_id}  -> progress live del crawl
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import admin, analyzer, health, lead

app = FastAPI(title="SiteIQ API", version="0.1.0")

# Frontend statico no-build (HTML/CSS/JS vanilla) servito dallo stesso processo.
_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_FRONTEND / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_page():
    """Pannello admin (UI). La protezione vera è sugli endpoint API (/api/*)."""
    return FileResponse(_FRONTEND / "admin.html")


@app.get("/report_viewer.html", include_in_schema=False)
def report_viewer():
    """Viewer report per admin (carica con auth l'endpoint /api/admin/report/{id})."""
    return FileResponse(_FRONTEND / "report_viewer.html")


# /static/styles.css · /static/app.js
app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")

app.include_router(health.router)
app.include_router(analyzer.router)
app.include_router(admin.router)
app.include_router(lead.router)