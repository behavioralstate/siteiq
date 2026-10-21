"""Rate limit in memoria (finestra scorrevole) per gli endpoint pubblici.

Un solo processo uvicorn: lo stato non è condiviso tra worker né sopravvive ai
riavvii, sufficiente per frenare abusi (email-bombing via /api/lead, scansioni
a raffica). Dietro nginx avviare uvicorn con --proxy-headers e
--forwarded-allow-ips, altrimenti l'IP del client è quello del proxy.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Registra un tentativo per `key`; False se il limite è già raggiunto."""
        if self.limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:
                self._prune(now)
            return True

    def _prune(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window_s]:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
