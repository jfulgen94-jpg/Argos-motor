"""
U5F — Ejecución AUTORIZADA del piloto CNMV de un único documento (Telefónica, ejercicio 2019, informe anual PDF).

Este módulo es la única pieza que, con una autorización explícita, une los artefactos de ``cnmv_pilot`` con el pipeline unificado:

1. valida la autorización (frase exacta, solicitante ≠ aprobadora, referencia y User-Agent con contacto);
2. completa los artefactos con los valores autorizados (identidad ``SLOT_ONLY``: el contrato NO se activa) y los registra en el
   ``ApprovalRegistry`` (solicitud + aprobación de cuatro ojos) dentro de la raíz aislada;
3. inicializa la raíz y ejecuta un canario SANDBOX offline (replay sintético en un directorio temporal) cuyo informe se guarda;
4. evalúa la puerta (aprobaciones + límites coherentes + raíz inicializada + canario OK reciente);
5. SOLO si la puerta permite, hace UNA descarga con ``PilotDownloadService`` (1 reintento como máximo y solo para 429/503; 403 no
   se reintenta y queda en ``NEEDS_REVIEW``), sin tocar ``raw/ES_CNMV``; registra hash, manifiesto, catálogo, ledger y telemetría.

El cliente HTTP es inyectable (``client``): las pruebas usan un transporte simulado; la ejecución real pasa ``None``.
"""
from __future__ import annotations

import dataclasses
import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.canary import run_canary
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore
from mod_01_ingestion.src.unified.cnmv_pilot import (CnmvPilotArtifacts, find_markers, load_artifacts, parse_artifacts)
from mod_01_ingestion.src.unified.configured_adapter import ConfiguredAdapter
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus, record_outcome
from mod_01_ingestion.src.unified.data_root import DEFAULT_PILOT_ROOT, UnifiedDataRoot, validate_unified_root
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DownloadRequest, DownloadResult, RunContext
from mod_01_ingestion.src.unified.pilot import PilotBudget, PilotLimitExceeded
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.router import SourceRouter
from mod_01_ingestion.src.unified.sandbox_replay import ReplayHttp, make_sandbox_runner
from mod_01_ingestion.src.unified.source_config import SourceConfigSet, parse_source_configs

AUTH_PHRASE = "AUTORIZO PILOTO CNMV TEF 2019"
RETRY_ONCE_STATUSES = frozenset({429, 503})
_EMAIL_IN_UA = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
SANDBOX_PDF = b"%PDF-1.4\n" + (b"1 0 obj << /Type /Catalog >> endobj\n" * 8) + b"%%EOF\n"
SANDBOX_URL = "https://www.cnmv.es/AUDITA/2019/18290.pdf"


class PilotRunError(DomainValidationError):
    pass


@dataclass(frozen=True)
class PilotAuthorization:
    phrase: str
    requester: str
    approver: str
    reference: str
    user_agent: str

    def __post_init__(self):
        if self.phrase != AUTH_PHRASE:
            raise PilotRunError("autorización no válida: la frase debe ser exactamente la acordada")
        for n in ("requester", "approver", "reference", "user_agent"):
            if not str(getattr(self, n) or "").strip():
                raise PilotRunError(f"autorización: {n} obligatorio")
        if self.requester.strip().casefold() == self.approver.strip().casefold():
            raise PilotRunError("autorización: solicitante y aprobadora deben ser personas distintas (cuatro ojos)")
        if not _EMAIL_IN_UA.search(self.user_agent) or any(p in self.user_agent.lower() for p in ("todo", "changeme", "placeholder")):
            raise PilotRunError("autorización: el User-Agent debe llevar un contacto real")

    @property
    def contact(self) -> str:
        return _EMAIL_IN_UA.search(self.user_agent).group(0)


def complete_artifacts(art: CnmvPilotArtifacts, auth: PilotAuthorization, root: Path) -> CnmvPilotArtifacts:
    """Sustituye los marcadores de configuración y plan por los valores autorizados. El contrato queda INTACTO (SLOT_ONLY)."""
    cfg, plan = json.loads(json.dumps(art.config)), json.loads(json.dumps(art.plan))
    ref = f"OWNER_AUTHORIZATION:{auth.reference}"
    cfg["config_version"] = "cnmv-pilot-1"
    cfg["official_evidence_ref"] = ref
    cfg["source"].update(allowed_domains_evidence=ref, user_agent=auth.user_agent, contact=auth.contact)
    plan["plan_version"] = "1"
    plan["control_document"].update(year_semantics=f"OWNER_STATED_FISCAL_YEAR_2019:{auth.reference}",
                                    url_status=f"OWNER_AUTHORIZED_NOT_INDEPENDENTLY_VERIFIED:{auth.reference}",
                                    control_status=f"LOCAL_MANIFEST_CONTROL_NOT_OFFICIAL:{auth.reference}")
    plan["destination_root"] = str(root).replace("\\", "/")
    return parse_artifacts(cfg, art.contract, plan)


def slot_only_blockers(art: CnmvPilotArtifacts, registry: ApprovalRegistry) -> List[str]:
    """Activación del piloto con identidad SLOT_ONLY: config y plan sin marcadores y APROBADOS en el registro."""
    from mod_01_ingestion.src.unified.cnmv_pilot import _coherence          # coherencia plan↔config (misma regla)
    out = [f"{n}_MARKER:{p}" for n, d in (("CONFIG", art.config), ("PLAN", art.plan)) for p in find_markers(d)] + _coherence(art)
    for kind in ("SOURCE_CONFIG", "PILOT_PLAN"):
        s = art.subjects()[kind]
        if not registry.is_active(s["subject_id"], kind, s["version"], s["content"]):
            out.append(f"{kind}_{registry.status(s['subject_id'], kind, s['version']) or 'NOT_SUBMITTED'}")
    return sorted(set(out))


def slot_only_configs(art: CnmvPilotArtifacts) -> SourceConfigSet:
    s = art.config["source"]
    return parse_source_configs({"schema_version": art.config["schema_version"], "config_version": art.config["config_version"],
                                 "sources": [{"source_id": s["source_id"], "authority": s["authority"],
                                              "country_code": s["country_code"], "allowed_domains": list(s["allowed_domains"]),
                                              "user_agent": s["user_agent"], "contact": s["contact"], "rate": dict(s["rate"]),
                                              "timeout_s": s["timeout_s"], "max_bytes": s["max_bytes"],
                                              "max_total_s": s["max_total_s"],
                                              "retries": {"max_retries": s["retries"]["max_retries"],
                                                          "retry_statuses": list(s["retries"]["retry_statuses"])}}]})


@dataclass
class GateDecision:
    allowed: bool
    blockers: List[str] = field(default_factory=list)
    canary: Optional[Dict[str, Any]] = None


def evaluate_gate(art: CnmvPilotArtifacts, registry: ApprovalRegistry, store: CanaryReportStore, root: UnifiedDataRoot, *,
                  now_iso: str) -> GateDecision:
    blockers = slot_only_blockers(art, registry)
    if not root.is_initialized():
        blockers.append("ROOT_NOT_INITIALIZED")
    gates = art.plan["gates"]
    reps = store.latest("CNMV", 1)
    canary = None
    if not reps:
        blockers.append("CANARY_MISSING")
    else:
        rep = reps[0]
        canary = {"report_id": rep["report_id"], "status": rep["status"], "mode": rep["mode"], "finished_at": rep["finished_at"]}
        if rep["mode"] not in ("SANDBOX", "TEST"):
            blockers.append("CANARY_MODE_INVALID")
        if rep["status"] != "OK":
            blockers.append(f"CANARY_{rep['status']}")
        from mod_01_ingestion.src.unified.canary_reports import _parse
        if (_parse(now_iso) - _parse(rep["finished_at"])).total_seconds() > gates["max_canary_age_s"]:
            blockers.append("CANARY_STALE")
    return GateDecision(not blockers, sorted(set(blockers)), canary)


class PilotDownloadService(DownloadService):
    """Una petición; como máximo UN reintento y SOLO tras 429/503. Red caída, timeout, 5xx distintos y 403 no se reintentan."""

    def __init__(self, *a, retry_wait_s: float = 15.0, overall_s: float = 300.0, **kw):
        super().__init__(*a, **kw)
        self.retry_wait_s, self.overall_s = retry_wait_s, overall_s

    def download(self, req: DownloadRequest, job=None) -> DownloadResult:
        t0 = self._monotonic()
        single = dataclasses.replace(req, max_retries=0, retry_statuses=None)
        res = super().download(single, job)
        if res.ok or res.http_status not in RETRY_ONCE_STATUSES:
            return res
        left = self.overall_s - (self._monotonic() - t0) - self.retry_wait_s
        if left < 1:
            return res
        self._emit("pilot_retry_once", job, status=res.http_status, wait_s=self.retry_wait_s)
        self._sleep(self.retry_wait_s)
        return super().download(dataclasses.replace(single, max_total_s=min(left, req.max_total_s or left)), job)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sandbox_canary(store: CanaryReportStore, run_id: str) -> Dict[str, Any]:
    """Canario SANDBOX offline: replay sintético del mismo flujo en un directorio temporal (nunca en la raíz del piloto)."""
    tmp = Path(tempfile.mkdtemp(prefix="cnmv_pilot_canary_"))
    try:
        rec = {"ticker": "TEF", "name": "Telefonica (sandbox)", "fiscal_year": 2019, "doc_type": "CNMV_ANNUAL_REPORT",
               "url": SANDBOX_URL}
        adapter = CNMVAdapter(lambda req: [rec])
        replay = ReplayHttp(["www.cnmv.es"]).add(SANDBOX_URL, SANDBOX_PDF, content_type="application/pdf")
        runner = make_sandbox_runner(tmp / "root", SourceRouter({"CNMV": adapter}), replay)
        report = run_canary(runner, "CNMV", expected=[CoverageKey("ES", "CNMV", "TEF", 2019, "CNMV_ANNUAL_REPORT")])
        saved = store.save(report, run_id=run_id, trigger="MANUAL")
        return {"report_id": saved["report_id"], "status": saved["status"], "alerts": [a.code for a in report.alerts]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_pilot(auth: PilotAuthorization, *, root_path: Path = DEFAULT_PILOT_ROOT, artifact_dir: Optional[Path] = None,
              client: Optional[httpx.Client] = None, sleep: Callable[[float], None] = time.sleep,
              retry_wait_s: float = 15.0, now: Callable[[], str] = _now) -> Dict[str, Any]:
    """Ejecuta el piloto de principio a fin. Devuelve (y guarda en ``reports/pilot``) un informe sin datos sensibles."""
    report: Dict[str, Any] = {"reference": auth.reference, "steps": [], "downloaded": False}
    step = lambda name, **kw: report["steps"].append({"step": name, "at": now(), **kw})      # noqa: E731
    art = complete_artifacts(load_artifacts(artifact_dir), auth, Path(root_path))
    root = UnifiedDataRoot(Path(root_path), ExecutionMode.PILOT)
    validate_unified_root(root.path, ExecutionMode.PILOT)
    existed = root.is_initialized()
    root.initialize()
    step("root_initialized", path=str(root.path), pre_existing=existed)
    lay = root.layout
    registry = ApprovalRegistry(lay.catalog_db)
    for kind, s in art.subjects().items():
        if kind == "IDENTITY_CONTRACT":
            continue                                           # SLOT_ONLY: el contrato no se envía ni se activa
        st = registry.submit(s["subject_id"], kind, s["version"], s["content"], auth.requester)
        if st != "APPROVED":
            registry.approve(s["subject_id"], kind, s["version"], auth.approver, auth.reference)
    step("approvals_recorded", kinds=["SOURCE_CONFIG", "PILOT_PLAN"], requester=auth.requester, approver=auth.approver,
         reference=auth.reference, identity="SLOT_ONLY")
    store = CanaryReportStore(lay.catalog_db)
    canary = _sandbox_canary(store, run_id=f"pilot-{auth.reference}")
    step("canary_sandbox", **canary)
    gate = evaluate_gate(art, registry, store, root, now_iso=now())
    step("gate", allowed=gate.allowed, blockers=gate.blockers)
    report["gate"] = {"allowed": gate.allowed, "blockers": gate.blockers, "canary": gate.canary}
    if not gate.allowed:
        return _write_report(root, report)

    configs = slot_only_configs(art)
    cfg = configs.get("CNMV")
    plan = art.pilot_plan()
    control = art.plan["control_document"]
    budget = PilotBudget(plan)
    budget.start()
    rate = DomainRateLimiter(max_concurrent_per_domain=1, min_interval_s=cfg.min_interval_s, overrides=cfg.rate_overrides(),
                             sleep=sleep)
    rec = {"ticker": control["ticker"], "name": control["issuer_name"], "fiscal_year": control["fiscal_year"],
           "doc_type": "CNMV_ANNUAL_REPORT", "url": control["candidate_url"]}
    adapter = ConfiguredAdapter(CNMVAdapter(lambda req: [rec]), cfg)
    run = RunContext(data_root=str(root.path), mode=ExecutionMode.PILOT, operator=f"pilot:{auth.reference}")
    http = client or httpx.Client(follow_redirects=True, timeout=cfg.timeout_s)
    service = PilotDownloadService(rate_limiter=rate, client=http, sleep=sleep, timeout_s=cfg.timeout_s, max_total_s=cfg.max_total_s,
                                   max_retry_after_s=30.0, retry_wait_s=retry_wait_s, overall_s=float(plan.limits.max_total_s))
    runner = UnifiedIngestRunner(lay, {"CNMV": adapter}, download=service, run=run)
    ledger = CoverageLedger(lay.catalog_db, ExecutionMode.PILOT, telemetry=runner.telemetry)
    key = CoverageKey("ES", "CNMV", control["ticker"], control["fiscal_year"], "CNMV_ANNUAL_REPORT")
    ledger.expect([key], run_id=run.run_id)
    known = ledger.get(key)
    if known is not None and known.status is LedgerStatus.PROMOTED:       # un solo documento en TOTAL: no se pide dos veces
        report["skipped"] = "LEDGER_ALREADY_PROMOTED"
        report["outcome"] = {"state": "SKIPPED_ALREADY_PRESENT", "sha256": known.sha256, "ledger_status": known.status.value}
        step("skipped", reason="LEDGER_ALREADY_PROMOTED")
        return _write_report(root, report)
    try:
        budget.begin_document("CNMV", control["candidate_url"])
        cand = adapter.discover(DiscoveryRequest(authority="CNMV", fiscal_years=[control["fiscal_year"]],
                                                 issuer_ids=[control["ticker"]], doc_types=["CNMV_ANNUAL_REPORT"], limit=1))[0]
        outcome = runner.process_candidate(adapter, cand)
        rec_res = record_outcome(ledger, cand, outcome, run_id=run.run_id)
    except PilotLimitExceeded as ex:
        report["aborted"] = ex.code
        step("budget_exceeded", code=ex.code)
        return _write_report(root, report)
    report["downloaded"] = outcome.state in ("COMPLETED", "SKIPPED_ALREADY_PRESENT")
    report["outcome"] = {"state": outcome.state, "error_class": outcome.error_class,
                         "message": sanitize_message(outcome.message or "") or None, "sha256": outcome.sha256,
                         "failure_stage": outcome.failure_stage, "attempt_id": outcome.attempt_id,
                         "document_id": cand.document_id, "ledger_status": rec_res.status.value}
    if outcome.sha256 and outcome.raw_path:
        size = Path(outcome.raw_path).stat().st_size
        report["outcome"]["size_bytes"] = size
        budget.record_bytes(size)
        report["control_comparison"] = {"sha256_matches_local_control": outcome.sha256 == control["local_control_sha256"],
                                        "size_matches_local_control": size == control["local_control_size_bytes"],
                                        "local_control_sha256": control["local_control_sha256"],
                                        "local_control_size_bytes": control["local_control_size_bytes"]}
    if rec_res.status is LedgerStatus.NEEDS_REVIEW:
        step("needs_review", reason=outcome.error_class)
    step("finished", state=outcome.state, calls=1)
    return _write_report(root, report)


def _write_report(root: UnifiedDataRoot, report: Dict[str, Any]) -> Dict[str, Any]:
    d = root.layout.reports / "pilot"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"pilot_run_{report['reference']}.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str),
                                                           encoding="utf-8")
    return report
