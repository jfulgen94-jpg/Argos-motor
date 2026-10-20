"""
Canarios por fuente en SANDBOX/REPLAY: miden qué descubre y qué promueve cada fuente y alertan cuando algo es anómalo.

Un canario NUNCA hace tráfico real: exige un runner en modo SANDBOX/TEST (el que construye ``make_sandbox_runner`` con HTTP de
replay). Por fuente: descubre candidatos, los pasa por preflight → runner → CAS → manifiesto/catálogo/UoW, actualiza el
Coverage Ledger (si se da uno) y produce un informe estructurado (JSON-serializable).

Contadores: ``found`` candidatos descubiertos · ``valid`` contenido que pasó la validación (COMPLETED, SKIPPED_ALREADY_PRESENT o
UNCONFIRMED conservada) · ``promoted`` COMPLETED + SKIPPED_ALREADY_PRESENT · ``skipped`` SKIPPED_ALREADY_PRESENT · ``errors``
FAILED (sin conflictos) · ``conflicts`` CONFLICT o FAILED/INVARIANT_VIOLATION · ``quarantined`` · ``needs_review`` ·
``unexpected`` encontrados fuera del universo esperado · ``missing_expected`` esperados que no aparecieron.
Una fuente que falla NO interrumpe a las demás ni corrompe el ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from mod_01_ingestion.src.unified.coverage_ledger import (
    CoverageKey, CoverageLedger, LedgerStatus, record_outcome)
from mod_01_ingestion.src.unified.domain.models import utc_now
from mod_01_ingestion.src.unified.domain.errors import sanitize_message
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.sandbox_replay import SANDBOX_MODES, SandboxViolation

ERROR, WARN = "ERROR", "WARN"


@dataclass(frozen=True)
class Alert:
    code: str
    severity: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "message": self.message, "details": dict(self.details)}


@dataclass
class CanaryReport:
    authority: str
    country_code: Optional[str]
    mode: str
    started_at: str
    finished_at: str = ""
    counts: Dict[str, int] = field(default_factory=dict)
    alerts: List[Alert] = field(default_factory=list)
    items: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Optional[Dict[str, Any]] = None
    discovery_error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not any(a.severity == ERROR for a in self.alerts)

    def to_dict(self) -> Dict[str, Any]:
        return {"authority": self.authority, "country_code": self.country_code, "mode": self.mode, "ok": self.ok,
                "started_at": self.started_at, "finished_at": self.finished_at, "counts": dict(self.counts),
                "alerts": [a.to_dict() for a in self.alerts], "items": list(self.items), "coverage": self.coverage,
                "discovery_error": self.discovery_error}


@dataclass
class CanarySuite:
    reports: Dict[str, CanaryReport] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.reports.values())

    @property
    def alerts(self) -> List[Alert]:
        return [a for r in self.reports.values() for a in r.alerts]

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "reports": {k: r.to_dict() for k, r in sorted(self.reports.items())}}


def _classify(outcome) -> Dict[str, bool]:
    st, kl, vs = outcome.state, outcome.error_class, getattr(outcome, "version_status", None)
    conflict = st == "CONFLICT" or (st == "FAILED" and kl == "INVARIANT_VIOLATION")
    unconfirmed = st == "MANUAL_REVIEW" and vs == "UNCONFIRMED"
    return {"promoted": st in ("COMPLETED", "SKIPPED_ALREADY_PRESENT"), "skipped": st == "SKIPPED_ALREADY_PRESENT",
            "valid": st in ("COMPLETED", "SKIPPED_ALREADY_PRESENT") or unconfirmed, "conflicts": conflict,
            "errors": st == "FAILED" and not conflict, "quarantined": st == "QUARANTINED",
            "needs_review": (st == "MANUAL_REVIEW" and not unconfirmed) or st == "RECOVERY_REQUIRED"}


def run_canary(runner, authority: str, *, expected: Iterable[CoverageKey] = (), ledger: Optional[CoverageLedger] = None,
               expect_results: bool = True, min_found: int = 1, max_error_ratio: float = 0.5,
               clock: Callable[[], str] = utc_now) -> CanaryReport:
    mode = runner.run.mode
    if mode not in SANDBOX_MODES:
        raise SandboxViolation(f"un canario solo corre en {[m.value for m in SANDBOX_MODES]}, no en {mode.value}")
    authority = str(authority).upper()
    exp = [k for k in expected if k.authority == authority]
    rep = CanaryReport(authority=authority, country_code=None, mode=mode.value, started_at=clock())
    ledger_errors: List[str] = []

    def guarded(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as ex:                       # un fallo del ledger no interrumpe al canario ni a otras fuentes
            ledger_errors.append(sanitize_message(f"{type(ex).__name__}: {ex}"))
            return None

    adapter = runner.adapters.get(authority)
    if adapter is None:
        rep.alerts.append(Alert("UNKNOWN_AUTHORITY", ERROR, f"autoridad sin adapter: {authority}"))
        rep.finished_at = clock()
        return rep
    rep.country_code = getattr(adapter, "country_code", None)
    if ledger is not None and exp:
        guarded(ledger.expect, exp, run_id=runner.run.run_id)

    try:
        candidates = list(adapter.discover(DiscoveryRequest(authority=authority)))
    except Exception as ex:
        rep.discovery_error = sanitize_message(f"{type(ex).__name__}: {ex}")
        rep.alerts.append(Alert("DISCOVERY_FAILED", ERROR, "el descubrimiento de la fuente falló", {"error": rep.discovery_error}))
        for k in exp:
            if ledger is not None:
                guarded(ledger.record, k, LedgerStatus.SOURCE_UNAVAILABLE, reason="DISCOVERY_FAILED",
                        evidence={"method": "canary_discovery", "ref": type(ex).__name__}, run_id=runner.run.run_id)
        return _finish(runner, rep, exp, ledger, ledger_errors, clock, found_keys=set())

    counts = {k: 0 for k in ("found", "valid", "promoted", "skipped", "errors", "conflicts", "quarantined", "needs_review",
                              "unexpected", "missing_expected")}
    found_keys = set()
    expected_set = {k.as_tuple() for k in exp}
    for cand in candidates:
        outcome = runner.process_candidate(adapter, cand)
        key = CoverageKey.from_candidate(cand)
        found_keys.add(key.as_tuple())
        counts["found"] += 1
        flags = _classify(outcome)
        for name, hit in flags.items():
            counts[name] += int(hit)
        if expected_set and key.as_tuple() not in expected_set:
            counts["unexpected"] += 1
        res = guarded(record_outcome, ledger, cand, outcome, run_id=runner.run.run_id) if ledger is not None else None
        rep.items.append({"document_id": cand.document_id, "issuer_id": cand.issuer_id, "fiscal_year": cand.fiscal_year,
                          "doc_type": cand.doc_type, "state": outcome.state, "error_class": outcome.error_class,
                          "attempt_id": getattr(outcome, "attempt_id", None),
                          "ledger_status": res.status.value if res is not None else None})
    missing = sorted(k.as_tuple() for k in exp if k.as_tuple() not in found_keys)
    counts["missing_expected"] = len(missing)
    rep.counts = counts

    if counts["found"] == 0 and expect_results:
        rep.alerts.append(Alert("ZERO_RESULTS_UNEXPECTED", ERROR, "la fuente no devolvió ningún candidato", {"expected": len(exp)}))
    elif 0 < counts["found"] < min_found:
        rep.alerts.append(Alert("FOUND_BELOW_MINIMUM", WARN, f"se esperaban al menos {min_found} candidatos",
                                {"found": counts["found"], "min_found": min_found}))
    if counts["found"] > 0 and counts["promoted"] == 0:
        rep.alerts.append(Alert("ZERO_PROMOTED", ERROR, "hay candidatos pero ninguno quedó promovido", {"found": counts["found"]}))
    if counts["conflicts"]:
        rep.alerts.append(Alert("CONFLICTS", ERROR, "hay conflictos de contenido o identidad", {"count": counts["conflicts"]}))
    if counts["found"] and (counts["errors"] + counts["quarantined"]) / counts["found"] > max_error_ratio:
        rep.alerts.append(Alert("HIGH_ERROR_RATE", ERROR, "la proporción de errores supera el umbral",
                                {"ratio": round((counts["errors"] + counts["quarantined"]) / counts["found"], 3),
                                 "threshold": max_error_ratio}))
    if counts["needs_review"]:
        rep.alerts.append(Alert("NEEDS_REVIEW", WARN, "hay documentos pendientes de revisión", {"count": counts["needs_review"]}))
    if missing:
        rep.alerts.append(Alert("MISSING_EXPECTED", WARN, "faltan documentos del universo esperado",
                                {"count": len(missing), "keys": [list(k) for k in missing[:50]]}))
    if counts["unexpected"]:
        rep.alerts.append(Alert("UNEXPECTED_FOUND", WARN, "se encontraron documentos fuera del universo esperado",
                                {"count": counts["unexpected"]}))
    return _finish(runner, rep, exp, ledger, ledger_errors, clock, found_keys)


def _finish(runner, rep: CanaryReport, exp, ledger, ledger_errors, clock, found_keys) -> CanaryReport:
    if ledger is not None:
        try:
            rep.coverage = ledger.coverage(authority=rep.authority).to_dict()
        except Exception as ex:
            ledger_errors.append(sanitize_message(f"{type(ex).__name__}: {ex}"))
    if ledger_errors:
        rep.alerts.append(Alert("LEDGER_ERROR", ERROR, "el ledger no pudo registrar el estado", {"errors": ledger_errors[:5]}))
    rep.finished_at = clock()
    try:
        runner.telemetry.emit("canary_report", None, "canary", authority=rep.authority, ok=rep.ok, counts=rep.counts,
                              alerts=[a.code for a in rep.alerts])
    except Exception:
        pass
    return rep


def run_canaries(runner, authorities: Iterable[str], *, expected: Optional[Mapping[str, Iterable[CoverageKey]]] = None,
                 ledger: Optional[CoverageLedger] = None, **kw) -> CanarySuite:
    """Un canario por fuente, aislados entre sí: la excepción de una se convierte en una alerta de ESA fuente."""
    suite = CanarySuite()
    expected = expected or {}
    for a in authorities:
        a = str(a).upper()
        try:
            suite.reports[a] = run_canary(runner, a, expected=expected.get(a, ()), ledger=ledger, **kw)
        except SandboxViolation:
            raise                                      # un modo no seguro es un error de configuración, no de la fuente
        except Exception as ex:
            r = CanaryReport(authority=a, country_code=None, mode=runner.run.mode.value, started_at=utc_now(),
                             finished_at=utc_now())
            r.alerts.append(Alert("CANARY_CRASHED", ERROR, "el canario de la fuente falló",
                                  {"error": sanitize_message(f"{type(ex).__name__}: {ex}")}))
            suite.reports[a] = r
    return suite
