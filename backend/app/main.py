"""SiteIQ backend — API per l'analisi web (crawler + report AI).

Architettura:
  POST /api/analyze -> avvia analisi in background
  GET  /health       -> healthcheck
  WS   /ws/{job_id}  -> progress live del crawl
  GET  /.well-known/best, /best/* -> superficie BEST per agenti (app/best/)
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.best.errors import BestError, best_error_handler
from app.best.router import router as best_router
from app.i18n import LOCALES_DIR, SUPPORTED, request_locale
from app.routers import admin, analyzer, health, lead

# log dei moduli app.* (job falliti, email non inviate, URL bloccati) su stderr,
# accanto a quelli di uvicorn
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

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


@app.get("/locales/{locale}.json", include_in_schema=False)
def locale_catalog(locale: str):
    """Catalogo di localizzazione per il frontend (stesso file usato dal backend)."""
    if locale not in SUPPORTED:
        raise HTTPException(status_code=404)
    return FileResponse(LOCALES_DIR / f"{locale}.json", media_type="application/json",
                        headers={"Cache-Control": "public, max-age=300"})


@app.middleware("http")
async def content_language(request: Request, call_next):
    """Le API rispondono nella lingua di Accept-Language: lo dichiarano."""
    response = await call_next(request)
    if request.url.path.startswith(("/api/", "/best/")):
        response.headers.setdefault("Content-Language", request_locale(request))
        response.headers.setdefault("Vary", "Accept-Language")
    return response


# /static/styles.css · /static/app.js
app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")

app.include_router(health.router)
app.include_router(analyzer.router)
app.include_router(admin.router)
app.include_router(lead.router)
# superficie BEST per agenti: /.well-known/best + /best/* (fuori da /openapi.json)
app.include_router(best_router)
app.add_exception_handler(BestError, best_error_handler)