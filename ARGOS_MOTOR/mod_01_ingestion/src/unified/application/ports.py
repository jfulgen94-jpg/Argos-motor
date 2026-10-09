"""Puertos de aplicación (U1): contratos hacia infraestructura. Solo Protocols; no importan implementaciones
nacionales, runners de ``descarga/``, httpx, requests, duckdb ni arelle."""
from __future__ import annotations

from pathlib import Path
from typing import ContextManager, Optional, Protocol, runtime_checkable

from mod_01_ingestion.src.unified.domain.models import (
    CatalogRecord, DownloadRequest, DownloadResult, JobContext, ManifestRecord, PromotionResult)


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
    """Contrato objetivo (ADR-004). Hoy el 2PC manifiesto/catálogo está inline en ``UnifiedIngestRunner``."""

    def stage(self, manifest: ManifestRecord, catalog: CatalogRecord) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
