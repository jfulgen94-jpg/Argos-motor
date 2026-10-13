"""Puertos de aplicación (U1): contratos hacia infraestructura. Solo Protocols; no importan implementaciones
nacionales, runners de ``descarga/``, httpx, requests, duckdb ni arelle."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, ContextManager, Mapping, Optional, Protocol, Sequence, Tuple, runtime_checkable

from mod_01_ingestion.src.unified.domain.models import (
    CatalogRecord, DownloadRequest, DownloadResult, JobContext, ManifestRecord, PromotionResult, UnitOfWorkOutcome)


@runtime_checkable
class DownloadServicePort(Protocol):
    def download(self, req: DownloadRequest, job: Optional[JobContext] = None) -> DownloadResult: ...


@runtime_checkable
class ContentAddressedStore(Protocol):
    def blob_path(self, sha256: str) -> Path: ...

    def promote(self, staged_path: Path, sha256: str, raw_relpath: Optional[Path],
                create_view: bool = True) -> PromotionResult: ...

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


@runtime_checkable
class KnownDocumentLookup(Protocol):
    """U5A — Consultas de SOLO LECTURA sobre lo ya registrado. Sin escritura, sin red, sin crear directorios.
    Cada método devuelve mapeos mínimos con las claves que existan (``document_id``, ``sha256``, ``status``,
    ``authority``, ``fiscal_year``, ``doc_type``, ``issuer_id``, ``issuer_lei``, ``entity_id``, ``instrument_id``...)."""

    def get_manifest(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Mapping[str, Any]]: ...

    def get_catalog(self, document_id: str) -> Optional[Mapping[str, Any]]: ...

    def find_by_sha256(self, sha256: str) -> Sequence[Mapping[str, Any]]:
        """Registros de catálogo cuyo contenido tiene ese SHA-256."""

    def content_is_intact(self, record: Mapping[str, Any]) -> bool:
        """Verificación de solo lectura de que el contenido registrado existe y coincide con su hash."""


@runtime_checkable
class VersionedDocumentLookup(KnownDocumentLookup, Protocol):
    """U5B — Consultas de SOLO LECTURA sobre versiones de contenido (identidad lógica / slot). Cada entrada trae
    ``identity_key, sha256, status, version_ref, revision, document_id, contract_id, contract_version, normalizer_version``
    y banderas de consistencia ``table_present / sidecar_present / facts_match``."""

    def find_versions(self, identity_key: str) -> Sequence[Mapping[str, Any]]: ...

    def find_versions_by_sha256(self, sha256: str) -> Sequence[Mapping[str, Any]]: ...

    def blob_is_intact(self, sha256: str) -> bool:
        """El blob del CAS existe y su contenido coincide con el hash (sin depender de ninguna vista raw)."""
