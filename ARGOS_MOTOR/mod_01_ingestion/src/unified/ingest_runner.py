"""
FASE 4 — UnifiedIngestRunner: ÚNICO orquestador de ingesta para todas las autoridades.

Pipeline por documento (máquina de estados de Fase 3):
DISCOVERED -> QUEUED -> DOWNLOADING -> VERIFYING/VALIDATING -> PROMOTING -> MANIFESTING ->
CATALOGING -> COMPLETED | QUARANTINED | FAILED | SKIPPED_DUPLICATE

Protocolo de dos fases (DEFECT-06): la promoción a raw se deshace (rollback) si falla el
manifiesto o el catálogo, de modo que nunca queda un raw sin su registro.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.lock_manager import LockManager, LockTimeout
from mod_01_ingestion.src.unified.models import (
    SCHEMA_VERSION, CatalogRecord, DiscoveryRequest, DocumentCandidate, ErrorClass, JobContext,
    JobState, ManifestRecord, RunContext)
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository, QuarantineService
from mod_01_ingestion.src.unified.source_adapter import SourceAdapter
from mod_01_ingestion.src.unified.telemetry import TelemetryLogger
from mod_01_ingestion.src.unified.validation_pipeline import ValidationPipeline


@dataclass
class JobOutcome:
    job_id: str
    document_id: str
    state: str
    error_class: Optional[str] = None
    message: Optional[str] = None
    raw_path: Optional[str] = None
    sha256: Optional[str] = None


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
        self.manifests = manifests or ManifestRepository(self.layout)
        self.catalog = catalog or CatalogRepository(self.layout.catalog_db)
        self.quarantine = QuarantineService(self.layout)

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
                            skipped=report.count(JobState.SKIPPED_DUPLICATE))
        return report

    def _state(self, job: JobContext, state: JobState, **kw):
        self.telemetry.emit("state_transition", job, "ingest_runner", state=state.value, **kw)

    def process_candidate(self, adapter: SourceAdapter, cand: DocumentCandidate) -> JobOutcome:
        self._seq += 1   # job_id único y monótono dentro del run (no se reinicia entre autoridades)
        job = JobContext.for_candidate(self.run, self._seq, cand)
        self._state(job, JobState.DISCOVERED, url=cand.source_url)

        # Idempotencia: manifiesto ya comprometido y raw íntegro => no se vuelve a descargar.
        prior = self.manifests.get(cand.authority, cand.fiscal_year, cand.document_id)
        if prior and self.cas.verify(prior["sha256"], Path(prior["raw_path"])):
            self._state(job, JobState.SKIPPED_DUPLICATE, sha256=prior["sha256"])
            return JobOutcome(job.job_id, job.document_id, JobState.SKIPPED_DUPLICATE.value,
                              raw_path=prior["raw_path"], sha256=prior["sha256"])

        try:
            with self.locks.acquire(f"doc-{cand.document_id}", timeout_s=self.lock_timeout_s):
                return self._process_locked(adapter, cand, job)
        except LockTimeout as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.LOCKED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.LOCKED.value, str(ex))

    # ------------------------------------------------------------------------------
    def _process_locked(self, adapter: SourceAdapter, cand: DocumentCandidate, job: JobContext) -> JobOutcome:
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

        self._state(job, JobState.PROMOTING)
        rel = Path(f"{cand.country_code}_{cand.authority}") / str(cand.fiscal_year) / _safe(cand.issuer_id) / meta.file_name
        promo = self.cas.promote(Path(dl.staged_path), dl.sha256, rel)

        pending = None
        cataloged = False
        try:
            self._state(job, JobState.MANIFESTING)
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
            try:
                pending = self.manifests.stage(record)
            except Exception as ex:
                raise _PhaseError(ErrorClass.MANIFEST_FAILED, ex)

            self._state(job, JobState.CATALOGING)
            final_manifest = self.manifests.path_for(cand.authority, cand.fiscal_year, cand.document_id)
            try:
                self.catalog.upsert(CatalogRecord(
                    document_id=job.document_id, run_id=job.run_id, job_id=job.job_id, authority=cand.authority,
                    country_code=cand.country_code, issuer_id=cand.issuer_id, fiscal_year=cand.fiscal_year,
                    doc_type=cand.doc_type, sha256=dl.sha256, raw_path=promo.raw_path,
                    manifest_path=str(final_manifest), status=record.status, size_bytes=dl.size_bytes))
                cataloged = True
                self.manifests.commit(pending)
            except Exception as ex:
                raise _PhaseError(ErrorClass.CATALOG_FAILED, ex)
        except _PhaseError as pe:
            if cataloged:
                try:
                    self.catalog.delete(job.document_id)
                except Exception:
                    pass
            if pending is not None:
                self.manifests.abort(pending)
            self.cas.rollback(promo)
            self._state(job, JobState.FAILED, error_class=pe.klass.value, message=str(pe.cause), rollback=True)
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, pe.klass.value, str(pe.cause))

        Path(dl.staged_path).unlink(missing_ok=True)
        self._state(job, JobState.COMPLETED, sha256=dl.sha256, raw_path=promo.raw_path, deduplicated=promo.deduplicated)
        return JobOutcome(job.job_id, job.document_id, JobState.COMPLETED.value, raw_path=promo.raw_path, sha256=dl.sha256)


class _PhaseError(Exception):
    def __init__(self, klass: ErrorClass, cause: Exception):
        super().__init__(str(cause))
        self.klass = klass
        self.cause = cause


def _safe(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)
