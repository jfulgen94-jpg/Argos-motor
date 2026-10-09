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
                       "url": rep.get("resolved_url") or rep["source_url"]}


class EsefCatalogProvider:
    def __init__(self, path: Path):
        self.path = Path(path)

    def __call__(self, request: DiscoveryRequest) -> Iterable[Dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for it in data.get("items", []):
            yield {"ticker": it.get("ticker"), "lei": it.get("lei"), "isin": it.get("isin") or None,
                   "name": it.get("legal_name"), "fiscal_year": int(it["year"]),
                   "doc_type": "ESEF_PACKAGE", "url": it["url"]}


class BaFinAdapter(BaseSourceAdapter):
    authority = "BAFIN"
    country_code = "DE"
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
                    issuer_name=rec.get("name"), issuer_lei=rec.get("lei"), ticker=rec.get("ticker"))
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
