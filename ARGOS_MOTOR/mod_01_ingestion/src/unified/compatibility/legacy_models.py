"""Mapeadores EXPLÍCITOS legacy -> dominio canónico (U1). Dirección única; sin alias silenciosos.

    mod_01_ingestion.src.models (legacy)  --mapper-->  unified.domain (canónico)

Conceptos con semántica distinta que NO se fusionan: ``PublicationRecord`` (publicación oficial descubierta)
se mapea a ``DocumentCandidate``; ``DocumentResource`` (recurso ya descargado) a ``DownloadResult``.
Cada mapper declara en ``LOSSY_FIELDS`` los campos que se pierden y exige los datos que el legacy no tiene.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from mod_01_ingestion.src.models import DocumentResource, IngestionMode, PublicationRecord
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, SourceType
from mod_01_ingestion.src.unified.domain.errors import CompatibilityMappingError, DomainValidationError
from mod_01_ingestion.src.unified.domain.models import DocumentCandidate, DownloadResult

LOSSY_FIELDS: Dict[str, tuple] = {
    "PublicationRecord->DocumentCandidate": (
        "publication_id", "publication_date", "isin", "discovered_at", "status",
        "reporting_period (mes, si venía YYYY-MM; se conserva en extra['legacy_reporting_period'])"),
    "DocumentResource->DownloadResult": (
        "resource_id", "publication_id", "original_url", "local_path (-> staged_path)", "filename", "blob_path",
        "resource_role", "resource_type", "source_column", "parent_resource_id", "downloaded_at",
        "extraction_status", "validation_status", "completeness_status", "parser_compatibility",
        "redirect_chain", "extracted_files", "missing_dependencies"),
}

_YEAR = re.compile(r"^(\d{4})(?:-\d{2})?$")


def execution_mode_from_legacy(mode: str) -> ExecutionMode:
    """LIVE -> LIVE. FIXTURE -> TEST (fixture solo es admisible fuera de LIVE/PILOT)."""
    try:
        legacy = IngestionMode(mode)
    except ValueError:
        raise CompatibilityMappingError(f"IngestionMode legacy desconocido: {mode!r}")
    return ExecutionMode.LIVE if legacy is IngestionMode.LIVE else ExecutionMode.TEST


def publication_to_candidate(pub: PublicationRecord, *, authority: str, country_code: str,
                             source_type: Optional[SourceType] = None) -> DocumentCandidate:
    """``authority``, ``country_code`` y (idealmente) ``source_type`` NO existen en el legacy: se exigen aquí.
    Un registro legacy ``FIXTURE`` nunca puede declararse fuente oficial."""
    m = _YEAR.match(pub.reporting_period or "")
    if not m:
        raise CompatibilityMappingError(f"reporting_period no convertible a ejercicio: {pub.reporting_period!r}")
    mode = execution_mode_from_legacy(pub.mode)
    if mode is not ExecutionMode.LIVE:
        if source_type not in (None, SourceType.TEST_FIXTURE):
            raise CompatibilityMappingError("un PublicationRecord FIXTURE solo puede mapearse como TEST_FIXTURE")
        source_type = SourceType.TEST_FIXTURE
    try:
        return DocumentCandidate(
            authority=authority, country_code=country_code, issuer_id=pub.issuer_identifier,
            fiscal_year=int(m.group(1)), doc_type=pub.document_type, source_url=pub.official_record_url,
            issuer_name=pub.issuer_name, issuer_lei=pub.lei, ticker=pub.ticker,
            source_page_url=pub.source_page_url, source=pub.source, source_type=source_type,
            extra={"legacy_reporting_period": pub.reporting_period})
    except DomainValidationError as ex:
        raise CompatibilityMappingError(f"PublicationRecord {pub.publication_id} no mapeable: {ex}")


def resource_to_download_result(res: DocumentResource) -> DownloadResult:
    ok = res.error_code is None
    return DownloadResult(
        ok=ok, staged_path=res.local_path or None, sha256=res.sha256 or None, size_bytes=res.file_size_bytes,
        http_status=res.http_status, mime_type=res.mime_type or None, final_url=res.final_url or None,
        error_class=res.error_code, error_message=res.error_message)
