"""
U4 — Base común para adapters de registros normalizados (replay/sandbox): FR, IT y NL (DE reutiliza ``BaFinAdapter``).

Cada subclase solo declara lo que VARÍA por autoridad (nombre, país, dominios, tipos documentales aceptados). La
normalización de un registro al ``DocumentCandidate`` común es única, y los registros inválidos NO abortan el descubrimiento:
se descartan con un motivo en ``rejected``.

Registro de entrada (diccionario, p. ej. de un ``ReplayLinkProvider``):
  ``lei`` | ``isin`` | ``ticker`` (al menos uno: identificador del emisor), ``name``, ``fiscal_year`` (int), ``doc_type``,
  ``url``, ``page_url`` (opcional), ``source_document_id`` (opcional, SIN autoridad), ``sha256`` (opcional).

Identidad: ``identity_contract`` solo si se inyecta uno APROBADO; por defecto ``SLOT_ONLY`` (no se inventa identidad).
Sin red ni disco.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple, Union

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.versions import SourceIdentityContract
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DocumentCandidate, SourceMetadata
from mod_01_ingestion.src.unified.source_adapter import BaseSourceAdapter

LinkProvider = Callable[[DiscoveryRequest], Iterable[Dict]]
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")
MAX_BYTES = 512 * 1024 * 1024


class StandardRecordAdapter(BaseSourceAdapter):
    accepted_doc_types: FrozenSet[str] = frozenset()
    default_headers = {"Accept": "application/zip, application/xhtml+xml, application/pdf, text/html, */*"}

    def __init__(self, link_providers: Union[LinkProvider, List[LinkProvider]], *,
                 identity_contract: Optional[SourceIdentityContract] = None):
        self._providers = [link_providers] if callable(link_providers) else list(link_providers)
        self.identity_contract = identity_contract
        self.rejected: List[Tuple[str, str]] = []          # (referencia, motivo) del último ``discover``

    # ------------------------------------------------------------------------------------------
    def _candidate(self, rec: Dict) -> Optional[DocumentCandidate]:
        issuer = next((str(rec[k]).strip() for k in ("lei", "isin", "ticker") if str(rec.get(k) or "").strip()), None)
        ref = str(rec.get("url") or "?").split("?")[0].split("#")[0][:80]
        doc_type = str(rec.get("doc_type") or "").strip().upper()
        why = None
        if issuer is None:
            why = "sin identificador de emisor (lei/isin/ticker)"
        elif doc_type not in self.accepted_doc_types:
            why = f"tipo documental no aceptado: {doc_type or '?'}"
        else:
            try:
                fy = int(rec.get("fiscal_year"))
            except (TypeError, ValueError):
                why = "ejercicio fiscal no determinable"
        if why is None:
            sha = rec.get("sha256")
            sdi = str(rec.get("source_document_id") or "").strip() or None
            try:
                return DocumentCandidate(
                    authority=self.authority, country_code=self.country_code, issuer_id=issuer, fiscal_year=fy,
                    doc_type=doc_type, source_url=str(rec.get("url") or ""), source_page_url=rec.get("page_url"),
                    issuer_name=rec.get("name"), issuer_lei=(str(rec["lei"]).strip() if rec.get("lei") else None),
                    ticker=rec.get("ticker"), source=self.name, source_type=self.source_type,
                    expected_sha256=str(sha).lower() if sha and _SHA_RE.match(str(sha)) else None,
                    source_document_id=sdi, identity_contract=self.identity_contract)
            except DomainValidationError as ex:
                why = f"candidato inválido: {type(ex).__name__}"
        self.rejected.append((ref, why))
        return None

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
        ext = self.extension_from_url(candidate.source_url) or (".zip" if "ESEF" in candidate.doc_type else ".pdf")
        stem = _SAFE_NAME.sub("-", f"{self.country_code}_{self.authority}_{candidate.issuer_id}_{candidate.fiscal_year}_"
                                   f"{candidate.doc_type}")
        return SourceMetadata(
            resolved_url=candidate.source_url, file_name=f"{stem}{ext}", extension=ext,
            expected_kind=self.kind_from_extension(ext),
            authority_rules={"allowed_kinds": ["ZIP", "PDF", "XHTML", "HTML"], "min_size_bytes": 64,
                             "max_bytes": MAX_BYTES, "allowed_domains": list(self.allowed_domains)})
