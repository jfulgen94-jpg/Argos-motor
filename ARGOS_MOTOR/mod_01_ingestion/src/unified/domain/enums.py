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
    # SKIPPED_DUPLICATE: duplicado detectado DURANTE o DESPUÉS del procesamiento
    # (incluye la segunda comprobación bajo lock). El runner actual solo emite este.
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    # --- añadidos en U1 (aún no emitidos por el runner) ---
    # SKIPPED_ALREADY_PRESENT: preflight positivo ANTES de adquirir lock o descargar.
    SKIPPED_ALREADY_PRESENT = "SKIPPED_ALREADY_PRESENT"
    DOWNLOAD_STARTED = "DOWNLOAD_STARTED"
    DOWNLOADED_TO_STAGING = "DOWNLOADED_TO_STAGING"
    VALIDATED = "VALIDATED"
    ATTESTED = "ATTESTED"
    PROMOTED = "PROMOTED"
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
    UNKNOWN = "UNKNOWN"


# --- Transiciones permitidas ---------------------------------------------------------------------
_S = PipelineStatus
_TERMINAL = frozenset({_S.COMPLETED, _S.QUARANTINED, _S.FAILED, _S.SKIPPED_DUPLICATE,
                       _S.SKIPPED_ALREADY_PRESENT, _S.NOT_PUBLISHED, _S.NOT_APPLICABLE})

ALLOWED_TRANSITIONS = {
    _S.DISCOVERED: frozenset({_S.QUEUED, _S.SKIPPED_ALREADY_PRESENT, _S.SKIPPED_DUPLICATE,
                              _S.NOT_PUBLISHED, _S.NOT_APPLICABLE, _S.FAILED}),
    _S.QUEUED: frozenset({_S.DOWNLOADING, _S.DOWNLOAD_STARTED, _S.NOT_PUBLISHED, _S.NOT_APPLICABLE, _S.FAILED}),
    # flujo observado en el runner actual
    _S.DOWNLOADING: frozenset({_S.VERIFYING, _S.VALIDATING, _S.FAILED}),
    _S.VERIFYING: frozenset({_S.VALIDATING, _S.FAILED, _S.QUARANTINED}),
    _S.VALIDATING: frozenset({_S.PROMOTING, _S.QUARANTINED, _S.FAILED}),
    _S.PROMOTING: frozenset({_S.MANIFESTING, _S.FAILED}),
    _S.MANIFESTING: frozenset({_S.CATALOGING, _S.FAILED}),
    _S.CATALOGING: frozenset({_S.COMPLETED, _S.FAILED}),
    # flujo objetivo (aún no emitido por el runner)
    _S.DOWNLOAD_STARTED: frozenset({_S.DOWNLOADED_TO_STAGING, _S.FAILED}),
    _S.DOWNLOADED_TO_STAGING: frozenset({_S.VALIDATED, _S.QUARANTINED, _S.FAILED}),
    _S.VALIDATED: frozenset({_S.ATTESTED, _S.PROMOTED, _S.QUARANTINED, _S.FAILED}),
    _S.ATTESTED: frozenset({_S.PROMOTED, _S.QUARANTINED, _S.FAILED}),
    _S.PROMOTED: frozenset({_S.MANIFESTING, _S.FAILED}),
    **{t: frozenset() for t in _TERMINAL},
}
TERMINAL_STATES = _TERMINAL


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
