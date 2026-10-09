"""Protocols de dominio (U1): contratos que dependen solo de modelos de dominio. Sin implementaciones.

- ``SourceAdapter`` aquí es el contrato CANÓNICO (U2): ``name``, ``allowed_domains``, ``discover`` -> Iterable,
  ``fetch_metadata``. ``unified.source_adapter.SourceAdapter`` (Fase 4) es ahora un reexport deprecado de este
  mismo objeto. Los adapters no declaran métodos de infraestructura (descarga, raw, DuckDB, manifiestos, CAS,
  cuarentena). ``source_type`` lo declaran las clases concretas (``BaseSourceAdapter``), no es parte del Protocol.
- Los puertos de infraestructura (CAS, locks, rate limiting, UoW, descarga) están en ``application.ports``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from mod_01_ingestion.src.unified.domain.models import (
    DiscoveryRequest, DocumentCandidate, JobContext, QuarantineRecord, SourceAttestation, SourceMetadata,
    ValidationResult, DownloadResult)


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    allowed_domains: tuple

    def discover(self, request: DiscoveryRequest) -> Iterable[DocumentCandidate]: ...

    def fetch_metadata(self, candidate: DocumentCandidate) -> SourceMetadata: ...


@runtime_checkable
class DiscoveryStrategy(Protocol):
    name: str

    def discover(self, request: DiscoveryRequest) -> Iterable[DocumentCandidate]: ...


@runtime_checkable
class CandidateQueue(Protocol):
    def put(self, candidate: DocumentCandidate) -> bool:
        """Encola; devuelve False si el candidato canónico ya estaba (deduplicación por document_id)."""

    def drain(self) -> Iterable[DocumentCandidate]: ...

    def __len__(self) -> int: ...


@runtime_checkable
class KnownDocumentRepository(Protocol):
    def get(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Mapping[str, Any]]:
        """Registro conocido (manifiesto comprometido) o None. Firma alineada con ``ManifestRepository.get``."""


@runtime_checkable
class ValidationService(Protocol):
    def validate(self, staged_path: Path, metadata: SourceMetadata, doc_type: Optional[str] = None) -> ValidationResult: ...


@runtime_checkable
class AttestationService(Protocol):
    def attest(self, candidate: DocumentCandidate, metadata: SourceMetadata,
               download: DownloadResult) -> Optional[SourceAttestation]:
        """Atestación oficial del contenido descargado, o None si la autoridad no publica hash."""


@runtime_checkable
class QuarantineService(Protocol):
    def quarantine(self, staged_path: Path, job: JobContext, error_class: str,
                   reasons: Sequence[str], sha256: Optional[str]) -> QuarantineRecord: ...


@runtime_checkable
class TelemetrySink(Protocol):
    def emit(self, event: str, job: Optional[JobContext], component: str, **fields: Any) -> Mapping[str, Any]: ...
