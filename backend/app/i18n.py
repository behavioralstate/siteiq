"""Localizzazione di SiteIQ.

Un catalogo per locale in locales/<locale>.json, condiviso con il frontend
(servito a /locales/<locale>.json). Le chiavi sono annidate e si usano con il
percorso puntato: t("it-IT", "checks.seo.title.label").

Valori del catalogo:
  - stringa, con segnaposto {nome}: t(loc, "chiave", nome=...)
  - plurale: {"one": "...", "other": "..."}, scelto da count=...
  - lista di stringhe (solo testi dimostrativi dello stub): t_list(loc, "chiave")

Locale scelto per richiesta da Accept-Language (il frontend lo invia sempre);
it-IT quando nulla corrisponde. Una chiave mancante in un locale ripiega su
it-IT, poi sulla chiave stessa (e viene loggata): i test verificano che i due
cataloghi abbiano le stesse chiavi.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from functools import lru_cache

from app.config import REPO_ROOT

log = logging.getLogger(__name__)

LOCALES_DIR = REPO_ROOT / "locales"
SUPPORTED = ("it-IT", "en-GB")
DEFAULT_LOCALE = "it-IT"
PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _is_plural(value) -> bool:
    return isinstance(value, dict) and "other" in value and set(value) <= PLURAL_FORMS


def _flatten(node: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and not _is_plural(value):
            out.update(_flatten(value, path + "."))
        else:
            out[path] = value
    return out


@lru_cache(maxsize=None)
def catalog(locale: str) -> dict:
    """Catalogo appiattito {chiave.puntata: valore} di un locale supportato."""
    with open(LOCALES_DIR / f"{locale}.json", encoding="utf-8") as f:
        return _flatten(json.load(f))


def match_locale(tag: str | None) -> str | None:
    """Locale supportato per un tag BCP 47 (esatto, poi per lingua: en-US -> en-GB)."""
    if not tag:
        return None
    tag = tag.strip().replace("_", "-").lower()
    for loc in SUPPORTED:
        if loc.lower() == tag:
            return loc
    lang = tag.split("-")[0]
    return next((loc for loc in SUPPORTED if loc.split("-")[0].lower() == lang), None)


def negotiate(accept_language: str | None) -> str:
    """Il locale preferito da un header Accept-Language, o il default."""
    ranked = []
    for i, part in enumerate((accept_language or "").split(",")):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        for p in params.split(";"):
            name, _, value = p.strip().partition("=")
            if name == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if tag and tag != "*" and q > 0:
            ranked.append((-q, i, tag))
    for _, _, tag in sorted(ranked):
        loc = match_locale(tag)
        if loc:
            return loc
    return DEFAULT_LOCALE


def request_locale(request) -> str:
    """Locale di una richiesta HTTP o WebSocket di Starlette (Accept-Language)."""
    return negotiate(request.headers.get("accept-language"))


def plural_category(locale: str, count) -> str:
    """Regole CLDR per italiano e inglese: "one" solo per 1 intero."""
    return "one" if count == 1 else "other"


def _lookup(locale: str, key: str):
    loc = locale if locale in SUPPORTED else DEFAULT_LOCALE
    value = catalog(loc).get(key)
    if value is None and loc != DEFAULT_LOCALE:
        value = catalog(DEFAULT_LOCALE).get(key)
    if value is None:
        log.warning("chiave di localizzazione mancante: %s", key)
    return value


def t(locale: str, key: str, **params) -> str:
    value = _lookup(locale, key)
    if value is None:
        return key
    if _is_plural(value):
        value = value.get(plural_category(locale, params.get("count")), value["other"])
    if not isinstance(value, str):
        return key
    return _PLACEHOLDER.sub(lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0),
                            value)


def t_optional(locale: str, key: str, **params) -> str | None:
    """Come t() ma None (senza log) se la chiave non esiste: per etichette di
    valori che possono non essere nel catalogo (dati storici, enum nuovi)."""
    loc = locale if locale in SUPPORTED else DEFAULT_LOCALE
    if key not in catalog(loc) and key not in catalog(DEFAULT_LOCALE):
        return None
    return t(locale, key, **params)


def t_list(locale: str, key: str) -> list[str]:
    value = _lookup(locale, key)
    return list(value) if isinstance(value, list) else []


def format_number(locale: str, value: float, decimals: int = 0) -> str:
    """Numero con i separatori del locale (catalogo: format.decimal / format.group)."""
    text = f"{value:,.{decimals}f}"
    dec, grp = t(locale, "format.decimal"), t(locale, "format.group")
    return text.replace(",", "\0").replace(".", dec).replace("\0", grp)


def format_date(locale: str, d: date) -> str:
    return t(locale, "format.date", dd=f"{d.day:02d}", mm=f"{d.month:02d}", yyyy=f"{d.year:04d}")


class Translator:
    """Scorciatoia legata a un locale: tr = Translator(loc); tr("chiave", n=1)."""

    def __init__(self, locale: str):
        self.locale = locale if locale in SUPPORTED else DEFAULT_LOCALE

    def __call__(self, key: str, **params) -> str:
        return t(self.locale, key, **params)

    def optional(self, key: str, **params) -> str | None:
        return t_optional(self.locale, key, **params)

    def list(self, key: str) -> list[str]:
        return t_list(self.locale, key)

    def number(self, value: float, decimals: int = 0) -> str:
        return format_number(self.locale, value, decimals)

    def date(self, d: date) -> str:
        return format_date(self.locale, d)
