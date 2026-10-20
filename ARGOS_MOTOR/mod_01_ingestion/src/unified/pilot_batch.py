"""
CNMV-U2 — Lote AUTORIZADO de 9 documentos (informes anuales PDF 2018-2019) descubiertos en CNMV-U1.

El lote es EXACTAMENTE el de ``EXPECTED`` (ticker, ejercicio, nº de registro, URL oficial de la ficha IFA); el candidato de Telefónica 2019
ya se descargó en el piloto y queda fuera. Mismas reglas que el piloto: un solo dominio, una petición concurrente, ≥5 s entre peticiones,
60 s por petición, un único reintento y solo tras 429/503, 403 → ``NEEDS_REVIEW`` sin reintento. Además:
* interruptor de seguridad: el lote se DETIENE ante el primer 403 o ante dos fallos seguidos (no se insiste contra la fuente);
* presupuesto de lote (documentos, bytes totales = suma de los Content-Length descubiertos + margen, tiempo) vía ``PilotBudget``;
* cada documento se contrasta con el Content-Length descubierto y con el hash local de ``raw/ES_CNMV`` (solo lectura, sin tocarlo);
* nada se escribe fuera de la raíz del piloto; ``raw/ES_CNMV`` no se abre en escritura.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore
from mod_01_ingestion.src.unified.cnmv_discovery import ISSUERS, local_comparison
from mod_01_ingestion.src.unified.cnmv_pilot import load_artifacts
from mod_01_ingestion.src.unified.configured_adapter import ConfiguredAdapter
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus, record_outcome
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot, validate_unified_root
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest, RunContext
from mod_01_ingestion.src.unified.pilot import PilotBudget, PilotLimitExceeded, PilotLimits, PilotPlan
from mod_01_ingestion.src.unified.pilot_runner import (
    AUTH_PHRASE, PilotAuthorization, PilotDownloadService, _sandbox_canary, complete_artifacts, slot_only_configs)
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter

BATCH_PHRASE = "AUTORIZO LOTE CNMV 2018-2019 9 DOCUMENTOS"
BATCH_REF = "CNMV-BATCH-2018-2019-001"
DOC_TYPE = "CNMV_ANNUAL_REPORT"
# (ticker, ejercicio, nº registro oficial) — URL = https://www.cnmv.es/AUDITA/<ejercicio>/<registro>.pdf (ficha IFA, CNMV-U1)
EXPECTED = (("TEF", 2018, "17817"), ("SAN", 2018, "17877"), ("SAN", 2019, "18359"), ("IBE", 2018, "17820"), ("IBE", 2019, "18362"),
            ("BBVA", 2018, "17810"), ("BBVA", 2019, "18285"), ("REP", 2018, "17857"), ("REP", 2019, "18291"))
MAX_CONSECUTIVE_FAILURES = 2
BYTES_MARGIN = 1.10


class BatchError(DomainValidationError):
    pass


class _RecordingService(PilotDownloadService):
    """Recuerda el último estado HTTP real (el runner solo devuelve el resultado tipado del documento)."""
    last_http_status: Optional[int] = None
    requests = 0

    def download(self, req, job=None):
        res = super().download(req, job)
        self.last_http_status = res.http_status
        self.requests += 1
        return res


def expected_url(fy: int, nreg: str) -> str:
    return f"https://www.cnmv.es/AUDITA/{fy}/{nreg}.pdf"


@dataclass(frozen=True)
class BatchItem:
    ticker: str
    fiscal_year: int
    nreg: str
    url: str
    expected_size: int
    last_modified: Optional[str] = None


def load_batch(root: Path) -> List[BatchItem]:
    """Lee los candidatos de CNMV-U1 y exige que coincidan EXACTAMENTE con el lote autorizado (ni uno más, ni uno menos)."""
    p = Path(root) / "reports" / "pilot" / "discovery" / "cnmv_u1_candidates.json"
    try:
        cands = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise BatchError(f"candidatos de CNMV-U1 ilegibles: {type(ex).__name__}") from ex
    by = {(c["ticker"], int(c["fiscal_year"])): c for c in cands}
    items: List[BatchItem] = []
    for ticker, fy, nreg in EXPECTED:
        c = by.get((ticker, fy))
        if c is None or str(c.get("nreg")) != nreg or c.get("url") != expected_url(fy, nreg) or not c.get("head_confirmed_pdf"):
            raise BatchError(f"el candidato {ticker} {fy} no coincide con el lote autorizado")
        size = c.get("head_content_length")
        if not isinstance(size, int) or size <= 0:
            raise BatchError(f"el candidato {ticker} {fy} no tiene tamaño oficial conocido")
        items.append(BatchItem(ticker, fy, nreg, c["url"], size, c.get("head_last_modified")))
    return items


def _auth() -> PilotAuthorization:
    """Reconstruye (solo para regenerar el CONTENIDO ya aprobado de la configuración) la autorización del piloto."""
    return PilotAuthorization(phrase=AUTH_PHRASE, requester="José Fulgencio Molina", approver="Francisca Garcia",
                              reference="CNMV-PILOT-TEF-2019-001", user_agent="Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com")


def run_batch(phrase: str, *, root_path: Path = Path("D:/ARGOS_DATA/unified_pilot"), client: Optional[httpx.Client] = None,
              sleep: Callable[[float], None] = time.sleep, retry_wait_s: float = 15.0, now: Callable[[], str] = None,
              inventory: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    from mod_01_ingestion.src.unified.pilot_runner import _now
    now = now or _now
    if phrase != BATCH_PHRASE:
        raise BatchError("autorización de lote no válida: la frase debe ser exactamente la acordada")
    root = UnifiedDataRoot(Path(root_path), ExecutionMode.PILOT)
    validate_unified_root(root.path, ExecutionMode.PILOT)
    if not root.is_initialized():
        raise BatchError("la raíz del piloto no está inicializada")
    lay = root.layout
    items = load_batch(root.path)
    report: Dict[str, Any] = {"reference": BATCH_REF, "authorized_by": "propietario (frase de autorización en el chat)",
                              "authorization_status": "OWNER_AUTHORIZED_NOT_INDEPENDENTLY_VERIFIED", "steps": [], "documents": [],
                              "downloaded": 0, "stopped": None}
    step = lambda name, **kw: report["steps"].append({"step": name, "at": now(), **kw})      # noqa: E731
    art = complete_artifacts(load_artifacts(), _auth(), root.path)
    registry = ApprovalRegistry(lay.catalog_db)
    cfg_subject = art.subjects()["SOURCE_CONFIG"]
    if not registry.is_active(cfg_subject["subject_id"], "SOURCE_CONFIG", cfg_subject["version"], cfg_subject["content"]):
        report["stopped"] = "SOURCE_CONFIG_NOT_APPROVED"
        return _write(root, report)
    store = CanaryReportStore(lay.catalog_db)
    canary = _sandbox_canary(store, run_id=f"batch-{BATCH_REF}")
    step("canary_sandbox", **canary)
    if canary["status"] != "OK":
        report["stopped"] = "CANARY_NOT_OK"
        return _write(root, report)

    configs = slot_only_configs(art)
    cfg = configs.get("CNMV")
    total_expected = sum(i.expected_size for i in items)
    total_cap = min(max(int(total_expected * BYTES_MARGIN), 1), 2 * 1024 ** 3)
    limits = PilotLimits(allowed_domains=("www.cnmv.es",), max_documents=len(items),
                         max_bytes_per_document=min(cfg.max_bytes, total_cap), max_total_bytes=total_cap, max_total_s=3600.0)
    plan = PilotPlan(authority="CNMV", config_version=configs.config_version, limits=limits, root=str(root.path),
                     plan_version=BATCH_REF)
    budget = PilotBudget(plan)
    budget.start()
    report["budget"] = {"max_documents": limits.max_documents, "max_total_bytes": limits.max_total_bytes,
                        "expected_total_bytes": total_expected, "max_total_s": limits.max_total_s}
    records = [{"ticker": i.ticker, "name": ISSUERS[i.ticker][1], "fiscal_year": i.fiscal_year, "doc_type": DOC_TYPE, "url": i.url}
               for i in items]
    adapter = ConfiguredAdapter(CNMVAdapter(lambda req: list(records)), cfg)
    run = RunContext(data_root=str(root.path), mode=ExecutionMode.PILOT, operator=f"batch:{BATCH_REF}")
    rate = DomainRateLimiter(max_concurrent_per_domain=1, min_interval_s=cfg.min_interval_s, overrides=cfg.rate_overrides(),
                             sleep=sleep)
    http = client or httpx.Client(follow_redirects=True, timeout=cfg.timeout_s)
    service = _RecordingService(rate_limiter=rate, client=http, sleep=sleep, timeout_s=cfg.timeout_s, max_total_s=cfg.max_total_s,
                                   max_retry_after_s=30.0, retry_wait_s=retry_wait_s, overall_s=float(cfg.max_total_s))
    runner = UnifiedIngestRunner(lay, {"CNMV": adapter}, download=service, run=run)
    ledger = CoverageLedger(lay.catalog_db, ExecutionMode.PILOT, telemetry=runner.telemetry)
    keys = {(i.ticker, i.fiscal_year): CoverageKey("ES", "CNMV", i.ticker, i.fiscal_year, DOC_TYPE) for i in items}
    ledger.expect(list(keys.values()), run_id=run.run_id)
    cands = {(c.ticker, c.fiscal_year): c for c in adapter.discover(DiscoveryRequest(authority="CNMV", doc_types=[DOC_TYPE]))}
    consecutive = 0
    for item in items:
        k = (item.ticker, item.fiscal_year)
        doc: Dict[str, Any] = {"ticker": item.ticker, "fiscal_year": item.fiscal_year, "nreg": item.nreg, "url": item.url,
                               "expected_size": item.expected_size}
        known = ledger.get(keys[k])
        if known is not None and known.status is LedgerStatus.PROMOTED:
            doc.update(state="SKIPPED_ALREADY_PROMOTED", sha256=known.sha256, requested=False)
            report["documents"].append(doc)
            continue
        try:
            budget.begin_document("CNMV", item.url)
        except PilotLimitExceeded as ex:
            doc.update(state="NOT_ATTEMPTED", requested=False, reason=ex.code)
            report["documents"].append(doc)
            report["stopped"] = ex.code
            break
        cand = cands[k]
        outcome = runner.process_candidate(adapter, cand)
        res = record_outcome(ledger, cand, outcome, run_id=run.run_id)
        doc.update(requested=True, state=outcome.state, error_class=outcome.error_class, sha256=outcome.sha256,
                   http_status=service.last_http_status,
                   message=sanitize_message(outcome.message or "") or None, ledger_status=res.status.value)
        ok = outcome.state in ("COMPLETED", "SKIPPED_ALREADY_PRESENT") and bool(outcome.sha256 and outcome.raw_path)
        if ok:
            consecutive = 0
            size = Path(outcome.raw_path).stat().st_size
            doc["size_bytes"], doc["size_matches_discovery"] = size, size == item.expected_size
            try:
                budget.record_bytes(size)
            except PilotLimitExceeded as ex:
                doc["budget"] = ex.code
                report["stopped"] = ex.code
            loc = local_comparison(item.ticker, item.fiscal_year, None, None, inventory)["local_manifest"] or {}
            local_sha = loc.get("inventory_sha256") or loc.get("manifest_sha256")
            doc["local_sha256"] = local_sha
            doc["hash_vs_local"] = ("NO_LOCAL_HASH" if not local_sha else
                                    "MATCH" if local_sha == outcome.sha256 else "DIFFERENT")
            report["downloaded"] += 1
        else:
            consecutive += 1
            if service.last_http_status == 403:
                doc["circuit_breaker"] = "HTTP_403"
                report["stopped"] = "HTTP_403"
            elif consecutive >= MAX_CONSECUTIVE_FAILURES:
                report["stopped"] = "CONSECUTIVE_FAILURES"
        report["documents"].append(doc)
        if report["stopped"]:
            break
    attempted = {(d["ticker"], d["fiscal_year"]) for d in report["documents"]}
    for item in items:
        if (item.ticker, item.fiscal_year) not in attempted:
            report["documents"].append({"ticker": item.ticker, "fiscal_year": item.fiscal_year, "nreg": item.nreg,
                                        "state": "NOT_ATTEMPTED", "requested": False, "reason": report["stopped"]})
    step("finished", downloaded=report["downloaded"], stopped=report["stopped"],
         requests=sum(1 for d in report["documents"] if d.get("requested")))
    return _write(root, report)


def _write(root: UnifiedDataRoot, report: Dict[str, Any]) -> Dict[str, Any]:
    from mod_01_ingestion.src.unified.domain.transport import assert_no_secret
    assert_no_secret(report, "informe")
    d = root.layout.reports / "pilot"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"batch_{report['reference']}.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str, ensure_ascii=False),
                                                         encoding="utf-8")
    return report
