"""
FASE 4 / DEFECT-09 — Limitador de concurrencia y cadencia por dominio.

Cada host tiene (a) un máximo de peticiones simultáneas y (b) un intervalo mínimo entre
inicios de petición. Reloj y sleep inyectables para pruebas deterministas.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, Optional
from urllib.parse import urlparse


class DomainRateLimiter:
    def __init__(self, max_concurrent_per_domain: int = 2, min_interval_s: float = 0.5,
                 overrides: Optional[Dict[str, Dict[str, float]]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.default_conc = max_concurrent_per_domain
        self.default_interval = min_interval_s
        self.overrides = overrides or {}
        self._clock = clock
        self._sleep = sleep
        self._sems: Dict[str, threading.BoundedSemaphore] = {}
        self._last_start: Dict[str, float] = {}
        self._mu = threading.Lock()
        self.peak_concurrency: Dict[str, int] = {}
        self._active: Dict[str, int] = {}

    @staticmethod
    def domain_of(url: str) -> str:
        return (urlparse(url).hostname or "unknown").lower()

    def _conf(self, domain: str):
        o = self.overrides.get(domain, {})
        return int(o.get("max_concurrent", self.default_conc)), float(o.get("min_interval_s", self.default_interval))

    @contextmanager
    def slot(self, url: str) -> Iterator[str]:
        domain = self.domain_of(url)
        conc, interval = self._conf(domain)
        with self._mu:
            sem = self._sems.setdefault(domain, threading.BoundedSemaphore(conc))
        with sem:
            with self._mu:
                now = self._clock()
                last = self._last_start.get(domain)
                wait = 0.0 if last is None else max(0.0, interval - (now - last))
                self._last_start[domain] = now + wait
            if wait > 0:
                self._sleep(wait)
            with self._mu:
                self._active[domain] = self._active.get(domain, 0) + 1
                self.peak_concurrency[domain] = max(self.peak_concurrency.get(domain, 0), self._active[domain])
            try:
                yield domain
            finally:
                with self._mu:
                    self._active[domain] -= 1
