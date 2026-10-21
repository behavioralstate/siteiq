"""Fingerprinting WordPress e rilevamento plugin/versioni (Fase 6 — WP).

Da una pagina di un sito si estraggono i segnali che rivelano un WordPress e la
sua composizione, SENZA toccare file riservati:

  - è WordPress?          -> meta generator="WordPress X.Y.Z", /wp-content/...
  - versione core         -> dal meta generator
  - plugin installati     -> path negli href/src: /wp-content/plugins/<slug>/
  - versione plugin       -> dal ?ver= nella STESSA URL del plugin (accuratezza)
  - tema                  -> /wp-content/themes/<slug>/

Le versioni vengono poi confrontate con la WPVulnerability API (wpvuln.py).
"""
from __future__ import annotations

import re

_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_GENERATOR_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']generator["\']', re.I)

# generator del feed RSS/Atom di WP: <generator>https://wordpress.org/?v=6.4.2</generator>
_FEED_GENERATOR_RE = re.compile(
    r'<generator[^>]*>https?://[^<]*\?v=([0-9]+\.[0-9]+(?:\.[0-9]+)?)[^<]*</generator>', re.I)

WP_CORE_VERSION_RE = re.compile(r'\bWordPress\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[a-z0-9]+)?)', re.I)

# cattura slug e ?ver= della stessa URL di asset plugin
_ASSET_RE = re.compile(
    r'/wp-content/plugins/([^/"\'\\]+)(?:/[^"\'\\\s]*?)?[?&]ver=([0-9]+\.[0-9]+(?:\.[0-9]+)?)',
    re.I)
_PLUGIN_PATH_RE = re.compile(r'/wp-content/plugins/([^/"\'\\]+)/', re.I)
_THEME_PATH_RE = re.compile(r'/wp-content/themes/([^/"\'\\]+)/', re.I)


def _generator_core(html: str) -> str | None:
    for rgx in (_GENERATOR_RE, _GENERATOR_RE2):
        m = rgx.search(html or "")
        if m and "wordpress" in m.group(1).lower():
            v = WP_CORE_VERSION_RE.search(m.group(1))
            if v:
                return v.group(1)
    return None


def is_wordpress(html: str) -> bool:
    """Segnali strutturali (path di asset WP o meta generator), mai il testo
    della pagina: un articolo che cita "WordPress 5.2" non è un sito WP."""
    low = (html or "").lower()
    return "/wp-content/" in low or "/wp-includes/" in low or _generator_core(html) is not None


def core_version(html: str) -> str | None:
    """Versione WP SOLO dal meta generator (il testo libero darebbe falsi CVE)."""
    return _generator_core(html)


def core_version_from_feed(feed: str) -> str | None:
    """Versione WP dal feed RSS/Atom (<generator>…?v=X.Y.Z</generator>)."""
    m = _FEED_GENERATOR_RE.search(feed or "")
    return m.group(1) if m else None


# intestazioni standard del readme.txt di un plugin WordPress
def version_from_readme(readme: str) -> str | None:
    """Versione del plugin dal readme.txt pubblico (Stable tag: / Version:).

    'Stable tag' ha priorità su 'Version' (è la versione consigliata/più recente).
    Nota: si evita l'f-string per il quantificatore {1,3} (le graffe nelle f-string
    sono placeholder), si costruisce il pattern con + formattazione esplicita.
    """
    body = r"([0-9]+(?:\.[0-9]+){1,3}(?:[.-][a-z0-9]+)?)"
    for name in ("Stable tag", "Version"):
        m = re.search(r"^" + name + r"\s*:\s*" + body, readme or "", re.I | re.M)
        if m:
            return m.group(1)
    return None


def detect_plugins(html: str) -> list[dict]:
    """Ritorna [{slug, version?}] dai path /wp-content/plugins/<slug>/.

    La versione viene presa SOLO dal ?ver= che appartiene alla stessa URL dell'
    asset del plugin (regex _ASSET_RE), mai da un'altra URL della pagina.
    """
    html = html or ""
    versions: dict[str, str] = {}
    seen: dict[str, bool] = {}
    # 1) versione dalla stessa URL dell'asset del plugin
    for m in _ASSET_RE.finditer(html):
        slug, ver = m.group(1), m.group(2)
        versions[slug] = ver
        seen[slug] = True
    # 2) plugin senza versione (path presente ma url asset senza ?ver=)
    for m in _PLUGIN_PATH_RE.finditer(html):
        slug = m.group(1)
        if slug not in seen:
            seen[slug] = True
    return [{"slug": s, "version": versions.get(s)} for s in seen]


def drop_core_versioned_plugins(wp: dict) -> None:
    """WordPress accoda ?ver=<versione core> agli asset dei plugin che non ne
    dichiarano una propria: quel numero NON è la versione del plugin. Lo scarta,
    così il plugin finisce in "non verificabile" (o viene letto dal readme)."""
    core = wp.get("core")
    if not core:
        return
    for pl in wp.get("plugins", []):
        if pl.get("version") == core:
            pl["version"] = None


def detect_theme(html: str) -> str | None:
    m = _THEME_PATH_RE.search(html or "")
    return m.group(1) if m else None


def fingerprint(html: str) -> dict:
    """Riepilogo fingerprint WP. Usa SOLO ciò che è davvero rilevato."""
    html = html or ""
    wp = is_wordpress(html)
    return {
        "is_wordpress": wp,
        "core": core_version(html) if wp else None,
        "plugins": detect_plugins(html) if wp else [],
        "theme": detect_theme(html) if wp else None,
    }