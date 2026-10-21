"""Protezione SSRF: SiteIQ scarica URL forniti da utenti anonimi (landing).

Regola: si contattano SOLO host che risolvono a indirizzi IP pubblici
(niente loopback, rete privata, link-local/metadata cloud, multicast, riservati)
e solo con schema http/https. Il controllo si applica:
  - all'URL in ingresso (API) prima di creare il job;
  - a ogni connessione del browser durante il crawl, tramite il proxy di uscita
    (egress_proxy.py) che si collega SOLO agli IP verificati: copre redirect,
    sotto-risorse, iframe e DNS rebinding;
  - alle richieste httpx ausiliarie (robots.txt, feed, readme dei plugin), con
    ogni redirect rivalidato. Qui resta una piccola finestra di DNS rebinding tra
    controllo e connessione: un firewall di uscita in produzione la chiude.

Per sviluppo e test locali: SITEIQ_ALLOW_PRIVATE_TARGETS=1 disattiva il blocco
degli IP privati (lo schema resta comunque limitato a http/https).
"""
from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import env_bool
from app.i18n import DEFAULT_LOCALE, t

ALLOWED_SCHEMES = ("http", "https")
MAX_URL_LENGTH = 2048
_DNS_TTL_S = 60


class BlockedTarget(ValueError):
    """URL non ammesso (schema, host non risolvibile o IP non pubblico).

    `key` indica il motivo (catalogo: errors.target.<key>); str(e) è nel locale
    di default per i log, localized(locale) per le risposte al client."""

    def __init__(self, key: str, **params):
        self.key = key
        self.params = params
        super().__init__(t(DEFAULT_LOCALE, f"errors.target.{key}", **params))

    def localized(self, locale: str) -> str:
        return t(locale, f"errors.target.{self.key}", **self.params)


def allow_private_targets() -> bool:
    return env_bool("SITEIQ_ALLOW_PRIVATE_TARGETS")


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _parse(url: str):
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LENGTH:
        raise BlockedTarget("empty_or_too_long")
    if any(ch.isspace() or ord(ch) < 32 for ch in url) or any(ch in url for ch in '<>"'):
        raise BlockedTarget("bad_characters")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedTarget("scheme")
    if not parts.hostname:
        raise BlockedTarget("no_host")
    return url, parts


class TargetGuard:
    """Verifica host/URL con una piccola cache DNS (una istanza per crawl)."""

    def __init__(self, allow_private: bool | None = None):
        self.allow_private = allow_private_targets() if allow_private is None else allow_private
        self._cache: dict[str, tuple[float, list[str], str | None]] = {}

    def resolve(self, host: str) -> list[str]:
        """IP di `host` ammessi dalla policy; solleva BlockedTarget altrimenti.
        Il proxy di uscita si collega a QUESTI IP, non a una nuova risoluzione."""
        host = host.strip("[]")
        now = time.monotonic()
        hit = self._cache.get(host)
        if hit and now - hit[0] < _DNS_TTL_S:
            _, ips, reason = hit
        else:
            ips = self._lookup(host)
            reason = ("unresolvable" if not ips
                      else None if self.allow_private else self._policy_reason(host, ips))
            self._cache[host] = (now, ips, reason)
        if reason:
            raise BlockedTarget(reason, host=host)
        return ips

    def check_host(self, host: str) -> None:
        """Solleva BlockedTarget se `host` non risolve SOLO a IP pubblici."""
        self.resolve(host)

    @staticmethod
    def _lookup(host: str) -> list[str]:
        try:
            return [str(ipaddress.ip_address(host))]
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except OSError:
            return []
        return list(dict.fromkeys(info[4][0].split("%")[0] for info in infos))

    @staticmethod
    def _policy_reason(host: str, ips: list[str]) -> str | None:
        """None se tutti gli IP sono pubblici, altrimenti la chiave del motivo."""
        if all(is_public_ip(ipaddress.ip_address(ip)) for ip in ips):
            return None
        return "not_public"

    def validate_url(self, url: str) -> str:
        """Ritorna l'URL ripulito o solleva BlockedTarget."""
        url, parts = _parse(url)
        self.check_host(parts.hostname)
        return url

    def get(self, url: str, *, timeout: float, headers: dict | None = None,
            max_redirects: int = 5) -> httpx.Response:
        """GET httpx che rivalida ogni hop di redirect."""
        current = self.validate_url(url)
        with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as client:
            for _ in range(max_redirects + 1):
                resp = client.get(current)
                if not resp.is_redirect:
                    return resp
                location = resp.headers.get("location")
                if not location:
                    return resp
                current = self.validate_url(urljoin(current, location))
        raise BlockedTarget("too_many_redirects")


def validate_target_url(url: str) -> str:
    """Validazione per le API: solleva BlockedTarget con un messaggio leggibile."""
    return TargetGuard().validate_url(url)
