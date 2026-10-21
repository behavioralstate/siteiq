"""Catalogo BEST: comandi, eventi e query, uno per file JSON Schema.

Fonte unica: schema/best/{commands|events|queries}/{schema}/{version}.json.
Il catalogo servito (GET /commands, GET /queries) e i documenti schema
(GET /{kind}/{schema}/{version}) derivano da questi file, quindi non possono
divergere. Gli URI assoluti (dataschema) partono da PUBLIC_BASE_URL.
"""
from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from app.config import REPO_ROOT, env_str

SCHEMA_ROOT = REPO_ROOT / "schema" / "best"
KINDS = ("commands", "events", "queries")
# sviluppo/test: nessun dominio da rovesciare; non implica alcun dominio reale
FALLBACK_SERVICE_ID = "local.siteiq.analysis"


@dataclass(frozen=True)
class Entry:
    kind: str
    schema: str      # kebab-case, segmento {schema} del path
    version: str
    document: dict   # il documento servito a GET /{kind}/{schema}/{version}

    @property
    def type_name(self) -> str | None:
        """Tipo PascalCase dell'envelope (comandi ed eventi)."""
        return self.document.get("commandType") or self.document.get("title")

    @property
    def description(self) -> str:
        return self.document.get("description", "")


@lru_cache(maxsize=None)
def entries(kind: str) -> tuple[Entry, ...]:
    out = []
    for path in sorted((SCHEMA_ROOT / kind).glob("*/*.json")):
        with open(path, encoding="utf-8") as f:
            out.append(Entry(kind, path.parent.name, path.stem, json.load(f)))
    return tuple(out)


def get(kind: str, schema: str, version: str) -> Entry | None:
    return next((e for e in entries(kind) if e.schema == schema and e.version == version), None)


def latest(kind: str, schema: str) -> Entry | None:
    found = [e for e in entries(kind) if e.schema == schema]
    return max(found, key=lambda e: tuple(int(x) for x in e.version.split("."))) if found else None


def by_type(kind: str, type_name: str) -> Entry | None:
    return next((e for e in entries(kind) if e.type_name == type_name), None)


def _public_base_url() -> str:
    return env_str("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"


def endpoint() -> str:
    """http.endpoint del servizio: indirizzo pubblico + /best."""
    return _public_base_url().rstrip("/") + "/best"


def service_id() -> str:
    """Chiave del servizio nel manifest: il nome a dominio dell'indirizzo
    pubblico rovesciato + ".analysis" (siteiq.example.org ->
    org.example.siteiq.analysis), come raccomanda la spec. Senza un nome a
    dominio da rovesciare (localhost, IP, nome senza punti) una chiave neutra."""
    host = (urlsplit(_public_base_url()).hostname or "").rstrip(".").lower()
    try:
        ipaddress.ip_address(host)
        host = ""
    except ValueError:
        pass
    if "." not in host or host.endswith(".localhost"):
        return FALLBACK_SERVICE_ID
    try:
        host = host.encode("idna").decode("ascii")  # nomi internazionali in forma A-label
    except UnicodeError:
        return FALLBACK_SERVICE_ID
    return ".".join(reversed(host.split("."))) + ".analysis"


def dataschema(entry: Entry) -> str:
    return f"{endpoint()}/{entry.kind}/{entry.schema}/{entry.version}"


def command_catalogue() -> dict:
    return {"commands": [
        {"schema": e.schema, "version": e.version, "commandType": e.type_name,
         "dataschema": dataschema(e), "description": e.description}
        for e in entries("commands")
    ]}


def query_catalogue() -> dict:
    return {"queries": [
        {"schema": e.schema, "version": e.version, "dataschema": dataschema(e),
         "description": e.description}
        for e in entries("queries")
    ]}
