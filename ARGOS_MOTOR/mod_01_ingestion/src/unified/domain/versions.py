"""U5B — Identidad lógica, versiones de contenido y evidencia de republicación (dominio puro: sin I/O).

Principios (diseño aprobado):
- ``document_id`` sigue siendo el *slot* histórico; NUNCA se trata como identidad autoritativa.
- Una identidad lógica solo existe si el adapter declara un ``SourceIdentityContract`` y el candidato trae
  ``source_document_id``. Sin ellos la identidad es ``SLOT_ONLY`` (no se inventa una).
- ``id_scope=LOGICAL_DOCUMENT``: el id se mantiene entre republicaciones => NUNCA prueba por sí solo que los bytes sean los
  mismos. ``id_scope=VERSION``: el id identifica UNA versión concreta (``version_ref``); las versiones del mismo slot se
  agrupan por el slot, no por el id.
- Un SHA-256 identifica bytes; no demuestra autoridad, identidad ni causa de republicación.
- ``identity_key`` NO incluye la versión del normalizador ni del contrato (se guardan como columnas): cambiar la política no
  duplica identidades en silencio; el preflight lo detecta y pide revisión.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError

NORMALIZER_V1 = "v1"                                  # Unicode NFC + strip; conserva mayúsculas, ceros y puntuación
SUPPORTED_NORMALIZERS = frozenset({NORMALIZER_V1})
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class IdScope(str, Enum):
    VERSION = "VERSION"                        # el id cambia con cada versión (identifica UNA versión)
    LOGICAL_DOCUMENT = "LOGICAL_DOCUMENT"      # el id es el mismo entre republicaciones


class IdentityKind(str, Enum):
    SOURCE_ID = "SOURCE_ID"                    # identidad lógica declarada por contrato (id_scope=LOGICAL_DOCUMENT)
    SLOT_ONLY = "SLOT_ONLY"                    # solo el slot histórico (sin contrato, sin id o id_scope=VERSION)
    LEGACY_UNCLASSIFIED = "LEGACY_UNCLASSIFIED"  # registro histórico sin campos de identidad (solo lectura)


class VersionStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    CONFLICT = "CONFLICT"


class InitialVersionPolicy(str, Enum):
    NONE = "NONE"                                          # por defecto: nunca asigna CURRENT a la primera versión
    REQUIRE_AUTHORITATIVE_HASH = "REQUIRE_AUTHORITATIVE_HASH"
    TRUST_FIRST_VALIDATED = "TRUST_FIRST_VALIDATED"


class EvidenceKind(str, Enum):
    REVISION_NUMBER = "REVISION_NUMBER"
    SUPERSEDES_REF = "SUPERSEDES_REF"
    OFFICIAL_RECTIFICATION_FLAG = "OFFICIAL_RECTIFICATION_FLAG"
    OFFICIAL_HASH = "OFFICIAL_HASH"


def normalize_sha256(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not _SHA_RE.match(v):
        raise DomainValidationError("sha256 inválido (se esperan 64 hex)")
    return v


def normalize_source_id(raw: Any, normalizer_version: str = NORMALIZER_V1) -> str:
    """Normalizador v1: NFC + strip. No cambia mayúsculas, ceros ni puntuación. Versión desconocida => error."""
    if normalizer_version not in SUPPORTED_NORMALIZERS:
        raise DomainValidationError(f"normalizador de identidad desconocido: {normalizer_version!r}")
    if raw is None:
        raise DomainValidationError("source_document_id vacío")
    value = unicodedata.normalize("NFC", str(raw)).strip()
    if not value:
        raise DomainValidationError("source_document_id vacío tras normalizar")
    return value


@dataclass(frozen=True)
class SourceIdentityContract:
    """Contrato declarado por el adapter (hoy solo fixtures sintéticos; ninguna fuente real lo declara)."""
    contract_id: str
    contract_version: str
    authority: str
    namespace: str
    id_scope: IdScope
    normalizer_version: str = NORMALIZER_V1
    allowed_evidence_kinds: Tuple[EvidenceKind, ...] = ()
    initial_version_policy: InitialVersionPolicy = InitialVersionPolicy.NONE
    expected_sha256_authority: bool = False         # la fuente publica el hash de cada versión (autoritativo)

    def __post_init__(self):
        for name in ("contract_id", "contract_version", "authority", "namespace"):
            if not str(getattr(self, name) or "").strip():
                raise DomainValidationError(f"contrato de identidad: {name} obligatorio")
        object.__setattr__(self, "id_scope", IdScope(self.id_scope))
        object.__setattr__(self, "initial_version_policy", InitialVersionPolicy(self.initial_version_policy))
        object.__setattr__(self, "allowed_evidence_kinds",
                           tuple(EvidenceKind(k) for k in self.allowed_evidence_kinds))
        if self.normalizer_version not in SUPPORTED_NORMALIZERS:
            raise DomainValidationError(f"normalizador de identidad desconocido: {self.normalizer_version!r}")
        if (self.initial_version_policy is InitialVersionPolicy.REQUIRE_AUTHORITATIVE_HASH
                and not self.expected_sha256_authority):
            raise DomainValidationError("REQUIRE_AUTHORITATIVE_HASH exige expected_sha256_authority")


@dataclass(frozen=True)
class RepublicationEvidence:
    """Evidencia estructurada y auditable. Solo vale si el contrato de la fuente la admite (ver validate_*)."""
    kind: EvidenceKind
    value: str
    contract_id: str
    contract_version: str

    def __post_init__(self):
        object.__setattr__(self, "kind", EvidenceKind(self.kind))
        if not str(self.value or "").strip():
            raise DomainValidationError("evidencia de republicación sin valor")

    def canonical_json(self) -> str:
        return json.dumps({"kind": self.kind.value, "value": str(self.value), "contract_id": self.contract_id,
                           "contract_version": self.contract_version}, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))


def validate_republication_evidence(
        contract: SourceIdentityContract, evidence: Optional[RepublicationEvidence], *,
        current_version_ref: Optional[str], current_revision: Optional[int], current_sha256: Optional[str],
        candidate_revision: Optional[int], expected_sha256: Optional[str]) -> Tuple[bool, str]:
    """Una categoría genérica NO basta: tipo permitido por el contrato + comprobación específica del tipo."""
    if evidence is None:
        return False, "NO_EVIDENCE"
    if evidence.contract_id != contract.contract_id or evidence.contract_version != contract.contract_version:
        return False, "EVIDENCE_CONTRACT_MISMATCH"
    if evidence.kind not in contract.allowed_evidence_kinds:
        return False, "EVIDENCE_KIND_NOT_ALLOWED_BY_CONTRACT"
    if evidence.kind is EvidenceKind.REVISION_NUMBER:
        ok = (isinstance(candidate_revision, int) and not isinstance(candidate_revision, bool)
              and isinstance(current_revision, int) and candidate_revision > current_revision
              and str(candidate_revision) == str(evidence.value).strip())
        return ok, "OK" if ok else "REVISION_NOT_GREATER_THAN_CURRENT"
    if evidence.kind is EvidenceKind.SUPERSEDES_REF:
        ok = bool(current_version_ref) and str(evidence.value).strip() == current_version_ref
        return ok, "OK" if ok else "SUPERSEDES_REF_DOES_NOT_MATCH_CURRENT"
    if evidence.kind is EvidenceKind.OFFICIAL_RECTIFICATION_FLAG:
        ok = str(evidence.value).strip().lower() == "true"
        return ok, "OK" if ok else "RECTIFICATION_FLAG_NOT_TRUE"
    if evidence.kind is EvidenceKind.OFFICIAL_HASH:
        ok = (contract.expected_sha256_authority and bool(expected_sha256) and expected_sha256 != current_sha256
              and normalize_sha256(evidence.value) == expected_sha256)
        return bool(ok), "OK" if ok else "OFFICIAL_HASH_NOT_AUTHORITATIVE_OR_NOT_NEW"
    return False, "EVIDENCE_KIND_UNSUPPORTED"


@dataclass(frozen=True)
class ResolvedIdentity:
    identity_key: str                 # clave de agrupación de versiones (lógica o slot)
    identity_kind: IdentityKind
    version_ref: Optional[str]        # solo id_scope=VERSION con id declarado
    id_scope: Optional[IdScope]
    normalized_id: Optional[str]
    raw_id: Optional[str]
    contract: Optional[SourceIdentityContract]

    @property
    def is_contracted(self) -> bool:
        return self.contract is not None and self.normalized_id is not None


def slot_key(document_id: str) -> str:
    return f"SLOT|{document_id}"


def _json_key(prefix: str, parts) -> str:
    return prefix + "|" + json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))


def resolve_identity(authority: str, document_id: str, contract: Optional[SourceIdentityContract],
                     source_document_id: Optional[str]) -> ResolvedIdentity:
    """Sin contrato o sin id => SLOT_ONLY (nunca se inventa una identidad autoritativa)."""
    if contract is None or source_document_id is None:
        return ResolvedIdentity(slot_key(document_id), IdentityKind.SLOT_ONLY, None, None, None, None, None)
    if str(contract.authority).strip().upper() != str(authority).strip().upper():
        raise DomainValidationError("el contrato de identidad no corresponde a la autoridad del candidato")
    nid = normalize_source_id(source_document_id, contract.normalizer_version)
    ref = _json_key("VR", (contract.authority.upper(), contract.namespace, nid))
    if contract.id_scope is IdScope.LOGICAL_DOCUMENT:
        return ResolvedIdentity(_json_key("ID", (contract.authority.upper(), contract.namespace, nid)),
                                IdentityKind.SOURCE_ID, ref, contract.id_scope, nid, str(source_document_id), contract)
    return ResolvedIdentity(slot_key(document_id), IdentityKind.SLOT_ONLY, ref, contract.id_scope, nid,
                            str(source_document_id), contract)


@dataclass(frozen=True)
class DocumentVersion:
    """Hechos inmutables de una versión de contenido. Dos registros con la misma clave deben coincidir en TODOS los
    ``FACT_FIELDS``; si no, es un CONFLICT (no se ignora en silencio)."""
    identity_key: str
    sha256: str
    identity_kind: str
    authority: str
    document_id: str
    size_bytes: int
    normalizer_version: str
    version_ref: Optional[str] = None
    revision: Optional[int] = None
    contract_id: Optional[str] = None
    contract_version: Optional[str] = None
    source_document_id_raw: Optional[str] = None
    evidence_json: Optional[str] = None
    # no comparables (observación, no hecho):
    first_observed_at: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None

    FACT_FIELDS = ("identity_key", "sha256", "identity_kind", "authority", "document_id", "size_bytes",
                   "normalizer_version", "version_ref", "revision", "contract_id", "contract_version",
                   "source_document_id_raw", "evidence_json")

    def __post_init__(self):
        object.__setattr__(self, "sha256", normalize_sha256(self.sha256))
        if self.sha256 is None or not self.identity_key:
            raise DomainValidationError("versión sin identity_key o sha256")
        object.__setattr__(self, "identity_kind", IdentityKind(self.identity_kind).value)

    def facts(self) -> Dict[str, Any]:
        return {n: getattr(self, n) for n in self.FACT_FIELDS}

    def to_row(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def diff_facts(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[str, ...]:
    """Campos de hecho que difieren (relectura y comparación completa tras un conflicto de clave)."""
    return tuple(k for k in DocumentVersion.FACT_FIELDS if a.get(k) != b.get(k))


@dataclass(frozen=True)
class VersionEvent:
    identity_key: str
    sha256: str
    event_seq: int
    status: str
    evidence_json: Optional[str] = None
    recorded_at: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "status", VersionStatus(self.status).value)


@dataclass(frozen=True)
class Observation:
    run_id: str
    job_id: str
    identity_key: str
    sha256: Optional[str]
    expected_sha256: Optional[str]
    preflight_status: str
    observed_at: Optional[str] = None

    FACT_FIELDS = ("run_id", "job_id", "identity_key", "sha256", "expected_sha256", "preflight_status")

    def facts(self) -> Dict[str, Any]:
        return {n: getattr(self, n) for n in self.FACT_FIELDS}
