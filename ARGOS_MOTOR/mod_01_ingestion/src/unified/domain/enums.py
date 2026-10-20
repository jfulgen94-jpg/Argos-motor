"""Enums canónicos del dominio (U1).

``PipelineStatus`` es el superconjunto de los estados que ya usaba ``unified`` (antes ``JobState``,
que sigue disponible como alias en ``unified.models``). Los valores existentes no cambian.
"""
from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    TEST = "TEST"
    SANDBOX = "SANDBOX"
    PILOT = "PILOT"
    LIVE = "LIVE"


class PipelineStatus(str, Enum):
    # --- estados en uso por UnifiedIngestRunner (Fases 4-6): valores inmutables ---
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
    # LEGACY_COMPATIBILITY_ALIAS: SKIPPED_DUPLICATE ya NO lo emite el runner (U5A). Se conserva solo para que el
    # vocabulario serializado de Fases 4-6 siga resolviendo. Único skip emitible: SKIPPED_ALREADY_PRESENT, y solo tras
    # PreflightStatus.SKIPPED_ALREADY_PRESENT (evidencia fuerte). Retirada prevista: U5B/U6, cuando no queden
    # consumidores externos (cli, legacy_bridge ya aceptan el nuevo estado).
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    # --- añadidos en U1 (aún no emitidos por el runner) ---
    # SKIPPED_ALREADY_PRESENT: preflight positivo ANTES de adquirir lock o descargar.
    SKIPPED_ALREADY_PRESENT = "SKIPPED_ALREADY_PRESENT"
    DOWNLOAD_STARTED = "DOWNLOAD_STARTED"
    DOWNLOADED_TO_STAGING = "DOWNLOADED_TO_STAGING"
    VALIDATED = "VALIDATED"
    ATTESTED = "ATTESTED"
    PROMOTED = "PROMOTED"
    # U4: el fallo dejó estado parcial (manifiesto/catálogo/CAS) que no se pudo restaurar: reconciliación manual.
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    # U5A: resultados terminales del KnownDocumentPreflight (antes de cualquier descarga)
    CONFLICT = "CONFLICT"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AttestationLevel(str, Enum):
    OFFICIAL_HASH = "OFFICIAL_HASH"
    CROSS_SOURCE_HASH = "CROSS_SOURCE_HASH"
    LOCAL_VALIDATION_ONLY = "LOCAL_VALIDATION_ONLY"
    UNATTESTED = "UNATTESTED"
    HASH_MISMATCH = "HASH_MISMATCH"


class AttestationScope(str, Enum):
    PACKAGE = "PACKAGE"
    DOCUMENT = "DOCUMENT"
    SNAPSHOT = "SNAPSHOT"


class SourceType(str, Enum):
    OFFICIAL_OAM = "OFFICIAL_OAM"
    OFFICIAL_INDEX = "OFFICIAL_INDEX"
    REGULATOR_API = "REGULATOR_API"
    AUTHORIZED_MIRROR = "AUTHORIZED_MIRROR"
    LEGACY_SCRAPER = "LEGACY_SCRAPER"
    TEST_FIXTURE = "TEST_FIXTURE"
    SIMULATED = "SIMULATED"


class CoverageStatus(str, Enum):
    """Solo vocabulario: el Coverage Ledger no se implementa en U1."""
    EXPECTED = "EXPECTED"
    DISCOVERED = "DISCOVERED"
    DOWNLOADED = "DOWNLOADED"
    VALIDATED = "VALIDATED"
    ATTESTED = "ATTESTED"
    PRESENT_EXISTING = "PRESENT_EXISTING"
    QUARANTINED = "QUARANTINED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ErrorClass(str, Enum):
    """Clasificación única de errores de infraestructura (movida sin cambios desde unified.models)."""
    HTTP_TRANSIENT = "HTTP_TRANSIENT"
    HTTP_PERMANENT = "HTTP_PERMANENT"
    NETWORK = "NETWORK"
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
    REDIRECT_NOT_ALLOWED = "REDIRECT_NOT_ALLOWED"
    SIZE_EXCEEDED = "SIZE_EXCEEDED"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"     # U4: manifiesto y catálogo no coinciden
    UNKNOWN = "UNKNOWN"


# --- Transiciones permitidas ---------------------------------------------------------------------
_S = PipelineStatus
_TERMINAL = frozenset({_S.COMPLETED, _S.QUARANTINED, _S.FAILED, _S.RECOVERY_REQUIRED, _S.CONFLICT, _S.MANUAL_REVIEW,
                       _S.SKIPPED_DUPLICATE,
                       _S.SKIPPED_ALREADY_PRESENT, _S.NOT_PUBLISHED, _S.NOT_APPLICABLE})

ALLOWED_TRANSITIONS = {
    _S.DISCOVERED: frozenset({_S.QUEUED, _S.SKIPPED_ALREADY_PRESENT, _S.SKIPPED_DUPLICATE,
                              _S.NOT_PUBLISHED, _S.NOT_APPLICABLE, _S.FAILED,
                              _S.RECOVERY_REQUIRED, _S.CONFLICT, _S.MANUAL_REVIEW}),
    _S.QUEUED: frozenset({_S.DOWNLOADING, _S.DOWNLOAD_STARTED, _S.NOT_PUBLISHED, _S.NOT_APPLICABLE, _S.FAILED}),
    # flujo observado en el runner actual
    _S.DOWNLOADING: frozenset({_S.VERIFYING, _S.VALIDATING, _S.FAILED}),
    _S.VERIFYING: frozenset({_S.VALIDATING, _S.FAILED, _S.QUARANTINED}),
    _S.VALIDATING: frozenset({_S.PROMOTING, _S.QUARANTINED, _S.FAILED}),
    _S.PROMOTING: frozenset({_S.MANIFESTING, _S.FAILED, _S.RECOVERY_REQUIRED, _S.MANUAL_REVIEW}),  # U5B: UNCONFIRMED
    _S.MANIFESTING: frozenset({_S.CATALOGING, _S.FAILED, _S.RECOVERY_REQUIRED}),
    _S.CATALOGING: frozenset({_S.COMPLETED, _S.FAILED, _S.RECOVERY_REQUIRED}),
    # flujo objetivo (aún no emitido por el runner)
    _S.DOWNLOAD_STARTED: frozenset({_S.DOWNLOADED_TO_STAGING, _S.FAILED}),
    _S.DOWNLOADED_TO_STAGING: frozenset({_S.VALIDATED, _S.QUARANTINED, _S.FAILED}),
    _S.VALIDATED: frozenset({_S.ATTESTED, _S.PROMOTED, _S.QUARANTINED, _S.FAILED}),
    _S.ATTESTED: frozenset({_S.PROMOTED, _S.QUARANTINED, _S.FAILED}),
    _S.PROMOTED: frozenset({_S.MANIFESTING, _S.FAILED}),
    **{t: frozenset() for t in _TERMINAL},
}
TERMINAL_STATES = _TERMINAL


class UnitOfWorkStatus(str, Enum):
    """Resultado tipado de ``ManifestCatalogUnitOfWork`` (U4)."""
    COMMITTED = "COMMITTED"
    FAILED_MANIFEST = "FAILED_MANIFEST"        # no se pudo preparar el manifiesto (incluye rechazo del guard)
    FAILED_CATALOG = "FAILED_CATALOG"          # no se pudo preparar el catálogo
    FAILED_INVARIANT = "FAILED_INVARIANT"      # manifiesto y catálogo preparados pero inconsistentes
    FAILED_COMMIT = "FAILED_COMMIT"            # fallo al promover el manifiesto pendiente a definitivo
    # Compensación incompleta o estado parcial no restaurable automáticamente: requiere revisión manual.
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


# --- Identidad de emisores e instrumentos (U3) ----------------------------------------------------
class IdentifierStatus(str, Enum):
    VALID = "VALID"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_CHECKSUM = "INVALID_CHECKSUM"
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"
    UNVERIFIED = "UNVERIFIED"      # forma plausible pero sin validación fiable disponible (p. ej. CIF/NIF)


class IdentityConfidence(str, Enum):
    CONFIRMED = "CONFIRMED"        # requiere evidencia externa (p. ej. GLEIF); offline nunca se asigna
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class IdentityReviewStatus(str, Enum):
    NO_REVIEW_REQUIRED = "NO_REVIEW_REQUIRED"
    POSSIBLE_SAME_ENTITY = "POSSIBLE_SAME_ENTITY"
    SHARED_IDENTIFIER_CONFLICT = "SHARED_IDENTIFIER_CONFLICT"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class DuplicateRelation(str, Enum):
    SAME_ENTITY_CONFIRMED = "SAME_ENTITY_CONFIRMED"
    SAME_ENTITY_POSSIBLE = "SAME_ENTITY_POSSIBLE"
    MULTIPLE_INSTRUMENTS_SAME_ENTITY = "MULTIPLE_INSTRUMENTS_SAME_ENTITY"
    TICKER_CHANGE_POSSIBLE = "TICKER_CHANGE_POSSIBLE"
    SAME_NAME_DIFFERENT_ENTITY = "SAME_NAME_DIFFERENT_ENTITY"
    IDENTIFIER_CONFLICT = "IDENTIFIER_CONFLICT"
    NOT_DUPLICATE = "NOT_DUPLICATE"
    UNRESOLVED = "UNRESOLVED"


class PreflightStatus(str, Enum):
    """Resultado de ``KnownDocumentPreflight`` (U5A). Solo ``SKIPPED_ALREADY_PRESENT`` evita la descarga con éxito."""
    SKIPPED_ALREADY_PRESENT = "SKIPPED_ALREADY_PRESENT"
    PROCEED_DOWNLOAD = "PROCEED_DOWNLOAD"
    POSSIBLE_REPUBLICATION = "POSSIBLE_REPUBLICATION"
    # U5B: republicación respaldada por evidencia válida según el contrato de la fuente (puede descargar).
    REPUBLICATION_CONFIRMED = "REPUBLICATION_CONFIRMED"
    # U5B: mismo contenido ya en el CAS bajo OTRA identidad y hash esperado autoritativo: se registra sin transporte.
    REUSE_EXISTING_CONTENT = "REUSE_EXISTING_CONTENT"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    CONFLICT = "CONFLICT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class PreflightMatch(str, Enum):
    """Evidencia por la que se tomó la decisión (de más a menos fuerte; URL y nombre nunca bastan para un skip)."""
    SHA256 = "SHA256"
    SOURCE_DOCUMENT_ID = "SOURCE_DOCUMENT_ID"
    DOCUMENT_ID = "DOCUMENT_ID"
    MANIFEST_AND_CATALOG = "MANIFEST_AND_CATALOG"
    SOURCE_URL = "SOURCE_URL"
    COMPOSITE_IDENTITY = "COMPOSITE_IDENTITY"
    VERSION_EVIDENCE = "VERSION_EVIDENCE"      # U5B: evidencia de republicación validada por contrato
    NONE = "NONE"
