"""Autenticazione SiteIQ (Fase 5).

Backend protetto: ogni client possiede un token condiviso (config in .env),
e viene identificato da un nome. Serve sia per proteggere l'analisi sia per
monitorare CHI richiede un test nel log di consumo.

Config (.env), formato "nome=token" separati da ';':
    AUTH_CLIENTS="fabio=sk-token-fabio;manuel=sk-token-manuel"
In assenza, si può usare un singolo token con nome di default:
    AUTH_TOKEN=sk-solo   (nome -> "default")

Il client invia:  Authorization: Bearer <token>
FastAPI risolve il token -> nome per il log.

Dipendenze: richiede la password solo su endpoint protetti; /health resta libero.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Header, HTTPException


def _load_env(path: str | None = None):
    """Carica un semplice .env (key=value, # commenti) senza dipendenze."""
    env_path = Path(path or (Path(__file__).resolve().parent.parent / ".env"))
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_env()


def _load_auth_config() -> dict[str, str]:
    """Restituisce {token: nome} dalla config."""
    raw = os.environ.get("AUTH_CLIENTS", "").strip()
    mapping: dict[str, str] = {}
    if raw:
        for entry in raw.split(";"):
            if "=" not in entry:
                continue
            name, _, token = entry.partition("=")
            name, token = name.strip(), token.strip()
            if token:
                mapping[token] = name
    solo = os.environ.get("AUTH_TOKEN", "").strip()
    if solo:
        mapping[solo] = os.environ.get("AUTH_CLIENT_DEFAULT", "default")
    return mapping


_client_tokens: dict[str, str] | None = None


def _mapping() -> dict[str, str]:
    global _client_tokens
    if _client_tokens is None:
        _client_tokens = _load_auth_config()
    return _client_tokens


def auth_mapping() -> dict[str, str]:
    """Mappa {token: nome} — accessibile ai router (es. protezione WebSocket)."""
    return dict(_mapping())


def require_auth(authorization: str | None = Header(default=None)) -> str:
    """Dependency FastAPI: verifica il Bearer e ritorna il nome del client."""
    mapping = _mapping()
    if not mapping:
        # nessun token configurato: dev-treatment, ma logga come 'unauthenticated'
        # (meglio bloccare: la feature va protetta). Alziamo 403 se disabilitato.
        raise HTTPException(status_code=503, detail="auth non configurata (AUTH_TOKEN/AUTH_CLIENTS)")

    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token:
        raise HTTPException(status_code=401, detail="autenticazione richiesta (Authorization: Bearer <token>)")

    client = mapping.get(token)
    if client is None:
        raise HTTPException(status_code=401, detail="token non valido")
    return client