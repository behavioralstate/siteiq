"""Lead & conferma email (Fase 5.5 — double opt-in per 1 scansione gratis).

Flusso:
  1. POST /api/lead {email, url}        -> crea lead PENDING + manda email di conferma
  2. GET  /api/confirm?token=<T>        -> LEAD CONFERMATO (email verificata)
  3. POST /api/scan {token}             -> esegue 1 scansione (1 pagina) SOLO se
                                           confermato e se la scansione non è già usata

Ogni email confermata ha diritto a 1 scansione (campo scan_used). Questo limita
il consumo di credito OpenRouter per il free-tier. L'email viene normalizzata
(minuscole, senza "+etichetta") in `email_key`, così varianti della stessa
casella non moltiplicano le scansioni gratuite.

Storage: stessa connessione/DB SQLite di usage_log (tabella leads).
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime, timezone

from app.usage import _get_conn, _lock

log = logging.getLogger(__name__)


def normalize_email(email: str) -> tuple[str, str]:
    """Ritorna (email in minuscolo, chiave canonica senza +etichetta)."""
    email = (email or "").strip().lower()
    local, _, domain = email.partition("@")
    key = f"{local.split('+', 1)[0]}@{domain}"
    return email, key


def _ensure_leads_table():
    with _lock:
        c = _get_conn()
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id          TEXT PRIMARY KEY,
                email       TEXT NOT NULL,
                url         TEXT NOT NULL,
                token       TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed
                scan_used   INTEGER NOT NULL DEFAULT 0,        -- 0 | 1
                created_at  TEXT NOT NULL,
                confirmed_at TEXT,
                email_key   TEXT,
                locale      TEXT
            )
        """)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
        # migrazione DB esistenti (prima di email_key)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(leads)").fetchall()}
        if "email_key" not in cols:
            c.execute("ALTER TABLE leads ADD COLUMN email_key TEXT")
        if "locale" not in cols:
            c.execute("ALTER TABLE leads ADD COLUMN locale TEXT")
        for row in c.execute("SELECT id, email FROM leads WHERE email_key IS NULL").fetchall():
            c.execute("UPDATE leads SET email_key=? WHERE id=?",
                      (normalize_email(row["email"])[1], row["id"]))
        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_email_key ON leads(email_key)")
        except sqlite3.IntegrityError:
            # dati storici con varianti della stessa casella: indice non unico
            log.warning("lead duplicati per email_key: indice non unico")
            c.execute("CREATE INDEX IF NOT EXISTS idx_leads_email_key_nu ON leads(email_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_leads_token ON leads(token)")
        c.commit()


_ensure_leads_table()


def create_lead(email: str, url: str, locale: str | None = None) -> dict:
    """Crea un lead pending e ritorna il dict (con token). Se la casella esiste
    già, RIUSA il lead esistente (aggiorna l'URL) e ne ritorna il token — così
    un utente può richiedere di nuovo la conferma senza andare in errore.
    `locale` è la lingua della richiesta: quella dell'email di conferma."""
    email, key = normalize_email(email)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        c = _get_conn()
        existing = c.execute("SELECT * FROM leads WHERE email_key=?", (key,)).fetchone()
        if existing is not None:
            c.execute("UPDATE leads SET url=?, locale=COALESCE(?, locale) WHERE id=?",
                      (url, locale, existing["id"]))
            c.commit()
            return dict(c.execute("SELECT * FROM leads WHERE id=?", (existing["id"],)).fetchone())
        rec_id = secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO leads (id, email, email_key, url, token, status, scan_used, created_at, locale) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (rec_id, email, key, url, token, "pending", 0, now, locale),
        )
        c.commit()
        return dict(c.execute("SELECT * FROM leads WHERE id=?", (rec_id,)).fetchone())


def get_lead_by_token(token: str) -> dict | None:
    with _lock:
        row = _get_conn().execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def confirm_lead(token: str) -> dict | None:
    """Conferma l'email (double opt-in). Idempotente: se già confermato,
    restituisce comunque il lead. Ritorna None solo se il token non esiste."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        c = _get_conn()
        c.execute(
            "UPDATE leads SET status='confirmed', confirmed_at=? "
            "WHERE token=? AND status!='confirmed'",
            (now, token),
        )
        c.commit()
        row = c.execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def claim_scan(token: str) -> dict | None:
    """Consuma ATOMICAMENTE la scansione gratuita. Ritorna il lead se il diritto
    c'era (confermato e non usato), altrimenti None. Due richieste concorrenti
    non possono passare entrambe: vince solo l'UPDATE che modifica la riga."""
    with _lock:
        c = _get_conn()
        cur = c.execute(
            "UPDATE leads SET scan_used=1 WHERE token=? AND scan_used=0 AND status='confirmed'",
            (token,),
        )
        c.commit()
        if cur.rowcount != 1:
            return None
        row = c.execute("SELECT * FROM leads WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def release_scan(token: str) -> None:
    """Restituisce la scansione se il job non è potuto partire (coda piena)."""
    with _lock:
        c = _get_conn()
        c.execute("UPDATE leads SET scan_used=0 WHERE token=?", (token,))
        c.commit()


def can_scan(token: str) -> bool:
    """True se il lead è confermato e non ha ancora usato la scansione."""
    lead = get_lead_by_token(token)
    return bool(lead and lead["status"] == "confirmed" and not lead["scan_used"])


def list_leads(limit: int = 50) -> list[dict]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT email,url,status,scan_used,created_at,confirmed_at "
            "FROM leads ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
