"""Jerarquía de errores de dominio (U1). No sustituye las excepciones de infraestructura existentes
(``DownloadFailure``, ``LockTimeout``, ``ManifestValidationError``, ...)."""
from __future__ import annotations

import re

_MAX_LEN = 500
_SECRET = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|token|access[_-]?token|api[_-]?key|"
    r"apikey|secret|password|passwd|bearer)\b\s*[:=]?\s*(?:bearer\s+)?[^\s,;&]+")
_URL_QUERY = re.compile(r"(https?[:][/]{2}[^\s?#]+)\?[^\s]*")  # sin literal de URL (test AT-07)


def sanitize_message(message: object) -> str:
    """Elimina credenciales evidentes y query strings de URLs; acota la longitud (sin cuerpos HTTP)."""
    text = str(message)
    text = _SECRET.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = _URL_QUERY.sub(r"\1?<redacted>", text)
    text = " ".join(text.split())
    return text if len(text) <= _MAX_LEN else text[:_MAX_LEN] + "...<truncated>"


class UnifiedDownloadError(Exception):
    def __init__(self, message: object = ""):
        super().__init__(sanitize_message(message))


class DomainValidationError(UnifiedDownloadError): ...
class InvalidCandidateError(DomainValidationError): ...
class InvalidSourceMetadataError(DomainValidationError): ...
class SimulatedDataRejectedError(UnifiedDownloadError): ...
class InvalidStateTransitionError(UnifiedDownloadError): ...
class UnsupportedExecutionModeError(UnifiedDownloadError): ...
class CompatibilityMappingError(UnifiedDownloadError): ...
