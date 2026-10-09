"""
FASE 4 — Adapter ES / CNMV (estado: UNIFIED_READY para descarga de URLs oficiales conocidas).

Sustituye el bajo nivel de ``es_cnmv_client.CNMVClient.download_annual_package`` (que usaba
``RobustDownloader`` + validación + manifiesto propios). El descubrimiento web interactivo de la
CNMV (``cnmv_portal_scraper``) queda como proveedor de enlaces externo (LinkProvider), fuera del
núcleo; este adapter solo normaliza sus registros al modelo canónico.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List

from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate, SourceMetadata
from mod_01_ingestion.src.unified.source_adapter import BaseSourceAdapter, register_adapter

LinkProvider = Callable[[DiscoveryRequest], Iterable[Dict]]

DOC_SLUGS = {  # mismo mapa que CNMVClient.REQUIRED_ANNUAL_DOCS
    "ESEF_PACKAGE": "cuentas_anuales_consolidadas_auditadas",
    "INFORME_GESTION": "informe_de_gestion_consolidado",
    "EINF_CSRD": "estado_informacion_no_financiera_csrd",
    "IAGC": "informe_anual_gobierno_corporativo_IAGC",
    "IARC": "informe_anual_remuneraciones_IARC",
}


class CNMVAdapter(BaseSourceAdapter):
    authority = "CNMV"
    country_code = "ES"
    # Contrato canónico (U2). Dominios demostrados por el código existente (es_cnmv_client.BASE_URL, motor v5).
    # ALLOWED_DOMAIN_REVIEW_REQUIRED: filings.xbrl.org aparece en el código ESEF pero no se ha demostrado que sirva
    # enlaces de este adapter, por lo que NO se incluye. Declarativo: aún no se aplica a las descargas (U3).
    name = "CNMV"
    allowed_domains = ("www.cnmv.es", "cnmv.es")
    source_type = SourceType.OFFICIAL_OAM
    default_headers = {
        "Accept": "application/zip, application/xhtml+xml, application/pdf, text/html, */*",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.cnmv.es",
    }

    def __init__(self, link_provider: LinkProvider):
        self._provider = link_provider

    def discover(self, request: DiscoveryRequest) -> List[DocumentCandidate]:
        out: List[DocumentCandidate] = []
        for rec in self._provider(request):
            cand = DocumentCandidate(
                authority=self.authority, country_code=self.country_code,
                issuer_id=rec.get("lei") or rec["ticker"], fiscal_year=int(rec["fiscal_year"]),
                doc_type=rec["doc_type"], source_url=rec["url"], issuer_name=rec.get("name"),
                issuer_lei=rec.get("lei"), ticker=rec.get("ticker"), source_page_url=rec.get("page_url"),
                source=self.name, source_type=self.source_type)
            if self._matches(cand, request):
                out.append(cand)
        return out[: request.limit] if request.limit else out

    def fetch_metadata(self, candidate: DocumentCandidate) -> SourceMetadata:
        ext = self.extension_from_url(candidate.source_url)
        if not ext:
            ext = ".zip" if candidate.doc_type == "ESEF_PACKAGE" else ".pdf"
        slug = DOC_SLUGS.get(candidate.doc_type, candidate.doc_type.lower())
        prefix = (candidate.ticker or candidate.issuer_id).lower()
        return SourceMetadata(
            resolved_url=candidate.source_url,
            file_name=f"{prefix}_{candidate.fiscal_year}_{slug}{ext}",
            extension=ext, expected_kind=self.kind_from_extension(ext),
            authority_rules={"allowed_kinds": ["ZIP", "PDF", "XHTML", "HTML"], "min_size_bytes": 64})


register_adapter("CNMV", lambda: CNMVAdapter(lambda req: []))
