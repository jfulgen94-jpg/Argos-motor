"""
FASE 4 — UnifiedIngestRunner: ÚNICO orquestador de ingesta para todas las autoridades.

Pipeline por documento (máquina de estados de Fase 3):
DISCOVERED -> QUEUED -> DOWNLOADING -> VERIFYING/VALIDATING -> PROMOTING -> MANIFESTING ->
CATALOGING -> COMPLETED | QUARANTINED | FAILED   (skip solo vía preflight: SKIPPED_ALREADY_PRESENT)

Protocolo de dos fases (DEFECT-06): la promoción a raw se deshace (rollback) si falla el
manifiesto o el catálogo, de modo que nunca queda un raw sin su registro.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from mod_01_ingestion.src.unified.application.preflight import KnownDocumentPreflight
from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.domain.enums import PreflightStatus
from mod_01_ingestion.src.unified.domain.errors import SimulatedDataRejectedError, sanitize_message
from mod_01_ingestion.src.unified.domain.policy import assert_not_simulated
from mod_01_ingestion.src.unified.persistence_guard import assert_persistable
from mod_01_ingestion.src.unified.preflight_lookup import RepositoryKnownDocumentLookup
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.lock_manager import LockManager, LockTimeout
from mod_01_ingestion.src.unified.models import (
    SCHEMA_VERSION, CatalogRecord, DiscoveryRequest, DocumentCandidate, ErrorClass, JobContext,
    JobState, ManifestRecord, PipelineResult, RunContext)
from mod_01_ingestion.src.unified.domain.models import PreflightOutcome
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository, QuarantineService
from mod_01_ingestion.src.unified.source_adapter import SourceAdapter
from mod_01_ingestion.src.unified.telemetry import TelemetryLogger
from mod_01_ingestion.src.unified.unit_of_work import ManifestCatalogUnitOfWork
from mod_01_ingestion.src.unified.validation_pipeline import ValidationPipeline


JobOutcome = PipelineResult   # alias U1: mismo concepto/campos que el JobOutcome de Fase 4


@dataclass
class RunReport:
    run_id: str
    outcomes: List[JobOutcome] = field(default_factory=list)

    def count(self, state: JobState) -> int:
        return sum(1 for o in self.outcomes if o.state == state.value)


class UnifiedIngestRunner:
    def __init__(
        self,
        layout: DataLayout,
        adapters: Dict[str, SourceAdapter],
        download: Optional[DownloadService] = None,
        validation: Optional[ValidationPipeline] = None,
        catalog: Optional[CatalogRepository] = None,
        manifests: Optional[ManifestRepository] = None,
        locks: Optional[LockManager] = None,
        run: Optional[RunContext] = None,
        rate_limiter: Optional[DomainRateLimiter] = None,
        lock_timeout_s: float = 30.0,
        preflight: Optional[KnownDocumentPreflight] = None,
    ):
        self.lock_timeout_s = lock_timeout_s
        self._seq = 0
        self.layout = layout.ensure()
        self.run = run or RunContext(data_root=str(layout.root))
        self.adapters = {k.upper(): v for k, v in adapters.items()}
        self.telemetry = TelemetryLogger(self.layout.telemetry, self.run)
        self.download = download or DownloadService(telemetry=self.telemetry, rate_limiter=rate_limiter)
        if self.download.telemetry is None:
            self.download.telemetry = self.telemetry
        self.validation = validation or ValidationPipeline()
        self.locks = locks or LockManager(self.layout.locks)
        self.cas = ContentAddressedRawStore(self.layout, self.locks)
        self.manifests = manifests or ManifestRepository(self.layout, mode=self.run.mode)
        self.catalog = catalog or CatalogRepository(self.layout.catalog_db, mode=self.run.mode)
        self.quarantine = QuarantineService(self.layout)
        # U5A: lectura previa de lo ya registrado; el UoW sigue siendo la autoridad final antes del commit.
        self.preflight = preflight or KnownDocumentPreflight(
            RepositoryKnownDocumentLookup(self.manifests, self.catalog, self.cas))

    # ------------------------------------------------------------------------------
    def run_discovery(self, request: DiscoveryRequest) -> RunReport:
        adapter = self.adapters[request.authority.upper()]
        report = RunReport(run_id=self.run.run_id)
        candidates = adapter.discover(request)
        self.telemetry.emit("run_started", None, "ingest_runner", authority=request.authority,
                            candidates=len(candidates))
        for cand in candidates:
            report.outcomes.append(self.process_candidate(adapter, cand))
        self.telemetry.emit("run_finished", None, "ingest_runner", authority=request.authority,
                            completed=report.count(JobState.COMPLETED), failed=report.count(JobState.FAILED),
                            quarantined=report.count(JobState.QUARANTINED),
                            skipped=report.count(JobState.SKIPPED_ALREADY_PRESENT))
        return report

    def _state(self, job: JobContext, state: JobState, **kw):
        self.telemetry.emit("state_transition", job, "ingest_runner", state=state.value, **kw)

    def process_candidate(self, adapter: SourceAdapter, cand: DocumentCandidate) -> JobOutcome:
        self._seq += 1   # job_id único y monótono dentro del run (no se reinicia entre autoridades)
        job = JobContext.for_candidate(self.run, self._seq, cand)
        self._state(job, JobState.DISCOVERED, url=cand.source_url)

        # U1 guard LIVE (ADR-005): ningún candidato simulado/fixture avanza fuera de TEST/SANDBOX.
        try:
            assert_not_simulated(cand, self.run.mode)
        except SimulatedDataRejectedError as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.VALIDATION_REJECTED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value,
                              ErrorClass.VALIDATION_REJECTED.value, str(ex))

        # U5A: preflight de SOLO LECTURA antes de cualquier lock, rate limiter, conexión, .part o CAS.
        pf = self._run_preflight(job, cand)
        if not pf.may_download:
            return self._preflight_terminal(job, pf)
        # ÚNICA autoridad de skip: KnownDocumentPreflight. No existe idempotencia por document_id + integridad local
        # (no prueba que la representación remota no haya cambiado); sin validador remoto se descarga y el UoW decide.

        try:
            with self.locks.acquire(f"doc-{cand.document_id}", timeout_s=self.lock_timeout_s):
                return self._process_locked(adapter, cand, job)
        except LockTimeout as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.LOCKED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.LOCKED.value, str(ex))

    # ------------------------------------------------------------------------------
    _PREFLIGHT_EVENT = {
        PreflightStatus.SKIPPED_ALREADY_PRESENT: "PREFLIGHT_SKIPPED", PreflightStatus.PROCEED_DOWNLOAD: "PREFLIGHT_PROCEED",
        PreflightStatus.POSSIBLE_REPUBLICATION: "PREFLIGHT_REPUBLICATION",
        PreflightStatus.RECOVERY_REQUIRED: "PREFLIGHT_RECOVERY_REQUIRED", PreflightStatus.CONFLICT: "PREFLIGHT_CONFLICT",
        PreflightStatus.MANUAL_REVIEW: "PREFLIGHT_MANUAL_REVIEW"}
    _PREFLIGHT_STATE = {
        PreflightStatus.SKIPPED_ALREADY_PRESENT: JobState.SKIPPED_ALREADY_PRESENT,
        PreflightStatus.RECOVERY_REQUIRED: JobState.RECOVERY_REQUIRED, PreflightStatus.CONFLICT: JobState.CONFLICT,
        PreflightStatus.MANUAL_REVIEW: JobState.MANUAL_REVIEW}

    def _run_preflight(self, job: JobContext, cand: DocumentCandidate) -> PreflightOutcome:
        """Ejecuta el preflight y registra sus eventos (solo códigos: sin URLs completas, tokens ni contenido).
        Fail-closed: si la consulta de registros falla no se descarga a ciegas; pasa a revisión manual."""
        self.telemetry.emit("PREFLIGHT_STARTED", job, "preflight")
        try:
            pf = self.preflight.evaluate(cand, self.run)
        except Exception as ex:
            pf = PreflightOutcome(
                status=PreflightStatus.MANUAL_REVIEW, reason_code=f"PREFLIGHT_LOOKUP_ERROR:{type(ex).__name__}",
                document_id=cand.document_id, discovered_at=self.run.started_at, needs_manual_review=True,
                safe_message=sanitize_message(f"no se pudieron consultar los registros existentes: {type(ex).__name__}"))
        self.telemetry.emit(self._PREFLIGHT_EVENT[pf.status], job, "preflight", status=pf.status.value,
                            matched_by=pf.matched_by.value, reason_code=pf.reason_code)
        return pf

    def _preflight_terminal(self, job: JobContext, pf: PreflightOutcome) -> JobOutcome:
        state = self._PREFLIGHT_STATE[pf.status]
        klass = None if pf.status in (PreflightStatus.SKIPPED_ALREADY_PRESENT, PreflightStatus.MANUAL_REVIEW) \
            else ErrorClass.INVARIANT_VIOLATION.value
        self._state(job, state, reason_code=pf.reason_code, matched_by=pf.matched_by.value, preflight=True,
                    sha256=pf.existing_sha256)
        return JobOutcome(job.job_id, job.document_id, state.value, klass, pf.safe_message, sha256=pf.existing_sha256,
                          needs_manual_review=pf.needs_manual_review,
                          failure_stage=None if pf.skips_download else "PREFLIGHT")

    def _abort_promotion(self, job: JobContext, promo, klass: ErrorClass, message: str, *, failure_stage: Optional[str],
                         uow=None) -> JobOutcome:
        """Cierra un intento fallido DESPUÉS de promover: revierte solo lo demostrablemente propio del CAS/raw
        (``rollback_owned``; el ``UnitOfWork`` nunca toca el CAS) y decide FAILED vs RECOVERY_REQUIRED.
        RECOVERY_REQUIRED = la compensación del manifiesto/catálogo falló, el estado previo era parcial, o queda un
        blob/vista raw sin propiedad demostrable (``orphaned_cas_*``): requiere reconciliación manual."""
        rb = self.cas.rollback_owned(promo)
        comp_errors = [sanitize_message(e) for e in (uow.compensation_errors if uow else ())]
        recovery = bool(comp_errors) or bool(uow and uow.recovery_required) or not rb.clean
        text = sanitize_message(message)
        if uow and uow.recovery_reason:
            text += f" | RECOVERY: {uow.recovery_reason}"
        if comp_errors:
            text += " | COMPENSACIÓN INCOMPLETA: " + "; ".join(comp_errors)
        if not rb.clean:
            text += f" | CAS HUÉRFANO: sha256={rb.orphaned_sha256} path={rb.orphaned_path}"
        state = JobState.RECOVERY_REQUIRED if recovery else JobState.FAILED
        fields = dict(error_class=klass.value, message=text, rollback=True, failure_stage=failure_stage,
                      recovery_required=recovery, compensation_errors=comp_errors, cas_blob_state=rb.blob_state,
                      cas_raw_view_state=rb.raw_view_state)
        if uow:
            fields["uow_status"] = uow.status.value
        if not rb.clean:
            fields.update(orphaned_cas_sha256=rb.orphaned_sha256, orphaned_cas_path=rb.orphaned_path)
        self._state(job, state, **fields)
        return JobOutcome(job.job_id, job.document_id, state.value, klass.value, text, needs_manual_review=recovery,
                          failure_stage=failure_stage, orphaned_cas_sha256=rb.orphaned_sha256,
                          orphaned_cas_path=rb.orphaned_path)

    def _process_locked(self, adapter: SourceAdapter, cand: DocumentCandidate, job: JobContext) -> JobOutcome:
        # Re-evaluación tras el lock (Fase 6): otro proceso pudo registrar el documento mientras esperábamos. La decisión
        # sigue siendo EXCLUSIVAMENTE del preflight; aquí solo se traduce su resultado.
        pf = self._run_preflight(job, cand)
        if not pf.may_download:
            return self._preflight_terminal(job, pf)
        self._state(job, JobState.QUEUED)
        meta = adapter.fetch_metadata(cand)
        build = getattr(adapter, "build_download_request", None)
        staging = self.layout.staging / job.run_id / job.document_id
        from mod_01_ingestion.src.unified.models import DownloadRequest
        dreq = build(cand, meta, staging) if build else DownloadRequest(
            url=meta.resolved_url, staging_dir=str(staging), file_name=meta.file_name,
            expected_sha256=meta.expected_sha256, headers=meta.headers)

        self._state(job, JobState.DOWNLOADING, url=dreq.url)
        dl = self.download.download(dreq, job)
        if not dl.ok:
            self._state(job, JobState.FAILED, error_class=dl.error_class, status=dl.http_status)
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, dl.error_class, dl.error_message)

        self._state(job, JobState.VALIDATING, sha256=dl.sha256)
        val = self.validation.validate(Path(dl.staged_path), meta, cand.doc_type)
        if not val.accepted:
            q = self.quarantine.quarantine(Path(dl.staged_path), job, val.error_class or ErrorClass.VALIDATION_REJECTED.value,
                                           val.reasons, dl.sha256)
            self._state(job, JobState.QUARANTINED, error_class=q.error_class, path=q.quarantine_path)
            return JobOutcome(job.job_id, job.document_id, JobState.QUARANTINED.value, q.error_class,
                              "; ".join(val.reasons), sha256=dl.sha256)

        # U2: la política de persistencia se evalúa ANTES de promover raw o enlazar el CAS.
        try:
            assert_persistable({"document_id": job.document_id, "doc_type": cand.doc_type, "sha256": dl.sha256,
                                "status": "RAW_VALIDATED", "extra": cand.extra,
                                "source_type": cand.source_type}, self.run.mode, self.layout.root)
        except SimulatedDataRejectedError as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.VALIDATION_REJECTED.value, message=str(ex))
            Path(dl.staged_path).unlink(missing_ok=True)
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value,
                              ErrorClass.VALIDATION_REJECTED.value, str(ex))

        self._state(job, JobState.PROMOTING)
        rel = Path(f"{cand.country_code}_{cand.authority}") / str(cand.fiscal_year) / _safe(cand.issuer_id) / meta.file_name
        promo = self.cas.promote(Path(dl.staged_path), dl.sha256, rel)

        # U4: manifiesto + catálogo se hacen consistentes en UNA unidad de trabajo; el raw/CAS lo compensa este método.
        try:
            record = ManifestRecord(
                manifest_version=SCHEMA_VERSION, document_id=job.document_id, run_id=job.run_id, job_id=job.job_id,
                authority=cand.authority, country_code=cand.country_code, issuer_id=cand.issuer_id,
                fiscal_year=cand.fiscal_year, doc_type=cand.doc_type, source_url=cand.source_url,
                final_url=dl.final_url, raw_path=promo.raw_path, cas_path=promo.cas_path, sha256=dl.sha256,
                size_bytes=dl.size_bytes, mime_type=dl.mime_type, http_status=dl.http_status, status="RAW_VALIDATED",
                completeness_status=val.completeness_status, validation_reasons=val.reasons,
                issuer_name=cand.issuer_name, issuer_lei=cand.issuer_lei, ticker=cand.ticker,
                source_page_url=cand.source_page_url, resumed=dl.resumed, retries_taken=dl.retries_taken,
                deduplicated=promo.deduplicated)
        except Exception as ex:      # modelo inválido: antes se propagaba dejando el raw promovido sin registro
            return self._abort_promotion(job, promo, ErrorClass.MANIFEST_FAILED, str(ex), failure_stage="MANIFEST")

        uow = ManifestCatalogUnitOfWork(self.manifests, self.catalog, mode=self.run.mode)
        catalog_record = CatalogRecord(
            document_id=job.document_id, run_id=job.run_id, job_id=job.job_id, authority=cand.authority,
            country_code=cand.country_code, issuer_id=cand.issuer_id, fiscal_year=cand.fiscal_year,
            doc_type=cand.doc_type, sha256=dl.sha256, raw_path=promo.raw_path,
            manifest_path=str(uow.final_manifest_path(record)), status=record.status, size_bytes=dl.size_bytes)
        result = uow.execute(record, catalog_record, on_phase=lambda p: self._state(job, JobState[p]))
        if not result.ok:
            return self._abort_promotion(job, promo, ErrorClass(result.error_class or ErrorClass.UNKNOWN.value),
                                         result.message or "", failure_stage=result.failure_stage, uow=result)

        Path(dl.staged_path).unlink(missing_ok=True)
        self._state(job, JobState.COMPLETED, sha256=dl.sha256, raw_path=promo.raw_path, deduplicated=promo.deduplicated)
        return JobOutcome(job.job_id, job.document_id, JobState.COMPLETED.value, raw_path=promo.raw_path, sha256=dl.sha256)


def _safe(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)
