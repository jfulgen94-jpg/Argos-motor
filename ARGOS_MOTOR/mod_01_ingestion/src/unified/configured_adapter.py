"""
U4 — ``ConfiguredAdapter``: aplica una ``SourceConfig`` validada a CUALQUIER adapter sin modificarlo.

* Dominios: la configuración solo puede ESTRECHAR los que el propio adapter declara (nunca ampliarlos).
* Descarga: User-Agent efectivo, tope de tamaño, timeout, plazo total, reintentos y estados reintentables viajan en cada
  ``DownloadRequest`` (el ``DownloadService`` los aplica por petición); ``allowed_domains`` controla también las redirecciones.
* Identidad: SOLO si la configuración trae un contrato APROBADO se inyecta en los candidatos que ya traen
  ``source_document_id``. Sin contrato aprobado, o sin id en el candidato, la identidad sigue siendo ``SLOT_ONLY``.
No hay red, disco ni estado.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Iterable, List, Mapping, Optional

from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate, DownloadRequest, SourceMetadata
from mod_01_ingestion.src.unified.source_config import ConfigError, SourceConfig, SourceConfigSet


def _narrow(a: Optional[Iterable[str]], b: Iterable[str]) -> List[str]:
    return [d for d in b if a is None or d in set(a)]


class ConfiguredAdapter:
    def __init__(self, adapter, config: SourceConfig):
        authority = str(getattr(adapter, "authority", "")).upper()
        country = str(getattr(adapter, "country_code", "")).upper()
        if authority != config.authority or country != config.country_code:
            raise ConfigError(f"la configuración {config.source_id!r} ({config.authority}/{config.country_code}) no "
                              f"corresponde al adapter {authority}/{country}")
        declared = tuple(getattr(adapter, "allowed_domains", ()))
        extra = sorted(set(config.allowed_domains) - set(declared))
        if extra:
            raise ConfigError(f"{config.source_id}: dominios no declarados por el adapter (la configuración solo puede "
                              f"estrechar): {extra}")
        self._adapter, self.config = adapter, config
        self.authority, self.country_code = authority, country
        self.name = getattr(adapter, "name", authority)
        self.source_type = getattr(adapter, "source_type", None)
        self.allowed_domains = tuple(config.allowed_domains)
        self.default_headers = {**getattr(adapter, "default_headers", {}), "User-Agent": config.effective_user_agent}

    # ------------------------------------------------------------------ descubrimiento
    def discover(self, request: DiscoveryRequest) -> List[DocumentCandidate]:
        out = []
        for c in self._adapter.discover(request):
            if self.config.contract is not None and c.identity_contract is None and c.source_document_id:
                c = dataclasses.replace(c, identity_contract=self.config.contract)
            out.append(c)
        return out

    # ------------------------------------------------------------------ metadatos y descarga
    def fetch_metadata(self, candidate: DocumentCandidate) -> SourceMetadata:
        meta = self._adapter.fetch_metadata(candidate)
        rules = dict(meta.authority_rules or {})
        rules["allowed_domains"] = _narrow(rules.get("allowed_domains"), self.config.allowed_domains)
        cur = rules.get("max_bytes")
        rules["max_bytes"] = min(int(cur), self.config.max_bytes) if cur else self.config.max_bytes
        headers = {**(meta.headers or {}), "User-Agent": self.config.effective_user_agent}
        return dataclasses.replace(meta, authority_rules=rules, headers=headers)

    def build_download_request(self, candidate: DocumentCandidate, metadata: SourceMetadata, staging_dir) -> DownloadRequest:
        build = getattr(self._adapter, "build_download_request", None)
        req = build(candidate, metadata, staging_dir) if build else DownloadRequest(
            url=metadata.resolved_url, staging_dir=str(staging_dir), file_name=metadata.file_name,
            expected_sha256=metadata.expected_sha256, headers=dict(metadata.headers or {}))
        cfg = self.config
        return dataclasses.replace(
            req, headers={**req.headers, "User-Agent": cfg.effective_user_agent},
            max_bytes=min(req.max_bytes, cfg.max_bytes) if req.max_bytes else cfg.max_bytes,
            allowed_domains=_narrow(req.allowed_domains, cfg.allowed_domains), timeout_s=cfg.timeout_s,
            max_total_s=cfg.max_total_s, max_retries=cfg.max_retries,
            retry_statuses=list(cfg.retry_statuses) or None)

    def __getattr__(self, item):
        return getattr(self._adapter, item)


def configure_adapters(adapters: Mapping[str, object], configs: SourceConfigSet) -> Dict[str, object]:
    """Envuelve cada adapter que tenga configuración; una configuración SIN adapter es un error (no se ignora)."""
    unknown = sorted(s.authority for s in configs.sources if s.authority not in {str(k).upper() for k in adapters})
    if unknown:
        raise ConfigError(f"configuración para autoridades sin adapter: {unknown}")
    out: Dict[str, object] = {}
    for key, adapter in adapters.items():
        cfg = configs.get(str(key))
        out[key] = ConfiguredAdapter(adapter, cfg) if cfg is not None else adapter
    return out
