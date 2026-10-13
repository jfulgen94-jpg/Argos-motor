"""
FASE 4 / DEFECT-06 — Repositorios de manifiesto y catálogo (con protocolo de dos fases) y
servicio de cuarentena.

ManifestRepository: ``stage`` (escribe ``.pending`` con fsync) -> ``commit`` (rename atómico)
| ``abort``. CatalogRepository: upsert idempotente por ``document_id`` en DuckDB.
Los datos operativos de producción (``stater_motor.duckdb``) NO se usan: el catálogo
unificado es una base nueva bajo ``<data_root>/catalog``.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.persistence_guard import assert_persistable
from mod_01_ingestion.src.unified.models import (
    CatalogRecord, JobContext, ManifestRecord, QuarantineRecord, SCHEMA_VERSION)

MANIFEST_REQUIRED = tuple(ManifestRecord.__dataclass_fields__.keys())  # type: ignore[attr-defined]
_MANIFEST_MANDATORY = (
    "manifest_version", "document_id", "run_id", "job_id", "authority", "country_code", "issuer_id",
    "fiscal_year", "doc_type", "source_url", "raw_path", "cas_path", "sha256", "size_bytes", "status",
    "completeness_status")


_DB_MUTEXES: Dict[str, "threading.RLock"] = {}
_DB_MUTEXES_GUARD = threading.Lock()


def db_mutex(path) -> "threading.RLock":
    """U3: exclusión mutua EN PROCESO por archivo DuckDB. Abrir ``duckdb.connect`` sobre el mismo archivo desde varios hilos a la
    vez da ``BinderError: Unique file handle conflict`` (no es ``IOException``). Entre PROCESOS sigue valiendo el reintento
    ante ``IOException``; esta función NO da ninguna garantía multiproceso."""
    key = os.path.normcase(os.path.abspath(str(path)))
    with _DB_MUTEXES_GUARD:
        return _DB_MUTEXES.setdefault(key, threading.RLock())


class ManifestValidationError(Exception):
    pass


class HistoricalOverwriteError(ManifestValidationError):
    """U3: un registro histórico (mismo document_id) NUNCA se sobrescribe con otro contenido (otro sha256)."""


_MODE_UNSET = object()


def _resolve_mode(mode, owner: str) -> ExecutionMode:
    """U2: el modo debe inyectarse. Transición explícita para callers de Fases 4-6: si se omite se aplica el
    valor MÁS restrictivo (LIVE) y se avisa; nunca se asume SANDBOX/TEST."""
    if mode is _MODE_UNSET:
        warnings.warn(f"{owner} creado sin ExecutionMode explícito: se aplica LIVE (el más restrictivo). "
                      "Pase mode=ExecutionMode.<...> (obligatorio en una versión futura).",
                      DeprecationWarning, stacklevel=3)
        return ExecutionMode.LIVE
    return ExecutionMode(mode)


def validate_manifest_dict(data: Dict[str, Any]) -> None:
    missing = [k for k in _MANIFEST_MANDATORY if data.get(k) in (None, "")]
    if missing:
        raise ManifestValidationError(f"Manifiesto incompleto, faltan: {missing}")
    if len(str(data["sha256"])) != 64:
        raise ManifestValidationError("sha256 inválido")


class ManifestRepository:
    def __init__(self, layout: DataLayout, mode=_MODE_UNSET, authorized_sandbox_roots=()):
        self.layout = layout
        self.mode = _resolve_mode(mode, "ManifestRepository")
        self.authorized_sandbox_roots = tuple(authorized_sandbox_roots)

    def path_for(self, authority: str, fiscal_year: int, document_id: str) -> Path:
        return self.layout.manifests / authority / str(fiscal_year) / f"{document_id}.json"

    def get(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Dict[str, Any]]:
        p = self.path_for(authority, fiscal_year, document_id)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def stage(self, rec: ManifestRecord) -> Path:
        # U2: la política se valida ANTES de crear ningún fichero (ADR-005).
        assert_persistable(rec, self.mode, self.layout.manifests,
                           authorized_sandbox_roots=self.authorized_sandbox_roots)
        data = rec.to_dict()
        validate_manifest_dict(data)
        final = self.path_for(rec.authority, rec.fiscal_year, rec.document_id)
        self._assert_no_overwrite(final, str(data["sha256"]))          # U3: antes de crear ningún fichero
        final.parent.mkdir(parents=True, exist_ok=True)
        pending = final.with_name(final.name + ".pending")
        with open(pending, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return pending

    @staticmethod
    def _assert_no_overwrite(final: Path, sha256: str) -> None:
        if final.exists():
            with open(final, "r", encoding="utf-8") as f:
                prev = json.load(f)
            if str(prev.get("sha256")) != sha256:
                raise HistoricalOverwriteError(
                    f"el manifiesto histórico {final.name} existe con otro sha256: no se sobrescribe")

    def commit(self, pending: Path) -> Path:
        pending = Path(pending)
        # U2: un .pending forjado o alterado tras el stage no puede promocionarse a manifiesto definitivo.
        with open(pending, "r", encoding="utf-8") as f:
            pending_data = json.load(f)
        assert_persistable(pending_data, self.mode, self.layout.manifests,
                           authorized_sandbox_roots=self.authorized_sandbox_roots)
        final = pending.with_name(pending.name[:-len(".pending")])
        self._assert_no_overwrite(final, str(pending_data.get("sha256")))      # U3: también en el commit (TOCTOU/forjado)
        os.replace(pending, final)
        return final

    def abort(self, pending: Path) -> None:
        Path(pending).unlink(missing_ok=True)


class CatalogRepository:
    """Catálogo DuckDB `unified_catalog` (upsert idempotente)."""

    DDL = """CREATE TABLE IF NOT EXISTS unified_catalog (
        document_id VARCHAR PRIMARY KEY, run_id VARCHAR, job_id VARCHAR, authority VARCHAR,
        country_code VARCHAR, issuer_id VARCHAR, fiscal_year INTEGER, doc_type VARCHAR,
        sha256 VARCHAR, raw_path VARCHAR, manifest_path VARCHAR, status VARCHAR,
        size_bytes BIGINT, cataloged_at VARCHAR)"""

    def __init__(self, db_path: Path, mode=_MODE_UNSET, authorized_sandbox_roots=()):
        self.db_path = Path(db_path)
        self.mode = _resolve_mode(mode, "CatalogRepository")
        self.authorized_sandbox_roots = tuple(authorized_sandbox_roots)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._exec(self.DDL)

    def _exec(self, sql: str, params: Iterable[Any] = ()):
        with db_mutex(self.db_path):
            return self._exec_unlocked(sql, params)

    def _exec_unlocked(self, sql: str, params: Iterable[Any] = ()):
        import time
        import duckdb
        last = None
        for _ in range(100):          # Fase 6: DuckDB admite un único escritor entre procesos; reintento corto
            try:
                con = duckdb.connect(str(self.db_path))
            except duckdb.IOException as ex:   # lock de archivo tomado por otro proceso
                last = ex
                time.sleep(0.05)
                continue
            try:
                return con.execute(sql, list(params)).fetchall()
            finally:
                con.close()
        raise last

    def upsert(self, rec: CatalogRecord) -> None:
        # U2: validar antes de abrir DuckDB.
        assert_persistable(rec, self.mode, self.db_path, authorized_sandbox_roots=self.authorized_sandbox_roots)
        prev = self._exec("SELECT sha256 FROM unified_catalog WHERE document_id = ?", [rec.document_id])
        if prev and str(prev[0][0]) != str(rec.sha256):             # U3: INSERT OR REPLACE no puede pisar historia
            raise HistoricalOverwriteError(f"el registro de catálogo {rec.document_id} existe con otro sha256: no se sobrescribe")
        d = asdict(rec)
        cols = list(d.keys())
        self._exec(
            f"INSERT OR REPLACE INTO unified_catalog ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [d[c] for c in cols])

    def delete(self, document_id: str) -> None:
        self._exec("DELETE FROM unified_catalog WHERE document_id = ?", [document_id])

    def get(self, document_id: str):
        rows = self._exec("SELECT document_id, sha256, status, raw_path FROM unified_catalog WHERE document_id = ?",
                          [document_id])
        return rows[0] if rows else None

    # --- U5A: consultas de SOLO LECTURA (conexión read_only; no crean el archivo ni toman el lock de escritura) ---
    def _query_ro(self, sql: str, params: Iterable[Any] = ()):
        with db_mutex(self.db_path):
            return self._query_ro_unlocked(sql, params)

    def _query_ro_unlocked(self, sql: str, params: Iterable[Any] = ()):
        import time
        import duckdb
        if not self.db_path.exists():
            return [], []
        last = None
        for _ in range(100):
            try:
                con = duckdb.connect(str(self.db_path), read_only=True)
            except duckdb.IOException as ex:      # otro proceso escribe: reintento corto
                last = ex
                time.sleep(0.05)
                continue
            try:
                cur = con.execute(sql, list(params))
                return [d[0] for d in cur.description], cur.fetchall()
            finally:
                con.close()
        raise last

    def get_record(self, document_id: str):
        """Fila completa del catálogo como dict (o None). Solo lectura."""
        cols, rows = self._query_ro("SELECT * FROM unified_catalog WHERE document_id = ?", [document_id])
        return dict(zip(cols, rows[0])) if rows else None

    def find_by_sha256(self, sha256: str):
        """Filas del catálogo con ese SHA-256 (orden determinista por document_id). Solo lectura."""
        cols, rows = self._query_ro("SELECT * FROM unified_catalog WHERE lower(sha256) = ? ORDER BY document_id",
                                    [str(sha256).lower()])
        return [dict(zip(cols, r)) for r in rows]

    def list_records(self):
        """U3: todas las filas del catálogo como dicts (SOLO LECTURA; vacío si no existe el archivo)."""
        cols, rows = self._query_ro("SELECT * FROM unified_catalog ORDER BY document_id")
        return [dict(zip(cols, r)) for r in rows]

    def count(self) -> int:
        return self._exec("SELECT count(*) FROM unified_catalog")[0][0]


class QuarantineService:
    def __init__(self, layout: DataLayout):
        self.layout = layout

    def quarantine(self, staged_path: Path, job: JobContext, error_class: str, reasons, sha256: Optional[str]) -> QuarantineRecord:
        qdir = self.layout.quarantine / job.run_id
        qdir.mkdir(parents=True, exist_ok=True)
        src = Path(staged_path)
        target = qdir / f"{job.document_id}__{src.name}"
        if src.exists():
            shutil.move(str(src), str(target))
        rec = QuarantineRecord(document_id=job.document_id, run_id=job.run_id, job_id=job.job_id,
                               quarantine_path=str(target), error_class=error_class,
                               reasons=list(reasons), sha256=sha256)
        with open(target.with_name(target.name + ".quarantine_reason.json"), "w", encoding="utf-8") as f:
            json.dump(rec.to_dict(), f, indent=2, ensure_ascii=False)
        return rec
