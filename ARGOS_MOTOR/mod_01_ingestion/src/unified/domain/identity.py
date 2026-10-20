"""Identidad de emisores e instrumentos (U3). Funciones y modelos PUROS: sin red, sin filesystem, sin DuckDB.

Principios (ver audits/UNIFIED_DOWNLOAD_U3_2026-10-09/01_IDENTITY_POLICY.md):
- ``LegalEntity`` (persona jurídica) y ``ListedInstrument`` (cotización/instrumento) son conceptos distintos.
- El ticker NO es identidad jurídica; una razón social NO es una clave.
- Un LEI solo participa en identidad fuerte si pasa formato Y checksum ISO 17442. Los valores inválidos se
  conservan en bruto (``lei_raw``) y se marcan; nunca se corrigen ni se sustituyen.
- No existe lógica fiable de validación de CIF/NIF en el repositorio: solo se normaliza y se comprueba la FORMA
  (``UNVERIFIED``), que nunca basta para identidad fuerte.
- La razón social normalizada solo genera candidatos a revisión; nunca confirma ni fusiona.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from mod_01_ingestion.src.unified.domain.enums import (
    DuplicateRelation, IdentifierStatus, IdentityConfidence, IdentityReviewStatus)

# ------------------------------------------------------------------------------------ LEI (ISO 17442)
_LEI_FORMAT = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")
_LEI_CHARS = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class IdentifierCheck:
    raw: Optional[str]
    normalized: str
    status: IdentifierStatus
    length: int
    valid_characters: bool
    checksum_ok: Optional[bool]      # None si no aplicaba (formato inválido o no hay checksum)
    error: Optional[str]             # tipo de error: LENGTH_<n>, INVALID_CHARACTERS, BAD_CHECK_DIGITS, CHECKSUM, ...

    @property
    def usable_for_identity(self) -> bool:
        return self.status is IdentifierStatus.VALID


def normalize_lei(raw: Optional[str]) -> str:
    """Normalización conservadora: espacios exteriores y mayúsculas. No corrige ni reinterpreta el valor."""
    return str(raw if raw is not None else "").strip().upper()


def _mod97(value: str) -> int:
    return int("".join(str(int(ch, 36)) for ch in value)) % 97


def check_lei(raw: Optional[str]) -> IdentifierCheck:
    n = normalize_lei(raw)
    if not n:
        return IdentifierCheck(raw, n, IdentifierStatus.MISSING, 0, True, None, None)
    chars_ok = bool(_LEI_CHARS.match(n))
    if not chars_ok:
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_FORMAT, len(n), False, None, "INVALID_CHARACTERS")
    if len(n) != 20:
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_FORMAT, len(n), True, None, f"LENGTH_{len(n)}")
    if not _LEI_FORMAT.match(n):
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_FORMAT, 20, True, None, "BAD_CHECK_DIGITS_FORMAT")
    if _mod97(n) != 1:
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_CHECKSUM, 20, True, False, "CHECKSUM")
    return IdentifierCheck(raw, n, IdentifierStatus.VALID, 20, True, True, None)


# ------------------------------------------------------------------------------------ ISIN (ISO 6166)
_ISIN_FORMAT = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def normalize_isin(raw: Optional[str]) -> str:
    return str(raw if raw is not None else "").strip().upper()


def check_isin(raw: Optional[str]) -> IdentifierCheck:
    n = normalize_isin(raw)
    if not n:
        return IdentifierCheck(raw, n, IdentifierStatus.MISSING, 0, True, None, None)
    if not _ISIN_FORMAT.match(n):
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_FORMAT, len(n), bool(_LEI_CHARS.match(n)), None,
                               f"LENGTH_{len(n)}" if len(n) != 12 else "BAD_FORMAT")
    digits = "".join(str(int(ch, 36)) for ch in n)           # letras -> 10..35
    total, double = 0, False
    for d in reversed(digits):                                # Luhn sobre la cadena expandida
        v = int(d)
        if double:
            v *= 2
            v = v - 9 if v > 9 else v
        total += v
        double = not double
    if total % 10 != 0:
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_CHECKSUM, 12, True, False, "CHECKSUM")
    return IdentifierCheck(raw, n, IdentifierStatus.VALID, 12, True, True, None)


# ------------------------------------------------------------------------------------ CIF / NIF (solo forma)
_ES_TAX_SHAPES = (
    re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$"),    # CIF
    re.compile(r"^\d{8}[A-Z]$"),                          # NIF persona física
    re.compile(r"^[XYZ]\d{7}[A-Z]$"),                     # NIE
    re.compile(r"^[KLM]\d{7}[A-Z0-9]$"),                  # NIF especiales
)


def normalize_tax_id(raw: Optional[str]) -> str:
    """Mayúsculas y sin separadores (espacio . - /). No inventa dígitos de control."""
    return re.sub(r"[\s.\-/]", "", str(raw if raw is not None else "").upper())


def check_tax_id(raw: Optional[str], country: str = "ES") -> IdentifierCheck:
    """NO valida dígito de control (no hay lógica fiable en el repositorio): ``UNVERIFIED`` ≠ ``VALID``."""
    n = normalize_tax_id(raw)
    if not n:
        return IdentifierCheck(raw, n, IdentifierStatus.MISSING, 0, True, None, None)
    if country.upper() == "ES" and not any(p.match(n) for p in _ES_TAX_SHAPES):
        return IdentifierCheck(raw, n, IdentifierStatus.INVALID_FORMAT, len(n), True, None, "UNKNOWN_SHAPE")
    return IdentifierCheck(raw, n, IdentifierStatus.UNVERIFIED, len(n), True, None, None)


# ------------------------------------------------------------------------------------ ticker y razón social
def normalize_ticker(raw: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(raw if raw is not None else "")).upper()


_LEGAL_FORMS = re.compile(r"\b(S\.?\s?A\.?\s?U?\.?|S\.?\s?L\.?\s?U?\.?|SOCIMI|SOCIEDAD ANONIMA|SOCIEDAD LIMITADA)\b")


def normalize_legal_name(raw: Optional[str]) -> str:
    """Normalización AUXILIAR para generar candidatos a revisión: sin acentos, mayúsculas, sin formas legales ni
    signos. Dos entidades con igual valor NO son la misma entidad."""
    text = unicodedata.normalize("NFKD", str(raw if raw is not None else ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).upper()
    text = _LEGAL_FORMS.sub(" ", text)
    return re.sub(r"[^A-Z0-9]", "", text)


# ------------------------------------------------------------------------------------ modelos
@dataclass(frozen=True)
class LegalEntity:
    entity_id: str
    legal_name: str
    normalized_legal_name: str
    country: str
    lei_raw: Optional[str]
    lei_normalized: str
    lei_status: IdentifierStatus
    local_tax_id_raw: Optional[str]
    local_tax_id_normalized: str
    local_tax_id_status: IdentifierStatus
    is_socimi: bool
    identity_confidence: IdentityConfidence
    source_references: Tuple[str, ...]
    review_status: IdentityReviewStatus


@dataclass(frozen=True)
class ListedInstrument:
    instrument_id: str
    entity_id: str
    ticker: str
    mic: Optional[str]
    market: Optional[str]
    isin: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    listing_status: str
    source_reference: str


@dataclass(frozen=True)
class IdentityIssue:
    code: str                 # p. ej. LEI_INVALID_CHECKSUM, SHARED_LEI, DUPLICATE_TICKER
    severity: str             # INFO | WARNING | ERROR
    source_reference: str
    detail: str


@dataclass(frozen=True)
class RelationRecord:
    source_reference_a: str
    source_reference_b: str
    relation: DuplicateRelation
    confidence: IdentityConfidence
    review_status: IdentityReviewStatus
    rule: str
    evidence: Tuple[str, ...]


@dataclass(frozen=True)
class IdentityResolution:
    entities: Tuple[LegalEntity, ...]
    instruments: Tuple[ListedInstrument, ...]
    relations: Tuple[RelationRecord, ...]
    issues: Tuple[IdentityIssue, ...]
    metrics: Dict[str, Any] = field(default_factory=dict, compare=False)


# ------------------------------------------------------------------------------------ identificadores internos
def _fingerprint(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def entity_id_from_lei(lei_normalized: str) -> str:
    return f"entity:lei:{lei_normalized}"


def entity_id_from_tax(country: str, tax_normalized: str) -> str:
    return f"entity:tax:{country.upper()}:{tax_normalized}"


def provisional_entity_id(*, country: str, normalized_name: str, lei_normalized: str, tax_normalized: str,
                          source_record_key: str) -> Tuple[str, IdentityConfidence]:
    """Fallback determinista. Incluye la clave del registro de origen: dos registros nunca se funden por azar.
    Confianza LOW si incorpora algún identificador bruto; UNRESOLVED si solo hay nombre y registro."""
    digest = _fingerprint({"country": country.upper(), "name": normalized_name, "lei": lei_normalized,
                           "tax": tax_normalized, "record": source_record_key})
    conf = IdentityConfidence.LOW if (lei_normalized or tax_normalized) else IdentityConfidence.UNRESOLVED
    return f"entity:provisional:{digest[:32]}", conf


def instrument_id_for(*, isin_check: IdentifierCheck, mic: Optional[str], ticker: str, valid_from: Optional[str],
                      source: str, source_key: str) -> str:
    """ISIN válido > MIC+ticker+vigencia > fuente+identificador estable de la fuente."""
    if isin_check.status is IdentifierStatus.VALID:
        return f"instrument:isin:{isin_check.normalized}"
    if mic and ticker and valid_from:
        return f"instrument:listing:{mic.upper()}:{normalize_ticker(ticker)}:{valid_from}"
    return f"instrument:source:{source}:{source_key}"
