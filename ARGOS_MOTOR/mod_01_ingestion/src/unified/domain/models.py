"""Modelos canónicos del dominio (U1).

Los modelos de Fase 4 se MOVIERON aquí sin cambiar campos existentes; ``unified.models`` los reexporta
(mismos objetos de clase), de modo que los imports actuales siguen resolviendo. Cambios respecto a Fase 4:
validación en ``__post_init__`` y campos nuevos OPCIONALES al final (``mode``, ``source``, ``source_type``,
``expected_sha256``, ``field_provenance``). El esquema persistente de manifiesto/catálogo NO cambia.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from mod_01_ingestion.src.unified.domain.enums import (
    AttestationLevel, AttestationScope, ExecutionMode, SourceType, UnitOfWorkStatus)
from mod_01_ingestion.src.unified.domain.errors import (
    DomainValidationError, InvalidCandidateError, InvalidSourceMetadataError, UnsupportedExecutionModeError)

SCHEMA_VERSION = "1.0.0"

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
PLACEHOLDER_HASHES = frozenset({"placeholder", "todo", "tbd", "none", "null", "xxx", "sha256", "dummy"})
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return f"run-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def build_document_id(authority: str, issuer_id: str, fiscal_year: int, doc_type: str) -> str:
    raw = f"{authority}_{issuer_id}_{fiscal_year}_{doc_type}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)


# --- validadores reutilizables -----------------------------------------------------------------
def is_placeholder_hash(value: Optional[str]) -> bool:
    return value is not None and str(value).strip().lower() in PLACEHOLDER_HASHES


def validate_sha256(value: Optional[str], field_name: str, exc=DomainValidationError, required: bool = False) -> None:
    if value is None or value == "":
        if required:
            raise exc(f"{field_name} es obligatorio")
        return
    if is_placeholder_hash(value):
        raise exc(f"{field_name} es un hash placeholder, no un SHA-256 válido")
    if not _SHA256_RE.match(str(value)):
        raise exc(f"{field_name} no es un SHA-256 hexadecimal de 64 caracteres")


def _require(value: Any, field_name: str, exc=DomainValidationError) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise exc(f"{field_name} es obligatorio y no puede estar vacío")


def _validate_http_url(url: str, field_name: str, exc) -> None:
    _require(url, field_name, exc)
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise exc(f"{field_name} no es una URL http(s) válida")


def _parse_aware(ts: str, field_name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        raise DomainValidationError(f"{field_name} no es un timestamp ISO-8601")
    if dt.tzinfo is None:
        raise DomainValidationError(f"{field_name} debe incluir zona horaria")
    return dt


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
    # Fail-closed: si el llamador no declara modo, se asume LIVE (la política más estricta).
    mode: ExecutionMode = ExecutionMode.LIVE

    def __post_init__(self):
        _require(self.run_id, "run_id")
        _parse_aware(self.started_at, "started_at")
        try:
            self.mode = ExecutionMode(self.mode)
        except ValueError:
            raise UnsupportedExecutionModeError(f"modo de ejecución no soportado: {self.mode!r}")


@dataclass
class JobContext(_Serializable):
    run_id: str
    job_id: str
    document_id: str
    authority: str
    attempt: int = 1

    def __post_init__(self):
        for name in ("run_id", "job_id", "document_id", "authority"):
            _require(getattr(self, name), name)

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

    def __post_init__(self):
        _require(self.authority, "authority")
        if self.limit is not None and self.limit < 0:
            raise DomainValidationError("limit no puede ser negativo")


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
    # U1: procedencia declarada. Opcionales por compatibilidad con adapters de Fase 4; la política LIVE
    # (``domain.policy``) exige ``source_type`` declarado. Los adapters deberán declararlos en U2.
    source: Optional[str] = None
    source_type: Optional[SourceType] = None
    expected_sha256: Optional[str] = None

    def __post_init__(self):
        for name in ("authority", "issuer_id", "doc_type"):
            _require(getattr(self, name), name, InvalidCandidateError)
        _require(self.country_code, "country_code", InvalidCandidateError)
        self.country_code = str(self.country_code).strip().upper()
        if not _COUNTRY_RE.match(self.country_code):
            raise InvalidCandidateError("country_code debe ser un código ISO de 2 letras")
        if (isinstance(self.fiscal_year, bool) or not isinstance(self.fiscal_year, int)
                or not 1990 <= self.fiscal_year <= 2100):
            raise InvalidCandidateError("fiscal_year debe ser un entero de periodo explícito (1990-2100)")
        _validate_http_url(self.source_url, "source_url", InvalidCandidateError)
        if self.source_type is not None:
            try:
                self.source_type = SourceType(self.source_type)
            except ValueError:
                raise InvalidCandidateError(f"source_type desconocido: {self.source_type!r}")
        validate_sha256(self.expected_sha256, "expected_sha256", InvalidCandidateError)

    @property
    def document_id(self) -> str:
        return build_document_id(self.authority, self.issuer_id, self.fiscal_year, self.doc_type)


_PROVENANCE_VALUES = frozenset({"VERIFIED", "INFERRED"})
_NEVER_VERIFIED = frozenset({"file_name", "extension"})  # derivados de la URL/ruta: nunca "verificados"


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
    # U1: procedencia por campo ("VERIFIED" | "INFERRED"); ausente => se considera INFERRED.
    field_provenance: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        _validate_http_url(self.resolved_url, "resolved_url", InvalidSourceMetadataError)
        _require(self.file_name, "file_name", InvalidSourceMetadataError)
        validate_sha256(self.expected_sha256, "expected_sha256", InvalidSourceMetadataError)
        if self.expected_size_bytes is not None and self.expected_size_bytes < 0:
            raise InvalidSourceMetadataError("expected_size_bytes no puede ser negativo")
        for k, v in self.field_provenance.items():
            if v not in _PROVENANCE_VALUES:
                raise InvalidSourceMetadataError(f"procedencia inválida para {k}: {v!r}")
            if v == "VERIFIED" and k in _NEVER_VERIFIED:
                raise InvalidSourceMetadataError(f"{k} deriva de la URL/ruta y no puede marcarse VERIFIED")

    def is_verified(self, field_name: str) -> bool:
        return self.field_provenance.get(field_name) == "VERIFIED"


@dataclass(frozen=True)
class SourceAttestation:
    """Hash publicado por una autoridad. U1 solo define el modelo; no existe servicio de atestación."""
    algorithm: str
    expected_digest: str
    authority: str
    evidence_ref: str
    scope: AttestationScope
    acquired_at: str
    level: AttestationLevel = AttestationLevel.OFFICIAL_HASH

    def __post_init__(self):
        if str(self.algorithm).lower().replace("-", "") != "sha256":
            raise DomainValidationError("algorithm debe ser sha256")
        validate_sha256(self.expected_digest, "expected_digest", required=True)
        _require(self.authority, "authority")
        _require(self.evidence_ref, "evidence_ref")
        object.__setattr__(self, "scope", AttestationScope(self.scope))
        object.__setattr__(self, "level", AttestationLevel(self.level))
        _parse_aware(self.acquired_at, "acquired_at")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DownloadRequest(_Serializable):
    url: str
    staging_dir: str
    file_name: str
    expected_sha256: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    allow_resume: bool = True
    max_bytes: Optional[int] = None                      # Fase 5: tope de tamaño aprobado
    allowed_domains: Optional[List[str]] = None          # Fase 5: dominios permitidos (origen + redirecciones)

    def __post_init__(self):
        _require(self.url, "url")
        _require(self.file_name, "file_name")
        validate_sha256(self.expected_sha256, "expected_sha256")


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


@dataclass(frozen=True)
class CasOwnershipReceipt:
    """Recibo emitido por ``promote`` SOLO cuando este intento creó físicamente el blob (bajo el lock del hash).
    Es la única evidencia con la que se admite borrar un blob del CAS (ver ``rollback_owned``)."""
    created_blob: bool
    blob_dev: int
    blob_ino: int
    blob_size: int
    blob_mtime_ns: int
    staged_path: str


@dataclass
class PromotionResult(_Serializable):
    raw_path: str
    cas_path: str
    sha256: str
    size_bytes: int
    deduplicated: bool            # el blob ya existía en el CAS
    link_mode: str                # hardlink | copy
    receipt: Optional[CasOwnershipReceipt] = None   # U4: None => este intento NO es propietario demostrable del blob


@dataclass
class CasRollbackResult(_Serializable):
    """Resultado de revertir una promoción. ``blob_state``: REMOVED | PREEXISTING_LEFT | SHARED_LEFT | UNPROVEN_ORPHAN.
    ``raw_view_state``: REMOVED | ABSENT | EXISTING_LEFT | UNPROVEN_LEFT. Solo ``UNPROVEN_*`` exige reconciliación."""
    blob_state: str
    raw_view_state: str
    orphaned_sha256: Optional[str] = None
    orphaned_path: Optional[str] = None      # relativa al data root (sin rutas personales absolutas)

    @property
    def clean(self) -> bool:
        return self.blob_state != "UNPROVEN_ORPHAN" and self.raw_view_state != "UNPROVEN_LEFT"


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
    """Esquema canónico único (03_MANIFEST_SCHEMA.json). Campos persistentes SIN cambios en U1.

    ``sha256`` es el hash LOCAL calculado en streaming. El hash oficial / nivel de atestación / source_type
    aún no se persisten (pendiente de migración de esquema en U2: PERSISTENCE_GUARD_PENDING_U2).
    """
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

    def __post_init__(self):
        for name in ("document_id", "run_id", "job_id", "authority", "doc_type", "raw_path"):
            _require(getattr(self, name), name)
        validate_sha256(self.sha256, "sha256", required=True)


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


@dataclass
class PipelineResult(_Serializable):
    """Resultado por documento. Misma forma que el ``JobOutcome`` de Fase 4 (que pasa a ser alias)."""
    job_id: str
    document_id: str
    state: str
    error_class: Optional[str] = None
    message: Optional[str] = None
    raw_path: Optional[str] = None
    sha256: Optional[str] = None
    attestation_level: Optional[str] = None   # U1: reservado; el runner aún no atestigua
    needs_manual_review: bool = False         # U4: True con state=RECOVERY_REQUIRED
    failure_stage: Optional[str] = None       # U4: MANIFEST | CATALOG | INVARIANT | COMMIT | CAS
    orphaned_cas_sha256: Optional[str] = None
    orphaned_cas_path: Optional[str] = None


@dataclass
class UnitOfWorkOutcome(_Serializable):
    """Resultado tipado de la unidad de trabajo manifiesto + catálogo (U4).

    Invariantes (se validan al construir):
    - ``compensation_errors`` no vacío  =>  ``status == RECOVERY_REQUIRED``;
    - ``RECOVERY_REQUIRED``  =>  ``needs_manual_review`` y NO ``committed``; conserva ``failure_stage`` o ``error_class``;
    - ``COMMITTED`` no lleva errores, violaciones ni ``error_class``.
    ``error_class`` conserva la clasificación histórica del runner (``MANIFEST_FAILED`` / ``CATALOG_FAILED``; un fallo al
    promover el manifiesto sigue etiquetándose ``CATALOG_FAILED`` por compatibilidad). ``failure_stage`` dice DÓNDE falló
    aunque la compensación también haya fallado.
    """
    status: UnitOfWorkStatus
    document_id: str
    error_class: Optional[str] = None
    message: Optional[str] = None
    manifest_path: Optional[str] = None
    compensated: bool = False
    compensation_errors: tuple = ()
    invariant_violations: tuple = ()
    failure_stage: Optional[str] = None
    idempotent: bool = False                 # COMMITTED sin escribir: ambos lados ya contenían el mismo registro
    recovery_reason: Optional[str] = None
    orphaned_cas_sha256: Optional[str] = None
    orphaned_cas_path: Optional[str] = None

    def __post_init__(self):
        if self.compensation_errors and self.status is not UnitOfWorkStatus.RECOVERY_REQUIRED:
            raise DomainValidationError("compensation_errors no vacío exige status RECOVERY_REQUIRED")
        if self.status is UnitOfWorkStatus.RECOVERY_REQUIRED and not (self.failure_stage or self.error_class):
            raise DomainValidationError("RECOVERY_REQUIRED debe conservar failure_stage o error_class")
        if self.status is UnitOfWorkStatus.COMMITTED and (self.error_class or self.compensation_errors
                                                          or self.invariant_violations):
            raise DomainValidationError("COMMITTED no admite error_class, errores de compensación ni violaciones")

    @property
    def ok(self) -> bool:
        return self.status is UnitOfWorkStatus.COMMITTED

    @property
    def committed(self) -> bool:
        return self.status is UnitOfWorkStatus.COMMITTED

    @property
    def recovery_required(self) -> bool:
        return self.status is UnitOfWorkStatus.RECOVERY_REQUIRED

    @property
    def needs_manual_review(self) -> bool:
        return self.recovery_required or bool(self.compensation_errors) or bool(self.orphaned_cas_sha256)
