"""Route HTTP della superficie BEST (transport HTTP della spec).

/.well-known/best è alla radice; tutto il resto sotto http.endpoint = <base>/best.
Le route sono escluse da /openapi.json: la spec vieta una seconda descrizione
della superficie BEST oltre al manifest.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator

from app.best import catalogue, service
from app.best.errors import BestError
from app.best.eventlog import EventFilter, log, parse_time
from app.config import env_int
from app.i18n import request_locale
from app.jobs import QueueFull
from app.netguard import BlockedTarget, validate_target_url
from app.ratelimit import SlidingWindowLimiter

router = APIRouter(include_in_schema=False)

BEST_VERSION = "0.9.17"
SERVICE_VERSION = "1.0.0"
MAX_BODY_BYTES = 64 * 1024
MAX_EVENTS_PAGE = 500
SSE_KEEPALIVE_S = 15
SSE_IDLE_CLOSE_S = 300
TERMINAL_EVENTS = {"SiteAnalysisCompleted", "SiteAnalysisFailed"}
COMMAND_MEDIA_TYPES = ("application/cloudevents+json", "application/json")

command_limiter = SlidingWindowLimiter(env_int("SITEIQ_BEST_COMMANDS_PER_IP_PER_HOUR", 10), 3600)


def _schema_response(document: dict) -> JSONResponse:
    return JSONResponse(document, media_type="application/schema+json")


def _capability(name: str, service: str, description: str,
                endpoints: list[tuple[str, str, str]], **extra) -> dict:
    short = name.rsplit(".", 1)[1]
    return {
        "name": name,
        "version": BEST_VERSION,
        "service": service,
        "description": description,
        "spec": f"https://behavioralstate.io/specs/agents/{short}",
        "schema": f"https://behavioralstate.io/v1/schemas/agents/{short}.json",
        "endpoints": [{"method": m, "path": p, "description": d} for m, p, d in endpoints],
        **extra,
    }


def manifest() -> dict:
    service = catalogue.service_id()
    return {"best": {
        "version": BEST_VERSION,
        "services": {service: {
            "version": SERVICE_VERSION,
            "description": ("SiteIQ analyses a public web page for security headers, SEO, "
                            "accessibility, performance and known WordPress vulnerabilities, "
                            "and reports deterministic findings. Analyses are public and kept "
                            "for about an hour."),
            "authentication": {"type": "none"},
            "http": {"endpoint": catalogue.endpoint()},
        }},
        "capabilities": [
            _capability("io.best.agents.commands", service, "Request a site analysis.", [
                ("GET", "/commands", "Command catalogue"),
                ("POST", "/commands", "Send a command"),
                ("GET", "/commands/{schema}/{version}", "Command schema document"),
            ]),
            _capability("io.best.agents.events", service, "Progress and outcome of each analysis.", [
                ("GET", "/events", "Recent events, filterable and paginated"),
                ("GET", "/events/stream", "Live events over Server-Sent Events"),
                ("GET", "/events/{schema}/{version}", "Event schema document"),
            ], push={"sse": True}),
            _capability("io.best.agents.queries", service, "Read the state, findings and raw "
                        "measurements of an analysis.", [
                ("GET", "/queries", "Query catalogue"),
                ("GET", "/queries/{schema}/{version}", "Query schema document"),
                ("GET", "/queries/{schema}", "Execute a query"),
            ]),
        ],
    }}


@router.get("/.well-known/best")
def well_known() -> JSONResponse:
    return JSONResponse(manifest())


# --------------------------------------------------------------- commands --

@router.get("/best/commands")
def command_catalogue() -> dict:
    return catalogue.command_catalogue()


@router.get("/best/commands/{schema}/{version}")
def command_schema(schema: str, version: str) -> JSONResponse:
    entry = catalogue.get("commands", schema, version)
    if entry is None:
        raise BestError(404, "SCHEMA_NOT_FOUND", "command_schema_not_found", schema=schema, version=version)
    return _schema_response(entry.document)


def _invalid(field: str, msg: str) -> BestError:
    return BestError(400, "INVALID_ENVELOPE", msg, {"field": field}, field=field)


def _parse_envelope(raw: bytes) -> dict:
    try:
        env = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise BestError(400, "INVALID_JSON", "invalid_json")
    if not isinstance(env, dict):
        raise BestError(400, "INVALID_ENVELOPE", "not_an_object")
    if env.get("specversion") != "1.0":
        raise _invalid("specversion", "specversion")
    for name in ("id", "source", "type", "dataschema", "time"):
        value = env.get(name)
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise _invalid(name, "field_required")
    if env.get("datacontenttype") != "application/json":
        raise _invalid("datacontenttype", "datacontenttype")
    if not isinstance(env.get("data"), dict):
        raise _invalid("data", "data_object")
    corr = env.get("correlationid")
    if corr is not None and (not isinstance(corr, str) or not corr or len(corr) > 256):
        raise _invalid("correlationid", "field_required")
    try:
        parse_time(env["time"])
    except ValueError:
        raise _invalid("time", "timestamp")
    return env


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/best/commands")
async def send_command(request: Request) -> JSONResponse:
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media not in COMMAND_MEDIA_TYPES:
        raise BestError(415, "UNSUPPORTED_MEDIA_TYPE", "unsupported_media_type",
                        {"accepted": list(COMMAND_MEDIA_TYPES)})
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise BestError(413, "PAYLOAD_TOO_LARGE", "payload_too_large", max=MAX_BODY_BYTES)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise BestError(413, "PAYLOAD_TOO_LARGE", "payload_too_large", max=MAX_BODY_BYTES)

    env = _parse_envelope(raw)
    entry = catalogue.by_type("commands", env["type"])
    if entry is None:
        raise BestError(400, "UNKNOWN_COMMAND_TYPE", "unknown_command_type",
                        {"accepted": [e.type_name for e in catalogue.entries("commands")]},
                        type=env["type"])
    # dataschema è solo informativo (mai scaricato): deve indicare questo comando
    if not env["dataschema"].rstrip("/").endswith(f"/commands/{entry.schema}/{entry.version}"):
        raise BestError(400, "DATASCHEMA_MISMATCH", "dataschema_mismatch",
                        {"expected": catalogue.dataschema(entry)})
    errors = sorted(Draft202012Validator(entry.document).iter_errors(env["data"]), key=str)
    if errors:
        raise BestError(400, "INVALID_DATA", "invalid_data", {
            "errors": [{"path": "/".join(map(str, e.absolute_path)), "message": e.message}
                       for e in errors[:5]],
        })
    loc = request_locale(request)
    try:
        url = validate_target_url(env["data"]["url"])
    except BlockedTarget as e:
        raise BestError(400, "TARGET_NOT_ALLOWED", "target_not_allowed", {"field": "data.url"},
                        reason=e.localized(loc))

    correlation_id = env.get("correlationid") or env["id"]
    fingerprint = service.idempotency.fingerprint(env)
    seen = service.idempotency.reserve(env["id"], fingerprint, correlation_id)
    if seen is not None:
        if seen[0] != fingerprint:
            raise BestError(409, "DUPLICATE_COMMAND_ID", "duplicate_command_id")
        return JSONResponse({"id": env["id"], "correlationId": seen[1]}, status_code=202)

    if not command_limiter.allow(_client_ip(request)):
        service.idempotency.release(env["id"])
        raise BestError(429, "RATE_LIMITED", "rate_limited", headers={"Retry-After": "600"})
    try:
        service.submit_analysis(url, correlation_id, locale=loc)
    except QueueFull:
        service.idempotency.release(env["id"])
        raise BestError(503, "QUEUE_FULL", "queue_full", headers={"Retry-After": "60"})
    # 202 e non 201: il comando è accodato in memoria, non in modo durevole
    return JSONResponse({"id": env["id"], "correlationId": correlation_id}, status_code=202)


# ----------------------------------------------------------------- events --

def _event_filter(request: Request) -> EventFilter:
    q = request.query_params
    flt = EventFilter(type=q.get("type") or None, correlation_id=q.get("correlationId") or None,
                      source=q.get("source") or None)
    for name, attr in (("from", "time_from"), ("to", "time_to")):
        if q.get(name):
            try:
                setattr(flt, attr, parse_time(q[name]))
            except ValueError:
                raise BestError(400, "INVALID_PARAMETERS", "parameter_timestamp",
                                {"parameter": name}, parameter=name)
    return flt


@router.get("/best/events")
def list_events(request: Request) -> dict:
    flt = _event_filter(request)
    q = request.query_params
    try:
        limit = int(q.get("limit", 100))
        after = int(q.get("after", 0))
        if limit < 1 or after < 0:
            raise ValueError
    except ValueError:
        raise BestError(400, "INVALID_PARAMETERS", "paging")
    events, next_cursor = log.query(flt, min(limit, MAX_EVENTS_PAGE), after)
    body = {"events": events}
    if next_cursor:
        body["nextCursor"] = next_cursor
    return body


def _sse(event: dict) -> str:
    return f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/best/events/stream")
async def stream_events(request: Request) -> StreamingResponse:
    flt = _event_filter(request)
    sub = log.subscribe(asyncio.get_running_loop(), flt)
    last_id = request.headers.get("last-event-id")
    backlog = log.after_event_id(last_id, flt) if last_id else []
    # con un filtro per correlazione lo stream si chiude all'esito finale
    close_on_terminal = flt.correlation_id is not None

    async def generate():
        sent: set[str] = set()
        idle = 0.0
        try:
            for ev in backlog:
                sent.add(ev["id"])
                yield _sse(ev)
                if close_on_terminal and ev["type"] in TERMINAL_EVENTS:
                    return
            yield ": connected\n\n"
            while idle < SSE_IDLE_CLOSE_S:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=SSE_KEEPALIVE_S)
                except asyncio.TimeoutError:
                    idle += SSE_KEEPALIVE_S
                    yield ": keepalive\n\n"
                    continue
                idle = 0.0
                if ev["id"] in sent:
                    continue
                sent.add(ev["id"])
                yield _sse(ev)
                if close_on_terminal and ev["type"] in TERMINAL_EVENTS:
                    return
        finally:
            log.unsubscribe(sub)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/best/events/{schema}/{version}")
def event_schema(schema: str, version: str) -> JSONResponse:
    entry = catalogue.get("events", schema, version)
    if entry is None:
        raise BestError(404, "SCHEMA_NOT_FOUND", "event_schema_not_found", schema=schema, version=version)
    return _schema_response(entry.document)


# ---------------------------------------------------------------- queries --

QUERY_HANDLERS = {
    "get-analysis": lambda job, p, loc: service.analysis_view(job, loc),
    "get-findings": lambda job, p, loc: service.findings_view(job, loc, p.get("category"), p.get("status")),
    "get-crawl-report": lambda job, p, loc: service.crawl_view(job),
}


@router.get("/best/queries")
def query_catalogue() -> dict:
    return catalogue.query_catalogue()


@router.get("/best/queries/{schema}/{version}")
def query_schema(schema: str, version: str) -> JSONResponse:
    entry = catalogue.get("queries", schema, version)
    if entry is None:
        raise BestError(404, "SCHEMA_NOT_FOUND", "query_schema_not_found", schema=schema, version=version)
    return _schema_response(entry.document)


@router.get("/best/queries/{schema}")
def execute_query(schema: str, request: Request) -> dict:
    entry = catalogue.latest("queries", schema)
    if entry is None or schema not in QUERY_HANDLERS:
        raise BestError(404, "SCHEMA_NOT_FOUND", "query_not_found", schema=schema)
    params = dict(request.query_params)
    errors = list(Draft202012Validator(entry.document["parameters"]).iter_errors(params))
    if errors:
        raise BestError(400, "INVALID_PARAMETERS", "query_parameters", {
            "errors": [{"path": "/".join(map(str, e.absolute_path)), "message": e.message}
                       for e in errors[:5]],
        })
    job = service.best_job(params["analysisId"])
    if job is None:
        raise BestError(404, "ANALYSIS_NOT_FOUND", "analysis_not_found")
    return QUERY_HANDLERS[schema](job, params, request_locale(request))


# ------------------------------------------------------------------ other --

@router.api_route("/best", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/best/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def not_found(request: Request) -> None:
    raise BestError(404, "NOT_FOUND", "route_not_found", method=request.method, path=request.url.path)
