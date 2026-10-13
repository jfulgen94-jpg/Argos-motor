"""
U5D — Preparación de un piloto controlado de UNA fuente (SEC o CNMV). Este módulo NO descarga: no importa el servicio de
descarga, el runner ni ningún adapter; solo prepara el plan, lo envía a aprobación, evalúa la puerta de entrada y ofrece un
presupuesto que la ejecución futura deberá consumir.

Flujo:
1. ``build_pilot_plan``: una única fuente (``PILOT_AUTHORITIES``), límites estrictos (documentos, tamaño, tiempo, dominios) y
   comprobación contra la configuración de la fuente (los dominios del piloto solo pueden ESTRECHAR los de la configuración).
2. ``submit_pilot``: envía a aprobación la configuración de ESA fuente, su contrato declarado y el plan (PILOT_PLAN). Todo queda en
   ``PENDING_APPROVAL``; nada se aprueba aquí.
3. ``evaluate_gate``: puerta de entrada. Solo permite si hay raíz unificado válido e inicializado, plan + configuración + contrato
   APROBADOS (con el contenido exacto enviado) y un canario SANDBOX reciente y en estado OK. Devuelve la lista de bloqueos.
4. ``PilotBudget``: contador de la ejecución futura; rechaza otra fuente, dominios no listados y excesos de documentos/bytes/tiempo.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from mod_01_ingestion.src.unified.approvals import (ApprovalRegistry, config_content, contract_content, fingerprint,
                                                   submit_configs)
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore, _parse
from mod_01_ingestion.src.unified.config import PathPolicyError
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot, validate_unified_root
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.source_config import SourceConfigSet

PILOT_AUTHORITIES = ("SEC", "CNMV")
PLAN_KIND = "PILOT_PLAN"
HARD_MAX_DOCUMENTS = 50
HARD_MAX_BYTES_PER_DOCUMENT = 256 * 1024 * 1024
HARD_MAX_TOTAL_BYTES = 2 * 1024 ** 3
HARD_MAX_TOTAL_S = 3600.0


class PilotError(DomainValidationError):
    pass


class PilotLimitExceeded(PilotError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _int(name: str, v: Any, hard: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > hard:
        raise PilotError(f"{name} debe ser un entero entre 1 y {hard}")
    return v


@dataclass(frozen=True)
class PilotLimits:
    allowed_domains: Tuple[str, ...]
    max_documents: int = 10
    max_bytes_per_document: int = 64 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_total_s: float = 1800.0

    def __post_init__(self):
        _int("max_documents", self.max_documents, HARD_MAX_DOCUMENTS)
        _int("max_bytes_per_document", self.max_bytes_per_document, HARD_MAX_BYTES_PER_DOCUMENT)
        _int("max_total_bytes", self.max_total_bytes, HARD_MAX_TOTAL_BYTES)
        if self.max_bytes_per_document > self.max_total_bytes:
            raise PilotError("max_bytes_per_document no puede superar max_total_bytes")
        if isinstance(self.max_total_s, bool) or not isinstance(self.max_total_s, (int, float)) \
                or not 0 < self.max_total_s <= HARD_MAX_TOTAL_S:
            raise PilotError(f"max_total_s debe estar en (0, {HARD_MAX_TOTAL_S}]")
        doms = tuple(sorted({str(d).strip().lower() for d in self.allowed_domains}))
        if not doms or any((not d) or "/" in d or ":" in d or "*" in d or " " in d or "." not in d for d in doms):
            raise PilotError("allowed_domains: al menos un host (sin esquema, ruta ni comodines)")
        object.__setattr__(self, "allowed_domains", doms)

    def to_dict(self) -> Dict[str, Any]:
        return {"allowed_domains": list(self.allowed_domains), "max_documents": self.max_documents,
                "max_bytes_per_document": self.max_bytes_per_document, "max_total_bytes": self.max_total_bytes,
                "max_total_s": float(self.max_total_s)}


@dataclass(frozen=True)
class PilotPlan:
    authority: str
    config_version: str
    limits: PilotLimits
    root: str
    plan_version: str = "1"
    mode: str = ExecutionMode.PILOT.value

    @property
    def subject_id(self) -> str:
        return f"pilot:{self.authority}"

    def content(self) -> Dict[str, Any]:
        return {"authority": self.authority, "config_version": self.config_version, "limits": self.limits.to_dict(),
                "root": self.root, "plan_version": self.plan_version, "mode": self.mode, "single_source": True}


def build_pilot_plan(configs: SourceConfigSet, authority: str, limits: PilotLimits, root: UnifiedDataRoot,
                     plan_version: str = "1") -> PilotPlan:
    authority = str(authority).upper()
    if authority not in PILOT_AUTHORITIES:
        raise PilotError(f"el piloto admite una única fuente de {PILOT_AUTHORITIES}, no {authority!r}")
    cfg = configs.get(authority)
    if cfg is None:
        raise PilotError(f"no hay configuración para {authority}")
    extra = [d for d in limits.allowed_domains
             if not any(d == c or d.endswith("." + c) for c in (x.lower() for x in cfg.allowed_domains))]
    if extra:
        raise PilotError(f"dominios del piloto fuera de la configuración de la fuente: {extra}")
    if limits.max_bytes_per_document > cfg.max_bytes:
        raise PilotError("max_bytes_per_document del piloto supera el máximo de la configuración de la fuente")
    if root.mode is not ExecutionMode.PILOT:
        raise PilotError("el piloto exige un raíz unificado en modo PILOT")
    validate_unified_root(root.path, ExecutionMode.PILOT)
    return PilotPlan(authority=authority, config_version=configs.config_version, limits=limits, root=str(root.path),
                     plan_version=plan_version)


def _single(configs: SourceConfigSet, authority: str) -> SourceConfigSet:
    cfg = configs.get(authority)
    return SourceConfigSet(config_version=configs.config_version, sources=(cfg,) if cfg else ())


def submit_pilot(plan: PilotPlan, configs: SourceConfigSet, registry: ApprovalRegistry, submitted_by: str) -> Dict[str, str]:
    """Envía a aprobación config+contrato de ESA fuente y el plan. Devuelve los estados (PENDING_APPROVAL). No aprueba ni descarga."""
    out = submit_configs(_single(configs, plan.authority), registry, submitted_by)
    out[f"{plan.subject_id}:{PLAN_KIND}"] = registry.submit(plan.subject_id, PLAN_KIND, plan.plan_version, plan.content(),
                                                            submitted_by)
    return out


def write_plan(root: UnifiedDataRoot, plan: PilotPlan) -> Path:
    """Copia de auditoría del plan en ``reports/pilot/`` (requiere raíz inicializado; nunca crea el raíz)."""
    if not root.is_initialized():
        raise PilotError("el raíz unificado no está inicializado")
    d = root.layout.reports / "pilot"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"pilot_plan_{plan.authority}_v{plan.plan_version}.json"
    p.write_text(json.dumps({**plan.content(), "content_hash": fingerprint(plan.content())}, indent=2, sort_keys=True),
                 encoding="utf-8")
    return p


@dataclass
class PilotDecision:
    allowed: bool
    blockers: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "blockers": list(self.blockers), "details": dict(self.details)}


def evaluate_gate(plan: PilotPlan, configs: SourceConfigSet, registry: ApprovalRegistry, store: CanaryReportStore, *,
                  now_iso: str, max_canary_age_s: float = 86400.0) -> PilotDecision:
    """Puerta de entrada del piloto. NO ejecuta nada: solo informa si podría empezar y, si no, por qué."""
    blockers: List[str] = []
    details: Dict[str, Any] = {"authority": plan.authority}
    if plan.authority not in PILOT_AUTHORITIES:
        blockers.append("AUTHORITY_NOT_ALLOWED")
    if plan.mode != ExecutionMode.PILOT.value:
        blockers.append("MODE_NOT_PILOT")
    try:
        validate_unified_root(plan.root, ExecutionMode.PILOT)
    except PathPolicyError:
        blockers.append("ROOT_INVALID")
    else:
        if not UnifiedDataRoot(Path(plan.root), ExecutionMode.PILOT).is_initialized():
            blockers.append("ROOT_NOT_INITIALIZED")
    # plan aprobado con su contenido exacto
    st = registry.status(plan.subject_id, PLAN_KIND, plan.plan_version)
    if not registry.is_active(plan.subject_id, PLAN_KIND, plan.plan_version, plan.content()):
        blockers.append(f"PLAN_{st or 'NOT_SUBMITTED'}")
    # configuración + contrato aprobados
    single = _single(configs, plan.authority)
    if not single.sources:
        blockers.append("CONFIG_MISSING")
    else:
        cfg = single.sources[0]
        if not registry.is_active(cfg.source_id, "SOURCE_CONFIG", configs.config_version, config_content(cfg)):
            blockers.append(f"SOURCE_CONFIG_{registry.status(cfg.source_id, 'SOURCE_CONFIG', configs.config_version) or 'NOT_SUBMITTED'}")
        c = cfg.declared_contract
        if c is None:
            blockers.append("CONTRACT_REQUIRED")
        elif not registry.is_active(cfg.source_id, "IDENTITY_CONTRACT", c.contract_version, contract_content(c)):
            blockers.append(f"IDENTITY_CONTRACT_{registry.status(cfg.source_id, 'IDENTITY_CONTRACT', c.contract_version) or 'NOT_SUBMITTED'}")
    # canario SANDBOX reciente y OK
    reps = store.latest(plan.authority, 1)
    if not reps:
        blockers.append("CANARY_MISSING")
    else:
        rep = reps[0]
        details["canary"] = {"report_id": rep["report_id"], "status": rep["status"], "finished_at": rep["finished_at"]}
        if rep["mode"] not in (ExecutionMode.SANDBOX.value, ExecutionMode.TEST.value):
            blockers.append("CANARY_MODE_INVALID")
        if rep["status"] != "OK":
            blockers.append(f"CANARY_{rep['status']}")
        if (_parse(now_iso) - _parse(rep["finished_at"])).total_seconds() > max_canary_age_s:
            blockers.append("CANARY_STALE")
    return PilotDecision(allowed=not blockers, blockers=sorted(set(blockers)), details=details)


class PilotBudget:
    """Presupuesto que la ejecución futura del piloto debe consumir. Sin red, sin disco."""

    def __init__(self, plan: PilotPlan, *, clock: Callable[[], float] = time.monotonic):
        self.plan, self._clock = plan, clock
        self._t0: Optional[float] = None
        self.documents = 0
        self.total_bytes = 0

    def start(self) -> None:
        self._t0 = self._clock()

    def check_time(self) -> None:
        if self._t0 is None:
            raise PilotError("el presupuesto no se inició (start)")
        if self._clock() - self._t0 > self.plan.limits.max_total_s:
            raise PilotLimitExceeded("PILOT_TIME_EXCEEDED", f"más de {self.plan.limits.max_total_s}s")

    def begin_document(self, authority: str, url: str) -> None:
        self.check_time()
        if str(authority).upper() != self.plan.authority:
            raise PilotLimitExceeded("PILOT_SINGLE_SOURCE", f"el piloto solo admite {self.plan.authority}")
        host = (urlsplit(url).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in self.plan.limits.allowed_domains):
            raise PilotLimitExceeded("PILOT_DOMAIN_NOT_ALLOWED", f"dominio fuera del piloto: {host or '?'}")
        if self.documents >= self.plan.limits.max_documents:
            raise PilotLimitExceeded("PILOT_MAX_DOCUMENTS", f"máximo {self.plan.limits.max_documents} documentos")
        self.documents += 1

    def record_bytes(self, n: int) -> None:
        if n > self.plan.limits.max_bytes_per_document:
            raise PilotLimitExceeded("PILOT_DOCUMENT_TOO_LARGE", f"{n} > {self.plan.limits.max_bytes_per_document}")
        if self.total_bytes + n > self.plan.limits.max_total_bytes:
            raise PilotLimitExceeded("PILOT_TOTAL_BYTES", f"supera {self.plan.limits.max_total_bytes}")
        self.total_bytes += n
