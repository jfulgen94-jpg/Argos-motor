"""
U5D — Raíz de datos UNIFICADA y aislada del árbol legacy.

* Por defecto apunta a ``D:\\ARGOS_DATA\\unified_pilot`` (solo para PILOT/LIVE). Nunca se crea ni se escribe al importar, al
  construir ni al validar: solo ``UnifiedDataRoot.initialize()`` crea la estructura y el marcador ``.argos_unified_root``.
* Validación estricta (``validate_unified_root``): ruta absoluta; no puede ser, contener ni estar dentro de una raíz legacy
  (``ARGOS_DATA_ROOT``, ``D:/ARGOS_DATA`` y su ``raw/``, ``ARGOS_MOTOR/data``); y en TEST/SANDBOX solo se admite bajo un directorio
  temporal autorizado y NUNCA bajo una ruta operativa.
* Estructura: raw/ cas/ cas_pins/ manifests/ versions/ catalog/ reports/ (+ staging, quarantine_unified, locks, telemetry).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mod_01_ingestion.src.unified.config import DataLayout, PathPolicyError
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.legacy_exclusions import ENV_VAR, MARKER, clear_cache
from mod_01_ingestion.src.unified.persistence_guard import (is_authorized_sandbox_location, is_operational_location,
                                                           _ARGOS_MOTOR, _norm, _resolved)

DEFAULT_PILOT_ROOT = Path("D:/ARGOS_DATA/unified_pilot")
STRUCTURE = ("raw", "cas", "cas_pins", "manifests", "versions", "catalog", "reports")


def _both(*paths) -> set:
    return {x for r in paths for x in (_norm(r), _resolved(r))}


def legacy_trees() -> set:
    """Árboles legacy DENTRO de los cuales el raíz unificado nunca puede estar (ni ser, ni contener)."""
    paths = ["D:/ARGOS_DATA/raw", str(_ARGOS_MOTOR / "data")]
    env = os.environ.get("ARGOS_DATA_ROOT")
    if env:
        paths.append(str(Path(env) / "raw"))
    return _both(*paths)


def legacy_data_roots() -> set:
    """Raíces de datos legacy: el raíz unificado puede colgar de ellas (hermano de ``raw/``), pero nunca ser una de ellas."""
    paths = ["D:/ARGOS_DATA"] + ([os.environ["ARGOS_DATA_ROOT"]] if os.environ.get("ARGOS_DATA_ROOT") else [])
    return _both(*paths)


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip(chr(92) + "/") + os.sep)


def validate_unified_root(path, mode, *, authorized_sandbox_roots: Iterable = ()) -> Path:
    """Valida ``path`` como raíz unificado para ``mode``. No toca el disco (solo resuelve rutas)."""
    try:
        mode = ExecutionMode(mode)
    except ValueError:
        raise PathPolicyError(f"modo no soportado: {mode!r}")
    p = Path(path)
    if not p.is_absolute():
        raise PathPolicyError(f"el raíz unificado debe ser absoluto: {p}")
    cands = _both(p)
    for tree in legacy_trees():
        if any(_within(c, tree) or _within(tree, c) for c in cands):
            raise PathPolicyError(f"el raíz unificado no puede ser, contener ni estar dentro del árbol legacy: {p} ({tree})")
    for root in legacy_data_roots():
        if any(_within(root, c) for c in cands):
            raise PathPolicyError(f"el raíz unificado no puede ser ni contener la raíz de datos legacy: {p} ({root})")
    if mode in (ExecutionMode.TEST, ExecutionMode.SANDBOX):
        if is_operational_location(p) or not is_authorized_sandbox_location(p, authorized_sandbox_roots):
            raise PathPolicyError(f"en {mode.value} el raíz unificado debe estar en un directorio temporal autorizado y nunca "
                                  f"en una ruta operativa: {p}")
    return p


def resolve_unified_root(explicit=None, mode=ExecutionMode.PILOT, *, authorized_sandbox_roots: Iterable = ()) -> "UnifiedDataRoot":
    """Argumento explícito > ``ARGOS_UNIFIED_ROOT`` > raíz por defecto (SOLO en PILOT/LIVE; en TEST/SANDBOX es obligatorio
    indicar uno explícito en un directorio temporal)."""
    mode = ExecutionMode(mode)
    value = explicit or os.environ.get(ENV_VAR)
    if not value:
        if mode in (ExecutionMode.TEST, ExecutionMode.SANDBOX):
            raise PathPolicyError(f"{mode.value}: hay que indicar el raíz unificado (no hay valor por defecto en pruebas)")
        value = DEFAULT_PILOT_ROOT
    return UnifiedDataRoot(validate_unified_root(value, mode, authorized_sandbox_roots=authorized_sandbox_roots), mode)


@dataclass(frozen=True)
class UnifiedDataRoot:
    path: Path
    mode: ExecutionMode = ExecutionMode.PILOT

    @property
    def layout(self) -> DataLayout:
        return DataLayout(self.path)

    @property
    def marker(self) -> Path:
        return self.path / MARKER

    def directories(self) -> list:
        lay = self.layout
        return [lay.raw, lay.cas, lay.cas_pins, lay.manifests, lay.versions, lay.catalog_db.parent, lay.reports]

    def is_initialized(self) -> bool:
        return self.marker.is_file()

    def initialize(self) -> "UnifiedDataRoot":
        """Crea la estructura y el marcador. Es la ÚNICA operación de esta clase que escribe en disco."""
        validate_unified_root(self.path, self.mode)
        self.path.mkdir(parents=True, exist_ok=True)
        for d in self.directories() + [self.layout.staging, self.layout.quarantine, self.layout.locks, self.layout.telemetry]:
            d.mkdir(parents=True, exist_ok=True)
        if not self.marker.exists():
            self.marker.write_text(json.dumps({"kind": "ARGOS_UNIFIED_ROOT", "schema": "1", "structure": list(STRUCTURE)},
                                              sort_keys=True), encoding="utf-8")
        clear_cache()
        return self
