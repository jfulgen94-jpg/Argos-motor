"""
Programación DETERMINISTA de canarios en SANDBOX. Sin hilos, sin daemon y sin dependencias externas: el llamador invoca
``tick()`` (o ``run_now()``) y el reloj es inyectable.

* Intervalo por fuente (segundos). La última ejecución sale del ALMACÉN de informes, de modo que sobrevive a un reinicio.
* ``tick(now)`` ejecuta, en orden alfabético, solo las fuentes vencidas; ``run_now`` fuerza las indicadas (disparador MANUAL).
* Aislamiento por fuente: la excepción de una se convierte en un informe ``CANARY_CRASHED`` de ESA fuente (se persiste) y las
  demás siguen; un fallo al persistir una no impide persistir las otras. Un modo no seguro (``SandboxViolation``) sí se propaga.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from mod_01_ingestion.src.unified.canary import CanaryReport, run_canaries
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore, RetentionPolicy, _parse
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.sandbox_replay import SANDBOX_MODES, SandboxViolation


class SchedulerError(DomainValidationError):
    pass


def iso_of(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


class CanaryScheduler:
    def __init__(self, runner, store: CanaryReportStore, *, intervals: Mapping[str, float],
                 ledger: Optional[CoverageLedger] = None, expected: Optional[Mapping[str, Iterable[CoverageKey]]] = None,
                 retention: Optional[RetentionPolicy] = None, clock: Callable[[], float] = time.time, **canary_kw):
        if runner.run.mode not in SANDBOX_MODES:
            raise SandboxViolation("el scheduler solo programa canarios en SANDBOX/TEST")
        self.runner, self.store, self.ledger, self.retention = runner, store, ledger, retention
        self.expected, self._clock, self._kw = dict(expected or {}), clock, canary_kw
        self.intervals: Dict[str, float] = {}
        for a, secs in intervals.items():
            a = str(a).upper()
            if a not in runner.adapters:
                raise SchedulerError(f"intervalo para una fuente sin adapter: {a}")
            if isinstance(secs, bool) or not isinstance(secs, (int, float)) or secs <= 0:
                raise SchedulerError(f"intervalo inválido para {a}: debe ser un número de segundos > 0")
            self.intervals[a] = float(secs)
        if not self.intervals:
            raise SchedulerError("se necesita al menos un intervalo")
        self.errors: List[Dict[str, str]] = []

    # ------------------------------------------------------------------ planificación
    def last_finished(self, authority: str) -> Optional[float]:
        rows = self.store.latest(authority, 1)
        return _parse(rows[0]["finished_at"]).timestamp() if rows else None

    def next_due(self, authority: str) -> Optional[float]:
        last = self.last_finished(authority)
        return None if last is None else last + self.intervals[authority.upper()]

    def due(self, now: Optional[float] = None) -> List[str]:
        now = self._clock() if now is None else now
        out = []
        for a in sorted(self.intervals):
            nd = self.next_due(a)
            if nd is None or now >= nd:
                out.append(a)
        return out

    # ------------------------------------------------------------------ ejecución
    def _run(self, authorities: List[str], now: float, trigger: str) -> List[Dict]:
        saved: List[Dict] = []
        if not authorities:
            return saved
        suite = run_canaries(self.runner, authorities, expected=self.expected, ledger=self.ledger,
                             clock=lambda: iso_of(now), **self._kw)
        for a in authorities:
            rep: CanaryReport = suite.reports[a]
            rep.finished_at = rep.finished_at or iso_of(now)
            try:
                saved.append({"authority": a, **self.store.save(rep, run_id=self.runner.run.run_id, trigger=trigger)})
            except Exception as ex:                       # un fallo al persistir una fuente no impide guardar las demás
                self.errors.append({"authority": a, "error": sanitize_message(f"{type(ex).__name__}: {ex}")})
                self.runner.telemetry.emit("canary_persist_failed", None, "canary_scheduler", authority=a,
                                           error=self.errors[-1]["error"])
        if self.retention is not None:
            try:
                self.store.apply_retention(self.retention, now=iso_of(now))
            except Exception as ex:
                self.errors.append({"authority": "*", "error": sanitize_message(f"retención: {type(ex).__name__}: {ex}")})
        self.runner.telemetry.emit("canary_scheduler_run", None, "canary_scheduler", trigger=trigger, authorities=authorities,
                                   saved=[s["report_id"] for s in saved])
        return saved

    def tick(self, now: Optional[float] = None) -> List[Dict]:
        now = self._clock() if now is None else now
        return self._run(self.due(now), now, "SCHEDULED")

    def run_now(self, authorities: Optional[Iterable[str]] = None, now: Optional[float] = None) -> List[Dict]:
        now = self._clock() if now is None else now
        targets = sorted({str(a).upper() for a in (authorities if authorities is not None else self.intervals)})
        unknown = [a for a in targets if a not in self.runner.adapters]
        if unknown:
            raise SchedulerError(f"fuentes sin adapter: {unknown}")
        return self._run(targets, now, "MANUAL")
