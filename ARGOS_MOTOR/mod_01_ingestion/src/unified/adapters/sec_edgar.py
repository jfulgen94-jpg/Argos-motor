"""
U4 — Adapter US / SEC EDGAR (estado: SANDBOX/REPLAY; sin red, sin descargas reales).

Normaliza registros del índice de presentaciones de EDGAR (campos de la API ``submissions`` ya aplanados por un proveedor:
``cik``, ``accessionNumber``, ``form``, ``reportDate``, ``primaryDocument``...) al ``DocumentCandidate`` común. La URL del
documento primario se CONSTRUYE de forma determinista (cadena pura) en ``www.sec.gov/Archives/edgar/data``.

Identidad: el número de accesión es un identificador por presentación (una enmienda trae otro). Se expone como
``source_document_id`` (metadato SIN autoridad). Solo si el propietario aprueba un ``SourceIdentityContract`` y se inyecta en
``identity_contract`` el candidato adquiere identidad; por defecto es ``SLOT_ONLY`` y NO se inventa ninguna.
Limitaciones documentadas: dos enmiendas del mismo ejercicio y formulario comparten ``document_id`` (slot) hasta que exista
ese contrato; el ejercicio fiscal sale de ``fiscal_year`` si viene, o del año de ``reportDate``.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.domain.versions import SourceIdentityContract
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate, SourceMetadata
from mod_01_ingestion.src.unified.source_adapter import BaseSourceAdapter, register_adapter

LinkProvider = Callable[[DiscoveryRequest], Iterable[Dict]]
ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"})
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_PRIMARY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
MAX_BYTES = 256 * 1024 * 1024


class SECAdapter(BaseSourceAdapter):
    authority = "SEC"
    country_code = "US"
    name = "SEC"
    allowed_domains = ("www.sec.gov", "sec.gov")
    source_type = SourceType.REGULATOR_API
    default_headers = {"Accept": "text/html, application/xhtml+xml, application/pdf, */*"}

    def __init__(self, link_providers: List[LinkProvider], *, identity_contract: Optional[SourceIdentityContract] = None,
                 annual_forms=ANNUAL_FORMS):
        self._providers = list(link_providers)
        self.identity_contract = identity_contract
        self.annual_forms = frozenset(annual_forms)
        self.rejected: List[Tuple[str, str]] = []          # (accessionNumber o '?', motivo) del último ``discover``

    # ------------------------------------------------------------------------------------------
    def _candidate(self, rec: Dict) -> Optional[DocumentCandidate]:
        acc = str(rec.get("accessionNumber") or "").strip()
        why = None
        form = str(rec.get("form") or "").strip().upper()
        cik = str(rec.get("cik") or "").strip()
        primary = str(rec.get("primaryDocument") or "").strip()
        if form not in self.annual_forms:
            why = f"formulario no anual: {form or '?'}"
        elif not cik.isdigit() or not 1 <= len(cik) <= 10 or int(cik) == 0:
            why = "cik inválido"
        elif not _ACCESSION_RE.match(acc):
            why = "accessionNumber inválido"
        elif not _PRIMARY_RE.match(primary):
            why = "primaryDocument no permitido"
        if why is None:
            fy = rec.get("fiscal_year")
            if fy is None:
                rd = str(rec.get("reportDate") or "")
                fy = int(rd[:4]) if re.match(r"^\d{4}-\d{2}-\d{2}$", rd) else None
            try:
                fy = int(fy)
            except (TypeError, ValueError):
                why = "ejercicio fiscal no determinable"
        if why is not None:
            self.rejected.append((acc or "?", why))
            return None
        cik10 = cik.zfill(10)
        folder = f"{_ARCHIVES}/{int(cik)}/{acc.replace('-', '')}"
        sha = rec.get("sha256")
        return DocumentCandidate(
            authority=self.authority, country_code=self.country_code, issuer_id=cik10, fiscal_year=fy, doc_type=form,
            source_url=f"{folder}/{primary}", source_page_url=f"{folder}/", issuer_name=rec.get("name"),
            ticker=rec.get("ticker"), source=self.name, source_type=self.source_type,
            expected_sha256=str(sha).lower() if sha and _SHA_RE.match(str(sha)) else None,
            source_document_id=acc, identity_contract=self.identity_contract)

    def discover(self, request: DiscoveryRequest) -> List[DocumentCandidate]:
        self.rejected = []
        out: List[DocumentCandidate] = []
        for provider in self._providers:
            for rec in provider(request):
                cand = self._candidate(rec)
                if cand is not None and self._matches(cand, request):
                    out.append(cand)
        return out[: request.limit] if request.limit else out

    def fetch_metadata(self, candidate: DocumentCandidate) -> SourceMetadata:
        ext = self.extension_from_url(candidate.source_url)
        primary = candidate.source_url.rsplit("/", 1)[-1]
        acc = candidate.source_document_id or "NOACC"
        return SourceMetadata(
            resolved_url=candidate.source_url, file_name=f"SEC_{candidate.issuer_id}_{acc}_{primary}"[:200],
            extension=ext, expected_kind=self.kind_from_extension(ext),
            authority_rules={"allowed_kinds": ["HTML", "XHTML", "PDF"], "min_size_bytes": 64, "max_bytes": MAX_BYTES,
                             "allowed_domains": list(self.allowed_domains)})


register_adapter("SEC", lambda: SECAdapter([]))
