"""Endpoint /api/analyze + /ws/{job_id} per l'analisi SiteIQ (admin, con token).

- POST /api/analyze body {url, max_pages?} -> {job_id} (avvia in background)
- GET  /api/analyze/{job_id}        -> stato/risultato job (polling fallback)
- WS   /ws/{job_id}?token=...       -> eventi live: status/progress/result

SVILUPPO: usa lo stub LLM di default (deterministico, offline). Passa
?llm=openrouter per usare OpenRouter (richiede LLM_API_KEY in env).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth import require_auth, token_client
from app.i18n import request_locale, t
from app.jobs import QueueFull, start_analysis, store
from app.llm import make_llm
from app.netguard import BlockedTarget, validate_target_url

log = logging.getLogger(__name__)
router = APIRouter()


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    max_pages: int = Field(default=1, ge=1, le=1)


@router.post("/api/analyze")
def analyze(req: AnalyzeRequest, request: Request,
            llm: Literal["stub", "openrouter"] = Query("stub"),
            client: str = Depends(require_auth)) -> dict:
    loc = request_locale(request)
    try:
        url = validate_target_url(req.url)
    except BlockedTarget as e:
        raise HTTPException(status_code=422, detail=t(loc, "errors.api.url_invalid", reason=e.localized(loc)))
    try:
        job = start_analysis(url, make_llm(stub=(llm == "stub")), req.max_pages, client=client,
                             locale=loc)
    except QueueFull:
        raise HTTPException(status_code=503, detail=t(loc, "errors.api.queue_full"))
    return {"job_id": job.id, "status": "pending", "url": url, "client": client}


@router.get("/api/analyze/{job_id}", dependencies=[Depends(require_auth)])
def get_job(job_id: str, request: Request) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=t(request_locale(request), "errors.api.job_not_found"))
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "report_email_errors": job.report_email_errors,
        "result": job.result,
    }


@router.websocket("/ws/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str):
    # I browser non possono impostare header sui WebSocket: il token arriva in
    # query string (?token=). Non loggare le URL complete dei WS.
    loc = request_locale(websocket)
    if token_client(websocket.query_params.get("token")) is None:
        await websocket.close(code=4401, reason=t(loc, "errors.api.token_invalid"))
        return
    job = store.get(job_id)
    if job is None:
        await websocket.close(code=4404, reason=t(loc, "errors.api.job_not_found"))
        return
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(kind: str, payload):
        # chiamato dal thread del job: consegna sul loop del WebSocket
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    job.on_progress(emit)
    try:
        # stato corrente (per connessioni arrivate a lavoro in corso o concluso)
        await websocket.send_json({"type": "status", "payload": {"status": job.status}})
        await websocket.send_json({"type": "progress", "payload": job.progress})
        if job.status == "done" and job.result is not None:
            await websocket.send_json({"type": "result", "payload": job.result})
            return
        if job.status == "error":
            await websocket.send_json({"type": "status",
                                       "payload": {"status": "error", "error": job.error}})
            return
        while True:
            kind, payload = await queue.get()
            if kind == "status" and payload.get("status") == "done":
                continue  # il result arriva come evento separato
            await websocket.send_json({"type": kind, "payload": payload})
            if kind == "result" or (kind == "status" and payload.get("status") == "error"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("errore WebSocket job %s", job_id)
    finally:
        job.off_progress(emit)
        try:
            await websocket.close()
        except Exception:
            pass
