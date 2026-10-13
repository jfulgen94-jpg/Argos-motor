"""
FASE 4 — ValidationPipeline: validación única (MIME/magic, HTML disfrazado, ZIP, contenido mínimo).

Delega la lógica forense de completitud en ``DocumentCompletenessValidator`` (núcleo conservado,
con DEFECT-01 corregido). Las reglas específicas de autoridad llegan por
``SourceMetadata.authority_rules`` (p.ej. ``min_size_bytes``, ``allowed_kinds``); no hay
validadores por país.
"""
from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path
from typing import List, Optional

from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.unified.models import ErrorClass, SourceMetadata, ValidationResult

HTMLISH = (b"<html", b"<!doctype html", b"<?xml", b"<head", b"<body", b"<!doctype")


# Límites por defecto frente a bombas de descompresión (sobrescribibles con ``authority_rules``)
DEFAULT_MAX_MEMBERS = 20000
DEFAULT_MAX_UNCOMPRESSED = 4 * 1024 ** 3
DEFAULT_MAX_RATIO = 1000
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def unsafe_zip_member_reason(name: str, external_attr: int = 0) -> Optional[str]:
    """Zip Slip: nombre absoluto, con ``..``, unidad, NUL, ADS de NTFS o enlace simbólico. Nunca se extrae nada aquí."""
    if "\x00" in name:
        return f"nombre con NUL: {name!r}"
    norm = name.replace("\\", "/")
    if norm.startswith("/") or _DRIVE_RE.match(norm) or norm.startswith("//"):
        return f"ruta absoluta: {name!r}"
    if any(part == ".." for part in norm.split("/")):
        return f"salida del directorio con '..': {name!r}"
    if ":" in norm:
        return f"flujo alterno/unidad en el nombre: {name!r}"
    if stat.S_ISLNK((external_attr >> 16) & 0xFFFF):
        return f"enlace simbólico dentro del ZIP: {name!r}"
    return None


def inspect_zip_safety(path: Path, rules: dict) -> List[str]:
    """Razones por las que un ZIP es inseguro (vacío = seguro o ilegible: lo ilegible lo rechaza el validador de completitud)."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, EOFError):
        return []
    reasons: List[str] = []
    for info in infos:
        why = unsafe_zip_member_reason(info.filename, info.external_attr)
        if why:
            reasons.append("ZIP_SLIP: " + why)
    max_members = int(rules.get("max_members", DEFAULT_MAX_MEMBERS))
    if len(infos) > max_members:
        reasons.append(f"ZIP_BOMB: {len(infos)} miembros > {max_members}")
    total = sum(i.file_size for i in infos)
    max_total = int(rules.get("max_uncompressed_bytes", DEFAULT_MAX_UNCOMPRESSED))
    if total > max_total:
        reasons.append(f"ZIP_BOMB: {total} bytes descomprimidos > {max_total}")
    max_ratio = int(rules.get("max_compression_ratio", DEFAULT_MAX_RATIO))
    for i in infos:
        if i.file_size > (1 << 20) and i.file_size / max(1, i.compress_size) > max_ratio:
            reasons.append(f"ZIP_BOMB: ratio de compresión anómalo en {i.filename!r}")
            break
    return reasons


def sniff_kind(header: bytes) -> str:
    if header.startswith(b"PK\x03\x04"):
        return "ZIP"
    if header.startswith(b"%PDF-"):
        return "PDF"
    low = header.lstrip().lower()
    if low.startswith(HTMLISH) or any(tok in low[:2048] for tok in (b"<html", b"<!doctype html")):
        return "XHTML" if low.startswith(b"<?xml") else "HTML"
    return "UNKNOWN"


class ValidationPipeline:
    def __init__(self, completeness: Optional[DocumentCompletenessValidator] = None):
        self.completeness = completeness or DocumentCompletenessValidator()

    def validate(self, staged_path: Path, metadata: SourceMetadata, doc_type: Optional[str] = None) -> ValidationResult:
        path = Path(staged_path)
        if not path.exists() or path.stat().st_size == 0:
            return self._reject("INVALID_FORMAT", "UNKNOWN", ErrorClass.EMPTY_FILE, ["Archivo ausente o vacío."])
        size = path.stat().st_size
        with open(path, "rb") as f:
            header = f.read(4096)
        kind = sniff_kind(header)
        rules = metadata.authority_rules or {}

        min_size = int(rules.get("min_size_bytes", 0))
        if size < min_size:
            return self._reject("PARTIAL", kind, ErrorClass.VALIDATION_REJECTED,
                                [f"Tamaño {size} < mínimo de autoridad {min_size}."])
        allowed = rules.get("allowed_kinds")
        if allowed and kind not in allowed:
            return self._reject("INVALID_FORMAT", kind, ErrorClass.VALIDATION_REJECTED,
                                [f"Tipo {kind} no permitido por la autoridad {allowed}."])

        expected = (metadata.expected_kind or "").upper() or None
        if expected in ("ZIP", "PDF") and kind in ("HTML", "XHTML"):
            return self._reject("ERROR_HTML", kind, ErrorClass.DISGUISED_HTML,
                                [f"Se esperaba {expected} pero el contenido es {kind} (probable página de error)."])
        if expected in ("ZIP", "PDF") and kind != expected:
            return self._reject("INVALID_FORMAT", kind, ErrorClass.VALIDATION_REJECTED,
                                [f"Firma mágica {kind} no coincide con lo esperado {expected}."])

        if kind == "ZIP":
            unsafe = inspect_zip_safety(path, rules)
            if unsafe:     # se rechaza ANTES de cualquier validación de contenido y de cualquier promoción
                return self._reject("UNSAFE_ARCHIVE", kind, ErrorClass.VALIDATION_REJECTED, unsafe[:20])

        try:
            res = self.completeness.validate_document(path, expected_doc_type=doc_type)
        except Exception as ex:  # nunca colapsar el worker por un archivo corrupto
            return self._reject("INVALID_FORMAT", kind, ErrorClass.CORRUPT_ARCHIVE,
                                [f"Validador lanzó {type(ex).__name__}: {ex}"])

        quarantine = bool(res["should_quarantine"])
        klass = None
        if quarantine:
            klass = ErrorClass.CORRUPT_ARCHIVE if (kind == "ZIP" and res["completeness_status"] == "INVALID_FORMAT") \
                else ErrorClass.DISGUISED_HTML if res["completeness_status"] in ("ERROR_HTML", "ERROR_RESPONSE") \
                else ErrorClass.VALIDATION_REJECTED
        return ValidationResult(
            accepted=not quarantine, completeness_status=res["completeness_status"], detected_kind=kind,
            should_quarantine=quarantine, reasons=list(res["reasons"]),
            error_class=klass.value if klass else None, metrics=res.get("metrics", {}))

    @staticmethod
    def _reject(status: str, kind: str, klass: ErrorClass, reasons) -> ValidationResult:
        return ValidationResult(accepted=False, completeness_status=status, detected_kind=kind,
                                should_quarantine=True, reasons=list(reasons), error_class=klass.value)
