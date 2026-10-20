"""
U5A — Adaptador de SOLO LECTURA del puerto ``KnownDocumentLookup`` sobre los repositorios existentes.

No escribe, no crea directorios ni el archivo DuckDB (consultas ``read_only``), no toma locks de escritura ni toca
``.part``/CAS más allá de leer y hashear el raw registrado. Capacidades reales de la persistencia actual:
  · manifiesto por (autoridad, ejercicio, document_id)        -> disponible (JSON)
  · catálogo por document_id y por sha256                       -> disponible (DuckDB)
  · versiones por identity_key / sha256 (U5B, tablas aditivas)   -> disponible si se inyecta un ``VersionRepository``
  · por URL / entity_id / instrument_id                           -> NO se almacenan hoy (no se filtra)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified.version_store import VersionRepository


class RepositoryKnownDocumentLookup:
    def __init__(self, manifests: ManifestRepository, catalog: CatalogRepository, cas: ContentAddressedRawStore,
                 versions: Optional[VersionRepository] = None):
        self.manifests, self.catalog, self.cas, self.versions = manifests, catalog, cas, versions

    def get_manifest(self, authority: str, fiscal_year: int, document_id: str) -> Optional[Mapping[str, Any]]:
        return self.manifests.get(authority, fiscal_year, document_id)

    def get_catalog(self, document_id: str) -> Optional[Mapping[str, Any]]:
        return self.catalog.get_record(document_id)

    def find_by_sha256(self, sha256: str) -> Sequence[Mapping[str, Any]]:
        return self.catalog.find_by_sha256(sha256)

    def find_versions(self, identity_key: str) -> Sequence[Mapping[str, Any]]:
        return self.versions.list_versions(identity_key) if self.versions is not None else []

    def find_versions_by_sha256(self, sha256: str) -> Sequence[Mapping[str, Any]]:
        return self.versions.list_versions_by_sha256(sha256) if self.versions is not None else []

    def blob_is_intact(self, sha256: str) -> bool:
        return bool(sha256) and self.cas.verify(str(sha256), self.cas.blob_path(str(sha256)))

    def content_is_intact(self, record: Mapping[str, Any]) -> bool:
        raw, sha = record.get("raw_path"), record.get("sha256")
        return bool(raw and sha) and self.cas.verify(str(sha), Path(str(raw)))
