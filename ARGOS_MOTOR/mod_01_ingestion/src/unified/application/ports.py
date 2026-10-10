"""Puertos de aplicación (U1): contratos hacia infraestructura. Solo Protocols; no importan implementaciones
nacionales, runners de ``descarga/``, httpx, requests, duckdb ni arelle."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, ContextManager, Optional, Protocol, Tuple, runtime_checkable

from mod_01_ingestion.src.unified.domain.models import (
    CatalogRecord, DownloadRequest, DownloadResult, JobContext, ManifestRecord, PromotionResult, UnitOfWorkOutcome)


@runtime_checkable
class DownloadServicePort(Protocol):
    def download(self, req: DownloadRequest, job: Optional[JobContext] = None) -> DownloadResult: ...


@runtime_checkable
class ContentAddressedStore(Protocol):
    def blob_path(self, sha256: str) -> Path: ...

    def promote(self, staged_path: Path, sha256: str, raw_relpath: Path) -> PromotionResult: ...

    def rollback(self, promo: PromotionResult) -> None: ...

    def verify(self, sha256: str, raw_path: Path) -> bool: ...


@runtime_checkable
class LockManager(Protocol):
    def acquire(self, key: str, timeout_s: float = 30.0) -> ContextManager[Path]: ...


@runtime_checkable
class DomainRateLimiter(Protocol):
    def slot(self, url: str) -> ContextManager[str]: ...


@runtime_checkable
class ManifestCatalogUnitOfWork(Protocol):
    """Contrato (ADR-004, U4): prepare manifest -> prepare catalog -> validate invariant -> commit | compensate.
    Implementación: ``unified.unit_of_work.ManifestCatalogUnitOfWork``. Una instancia por documento."""

    def prepare_manifest(self, manifest: ManifestRecord) -> Optional[UnitOfWorkOutcome]: ...

    def prepare_catalog(self, catalog_record: CatalogRecord) -> Optional[UnitOfWorkOutcome]: ...

    def validate_invariant(self) -> Tuple[str, ...]: ...

    def commit(self) -> UnitOfWorkOutcome: ...

    def compensate(self) -> UnitOfWorkOutcome: ...

    def execute(self, manifest: ManifestRecord, catalog_record: CatalogRecord,
                on_phase: Optional[Callable[[str], None]] = None) -> UnitOfWorkOutcome: ...
