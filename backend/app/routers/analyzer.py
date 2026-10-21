"""Endpoint /api/analyze + /ws/{job_id} per l'analisi SiteIQ.

- POST /api/analyze body {url, max_pages?} -> {job_id} (avvia in background)
- GET  /api/analyze/{job_id}        -> stato/risultato job (polling fallback)
- WS   /ws/{job_id}                 -> eventi live: status/progress/result

SVILUPPO: usa lo stub LLM di default (deterministico, offline). Passa
?llm=openrouter per usare OpenRouter (richiede LLM_API_KEY in env).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth import auth_mapping, require_auth
from app.jobs import start_analysis, store
from app.llm import make_llm

router = APIRouter()


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=4)
    max_pages: int = Field(default=1, ge=1, le=1)


@router.post("/api/analyze", dependencies=[Depends(require_auth)])
def analyze(req: AnalyzeRequest, llm: str = Query("stub"), client: str = Depends(require_auth)) -> dict:
    llm_client = make_llm(stub=(llm == "stub"))
    job = start_analysis(req.url, llm_client, req.max_pages, client=client)
    return {"job_id": job.id, "status": "pending", "url": req.url, "client": client}


@router.get("/api/analyze/{job_id}", dependencies=[Depends(require_auth)])
def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job non trovato")
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "result": job.result,
    }


@router.websocket("/ws/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str):
    # Protezione: il client deve passare il token (query ?token=) o header.
    token = websocket.query_params.get("token")
    if not (token and token in auth_mapping()):
        await websocket.close(code=4401, reason="non autorizzato")
        return
    job = store.get(job_id)
    if job is None:
        await websocket.close(code=4404, reason="job non trovato")
        return
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def emit(kind: str, payload):
        # thread-safe: sospende sul loop dell'WebSocket
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    job.on_progress(emit)

    # invia lo stato corrente (per connessioni arrivate a lavoro in corso)
    await websocket.send_json({"type": "status", "payload": {"status": job.status}})
    await websocket.send_json({"type": "progress", "payload": job.progress})
    if job.status == "done" and job.result:
        await websocket.send_json({"type": "result", "payload": job.result})

    try:
        while True:
            kind, payload = await queue.get()
            if kind == "status" and payload.get("status") == "done":
                # il result viene inviato come evento separato dal job
                continue
            await websocket.send_json({"type": kind, "payload": payload})
            if kind == "result":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        await websocket.close()