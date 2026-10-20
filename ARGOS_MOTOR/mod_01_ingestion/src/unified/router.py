"""
U4 — Router DETERMINISTA por fuente y aplicación del contrato común de candidato.

* ``route(authority=… | country_code=…)``: sin heurísticas ni "mejor candidato". Una autoridad -> un adapter. Un país solo se
  resuelve si exactamente UN adapter lo declara; si hay varios (o ninguno) es un error explícito.
* ``discover(request)``: descubre con el adapter de ``request.authority``, NORMALIZA cada candidato (URL saneada, ``source``
  por defecto) y lo VALIDA contra el contrato común; el resultado sale ordenado por una clave estable (independiente del
  orden del proveedor).
* ``as_runner_adapters()``: adapta el router al ``UnifiedIngestRunner`` sin tocarlo: el runner solo ve candidatos ya
  normalizados y validados.
Sin red, sin disco, sin estado mutable tras la construcción.
"""
from __future__ import annotations

import dataclasses
from typing import Dict, Iterable, List, Mapping

from mod_01_ingestion.src.unified.adapters.common import assert_common_candidate, sanitize_source_url
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.policy import validate_allowed_domains
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate


class UnroutableSourceError(DomainValidationError):
    pass


class SourceRouter:
    def __init__(self, adapters: Mapping[str, object]):
        self._by_authority: Dict[str, object] = {}
        self._by_country: Dict[str, List[str]] = {}
        for key, adapter in adapters.items():
            authority = str(getattr(adapter, "authority", "") or key).upper()
            if authority != str(key).upper():
                raise UnroutableSourceError(f"clave {key!r} no coincide con la autoridad del adapter {authority!r}")
            country = str(getattr(adapter, "country_code", "")).upper()
            if len(country) != 2 or not country.isalpha():
                raise UnroutableSourceError(f"el adapter {authority} no declara un país ISO válido")
            validate_allowed_domains(getattr(adapter, "allowed_domains", ()))
            if authority in self._by_authority:
                raise UnroutableSourceError(f"autoridad duplicada: {authority}")
            self._by_authority[authority] = adapter
            self._by_country.setdefault(country, []).append(authority)

    # ------------------------------------------------------------------ resolución
    def authorities(self) -> List[str]:
        return sorted(self._by_authority)

    def route(self, *, authority: str = None, country_code: str = None):
        if authority:
            try:
                return self._by_authority[str(authority).upper()]
            except KeyError:
                raise UnroutableSourceError(f"autoridad sin adapter: {authority!r}. Disponibles: {self.authorities()}")
        if country_code:
            cands = self._by_country.get(str(country_code).upper(), [])
            if len(cands) == 1:
                return self._by_authority[cands[0]]
            raise UnroutableSourceError(
                f"país {country_code!r} no resoluble: " + ("ningún adapter" if not cands else f"ambiguo entre {sorted(cands)}"))
        raise UnroutableSourceError("se necesita authority o country_code")

    # ------------------------------------------------------------------ contrato común
    def normalize(self, candidate: DocumentCandidate, adapter) -> DocumentCandidate:
        normalized = dataclasses.replace(
            candidate, source_url=sanitize_source_url(candidate.source_url),
            source_page_url=sanitize_source_url(candidate.source_page_url),
            source=candidate.source or getattr(adapter, "name", None) or adapter.authority,
            source_type=candidate.source_type or getattr(adapter, "source_type", None))
        assert_common_candidate(normalized, authority=adapter.authority, country_code=adapter.country_code,
                                allowed_domains=adapter.allowed_domains)
        return normalized

    @staticmethod
    def _order_key(c: DocumentCandidate):
        return (c.authority, c.issuer_id, c.fiscal_year, c.doc_type, c.source_url, c.source_document_id or "")

    def discover(self, request: DiscoveryRequest) -> List[DocumentCandidate]:
        adapter = self.route(authority=request.authority)
        out = [self.normalize(c, adapter) for c in adapter.discover(request)]
        return sorted(out, key=self._order_key)

    def as_runner_adapters(self) -> Dict[str, object]:
        return {a: _RoutedAdapter(self, a) for a in self.authorities()}


class _RoutedAdapter:
    """Vista del router para el runner: delega metadatos/descarga en el adapter real y centraliza el descubrimiento."""

    def __init__(self, router: SourceRouter, authority: str):
        self._router, self.authority = router, authority
        real = router.route(authority=authority)
        self._real = real
        self.name = getattr(real, "name", authority)
        self.country_code = real.country_code
        self.allowed_domains = real.allowed_domains

    def discover(self, request: DiscoveryRequest) -> Iterable[DocumentCandidate]:
        return self._router.discover(request)

    def fetch_metadata(self, candidate: DocumentCandidate):
        return self._real.fetch_metadata(candidate)

    def __getattr__(self, item):          # build_download_request y demás utilidades del adapter real
        return getattr(self._real, item)
