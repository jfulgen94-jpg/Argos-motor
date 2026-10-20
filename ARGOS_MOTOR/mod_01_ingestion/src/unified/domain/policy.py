"""Política LIVE/PILOT contra datos simulados (ADR-005). Funciones puras, sin I/O.

Desviación documentada de la estructura autorizada: archivo propio ``policy.py`` (el guard no es un modelo
ni un enum y no existía una capacidad equivalente en ``unified``).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, SourceType
from mod_01_ingestion.src.unified.domain.errors import SimulatedDataRejectedError, UnsupportedExecutionModeError
from mod_01_ingestion.src.unified.domain.models import is_placeholder_hash

SIMULATED_DOC_TYPE = "SIMULATED"
_FAKE_FLAGS = ("simulated", "simulate", "fixture", "fake", "synthetic", "mock", "is_fixture", "is_simulated")
_FORBIDDEN_STATUS = frozenset({"SIMULATED"})


def _flags_set(mapping: Optional[Mapping[str, Any]]) -> list:
    if not mapping:
        return []
    return [k for k in _FAKE_FLAGS if mapping.get(k)]


def _coerce_mode(mode) -> ExecutionMode:
    try:
        return ExecutionMode(mode)
    except ValueError:
        raise UnsupportedExecutionModeError(f"modo de ejecución no soportado: {mode!r}")


def _simulated_markers(doc_type, source_type, sha256s: Iterable, flags, status=None) -> list:
    found = []
    if str(doc_type or "").upper() == SIMULATED_DOC_TYPE:
        found.append("doc_type=SIMULATED")
    if source_type is not None and SourceType(source_type) is SourceType.SIMULATED:
        found.append("source_type=SIMULATED")
    if any(is_placeholder_hash(h) for h in sha256s):
        found.append("sha256=placeholder")
    if str(status or "").upper() in _FORBIDDEN_STATUS:
        found.append("status=SIMULATED")
    found += [f"flag:{f}" for f in _flags_set(flags)]
    return found


def assert_not_simulated(candidate, mode, *, pilot_fixture_allowlist: frozenset = frozenset()) -> None:
    """Rechaza marcadores de simulación; NO exige source_type declarado (apto para el runner de Fases 4-6).

    TEST y SANDBOX admiten fixtures. LIVE rechaza todo marcador. PILOT es igual de estricto que LIVE salvo
    ``TEST_FIXTURE`` cuyo ``document_id`` figure en ``pilot_fixture_allowlist`` (configuración inmutable).
    """
    mode = _coerce_mode(mode)
    if mode in (ExecutionMode.TEST, ExecutionMode.SANDBOX):
        return
    markers = _simulated_markers(candidate.doc_type, candidate.source_type,
                                 [candidate.expected_sha256], candidate.extra)
    if candidate.source_type is SourceType.TEST_FIXTURE:
        if mode is ExecutionMode.PILOT and candidate.document_id in pilot_fixture_allowlist:
            markers = [m for m in markers if not m.startswith("flag:")]
        else:
            markers.append("source_type=TEST_FIXTURE")
    if markers:
        raise SimulatedDataRejectedError(
            f"candidato {candidate.document_id} rechazado en modo {mode.value}: {', '.join(markers)}")


def assert_candidate_allowed(candidate, mode, *, pilot_fixture_allowlist: frozenset = frozenset()) -> None:
    """Política completa: además exige ``source_type`` declarado en LIVE y PILOT (fail-closed)."""
    mode = _coerce_mode(mode)
    assert_not_simulated(candidate, mode, pilot_fixture_allowlist=pilot_fixture_allowlist)
    if mode in (ExecutionMode.LIVE, ExecutionMode.PILOT) and candidate.source_type is None:
        raise SimulatedDataRejectedError(
            f"candidato {candidate.document_id} sin source_type declarado: no admitido en {mode.value}")


def manifest_simulation_markers(record) -> list:
    """Marcadores de simulación de un manifiesto/catálogo (``ManifestRecord``, ``CatalogRecord`` o dict)."""
    get = record.get if isinstance(record, Mapping) else (lambda k, d=None: getattr(record, k, d))
    return _simulated_markers(get("doc_type"), get("source_type"), [get("sha256")], get("extra"), get("status"))


def assert_manifest_allowed(record, mode) -> None:
    """Barrera para manifiestos (``ManifestRecord`` o dict con las claves de ``MANIFEST_CNMV_<año>.json``)."""
    mode = _coerce_mode(mode)
    if mode in (ExecutionMode.TEST, ExecutionMode.SANDBOX):
        return
    markers = manifest_simulation_markers(record)
    if markers:
        get = record.get if isinstance(record, Mapping) else (lambda k, d=None: getattr(record, k, d))
        ident = get("document_id") or get("ticker") or "?"
        raise SimulatedDataRejectedError(f"manifiesto {ident} rechazado en modo {mode.value}: {', '.join(markers)}")


def validate_allowed_domains(domains) -> None:
    """Un adapter debe declarar dominios explícitos: hosts en minúsculas, sin comodines, esquema, ruta ni puerto."""
    from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
    if not isinstance(domains, tuple) or not domains:
        raise DomainValidationError("allowed_domains debe ser una tupla no vacía")
    for d in domains:
        if (not isinstance(d, str) or d != d.strip().lower() or "*" in d or "/" in d or ":" in d or " " in d
                or d.startswith(".") or d.endswith(".") or "." not in d):
            raise DomainValidationError(f"dominio no válido en allowed_domains: {d!r}")


def is_host_allowed(host: str, domains) -> bool:
    """Coincidencia exacta o subdominio con frontera de punto (``a.cnmv.es`` sí; ``evilcnmv.es`` no)."""
    h = (host or "").strip().lower().rstrip(".")
    return bool(h) and any(h == d or h.endswith("." + d) for d in domains)
