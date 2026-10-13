"""
U4 — Contrato COMÚN de candidato para todos los adapters (ES, US, y los siguientes países).

Un candidato común lleva: autoridad y país consistentes con el adapter, fuente (``source``) y tipo de fuente declarados,
URL SANEADA (sin credenciales, fragmento ni parámetros secretos), tipo documental, periodo explícito y, SOLO si existe,
identidad (``source_document_id`` + ``identity_contract``). Sin contrato la identidad es ``SLOT_ONLY``: nunca se inventa.

Sin red, sin disco y sin dependencias de infraestructura: solo ``urllib``.
"""
from __future__ import annotations

from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mod_01_ingestion.src.unified.domain.errors import InvalidCandidateError
from mod_01_ingestion.src.unified.domain.policy import is_host_allowed

# Parámetros de consulta que suelen llevar secretos o firmas: no viajan en ``source_url`` (se persistiría en el manifiesto).
SENSITIVE_QUERY_KEYS = frozenset({
    "token", "access_token", "id_token", "refresh_token", "api_key", "apikey", "key", "sig", "signature", "auth",
    "authorization", "password", "passwd", "pwd", "secret", "session", "sessionid", "sid", "jsessionid", "code",
    "x-amz-signature", "x-amz-credential", "x-amz-security-token", "awsaccesskeyid", "x-api-key", "client_secret"})


class CandidateContractError(InvalidCandidateError):
    """El candidato no cumple el contrato común (el router lo rechaza antes de que llegue al pipeline)."""


def sanitize_source_url(url: Optional[str]) -> Optional[str]:
    """Quita credenciales (``user:pass@``), fragmento y parámetros sensibles. Conserva esquema, host, ruta y el resto de la
    consulta, en orden estable. Una URL sin esquema/host se devuelve tal cual (la rechazará la validación del candidato)."""
    if not url:
        return url
    p = urlsplit(url)
    if not p.scheme or not p.hostname:
        return url
    host = p.hostname + (f":{p.port}" if p.port else "")
    kept = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in SENSITIVE_QUERY_KEYS]
    return urlunsplit((p.scheme, host, p.path, urlencode(kept), ""))


def has_unsafe_url_parts(url: str) -> bool:
    p = urlsplit(url)
    if p.username or p.password or p.fragment:
        return True
    return any(k.lower() in SENSITIVE_QUERY_KEYS for k, _ in parse_qsl(p.query, keep_blank_values=True))


def assert_common_candidate(candidate, *, authority: str, country_code: str, allowed_domains: Iterable[str]) -> None:
    """Verifica el contrato común. No muta. Lanza ``CandidateContractError`` con la causa."""
    def fail(why: str):
        raise CandidateContractError(f"{candidate.authority}/{candidate.issuer_id}/{candidate.fiscal_year}: {why}")
    if str(candidate.authority).upper() != str(authority).upper():
        fail(f"autoridad {candidate.authority!r} distinta de la del adapter {authority!r}")
    if str(candidate.country_code).upper() != str(country_code).upper():
        fail(f"país {candidate.country_code!r} distinto del del adapter {country_code!r}")
    if not candidate.source:
        fail("falta la fuente (source)")
    if candidate.source_type is None:
        fail("falta source_type declarado")
    if not candidate.doc_type or not str(candidate.doc_type).strip():
        fail("falta el tipo documental")
    p = urlsplit(candidate.source_url)
    if p.scheme != "https":
        fail("solo https")
    if has_unsafe_url_parts(candidate.source_url):
        fail("la URL lleva credenciales, fragmento o parámetros secretos")
    if candidate.source_page_url and has_unsafe_url_parts(candidate.source_page_url):
        fail("source_page_url lleva credenciales, fragmento o parámetros secretos")
    domains = tuple(allowed_domains)
    if not domains or not is_host_allowed(p.hostname or "", domains):
        fail(f"host {p.hostname!r} fuera de allowed_domains del adapter")
    if candidate.identity_contract is None and candidate.source_document_id is not None:
        pass      # permitido: el id viaja como metadato SIN autoridad (SLOT_ONLY); nunca autoriza un skip
