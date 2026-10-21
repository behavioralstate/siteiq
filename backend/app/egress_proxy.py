"""Proxy di uscita per il browser del crawler (protezione SSRF).

Chromium viene avviato con questo proxy: OGNI connessione (navigazioni, redirect,
sotto-risorse, iframe, worker) passa da qui. Per ogni richiesta il proxy risolve
l'host, verifica gli IP con TargetGuard e si collega all'IP già verificato: così
niente redirect "dimenticati" e niente DNS rebinding tra controllo e connessione.

Supporta CONNECT (HTTPS, tunnel cifrato end-to-end, nessuna ispezione TLS) e
richieste HTTP in chiaro con URI assoluto. Un'istanza per crawl, su 127.0.0.1
con porta effimera.
"""
from __future__ import annotations

import logging
import select
import socket
import socketserver
import threading
from urllib.parse import urlsplit

from app.netguard import BlockedTarget, TargetGuard

log = logging.getLogger(__name__)

MAX_HEAD_BYTES = 64 * 1024
CONNECT_TIMEOUT_S = 10
IDLE_TIMEOUT_S = 60
_HOP_HEADERS = {b"proxy-connection", b"proxy-authorization", b"connection", b"keep-alive"}


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    """Legge fino a fine header; ritorna (head, byte già letti del body)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
        if len(buf) > MAX_HEAD_BYTES:
            raise ValueError("header troppo grandi")
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def _split_host_port(hostport: str, default_port: int) -> tuple[str, int]:
    if hostport.startswith("["):
        host, _, rest = hostport[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default_port
    host, sep, port = hostport.rpartition(":")
    if not sep:
        return hostport, default_port
    return host, int(port)


def _relay(a: socket.socket, b: socket.socket) -> None:
    """Copia byte in entrambe le direzioni finché uno dei due lati chiude."""
    socks = [a, b]
    while True:
        readable, _, errored = select.select(socks, [], socks, IDLE_TIMEOUT_S)
        if errored or not readable:
            return
        for s in readable:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)


class _Handler(socketserver.BaseRequestHandler):
    server: "_ProxyServer"

    def handle(self) -> None:
        client = self.request
        client.settimeout(IDLE_TIMEOUT_S)
        upstream = None
        try:
            head, rest = _read_head(client)
            if not head:
                return
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("latin-1").split(" ", 2)
            if method.upper() == "CONNECT":
                host, port = _split_host_port(target, 443)
                upstream = self._connect(host, port)
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    raise BlockedTarget("bad_proxy_request")
                upstream = self._connect(parts.hostname, parts.port or 80)
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                out = [f"{method} {path} {version}".encode("latin-1")]
                out += [h for h in lines[1:] if h.split(b":", 1)[0].strip().lower() not in _HOP_HEADERS]
                out.append(b"Connection: close")
                upstream.sendall(b"\r\n".join(out) + b"\r\n\r\n" + rest)
            _relay(client, upstream)
        except BlockedTarget as e:
            log.info("proxy: bloccato %s", e)
            self._refuse(client, b"403 Forbidden")
        except (OSError, ValueError) as e:
            log.debug("proxy: errore %s", e)
            self._refuse(client, b"502 Bad Gateway")
        finally:
            if upstream is not None:
                upstream.close()

    def _connect(self, host: str, port: int) -> socket.socket:
        last_err: OSError | None = None
        for ip in self.server.guard.resolve(host):
            try:
                return socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT_S)
            except OSError as e:
                last_err = e
        raise last_err or OSError(f"connessione a {host} fallita")

    @staticmethod
    def _refuse(client: socket.socket, status: bytes) -> None:
        try:
            client.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass


class _ProxyServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, guard: TargetGuard):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.guard = guard


class EgressProxy:
    """Context manager: avvia il proxy e ne espone l'URL per Playwright."""

    def __init__(self, guard: TargetGuard):
        self._server = _ProxyServer(guard)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="siteiq-egress-proxy", daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "EgressProxy":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()
