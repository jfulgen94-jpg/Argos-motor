"""
Modelos canónicos del flujo unificado de ingesta — FACHADA DE COMPATIBILIDAD (U1).

Desde U1 las definiciones viven en ``unified.domain`` (``domain.models``, ``domain.enums``). Este módulo
reexporta exactamente los mismos objetos para que los imports de Fases 4-6 sigan funcionando.
``JobState`` es un alias de ``PipelineStatus`` (superconjunto con los mismos valores previos);
``JobOutcome`` de ``ingest_runner`` es alias de ``PipelineResult``.
"""
from __future__ import annotations

from mod_01_ingestion.src.unified.domain.enums import ErrorClass, PipelineStatus as JobState
from mod_01_ingestion.src.unified.domain.models import (  # noqa: F401
    SCHEMA_VERSION, CatalogRecord, DiscoveryRequest, DocumentCandidate, DownloadRequest, DownloadResult,
    JobContext, ManifestRecord, PipelineResult, PromotionResult, QuarantineRecord, RunContext,
    SourceAttestation, SourceMetadata, ValidationResult, _Serializable, build_document_id, new_run_id,
    utc_now)

__all__ = [
    "SCHEMA_VERSION", "CatalogRecord", "DiscoveryRequest", "DocumentCandidate", "DownloadRequest",
    "DownloadResult", "ErrorClass", "JobContext", "JobState", "ManifestRecord", "PipelineResult",
    "PromotionResult", "QuarantineRecord", "RunContext", "SourceAttestation", "SourceMetadata",
    "ValidationResult", "build_document_id", "new_run_id", "utc_now",
]
