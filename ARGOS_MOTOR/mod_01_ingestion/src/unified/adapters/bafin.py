"""
FASE 4 — Adapter DE / BaFin (estado: UNIFIED_READY para enlaces verificados EQS y paquetes ESEF).

Sustituye el bajo nivel de ``de_bafin_client.BaFinClient.download_filing`` y de
``download_eqs_verified.py``. Proveedores de enlaces incluidos (solo lectura de JSON, sin red):
* ``EqsVerifiedLinksProvider``  -> ``config/eqs_verified_links.json`` (informes anuales PDF, 2012-2025)
* ``EsefCatalogProvider``       -> ``config/esef_packages_catalog.json`` (paquetes ESEF filings.xbrl.org)
La autenticación Wicket de Bundesanzeiger NO está soportada aquí (bloqueo documentado: requiere
navegador); queda como proveedor externo futuro (LinkProvider).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List

from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate, SourceMetadata
from mod_01_ingestion.src.unified.source_adapter import BaseSourceAdapter, register_adapter

LinkProvider = Callable[[DiscoveryRequest], Iterable[Dict]]


class EqsVerifiedLinksProvider:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __call__(self, request: DiscoveryRequest) -> Iterable[Dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for ticker, comp in data.get("companies", {}).items():
            for year, rep in comp.get("reports", {}).items():
                yield {"ticker": ticker, "isin": comp.get("isin"), "name": comp.get("name"),
                       "fiscal_year": int(year), "doc_type": "ANNUAL_REPORT",
                       "url": rep.get("resolved_url") or rep["source_url"],
                       "source_type": SourceType.LEGACY_SCRAPER}   # catálogo producido por crawler EQS; no es el OAM


class EsefCatalogProvider:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __call__(self, request: DiscoveryRequest) -> Iterable[Dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for it in data.get("items", []):
            yield {"ticker": it.get("ticker"), "lei": it.get("lei"), "isin": it.get("isin") or None,
                   "name": it.get("legal_name"), "fiscal_year": int(it["year"]),
                   "doc_type": "ESEF_PACKAGE", "url": it["url"],
                   "source_type": SourceType.OFFICIAL_INDEX}   # índice ESEF de filings.xbrl.org


class BaFinAdapter(BaseSourceAdapter):
    authority = "BAFIN"
    country_code = "DE"
    # Contrato canónico (U2). Solo se declaran los dominios demostrados por los proveedores actuales:
    # ir-api.eqs.com (368/368 enlaces de config/eqs_verified_links.json) y filings.xbrl.org (canal ESEF del código).
    # Bundesanzeiger / Unternehmensregister NO se incluyen: este adapter no los consulta (Wicket no soportado).
    # SOURCE_CLASSIFICATION_REVIEW_REQUIRED: ``source_type`` del adapter es el de su canal oficial (índice ESEF);
    # los candidatos EQS lo sobrescriben con LEGACY_SCRAPER (no son el OAM alemán) hasta decidir su clasificación.
    name = "BAFIN"
    allowed_domains = ("ir-api.eqs.com", "filings.xbrl.org")
    source_type = SourceType.OFFICIAL_INDEX
    default_headers = {"Accept": "application/zip, application/xhtml+xml, application/pdf, */*"}

    def __init__(self, link_providers: List[LinkProvider]):
        self._providers = link_providers

    def discover(self, request: DiscoveryRequest) -> List[DocumentCandidate]:
        out: List[DocumentCandidate] = []
        for provider in self._providers:
            for rec in provider(request):
                issuer = rec.get("lei") or rec.get("isin") or rec["ticker"]
                cand = DocumentCandidate(
                    authority=self.authority, country_code=self.country_code, issuer_id=issuer,
                    fiscal_year=int(rec["fiscal_year"]), doc_type=rec["doc_type"], source_url=rec["url"],
                    issuer_name=rec.get("name"), issuer_lei=rec.get("lei"), ticker=rec.get("ticker"),
                    source=self.name, source_type=rec.get("source_type") or self.source_type)
                if self._matches(cand, request):
                    out.append(cand)
        return out[: request.limit] if request.limit else out

    def fetch_metadata(self, candidate: DocumentCandidate) -> SourceMetadata:
        ext = self.extension_from_url(candidate.source_url)
        if not ext:
            ext = ".zip" if candidate.doc_type == "ESEF_PACKAGE" else ".pdf"
        prefix = (candidate.ticker or candidate.issuer_id)
        return SourceMetadata(
            resolved_url=candidate.source_url,
            file_name=f"DE_BAFIN_{prefix}_{candidate.fiscal_year}_{candidate.doc_type}{ext}",
            extension=ext, expected_kind=self.kind_from_extension(ext),
            authority_rules={"allowed_kinds": ["ZIP", "PDF", "XHTML", "HTML"], "min_size_bytes": 64})


register_adapter("BAFIN", lambda: BaFinAdapter([]))
