"""Configurazione SiteIQ: caricamento del .env e lettura tipizzata delle variabili.

Il .env viene letto UNA volta all'import (backend/.env). Le variabili già
presenti nell'ambiente hanno la precedenza (os.environ.setdefault), così i test
e systemd possono sovrascrivere i valori del file.
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def load_env(path: str | None = None) -> None:
    """Carica un semplice .env (key=value, # commenti) senza dipendenze."""
    env_path = Path(path) if path else BACKEND_DIR / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


load_env()
