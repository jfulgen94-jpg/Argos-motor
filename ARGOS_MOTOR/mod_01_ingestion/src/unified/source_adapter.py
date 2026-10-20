"""
FASE 4 — Contrato de conector (SourceAdapter) y registro de autoridades.

Lo ÚNICO que varía por autoridad: descubrimiento, metadatos de fuente, autenticación (cuando
proceda) y reglas de validación específicas (``SourceMetadata.authority_rules``). Nada de
HTTP de bajo nivel, hash, promoción, manifiesto, cuarentena o telemetría en los adapters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse, unquote

from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.domain.protocols import SourceAdapter  # noqa: F401  (contrato CANÓNICO, U2)
from mod_01_ingestion.src.unified.models import (
    DiscoveryRequest, DocumentCandidate, DownloadRequest, SourceMetadata)

# DEPRECADO (U2): el Protocol ``SourceAdapter`` de Fase 4 (``authority``/``country_code``, ``discover`` -> List)
# se sustituye por el canónico ``unified.domain.protocols.SourceAdapter`` (``name``/``allowed_domains``,
# ``discover`` -> Iterable). Este nombre es un REEXPORT para no romper imports. Diferencia semántica: el v1
# exigía ``authority``/``country_code``; el runner nunca los leía del adapter (usa los del candidato), así que
# basta el contrato v2. ``BaseSourceAdapter`` conserva ``authority``/``country_code`` por compatibilidad.


class BaseSourceAdapter:
    """Utilidades comunes NO críticas (normalización de nombre/extensión)."""

    authority = "UNKNOWN"
    country_code = "XX"
    default_headers: Dict[str, str] = {}
    # Contrato canónico (U2). Cada adapter concreto DEBE declararlos; los valores por defecto son inválidos a propósito.
    name: str = ""
    allowed_domains: tuple = ()
    source_type: Optional[SourceType] = None

    @staticmethod
    def extension_from_url(url: str) -> str:
        return Path(unquote(urlparse(url).path)).suffix.lower()

    @staticmethod
    def kind_from_extension(ext: str) -> Optional[str]:
        return {".zip": "ZIP", ".pdf": "PDF", ".xhtml": "XHTML", ".htm": "HTML", ".html": "HTML"}.get(ext)

    @staticmethod
    def _matches(candidate: DocumentCandidate, request: DiscoveryRequest) -> bool:
        if request.fiscal_years and candidate.fiscal_year not in request.fiscal_years:
            return False
        if request.issuer_ids and candidate.issuer_id not in request.issuer_ids:
            return False
        if request.doc_types and candidate.doc_type not in request.doc_types:
            return False
        return True

    def build_download_request(self, candidate: DocumentCandidate, metadata: SourceMetadata,
                               staging_dir: Path) -> DownloadRequest:
        return DownloadRequest(url=metadata.resolved_url, staging_dir=str(staging_dir),
                               file_name=metadata.file_name, expected_sha256=metadata.expected_sha256,
                               headers={**self.default_headers, **metadata.headers},
                               max_bytes=metadata.authority_rules.get("max_bytes"),
                               allowed_domains=metadata.authority_rules.get("allowed_domains"))


AdapterFactory = Callable[[], SourceAdapter]
_REGISTRY: Dict[str, AdapterFactory] = {}


def register_adapter(authority: str, factory: AdapterFactory) -> None:
    _REGISTRY[authority.upper()] = factory


def get_adapter(authority: str) -> SourceAdapter:
    try:
        return _REGISTRY[authority.upper()]()
    except KeyError:
        raise KeyError(f"Autoridad sin adapter registrado: {authority}. Registradas: {sorted(_REGISTRY)}")


def registered_authorities() -> List[str]:
    return sorted(_REGISTRY)
