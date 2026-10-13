"""
U4 — Configuración VERSIONADA por fuente (infraestructura; ningún valor real se declara aquí).

Formato JSON (``schema_version`` "1"):

    {"schema_version": "1", "config_version": "<id de la edición>",
     "sources": [{"source_id": "...", "authority": "...", "country_code": "..",
                  "allowed_domains": ["host.tld"], "user_agent": "...", "contact": "correo-o-https-url",
                  "rate": {"min_interval_s": 0.5, "max_concurrent": 2}, "timeout_s": 60, "max_bytes": 268435456,
                  "max_total_s": 3600, "retries": {"max_retries": 4, "retry_statuses": [429]},
                  "identity_contract": {... ver ``_build_contract`` ..., "approval": {"status": "APPROVED", "ref": "..."}}}]}

Principios (FAIL CLOSED): claves desconocidas, valores fuera de rango, dominios no válidos, User-Agent sin contacto real,
credenciales (en claves o valores), rutas de datos operativos y contratos sin versión se RECHAZAN con ``ConfigError``.
Un ``identity_contract`` solo está ACTIVO si lleva ``approval.status == "APPROVED"`` y una referencia: declarado pero sin
aprobar queda inactivo (la identidad sigue siendo ``SLOT_ONLY``). Este módulo no lee red, ni ``.env``, ni datos operativos.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.policy import validate_allowed_domains
from mod_01_ingestion.src.unified.domain.versions import (
    EvidenceKind, IdScope, InitialVersionPolicy, SourceIdentityContract)
from mod_01_ingestion.src.unified.persistence_guard import is_operational_location

CONFIG_SCHEMA_VERSION = "1"
MAX_CONFIG_BYTES = 1 << 20
_TOP = {"schema_version", "config_version", "sources"}
_SOURCE = {"source_id", "authority", "country_code", "allowed_domains", "user_agent", "contact", "rate", "timeout_s",
           "max_bytes", "max_total_s", "retries", "identity_contract"}
_RATE = {"min_interval_s", "max_concurrent"}
_RETRIES = {"max_retries", "retry_statuses"}
_CONTRACT = {"contract_id", "contract_version", "namespace", "id_scope", "normalizer_version", "initial_version_policy",
             "allowed_evidence_kinds", "expected_sha256_authority", "approval"}
_APPROVAL = {"status", "ref"}
_FORBIDDEN_KEYS = frozenset({"password", "passwd", "pwd", "token", "access_token", "refresh_token", "secret",
                             "client_secret", "api_key", "apikey", "authorization", "cookie", "cookies", "credentials",
                             "bearer", "private_key"})
_URL_CREDS = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
_AUTH_VALUE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_PATHLIKE = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")
_UA_RE = re.compile(r"^[\x20-\x7E]{1,200}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PLACEHOLDERS = ("example.", "todo", "changeme", "placeholder", "xxx", "your@", "tu@")
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")


class ConfigError(DomainValidationError):
    """La configuración de fuentes es inválida o insegura (se rechaza entera: nada se aplica a medias)."""


def _err(where: str, why: str):
    raise ConfigError(f"{where}: {why}")


def _scan(obj: Any, where: str) -> None:
    """Credenciales, rutas y caracteres de control en TODA la estructura."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if str(k).lower() in _FORBIDDEN_KEYS:
                _err(f"{where}.{k}", "las credenciales no pueden estar en la configuración")
            _scan(v, f"{where}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _scan(v, f"{where}[{i}]")
    elif isinstance(obj, str):
        if any(ord(c) < 32 or ord(c) == 127 for c in obj):
            _err(where, "caracteres de control no permitidos")
        if _URL_CREDS.search(obj) or _AUTH_VALUE.search(obj):
            _err(where, "valor con apariencia de credencial")
        if _PATHLIKE.match(obj.strip()) or "ARGOS_DATA" in obj.upper():
            _err(where, "las rutas (y en particular las operativas) no pueden estar en la configuración")


def _keys(d: Mapping, allowed: set, where: str) -> None:
    if not isinstance(d, Mapping):
        _err(where, "se esperaba un objeto")
    extra = sorted(set(d) - allowed)
    if extra:
        _err(where, f"claves desconocidas: {extra}")


def _num(d: Mapping, key: str, where: str, lo: float, hi: float, default, integer: bool = False):
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (integer and not isinstance(v, int)):
        _err(f"{where}.{key}", "debe ser un número" + (" entero" if integer else ""))
    if not lo <= v <= hi:
        _err(f"{where}.{key}", f"fuera de rango [{lo}, {hi}]")
    return v


def _build_contract(d: Mapping, authority: str, where: str):
    """Devuelve ``(contrato DECLARADO, aprobado_en_el_archivo)``. Quien decide si se ACTIVA es el llamador: con la aprobación
    declarada en el propio archivo (``SourceConfig.contract``) o, mejor, con el registro auditado de ``approvals``."""
    _keys(d, _CONTRACT, where)
    for req in ("contract_id", "contract_version", "namespace", "id_scope"):
        if not str(d.get(req) or "").strip():
            _err(f"{where}.{req}", "obligatorio (los contratos sin versión se rechazan)")
    approval = d.get("approval") or {}
    _keys(approval, _APPROVAL, f"{where}.approval")
    approved = str(approval.get("status", "")).upper() == "APPROVED" and bool(str(approval.get("ref") or "").strip())
    try:
        kinds = tuple(EvidenceKind(k) for k in d.get("allowed_evidence_kinds", ()))
        contract = SourceIdentityContract(
            contract_id=str(d["contract_id"]), contract_version=str(d["contract_version"]), authority=authority,
            namespace=str(d["namespace"]), id_scope=IdScope(d["id_scope"]),
            normalizer_version=str(d.get("normalizer_version", "v1")), allowed_evidence_kinds=kinds,
            initial_version_policy=InitialVersionPolicy(d.get("initial_version_policy", "NONE")),
            expected_sha256_authority=bool(d.get("expected_sha256_authority", False)))
    except (ValueError, DomainValidationError) as ex:
        raise ConfigError(f"{where}: contrato inválido: {ex}") from ex
    if not isinstance(d.get("expected_sha256_authority", False), bool):
        _err(f"{where}.expected_sha256_authority", "debe ser booleano")
    return contract, approved


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    authority: str
    country_code: str
    allowed_domains: Tuple[str, ...]
    user_agent: str
    contact: str
    min_interval_s: float = 0.5
    max_concurrent: int = 2
    timeout_s: float = 60.0
    max_bytes: int = 256 * 1024 * 1024
    max_total_s: float = 3600.0
    max_retries: int = 4
    retry_statuses: Tuple[int, ...] = ()
    contract: Optional[SourceIdentityContract] = None       # SOLO si está aprobado
    contract_status: str = "NONE"                            # NONE | PENDING_APPROVAL | ACTIVE
    declared_contract: Optional[SourceIdentityContract] = None   # U5C: el contrato declarado, aprobado o no

    @property
    def effective_user_agent(self) -> str:
        return self.user_agent if self.contact in self.user_agent else f"{self.user_agent} ({self.contact})"

    def rate_overrides(self) -> Dict[str, Dict[str, float]]:
        return {d: {"max_concurrent": self.max_concurrent, "min_interval_s": self.min_interval_s}
                for d in self.allowed_domains}


@dataclass(frozen=True)
class SourceConfigSet:
    config_version: str
    sources: Tuple[SourceConfig, ...] = field(default_factory=tuple)

    def get(self, authority: str) -> Optional[SourceConfig]:
        for s in self.sources:
            if s.authority == str(authority).upper():
                return s
        return None

    def rate_overrides(self) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for s in self.sources:
            out.update(s.rate_overrides())
        return out


def _parse_source(d: Mapping, where: str) -> SourceConfig:
    _keys(d, _SOURCE, where)
    sid = str(d.get("source_id") or "")
    if not _SOURCE_ID.match(sid):
        _err(f"{where}.source_id", "obligatorio: minúsculas, dígitos, '_', '.', '-' (2-64)")
    authority = str(d.get("authority") or "").strip().upper()
    country = str(d.get("country_code") or "").strip().upper()
    if not authority or len(country) != 2 or not country.isalpha():
        _err(where, "authority obligatoria y country_code ISO de 2 letras")
    domains = d.get("allowed_domains")
    if not isinstance(domains, (list, tuple)):
        _err(f"{where}.allowed_domains", "debe ser una lista")
    try:
        validate_allowed_domains(tuple(domains))
    except DomainValidationError as ex:
        raise ConfigError(f"{where}.allowed_domains: {ex}") from ex
    ua, contact = d.get("user_agent"), d.get("contact")
    if not isinstance(ua, str) or not _UA_RE.match(ua):
        _err(f"{where}.user_agent", "obligatorio: ASCII imprimible de 1 a 200 caracteres")
    if not isinstance(contact, str) or not (_EMAIL.match(contact) or (contact.startswith("https://") and " " not in contact)):
        _err(f"{where}.contact", "obligatorio: correo o URL https de contacto")
    if any(p in contact.lower() for p in _PLACEHOLDERS) or any(p in ua.lower() for p in ("todo", "changeme", "placeholder")):
        _err(f"{where}.contact", "contacto o User-Agent con aspecto de marcador de posición")
    rate, retries = d.get("rate", {}), d.get("retries", {})
    _keys(rate, _RATE, f"{where}.rate")
    _keys(retries, _RETRIES, f"{where}.retries")
    statuses = retries.get("retry_statuses", [])
    if (not isinstance(statuses, (list, tuple)) or any(isinstance(s, bool) or not isinstance(s, int) or not 400 <= s <= 599
                                                       for s in statuses)):
        _err(f"{where}.retries.retry_statuses", "lista de códigos HTTP 400-599")
    contract, status, declared = None, "NONE", None
    if d.get("identity_contract") is not None:
        declared, approved = _build_contract(d["identity_contract"], authority, f"{where}.identity_contract")
        contract, status = (declared, "ACTIVE") if approved else (None, "PENDING_APPROVAL")
    return SourceConfig(
        source_id=sid, authority=authority, country_code=country, allowed_domains=tuple(domains), user_agent=ua,
        contact=contact, min_interval_s=float(_num(rate, "min_interval_s", f"{where}.rate", 0, 3600, 0.5)),
        max_concurrent=int(_num(rate, "max_concurrent", f"{where}.rate", 1, 32, 2, integer=True)),
        timeout_s=float(_num(d, "timeout_s", where, 1, 600, 60)),
        max_bytes=int(_num(d, "max_bytes", where, 1, 4 * 1024 ** 3, 256 * 1024 * 1024, integer=True)),
        max_total_s=float(_num(d, "max_total_s", where, 1, 86400, 3600)),
        max_retries=int(_num(retries, "max_retries", f"{where}.retries", 0, 10, 4, integer=True)),
        retry_statuses=tuple(sorted(set(statuses))), contract=contract, contract_status=status, declared_contract=declared)


def parse_source_configs(data: Mapping[str, Any]) -> SourceConfigSet:
    _keys(data, _TOP, "config")
    _scan(data, "config")
    if str(data.get("schema_version")) != CONFIG_SCHEMA_VERSION:
        _err("config.schema_version", f"versión de esquema no soportada (se espera {CONFIG_SCHEMA_VERSION!r})")
    if not str(data.get("config_version") or "").strip():
        _err("config.config_version", "obligatorio")
    raw = data.get("sources")
    if not isinstance(raw, list) or not raw:
        _err("config.sources", "debe ser una lista no vacía")
    parsed = tuple(_parse_source(s, f"sources[{i}]") for i, s in enumerate(raw))
    for attr in ("source_id", "authority"):
        vals = [getattr(s, attr) for s in parsed]
        if len(set(vals)) != len(vals):
            _err("config.sources", f"{attr} duplicado")
    seen: Dict[str, Tuple[float, int]] = {}
    for s in parsed:
        for dom in s.allowed_domains:
            if dom in seen and seen[dom] != (s.min_interval_s, s.max_concurrent):
                _err("config.sources", f"el dominio {dom} tiene límites de tasa contradictorios entre fuentes")
            seen[dom] = (s.min_interval_s, s.max_concurrent)
    return SourceConfigSet(config_version=str(data["config_version"]), sources=parsed)


def load_source_configs(source: Union[str, Path, Mapping[str, Any]]) -> SourceConfigSet:
    """Carga desde un dict o un archivo JSON. Se niega a leer un archivo de una ubicación operativa."""
    if isinstance(source, Mapping):
        return parse_source_configs(source)
    p = Path(source)
    if is_operational_location(p):
        raise ConfigError("la configuración no puede leerse de una ubicación operativa de datos")
    try:
        if p.stat().st_size > MAX_CONFIG_BYTES:
            raise ConfigError("configuración demasiado grande")
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise ConfigError(f"configuración ilegible: {type(ex).__name__}") from ex
    return parse_source_configs(data)
