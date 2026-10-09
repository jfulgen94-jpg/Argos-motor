"""
FASE 4 — Modelos canónicos del flujo unificado de ingesta.

Fuente de verdad del contrato: audits/FASE4_UNIFICACION_2026-10-09/03_CANONICAL_MODELS.md.
Todos los modelos son serializables a JSON mediante ``to_dict()``.
Identificadores: ``run_id`` (ejecución), ``job_id`` (un documento dentro de una ejecución),
``document_id`` (determinista: AUTORIDAD_EMISOR_EJERCICIO_TIPO, estable entre ejecuciones).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def build_document_id(authority: str, issuer_id: str, fiscal_year: int, doc_type: str) -> str:
    raw = f"{authority}_{issuer_id}_{fiscal_year}_{doc_type}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)


class JobState(str, Enum):
    """Máquina de estados del contrato objetivo (Fase 3, 13_PROPOSED_TARGET_CONTRACT)."""
    DISCOVERED = "DISCOVERED"
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    VALIDATING = "VALIDATING"
    PROMOTING = "PROMOTING"
    MANIFESTING = "MANIFESTING"
    CATALOGING = "CATALOGING"
    COMPLETED = "COMPLETED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"


class ErrorClass(str, Enum):
    """Clasificación única de errores (idéntica para todas las autoridades)."""
    HTTP_TRANSIENT = "HTTP_TRANSIENT"          # 429 / 5xx agotados
    HTTP_PERMANENT = "HTTP_PERMANENT"          # 4xx no reintentable
    NETWORK = "NETWORK"                        # conexión caída
    TIMEOUT = "TIMEOUT"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    EMPTY_FILE = "EMPTY_FILE"
    CORRUPT_ARCHIVE = "CORRUPT_ARCHIVE"
    DISGUISED_HTML = "DISGUISED_HTML"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    LOCKED = "LOCKED"
    MANIFEST_FAILED = "MANIFEST_FAILED"
    CATALOG_FAILED = "CATALOG_FAILED"
    PATH_VIOLATION = "PATH_VIOLATION"
    UNKNOWN = "UNKNOWN"


class _Serializable:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass
class RunContext(_Serializable):
    run_id: str = field(default_factory=new_run_id)
    started_at: str = field(default_factory=utc_now)
    operator: str = "unified_ingest_runner"
    data_root: Optional[str] = None
    dry_run: bool = False
    schema_version: str = SCHEMA_VERSION


@dataclass
class JobContext(_Serializable):
    run_id: str
    job_id: str
    document_id: str
    authority: str
    attempt: int = 1

    @classmethod
    def for_candidate(cls, run: RunContext, seq: int, candidate: "DocumentCandidate") -> "JobContext":
        return cls(run_id=run.run_id, job_id=f"{run.run_id}:{seq:06d}",
                   document_id=candidate.document_id, authority=candidate.authority)


@dataclass
class DiscoveryRequest(_Serializable):
    authority: str
    fiscal_years: List[int] = field(default_factory=list)
    issuer_ids: List[str] = field(default_factory=list)
    doc_types: List[str] = field(default_factory=list)
    limit: Optional[int] = None


@dataclass
class DocumentCandidate(_Serializable):
    authority: str                 # CNMV, BAFIN, AMF, CONSOB, AFM, SEC
    country_code: str
    issuer_id: str                 # LEI / ticker / CIK (identificador estable del emisor)
    fiscal_year: int
    doc_type: str
    source_url: str
    issuer_name: Optional[str] = None
    issuer_lei: Optional[str] = None
    ticker: Optional[str] = None
    source_page_url: Optional[str] = None
    expected_kind: Optional[str] = None   # ZIP | PDF | XHTML | HTML | None (autodetectar)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def document_id(self) -> str:
        return build_document_id(self.authority, self.issuer_id, self.fiscal_year, self.doc_type)


@dataclass
class SourceMetadata(_Serializable):
    resolved_url: str
    file_name: str
    extension: str = ""
    expected_kind: Optional[str] = None
    expected_sha256: Optional[str] = None
    expected_size_bytes: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    authority_rules: Dict[str, Any] = field(default_factory=dict)  # reglas de validación específicas


@dataclass
class DownloadRequest(_Serializable):
    url: str
    staging_dir: str
    file_name: str
    expected_sha256: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    allow_resume: bool = True


@dataclass
class DownloadResult(_Serializable):
    ok: bool
    staged_path: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: int = 0
    http_status: Optional[int] = None
    mime_type: Optional[str] = None
    final_url: Optional[str] = None
    resumed: bool = False
    retries_taken: int = 0
    duration_s: float = 0.0
    error_class: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class ValidationResult(_Serializable):
    accepted: bool
    completeness_status: str
    detected_kind: str
    should_quarantine: bool
    reasons: List[str] = field(default_factory=list)
    error_class: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromotionResult(_Serializable):
    raw_path: str
    cas_path: str
    sha256: str
    size_bytes: int
    deduplicated: bool            # el blob ya existía en el CAS
    link_mode: str                # hardlink | copy


@dataclass
class QuarantineRecord(_Serializable):
    document_id: str
    run_id: str
    job_id: str
    quarantine_path: str
    error_class: str
    reasons: List[str]
    sha256: Optional[str] = None
    quarantined_at: str = field(default_factory=utc_now)


@dataclass
class ManifestRecord(_Serializable):
    """Esquema canónico único (03_MANIFEST_SCHEMA.json)."""
    manifest_version: str
    document_id: str
    run_id: str
    job_id: str
    authority: str
    country_code: str
    issuer_id: str
    fiscal_year: int
    doc_type: str
    source_url: str
    final_url: Optional[str]
    raw_path: str
    cas_path: str
    sha256: str
    size_bytes: int
    mime_type: Optional[str]
    http_status: Optional[int]
    status: str
    completeness_status: str
    validation_reasons: List[str] = field(default_factory=list)
    issuer_name: Optional[str] = None
    issuer_lei: Optional[str] = None
    ticker: Optional[str] = None
    source_page_url: Optional[str] = None
    downloaded_at: str = field(default_factory=utc_now)
    resumed: bool = False
    retries_taken: int = 0
    deduplicated: bool = False


@dataclass
class CatalogRecord(_Serializable):
    document_id: str
    run_id: str
    job_id: str
    authority: str
    country_code: str
    issuer_id: str
    fiscal_year: int
    doc_type: str
    sha256: str
    raw_path: str
    manifest_path: str
    status: str
    size_bytes: int
    cataloged_at: str = field(default_factory=utc_now)
