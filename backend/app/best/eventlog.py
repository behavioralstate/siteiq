"""Log degli eventi BEST in memoria, con iscrizioni per lo stream SSE.

Nessuna persistenza: finestra recente limitata per numero (SITEIQ_BEST_MAX_EVENTS)
e per età (SITEIQ_JOB_TTL_S, come i job). La spec non garantisce replay da
GET /events, quindi una finestra è conforme. Il cursore di paginazione è il
numero di sequenza interno, opaco per il client.

publish() è chiamato dai thread dei job; gli iscritti SSE vivono sul loop
asyncio di uvicorn e ricevono gli eventi tramite call_soon_threadsafe.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from app.config import env_int


def parse_time(value: str) -> datetime:
    """ISO 8601 -> datetime con fuso (accetta il suffisso Z)."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp senza fuso orario")
    return dt


@dataclass
class EventFilter:
    type: str | None = None
    correlation_id: str | None = None
    source: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None

    def matches(self, event: dict, when: datetime) -> bool:
        return ((self.type is None or event["type"] == self.type)
                and (self.correlation_id is None or event.get("correlationid") == self.correlation_id)
                and (self.source is None or event["source"] == self.source)
                and (self.time_from is None or when >= self.time_from)
                and (self.time_to is None or when <= self.time_to))


@dataclass(eq=False)
class Subscription:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    filter: EventFilter = field(default_factory=EventFilter)


class EventLog:
    def __init__(self, max_events: int | None = None, ttl_s: int | None = None):
        self.max_events = max_events or env_int("SITEIQ_BEST_MAX_EVENTS", 5000)
        self.ttl_s = ttl_s or env_int("SITEIQ_JOB_TTL_S", 3600)
        self._items: deque[tuple[int, float, datetime, dict]] = deque()
        self._seq = 0
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.ttl_s
        while self._items and (len(self._items) > self.max_events or self._items[0][1] < cutoff):
            self._items.popleft()

    def publish(self, event: dict) -> None:
        when = parse_time(event["time"])
        with self._lock:
            self._seq += 1
            self._items.append((self._seq, time.monotonic(), when, event))
            self._prune()
            subs = [s for s in self._subs if s.filter.matches(event, when)]
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
            except RuntimeError:
                pass  # loop chiuso: l'iscritto se n'è andato

    def query(self, flt: EventFilter, limit: int, after: int = 0) -> tuple[list[dict], str | None]:
        """Eventi in ordine di pubblicazione dopo il cursore `after`."""
        with self._lock:
            self._prune()
            matched = [(seq, ev) for seq, _, when, ev in self._items
                       if seq > after and flt.matches(ev, when)]
        page = matched[:limit]
        next_cursor = str(page[-1][0]) if len(matched) > limit else None
        return [ev for _, ev in page], next_cursor

    def after_event_id(self, event_id: str, flt: EventFilter) -> list[dict]:
        """Per Last-Event-ID: gli eventi pubblicati dopo quello indicato."""
        with self._lock:
            seq = next((s for s, _, _, ev in self._items if ev["id"] == event_id), None)
            if seq is None:
                return []
            return [ev for s, _, when, ev in self._items if s > seq and flt.matches(ev, when)]

    def subscribe(self, loop: asyncio.AbstractEventLoop, flt: EventFilter) -> Subscription:
        sub = Subscription(loop, asyncio.Queue(), flt)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


log = EventLog()
