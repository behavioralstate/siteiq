"""Errori nel formato BEST: {"error": {"code", "message", "details"}}.

`code` è il codice macchina (stabile, inglese); `message` è reso nella lingua
della richiesta dal catalogo, chiave best.errors.<msg>, con i parametri dati.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.i18n import request_locale, t


class BestError(Exception):
    def __init__(self, status: int, code: str, msg: str, details: dict | None = None,
                 headers: dict | None = None, **params):
        super().__init__(code)
        self.status = status
        self.code = code
        self.msg = msg
        self.params = params
        self.details = details or {}
        self.headers = headers


async def best_error_handler(request: Request, exc: BestError) -> JSONResponse:
    message = t(request_locale(request), f"best.errors.{exc.msg}", **exc.params)
    body = {"error": {"code": exc.code, "message": message, "details": exc.details}}
    return JSONResponse(body, status_code=exc.status, headers=exc.headers)
