"""Lead & conferma email (Fase 5.5 — double opt-in per 1 scansione gratis).

Flusso:
  1. POST /api/lead {email, url}        -> crea lead PENDING + manda email di conferma
  2. GET  /api/confirm?token=<T>        -> LEAD CONFERMATO (email verificata)
  3. POST /api/scan {email, token}       -> esegue 1 scansione (1 pagina) SOLO se
                                           confermato e se la scansione non è già usata

Ogni email confermata ha diritto a 1 scansione (campo scan_used). Questo limita
il consumo di credito OpenRouter per il free-tier.

Storage: SQLite separato dal usage (same db file, tabella leads).
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.usage import _db_path, _get_conn, _lock  # riusa connessione sqlite

# usa la stessa connessione/DB di usage_log (unico file SQLite)
_conn_locked = threading.Lock()


def _ensure_leads_table():
    c = _get_conn()
    with _lock:
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id          TEXT PRIMARY KEY,
                email       TEXT NOT NULL,
                url         TEXT NOT NULL,
                token       TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed
                scan_used   INTEGER NOT NULL DEFAULT 0,        -- 0 | 1
                created_at  TEXT NOT NULL,
                confirmed_at TEXT
            )
        """)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
        c.commit()


_ensure_leads_table()


def create_lead(email: str, url: str) -> dict:
    """Crea un lead pending e ritorna il dict (con token). Se l'email esiste
    già, RIUSA il lead esistente (aggiorna l'URL) e ne ritorna il token — così
    un utente può richiedere di nuovo la conferma senza andare in errore."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        c = _get_conn()
        # già registrato?
        existing = c.execute(
            "SELECT * FROM leads WHERE email=?", (email,)
        ).fetchone()
        if existing is not None:
            # aggiorna l'URL e libera lo scan se l'utente non l'ha ancora usato
            c.execute(
                "UPDATE leads SET url=? WHERE email=?",
                (url, email),
            )
            c.commit()
            row = c.execute("SELECT * FROM leads WHERE email=?", (email,)).fetchone()
            return dict(row)
        # nuovo lead
        rec_id = secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO leads (id, email, url, token, status, scan_used, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (rec_id, email, url, token, "pending", 0, now),
        )
        c.commit()
        row = c.execute("SELECT * FROM leads WHERE email=?", (email,)).fetchone()
        return dict(row) if row else {
            "id": rec_id, "email": email, "url": url, "token": token,
            "status": "pending", "scan_used": 0,
        }


def get_lead_by_token(token: str) -> dict | None:
    with _lock:
        c = _get_conn()
        row = c.execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def confirm_lead(token: str) -> dict | None:
    """Conferma l'email (double opt-in). Idempotente: se già confermato,
    restituisce comunque il lead (nessun errore). Ritorna None solo se il
    token non esiste affatto."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        c = _get_conn()
        row = c.execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
        if row is None:
            return None
        # se già confermato, non fare nulla (idempotente)
        if row["status"] != "confirmed":
            c.execute(
                "UPDATE leads SET status='confirmed', confirmed_at=? WHERE token=?",
                (now, token),
            )
            c.commit()
        row = c.execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def mark_scan_used(token: str) -> bool:
    """Segna la scansione come usata. Ritorna True se c'era ancora diritto."""
    with _lock:
        c = _get_conn()
        c.execute(
            "UPDATE leads SET scan_used=1 WHERE token=? AND scan_used=0 AND status='confirmed'",
            (token,),
        )
        c.commit()
        return c.total_changes > 0


def can_scan(token: str) -> bool:
    """True se il lead è confermato e non ha ancora usato la scansione."""
    lead = get_lead_by_token(token)
    return bool(lead and lead["status"] == "confirmed" and not lead["scan_used"])


def list_leads(limit: int = 50) -> list[dict]:
    with _lock:
        c = _get_conn()
        rows = c.execute(
            "SELECT email,url,status,scan_used,created_at,confirmed_at "
            "FROM leads ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]