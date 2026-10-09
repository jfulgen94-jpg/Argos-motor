"""
FASE 4 / DEFECT-10 — Resolución de rutas sin hardcodeo relativo.

Orden: argumento explícito > ``ARGOS_DATA_ROOT`` > error. No existe default silencioso
al CWD: un flujo migrado nunca escribe en ``data/raw`` relativo.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mod_01_ingestion.src.unified.models import ErrorClass


class PathPolicyError(Exception):
    error_class = ErrorClass.PATH_VIOLATION.value


@dataclass(frozen=True)
class DataLayout:
    root: Path

    @property
    def raw(self) -> Path: return self.root / "raw"
    @property
    def cas(self) -> Path: return self.root / "cas"
    @property
    def staging(self) -> Path: return self.root / "staging" / "unified"
    @property
    def quarantine(self) -> Path: return self.root / "quarantine_unified"
    @property
    def manifests(self) -> Path: return self.root / "manifests"
    @property
    def telemetry(self) -> Path: return self.root / "telemetry"
    @property
    def locks(self) -> Path: return self.root / "locks"
    @property
    def catalog_db(self) -> Path: return self.root / "catalog" / "unified_catalog.duckdb"

    def ensure(self) -> "DataLayout":
        for p in (self.raw, self.cas, self.staging, self.quarantine, self.manifests,
                  self.telemetry, self.locks, self.catalog_db.parent):
            p.mkdir(parents=True, exist_ok=True)
        return self

    def assert_inside(self, path: Path) -> Path:
        """Garantiza que ``path`` resida dentro del data root (cero escrituras externas)."""
        resolved = Path(path).resolve()
        root = self.root.resolve()
        if resolved != root and root not in resolved.parents:
            raise PathPolicyError(f"Ruta fuera del data root: {resolved} (root={root})")
        return resolved


def resolve_layout(data_root: Optional[os.PathLike] = None) -> DataLayout:
    value = data_root or os.environ.get("ARGOS_DATA_ROOT")
    if not value:
        raise PathPolicyError("ARGOS_DATA_ROOT no definido y no se indicó data_root explícito.")
    path = Path(value)
    if not path.is_absolute():
        raise PathPolicyError(f"data_root debe ser absoluto: {path}")
    return DataLayout(path)
