"""Invio email di conferma (double opt-in) via SMTP.

Config: legge da env (SMTP_HOST/PORT/USER/PASS/SENDER) oppure, in assenza,
prova a ricavare account+password dalla config di himalaya
(~/.config/himalaya/config.toml, account 'pensareweb').
"""
from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode


def _himalaya_smtp() -> dict | None:
    try:
        cfg = Path.home() / ".config" / "himalaya" / "config.toml"
        text = cfg.read_text()
        user = re.search(r'smtp\.username\s*=\s*"([^"]+)"', text) or \
               re.search(r'smtp\.sasl\.plain\.username\s*=\s*"([^"]+)"', text)
        # password può essere inline ("...") o via command
        pw_inline = re.search(r'smtp\.password\s*=\s*"([^"]+)"', text) or \
                    re.search(r'smtp\.sasl\.plain\.password\s*=\s*"([^"]+)"', text)
        server = re.search(r'smtp\.server\s*=\s*"smtp://([^":]+):(\d+)"', text)
        if not (user and server):
            return None
        password = pw_inline.group(1) if pw_inline else None
        if password is None:
            # via command: esegui (es. echo 'password')
            cmd = re.search(r'smtp\.sasl\.plain\.password\.command\s*=\s*"(.+?)"', text) or \
                  re.search(r'smtp\.password\.command\s*=\s*"(.+?)"', text)
            if cmd:
                password = os.popen(cmd.group(1)).read().strip()
        return {
            "host": server.group(1),
            "port": int(server.group(2)),
            "user": user.group(1),
            "pass": password or "",
        }
    except Exception:
        return None


def smtp_config() -> dict:
    """Ritorna la config SMTP (env prima, himalaya come fallback)."""
    if os.environ.get("SMTP_HOST"):
        return {
            "host": os.environ["SMTP_HOST"],
            "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": os.environ.get("SMTP_USER", ""),
            "pass": os.environ.get("SMTP_PASS", ""),
        }
    return _himalaya_smtp() or {}


def sender_address() -> str:
    cfg = smtp_config()
    return cfg.get("user") or os.environ.get("SMTP_SENDER", "fabio@pensareweb.it")


def send_confirmation(email: str, confirm_url: str) -> None:
    """Invia l'email di conferma col link. Solleva se SMTP non è configurato."""
    cfg = smtp_config()
    if not cfg or not cfg.get("host"):
        raise RuntimeError("SMTP non configurato (imposta SMTP_* o usa himalaya)")

    msg = EmailMessage()
    msg["Subject"] = "Conferma la tua email — SiteIQ"
    msg["From"] = f"SiteIQ <{sender_address()}>"
    msg["To"] = email
    msg.set_content(
        "Ciao!\n\n"
        "Hai richiesto un'analisi gratuita del tuo sito con SiteIQ.\n"
        "Per verificare la tua email e sbloccare l'analisi (1 pagina, gratis), "
        "clicca su questo link:\n\n"
        f"{confirm_url}\n\n"
        "Se non hai richiesto tu questa email, puoi ignorarla.\n\n"
        "A presto,\nil team SiteIQ\n"
    )

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg["user"], cfg["pass"])
        smtp.send_message(msg)


def build_confirm_url(base_url: str, token: str) -> str:
    """Link di conferma che punta alla landing con ?confirmed&token."""
    q = urlencode({"confirmed": "1", "token": token})
    return f"{base_url.rstrip('/')}/?{q}"


def send_report(email: str, subject: str, html_body: str) -> None:
    """Invia un report email in HTML all'indirizzo indicato."""
    cfg = smtp_config()
    if not cfg or not cfg.get("host"):
        raise RuntimeError("SMTP non configurato (imposta SMTP_* o usa himalaya)")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"SiteIQ <{sender_address()}>"
    msg["To"] = email
    # testo semplice come fallback e HTML come parte principale
    import re as _re
    plain = _re.sub(r"<[^>]+>", " ", html_body)
    plain = _re.sub(r"\s+", " ", plain).strip()
    msg.set_content("\n\n".join(line for line in plain.split("  ") if line.strip()))
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg["user"], cfg["pass"])
        smtp.send_message(msg)