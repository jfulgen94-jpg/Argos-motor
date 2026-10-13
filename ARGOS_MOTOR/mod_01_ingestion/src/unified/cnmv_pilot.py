"""
U5E — Artefactos PENDIENTES de configuración, contrato y plan del piloto CNMV (un único documento de control).

Los tres artefactos viven en ``mod_01_ingestion/config/pilot/cnmv/*.pending.json`` y están en ``PENDING_APPROVAL``: son
PLANTILLAS versionables, no configuración activa. Cada valor que falta (User-Agent, contacto, namespace, ``id_scope``, evidencia
de republicación, procedencia oficial del dominio/URL/SHA) lleva un MARCADOR (``PENDING_APPROVAL…`` / ``REQUIRES_OFFICIAL_EVIDENCE``)
y NADA se inventa. Este módulo solo lee JSON del checkout: sin red, sin DuckDB, sin escritura y sin tocar D:.

Activación (``activate``): solo si, a la vez,
1. ningún campo sustantivo conserva un marcador,
2. los tres contenidos están APROBADOS en el ``ApprovalRegistry`` con ese contenido exacto (cambiar URL, NIF, año, tipo, hash o
   límites cambia la huella y la aprobación deja de valer; cuatro ojos lo impone el propio registro) y
3. la coherencia plan↔configuración se cumple.
Un User-Agent marcador no es activable aunque alguien lo apruebe por error en el registro. Los campos administrativos ``status``
no entran en la huella.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.config import PathPolicyError
from mod_01_ingestion.src.unified.data_root import validate_unified_root
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.policy import validate_allowed_domains
from mod_01_ingestion.src.unified.persistence_guard import is_operational_location
from mod_01_ingestion.src.unified.pilot import PilotLimits, PilotPlan
from mod_01_ingestion.src.unified.source_config import (
    _FORBIDDEN_KEYS, ConfigError, SourceConfigSet, _scan, parse_source_configs)

PENDING = "PENDING_APPROVAL"
NEEDS_EVIDENCE = "REQUIRES_OFFICIAL_EVIDENCE"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "config" / "pilot" / "cnmv"
FILES = {"config": "source_config.pending.json", "contract": "identity_contract.pending.json",
         "plan": "pilot_plan.pending.json"}
_ADMIN_KEYS = frozenset({"status", "artifact"})
_NIF = re.compile(r"^[A-Z]\d{7}[A-Z0-9]$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_KEYS = {"artifact", "status", "schema_version", "config_version", "official_evidence_ref", "source"}
_SOURCE_KEYS = {"source_id", "authority", "country_code", "allowed_domains", "allowed_domains_evidence", "user_agent", "contact",
                "rate", "timeout_s", "max_total_s", "max_bytes", "retries", "http_403_policy"}
_CONTRACT_KEYS = {"artifact", "status", "contract_id", "contract_version", "authority", "normalizer_version",
                  "initial_version_policy", "expected_sha256_authority", "namespace", "id_scope", "source_document_id_field",
                  "allowed_evidence_kinds", "republication_evidence"}
_PLAN_KEYS = {"artifact", "status", "plan_version", "authority", "single_source", "control_document", "limits",
              "destination_root", "destination_status", "gates"}
_CONTROL_KEYS = {"issuer_name", "ticker", "nif", "fiscal_year", "year_semantics", "document_family", "candidate_url", "url_status",
                 "local_control_sha256", "local_control_size_bytes", "local_control_origin", "control_status"}
_LIMIT_KEYS = {"max_documents", "max_concurrent", "min_interval_s", "request_timeout_s", "max_total_s", "max_bytes_per_document",
               "max_total_bytes", "allowed_domains"}
_GATE_KEYS = {"canary_sandbox_ok_required", "four_eyes_required", "max_canary_age_s"}


class PilotArtifactError(DomainValidationError):
    """Un artefacto pendiente es inválido o inseguro (se rechaza entero)."""


class NotActivatable(DomainValidationError):
    def __init__(self, blockers: List[str]):
        super().__init__("no activable: " + ", ".join(blockers))
        self.blockers = list(blockers)


def is_marker(v: Any) -> bool:
    return isinstance(v, str) and (v.strip() == "" or v.startswith((PENDING, NEEDS_EVIDENCE)) or "NOT_ACTIVATABLE" in v)


def find_markers(obj: Any, path: str = "") -> List[str]:
    """Rutas de los campos SUSTANTIVOS que siguen siendo un marcador (los campos administrativos no cuentan)."""
    out: List[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k in _ADMIN_KEYS:
                continue
            out += find_markers(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += find_markers(v, f"{path}[{i}]")
    elif is_marker(obj):
        out.append(path)
    return out


def _keys(d: Any, allowed: set, where: str) -> None:
    if not isinstance(d, Mapping):
        raise PilotArtifactError(f"{where}: se esperaba un objeto")
    extra = sorted(set(d) - allowed)
    missing = sorted(allowed - set(d))
    if extra or missing:
        raise PilotArtifactError(f"{where}: claves desconocidas {extra} / ausentes {missing}")


def _no_credentials(obj: Any, where: str) -> None:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if str(k).lower() in _FORBIDDEN_KEYS:
                raise PilotArtifactError(f"{where}.{k}: las credenciales no pueden estar en un artefacto")
            _no_credentials(v, f"{where}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _no_credentials(v, f"{where}[{i}]")


def _content(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Contenido sustantivo (sin campos administrativos): es lo que se aprueba y lo que fija la huella."""
    return {k: copy.deepcopy(v) for k, v in data.items() if k not in _ADMIN_KEYS}


@dataclass(frozen=True)
class CnmvPilotArtifacts:
    config: Dict[str, Any]
    contract: Dict[str, Any]
    plan: Dict[str, Any]

    # ---- identificadores de aprobación
    @property
    def source_id(self) -> str:
        return self.config["source"]["source_id"]

    def subjects(self) -> Dict[str, Dict[str, Any]]:
        return {"SOURCE_CONFIG": {"subject_id": self.source_id, "version": self.config["config_version"],
                                  "content": _content(self.config)},
                "IDENTITY_CONTRACT": {"subject_id": self.source_id, "version": self.contract["contract_version"],
                                      "content": _content(self.contract)},
                "PILOT_PLAN": {"subject_id": "pilot:CNMV", "version": self.plan["plan_version"], "content": _content(self.plan)}}

    # ---- bloqueos de activación (sin registro)
    def blockers(self) -> List[str]:
        out = [f"{name.upper()}_MARKER:{p}" for name, art in (("config", self.config), ("contract", self.contract),
                                                              ("plan", self.plan)) for p in find_markers(art)]
        return sorted(out)

    # ---- construcción de la configuración REAL (solo si no hay marcadores)
    def source_config_set(self) -> SourceConfigSet:
        marks = self.blockers()
        if marks:
            raise NotActivatable(marks)
        s, c = self.config["source"], self.contract
        contract = {"contract_id": c["contract_id"], "contract_version": c["contract_version"], "namespace": c["namespace"],
                    "id_scope": c["id_scope"], "normalizer_version": c["normalizer_version"],
                    "initial_version_policy": c["initial_version_policy"],
                    "allowed_evidence_kinds": list(c["allowed_evidence_kinds"]),
                    "expected_sha256_authority": c["expected_sha256_authority"]}
        src = {"source_id": s["source_id"], "authority": s["authority"], "country_code": s["country_code"],
               "allowed_domains": list(s["allowed_domains"]), "user_agent": s["user_agent"], "contact": s["contact"],
               "rate": dict(s["rate"]), "timeout_s": s["timeout_s"], "max_bytes": s["max_bytes"], "max_total_s": s["max_total_s"],
               "retries": {"max_retries": s["retries"]["max_retries"], "retry_statuses": list(s["retries"]["retry_statuses"])},
               "identity_contract": contract}
        try:
            return parse_source_configs({"schema_version": self.config["schema_version"],
                                         "config_version": self.config["config_version"], "sources": [src]})
        except ConfigError as ex:
            raise NotActivatable([f"CONFIG_INVALID:{ex}"]) from ex

    def pilot_plan(self) -> PilotPlan:
        p = self.plan
        lim = p["limits"]
        return PilotPlan(authority="CNMV", config_version=self.config["config_version"],
                         limits=PilotLimits(allowed_domains=tuple(lim["allowed_domains"]), max_documents=lim["max_documents"],
                                            max_bytes_per_document=lim["max_bytes_per_document"],
                                            max_total_bytes=lim["max_total_bytes"], max_total_s=float(lim["max_total_s"])),
                         root=p["destination_root"], plan_version=p["plan_version"])


# ================================================================== validación estructural (fail closed)
def _validate_config(d: Mapping[str, Any]) -> None:
    _keys(d, _CONFIG_KEYS, "config")
    if d["artifact"] != "CNMV_SOURCE_CONFIG" or d["status"] != PENDING:
        raise PilotArtifactError("config: artifact/status inválidos (el archivo solo puede estar en PENDING_APPROVAL)")
    _no_credentials(d, "config")
    _scan(d, "config")
    s = d["source"]
    _keys(s, _SOURCE_KEYS, "config.source")
    if (s["source_id"], s["authority"], s["country_code"]) != ("cnmv_pilot", "CNMV", "ES"):
        raise PilotArtifactError("config: solo la fuente cnmv_pilot / CNMV / ES")
    doms = s["allowed_domains"]
    if not isinstance(doms, list) or doms != ["www.cnmv.es"]:
        raise PilotArtifactError("config: dominio único www.cnmv.es")
    validate_allowed_domains(tuple(doms))
    if s["http_403_policy"] != "PERMANENT_NO_RETRY" or 403 in s["retries"].get("retry_statuses", []):
        raise PilotArtifactError("config: 403 es permanente (no reintentable)")
    if s["rate"].get("max_concurrent") != 1 or s["rate"].get("min_interval_s", 0) < 5:
        raise PilotArtifactError("config: 1 petición concurrente y al menos 5 s entre peticiones")
    if not (0 < s["timeout_s"] <= 60 and 0 < s["max_total_s"] <= 300 and 0 < s["max_bytes"] <= 64 * 1024 * 1024):
        raise PilotArtifactError("config: límites fuera de los del piloto (60 s, 300 s, 64 MiB)")
    if s["retries"].get("max_retries", 99) > 2:
        raise PilotArtifactError("config: como máximo 2 reintentos")


def _validate_contract(d: Mapping[str, Any]) -> None:
    _keys(d, _CONTRACT_KEYS, "contract")
    if d["artifact"] != "CNMV_IDENTITY_CONTRACT" or d["status"] != PENDING or d["authority"] != "CNMV":
        raise PilotArtifactError("contract: artifact/status/authority inválidos")
    _no_credentials(d, "contract")
    _scan(d, "contract")
    if d["initial_version_policy"] != "NONE" or d["expected_sha256_authority"] is not False:
        raise PilotArtifactError("contract: política inicial NONE y sin autoridad de hash hasta tener evidencia oficial")


def _validate_plan(d: Mapping[str, Any]) -> None:
    _keys(d, _PLAN_KEYS, "plan")
    if d["artifact"] != "CNMV_PILOT_PLAN" or d["status"] != PENDING or d["authority"] != "CNMV" or d["single_source"] is not True:
        raise PilotArtifactError("plan: artifact/status/authority inválidos o no es de fuente única")
    _no_credentials(d, "plan")
    c, lim, g = d["control_document"], d["limits"], d["gates"]
    _keys(c, _CONTROL_KEYS, "plan.control_document")
    _keys(lim, _LIMIT_KEYS, "plan.limits")
    _keys(g, _GATE_KEYS, "plan.gates")
    if lim["max_documents"] != 1 or lim["max_concurrent"] != 1:
        raise PilotArtifactError("plan: exactamente 1 documento y 1 petición concurrente")
    if lim["allowed_domains"] != ["www.cnmv.es"]:
        raise PilotArtifactError("plan: dominio único www.cnmv.es")
    if not _NIF.match(str(c["nif"])) or c["ticker"] != "TEF" or c["fiscal_year"] != 2019 or c["document_family"] != "ANNUAL_REPORT_PDF":
        raise PilotArtifactError("plan: el documento de control es exactamente TEF / A28015865 / 2019 / informe anual PDF")
    u = urlsplit(str(c["candidate_url"]))
    if u.scheme != "https" or u.hostname != "www.cnmv.es" or u.username or u.password or u.query or u.fragment:
        raise PilotArtifactError("plan: la URL candidata debe ser https://www.cnmv.es/… sin credenciales ni query")
    if not _SHA.match(str(c["local_control_sha256"])) or not isinstance(c["local_control_size_bytes"], int) \
            or not 0 < c["local_control_size_bytes"] <= lim["max_bytes_per_document"]:
        raise PilotArtifactError("plan: SHA-256 y tamaño de control inválidos")
    if d["destination_status"] != "NOT_CREATED":
        raise PilotArtifactError("plan: el destino no se crea en esta unidad (destination_status=NOT_CREATED)")
    if g["canary_sandbox_ok_required"] is not True or g["four_eyes_required"] is not True:
        raise PilotArtifactError("plan: canario SANDBOX OK y cuatro ojos son obligatorios")
    PilotLimits(allowed_domains=tuple(lim["allowed_domains"]), max_documents=lim["max_documents"],
                max_bytes_per_document=lim["max_bytes_per_document"], max_total_bytes=lim["max_total_bytes"],
                max_total_s=float(lim["max_total_s"]))
    try:
        validate_unified_root(d["destination_root"], ExecutionMode.PILOT)       # no toca el disco
    except PathPolicyError as ex:
        raise PilotArtifactError(f"plan.destination_root: {ex}") from ex


def parse_artifacts(config: Mapping[str, Any], contract: Mapping[str, Any], plan: Mapping[str, Any]) -> CnmvPilotArtifacts:
    _validate_config(config)
    _validate_contract(contract)
    _validate_plan(plan)
    return CnmvPilotArtifacts(copy.deepcopy(dict(config)), copy.deepcopy(dict(contract)), copy.deepcopy(dict(plan)))


def load_artifacts(directory: Optional[Path] = None) -> CnmvPilotArtifacts:
    """Carga los tres artefactos del checkout. Se niega a leer de una ubicación operativa de datos."""
    base = Path(directory) if directory is not None else ARTIFACT_DIR
    if is_operational_location(base):
        raise PilotArtifactError("los artefactos no pueden leerse de una ubicación operativa de datos")
    loaded = {}
    for key, name in FILES.items():
        p = base / name
        try:
            if p.stat().st_size > (1 << 20):
                raise PilotArtifactError(f"{name}: demasiado grande")
            loaded[key] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            raise PilotArtifactError(f"{name}: ilegible ({type(ex).__name__})") from ex
    return parse_artifacts(loaded["config"], loaded["contract"], loaded["plan"])


# ================================================================== aprobación y activación
def submit_pending(art: CnmvPilotArtifacts, registry: ApprovalRegistry, submitted_by: str) -> Dict[str, str]:
    """Envía al registro los tres contenidos. Devuelve sus estados (PENDING_APPROVAL). No aprueba ni activa nada."""
    return {kind: registry.submit(s["subject_id"], kind, s["version"], s["content"], submitted_by)
            for kind, s in art.subjects().items()}


@dataclass
class ActivationResult:
    active: bool
    blockers: List[str] = field(default_factory=list)
    configs: Optional[SourceConfigSet] = None
    plan: Optional[PilotPlan] = None


def _coherence(art: CnmvPilotArtifacts) -> List[str]:
    s, p = art.config["source"], art.plan
    lim, out = p["limits"], []
    if lim["allowed_domains"] != s["allowed_domains"]:
        out.append("PLAN_DOMAINS_DIFFER_FROM_CONFIG")
    if lim["max_bytes_per_document"] > s["max_bytes"]:
        out.append("PLAN_BYTES_EXCEED_CONFIG")
    if lim["request_timeout_s"] > s["timeout_s"] or lim["max_total_s"] > s["max_total_s"]:
        out.append("PLAN_TIME_EXCEEDS_CONFIG")
    if lim["min_interval_s"] < s["rate"]["min_interval_s"] or lim["max_concurrent"] != s["rate"]["max_concurrent"]:
        out.append("PLAN_RATE_INCONSISTENT_WITH_CONFIG")
    if art.contract["authority"] != s["authority"]:
        out.append("CONTRACT_AUTHORITY_MISMATCH")
    return out


def activate(art: CnmvPilotArtifacts, registry: ApprovalRegistry) -> ActivationResult:
    """ÚNICA vía de activación: marcadores resueltos + los tres contenidos exactos APROBADOS en el registro."""
    blockers = art.blockers() + _coherence(art)
    for kind, s in art.subjects().items():
        if not registry.is_active(s["subject_id"], kind, s["version"], s["content"]):
            blockers.append(f"{kind}_{registry.status(s['subject_id'], kind, s['version']) or 'NOT_SUBMITTED'}")
    if blockers:
        return ActivationResult(False, sorted(set(blockers)))
    cfgs = art.source_config_set()
    s = cfgs.sources[0]
    active = dataclasses.replace(s, contract=s.declared_contract, contract_status="ACTIVE")    # el registro aprobó el contrato
    return ActivationResult(True, [], SourceConfigSet(config_version=cfgs.config_version, sources=(active,)), art.pilot_plan())
