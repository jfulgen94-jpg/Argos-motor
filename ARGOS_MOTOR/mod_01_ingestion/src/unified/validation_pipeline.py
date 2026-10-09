"""
FASE 4 — ValidationPipeline: validación única (MIME/magic, HTML disfrazado, ZIP, contenido mínimo).

Delega la lógica forense de completitud en ``DocumentCompletenessValidator`` (núcleo conservado,
con DEFECT-01 corregido). Las reglas específicas de autoridad llegan por
``SourceMetadata.authority_rules`` (p.ej. ``min_size_bytes``, ``allowed_kinds``); no hay
validadores por país.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.unified.models import ErrorClass, SourceMetadata, ValidationResult

HTMLISH = (b"<html", b"<!doctype html", b"<?xml", b"<head", b"<body", b"<!doctype")


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
