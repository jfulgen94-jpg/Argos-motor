"""
U5A — Adaptador de SOLO LECTURA del puerto ``KnownDocumentLookup`` sobre los repositorios existentes.

No escribe, no crea directorios ni el archivo DuckDB (consultas ``read_only``), no toma locks de escritura ni toca
``.part``/CAS más allá de leer y hashear el raw registrado. Capacidades reales de la persistencia actual:
  · manifiesto por (autoridad, ejercicio, document_id)        -> disponible (JSON)
  · catálogo por document_id y por sha256                       -> disponible (DuckDB)
  · por source_document_id / URL / entity_id / instrument_id    -> NO se almacenan hoy (devuelve [] / no filtra)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository


class RepositoryKnownDocumentLookup:
    def __init__(self, manifests: ManifestRepository, catalog: CatalogRepository, cas: ContentAddressedRawStore):
        self.manifests, self.catalog, self.cas = manifests, catalog, cas

    def get_manifest(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Mapping[str, Any]]:
        return self.manifests.get(authority, fiscal_year, document_id)

    def get_catalog(self, document_id: str) -> Optional[Mapping[str, Any]]:
        return self.catalog.get_record(document_id)

    def find_by_sha256(self, sha256: str) -> Sequence[Mapping[str, Any]]:
        return self.catalog.find_by_sha256(sha256)

    def find_by_source_document_id(self, authority: str, source_document_id: str) -> Sequence[Mapping[str, Any]]:
        return []     # el identificador de fuente aún no se persiste: el preflight no puede aplicar P4 en producción

    def content_is_intact(self, record: Mapping[str, Any]) -> bool:
        raw, sha = record.get("raw_path"), record.get("sha256")
        return bool(raw and sha) and self.cas.verify(str(sha), Path(str(raw)))
