"""Autenticazione SiteIQ (Fase 5).

Backend protetto: ogni client possiede un token condiviso (config in .env),
e viene identificato da un nome. Serve sia per proteggere l'analisi sia per
monitorare CHI richiede un test nel log di consumo.

Config (.env), formato "nome=token", più client separati da ',' o ';':
    AUTH_CLIENTS=fabio=sk-token-fabio,manuel=sk-token-manuel
In assenza, si può usare un singolo token con nome di default:
    AUTH_TOKEN=sk-solo   (nome -> "default", o AUTH_CLIENT_DEFAULT)

Il client invia:  Authorization: Bearer <token>
FastAPI risolve il token -> nome per il log. /health resta libero.
"""
from __future__ import annotations

import hmac
import re

from fastapi import Header, HTTPException, Request

from app.config import env_str
from app.i18n import request_locale, t


def _load_auth_config() -> dict[str, str]:
    """Restituisce {token: nome} dalla config."""
    mapping: dict[str, str] = {}
    for entry in re.split(r"[,;]", env_str("AUTH_CLIENTS")):
        name, sep, token = entry.partition("=")
        name, token = name.strip(), token.strip()
        if sep and name and token:
            mapping[token] = name
    solo = env_str("AUTH_TOKEN")
    if solo:
        mapping[solo] = env_str("AUTH_CLIENT_DEFAULT") or "default"
    return mapping


_client_tokens: dict[str, str] | None = None


def _mapping() -> dict[str, str]:
    global _client_tokens
    if _client_tokens is None:
        _client_tokens = _load_auth_config()
    return _client_tokens


def token_client(token: str | None) -> str | None:
    """Nome del client per `token`, o None. Confronto a tempo costante."""
    if not token:
        return None
    found = None
    for known, name in _mapping().items():
        if hmac.compare_digest(known.encode(), token.encode()):
            found = name
    return found


def require_auth(request: Request, authorization: str | None = Header(default=None)) -> str:
    """Dependency FastAPI: verifica il Bearer e ritorna il nome del client."""
    loc = request_locale(request)
    if not _mapping():
        raise HTTPException(status_code=503, detail=t(loc, "errors.api.auth_not_configured"))

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail=t(loc, "errors.api.auth_required"))

    client = token_client(token)
    if client is None:
        raise HTTPException(status_code=401, detail=t(loc, "errors.api.token_invalid"))
    return client
