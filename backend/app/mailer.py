"""Invio email (conferma double opt-in e report) via SMTP.

Config da env (vedi backend/.env.example):
    SMTP_HOST, SMTP_PORT (587 = STARTTLS, 465 = TLS implicito),
    SMTP_USER, SMTP_PASSWORD, SMTP_FROM (default: SMTP_USER)
"""
from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from app.config import env_int, env_str
from app.i18n import DEFAULT_LOCALE, t


def smtp_config() -> dict:
    """Config SMTP dall'ambiente ({} se SMTP_HOST non è impostato)."""
    host = env_str("SMTP_HOST")
    if not host:
        return {}
    user = env_str("SMTP_USER")
    return {
        "host": host,
        "port": env_int("SMTP_PORT", 587),
        "user": user,
        # SMTP_PASS / SMTP_SENDER: nomi storici, accettati per compatibilità
        "password": env_str("SMTP_PASSWORD") or env_str("SMTP_PASS"),
        "sender": env_str("SMTP_FROM") or env_str("SMTP_SENDER") or user,
    }


def _send(msg: EmailMessage) -> None:
    cfg = smtp_config()
    if not cfg:
        raise RuntimeError("SMTP non configurato (imposta SMTP_HOST e le altre SMTP_*)")
    if not cfg["sender"]:
        raise RuntimeError("mittente non configurato (SMTP_FROM o SMTP_USER)")
    msg["From"] = f"SiteIQ <{cfg['sender']}>"
    if cfg["port"] == 465:
        smtp = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30)
    else:
        smtp = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
    with smtp:
        if cfg["port"] != 465:
            smtp.starttls()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


def send_confirmation(email: str, confirm_url: str, locale: str = DEFAULT_LOCALE) -> None:
    """Invia l'email di conferma col link, nella lingua `locale`.
    Solleva se SMTP non è configurato."""
    msg = EmailMessage()
    msg["Subject"] = t(locale, "email.confirm.subject")
    msg["To"] = email
    msg.set_content(t(locale, "email.confirm.body", url=confirm_url))
    _send(msg)


def build_confirm_url(base_url: str, token: str, locale: str | None = None) -> str:
    """Link di conferma che punta alla landing con ?confirmed&token (e la lingua)."""
    params = {"confirmed": "1", "token": token}
    if locale:
        params["lang"] = locale
    return f"{base_url.rstrip('/')}/?{urlencode(params)}"


def send_report(email: str, subject: str, html_body: str) -> None:
    """Invia un report email in HTML (con alternativa testo semplice)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = email
    plain = re.sub(r"<[^>]+>", " ", html_body)
    plain = re.sub(r"\s+", " ", plain).strip()
    msg.set_content("\n\n".join(line for line in plain.split("  ") if line.strip()))
    msg.add_alternative(html_body, subtype="html")
    _send(msg)
