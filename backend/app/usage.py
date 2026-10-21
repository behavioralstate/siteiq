"""Monitoraggio consumo SiteIQ (Fase 5).

Registra ogni analisi richiesta e i token/credito consumati dall'LLM, per
rispondere a: CHI ha richiesto il test, QUANDO, SU QUALE URL, e quanto credito
OpenRouter è stato consumato.

Storage: SQLite locale (nessuna dipendenza esterna). Posizione DB configurabile
via env USAGE_DB (default <repo>/siteiq_usage.db). Thread-safe: ogni accesso
alla connessione condivisa avviene sotto `_lock`.

Endpoints di lettura (protetti): vedi routers/admin.py
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from app.config import REPO_ROOT, env_str


def _db_path() -> str:
    return env_str("USAGE_DB") or str(REPO_ROOT / "siteiq_usage.db")


_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _db_path()
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id         TEXT PRIMARY KEY,
                ts         TEXT NOT NULL,
                client     TEXT NOT NULL,
                url        TEXT NOT NULL,
                model      TEXT,
                status     TEXT NOT NULL,          -- ok | error | skipped
                prompt_tokens   INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens    INTEGER DEFAULT 0,
                cost_usd        REAL DEFAULT 0,
                evidence_refs   TEXT               -- JSON (per debug)
            )
        """)
        _conn.commit()
    return _conn


def log_request(client: str, url: str, *, model: str | None = None,
                status: str = "ok", usage: dict | None = None,
                evidence_refs: list | None = None) -> str:
    """Registra una richiesta di analisi e ritorna l'id del record."""
    usage = usage or {}
    rec_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        c = _get_conn()
        c.execute(
            """INSERT INTO usage_log
               (id, ts, client, url, model, status,
                prompt_tokens, completion_tokens, total_tokens, cost_usd, evidence_refs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec_id, now, client, url, model, status,
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
                int(usage.get("total_tokens", 0) or 0),
                float(usage.get("cost", 0) or 0),
                json.dumps(evidence_refs or []),
            ),
        )
        c.commit()
    return rec_id


def update_status(rec_id: str, status: str, usage: dict | None = None,
                   evidence_refs: list | None = None) -> None:
    """Aggiorna esito + consumi di una richiesta già registrata (a fine job)."""
    usage = usage or {}
    with _lock:
        c = _get_conn()
        c.execute(
            """UPDATE usage_log
               SET status=?, prompt_tokens=?, completion_tokens=?, total_tokens=?,
                   cost_usd=?, evidence_refs=?
               WHERE id=?""",
            (
                status,
                int(usage.get("prompt_tokens", 0) or 0),
                int(usage.get("completion_tokens", 0) or 0),
                int(usage.get("total_tokens", 0) or 0),
                float(usage.get("cost", 0) or 0),
                json.dumps(evidence_refs or []),
                rec_id,
            ),
        )
        c.commit()


def list_requests(client: str | None = None, limit: int = 100) -> list[dict]:
    with _lock:
        c = _get_conn()
        if client:
            rows = c.execute(
                "SELECT * FROM usage_log WHERE client=? ORDER BY ts DESC LIMIT ?",
                (client, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM usage_log ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def totals(client: str | None = None) -> dict:
    """Riepilogo consumo aggregato (per client, o totale)."""
    with _lock:
        c = _get_conn()
        where, params = ("WHERE client=?", (client,)) if client else ("", ())
        row = c.execute(
            f"""SELECT COUNT(*)                AS requests,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(cost_usd), 0)     AS total_cost_usd,
                       COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                       SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok,
                       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
                       SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped
                  FROM usage_log {where}""",
            params,
        ).fetchone()
    d = dict(row)
    return {
        **d,
        "ok": int(d.get("ok") or 0),
        "errors": int(d.get("errors") or 0),
        "skipped": int(d.get("skipped") or 0),
    }