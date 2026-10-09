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
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.models import (
    CatalogRecord, JobContext, ManifestRecord, QuarantineRecord, SCHEMA_VERSION)

MANIFEST_REQUIRED = tuple(ManifestRecord.__dataclass_fields__.keys())  # type: ignore[attr-defined]
_MANIFEST_MANDATORY = (
    "manifest_version", "document_id", "run_id", "job_id", "authority", "country_code", "issuer_id",
    "fiscal_year", "doc_type", "source_url", "raw_path", "cas_path", "sha256", "size_bytes", "status",
    "completeness_status")


class ManifestValidationError(Exception):
    pass


def validate_manifest_dict(data: Dict[str, Any]) -> None:
    missing = [k for k in _MANIFEST_MANDATORY if data.get(k) in (None, "")]
    if missing:
        raise ManifestValidationError(f"Manifiesto incompleto, faltan: {missing}")
    if len(str(data["sha256"])) != 64:
        raise ManifestValidationError("sha256 inválido")


class ManifestRepository:
    def __init__(self, layout: DataLayout):
        self.layout = layout

    def path_for(self, authority: str, fiscal_year: int, document_id: str) -> Path:
        return self.layout.manifests / authority / str(fiscal_year) / f"{document_id}.json"

    def get(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Dict[str, Any]]:
        p = self.path_for(authority, fiscal_year, document_id)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def stage(self, rec: ManifestRecord) -> Path:
        data = rec.to_dict()
        validate_manifest_dict(data)
        final = self.path_for(rec.authority, rec.fiscal_year, rec.document_id)
        final.parent.mkdir(parents=True, exist_ok=True)
        pending = final.with_name(final.name + ".pending")
        with open(pending, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return pending

    def commit(self, pending: Path) -> Path:
        pending = Path(pending)
        final = pending.with_name(pending.name[:-len(".pending")])
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

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._exec(self.DDL)

    def _exec(self, sql: str, params: Iterable[Any] = ()):
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
