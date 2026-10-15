"""
U2 — Barrera de persistencia contra datos simulados (ADR-005).

Se aplica en la FRONTERA de escritura (``ManifestRepository.stage/commit``, ``CatalogRepository.upsert``,
``ContentAddressedRawStore.promote``) y no solo en el runner: ningún caller puede omitir la política.
Orden obligatorio: la validación ocurre ANTES de crear ficheros, tocar DuckDB, promover raw o enlazar CAS.

Reglas:
- Un SHA-256 vacío, inválido o placeholder se rechaza en TODOS los modos (el registro representa contenido).
- LIVE y PILOT rechazan cualquier marcador de simulación (doc_type/source_type/status SIMULATED, flags
  fake/synthetic/fixture/mock, ``CACHE_HIT`` con hash placeholder).
- TEST y SANDBOX solo admiten registros simulados si el destino está bajo un root temporal autorizado
  (directorio temporal del sistema o ``authorized_sandbox_roots``) y NO bajo un root operativo.
- Root operativo = ``D:/ARGOS_DATA``, ``ARGOS_MOTOR/data`` (raw histórico) y el valor de ``ARGOS_DATA_ROOT``.
  El CWD no se usa nunca como criterio de seguridad.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable, List

from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, SimulatedDataRejectedError
from mod_01_ingestion.src.unified.domain.models import validate_sha256
from mod_01_ingestion.src.unified.domain.policy import manifest_simulation_markers
from mod_01_ingestion.src.unified.domain.transport import assert_no_secret

_ARGOS_MOTOR = Path(__file__).resolve().parents[3]


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _resolved(p) -> str:
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except OSError:
        return _norm(p)


def operational_roots() -> List[str]:
    roots = ["D:/ARGOS_DATA", str(_ARGOS_MOTOR / "data")]
    env = os.environ.get("ARGOS_DATA_ROOT")
    if env:
        roots.append(env)
    return sorted({x for r in roots for x in (_norm(r), _resolved(r))})


def _is_under(path, root: str) -> bool:
    for candidate in {_norm(path), _resolved(path)}:
        if candidate == root or candidate.startswith(root.rstrip("\\/") + os.sep):
            return True
    return False


def is_operational_location(path) -> bool:
    return any(_is_under(path, r) for r in operational_roots())


def is_authorized_sandbox_location(path, authorized_sandbox_roots: Iterable = ()) -> bool:
    if is_operational_location(path):
        return False
    allowed = [_norm(tempfile.gettempdir()), _resolved(tempfile.gettempdir())]
    allowed += [x for r in authorized_sandbox_roots for x in (_norm(r), _resolved(r))]
    return any(_is_under(path, a) for a in allowed)


def assert_persistable(record, mode, location, *, authorized_sandbox_roots: Iterable = ()) -> None:
    """Lanza ``SimulatedDataRejectedError``/``DomainValidationError`` si ``record`` no puede persistirse."""
    try:
        mode = ExecutionMode(mode)
    except ValueError:
        from mod_01_ingestion.src.unified.domain.errors import UnsupportedExecutionModeError
        raise UnsupportedExecutionModeError(f"modo de ejecución no soportado: {mode!r}")
    assert_no_secret(record, "registro")        # CNMV-U4: ningún token/query/cookie/credencial/URL de transporte llega a disco
    get = record.get if hasattr(record, "get") else (lambda k, d=None: getattr(record, k, d))
    ident = get("document_id") or get("ticker") or "?"

    sha = get("sha256")
    try:
        validate_sha256(sha, "sha256", required=True)
    except DomainValidationError as ex:
        raise SimulatedDataRejectedError(f"registro {ident} no persistible: {ex}")

    markers = manifest_simulation_markers(record)
    if not markers:
        return
    if mode in (ExecutionMode.LIVE, ExecutionMode.PILOT):
        raise SimulatedDataRejectedError(f"registro {ident} rechazado en modo {mode.value}: {', '.join(markers)}")
    if not is_authorized_sandbox_location(location, authorized_sandbox_roots):
        raise SimulatedDataRejectedError(
            f"registro simulado {ident} solo puede persistirse bajo un root temporal autorizado ({', '.join(markers)})")
