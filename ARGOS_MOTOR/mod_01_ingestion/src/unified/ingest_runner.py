"""
FASE 4 — UnifiedIngestRunner: ÚNICO orquestador de ingesta para todas las autoridades.

Pipeline por documento (máquina de estados de Fase 3):
DISCOVERED -> QUEUED -> DOWNLOADING -> VERIFYING/VALIDATING -> PROMOTING -> MANIFESTING ->
CATALOGING -> COMPLETED | QUARANTINED | FAILED   (skip solo vía preflight: SKIPPED_ALREADY_PRESENT)

Protocolo de dos fases (DEFECT-06): la promoción a raw se deshace (rollback) si falla el
manifiesto o el catálogo, de modo que nunca queda un raw sin su registro.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from mod_01_ingestion.src.unified.application.preflight import KnownDocumentPreflight
from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.domain.enums import PreflightStatus
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, SimulatedDataRejectedError, sanitize_message
from mod_01_ingestion.src.unified.domain.republication import POSSIBLE_REPUBLICATION
from mod_01_ingestion.src.unified.domain.transport import strip_url
from mod_01_ingestion.src.unified.domain.versions import (
    DocumentVersion, IdentityKind, IdScope, InitialVersionPolicy, Observation, ResolvedIdentity, VersionStatus,
    resolve_identity)
from mod_01_ingestion.src.unified.version_store import RegisterResult, VersionRepository
from mod_01_ingestion.src.unified.domain.policy import assert_not_simulated
from mod_01_ingestion.src.unified.persistence_guard import assert_persistable
from mod_01_ingestion.src.unified.preflight_lookup import RepositoryKnownDocumentLookup
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.lock_manager import LockManager, LockTimeout
from mod_01_ingestion.src.unified.models import (
    SCHEMA_VERSION, CatalogRecord, DiscoveryRequest, DocumentCandidate, DownloadResult, ErrorClass, JobContext,
    JobState, ManifestRecord, PipelineResult, RunContext, utc_now)
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
        self._attempts: Dict[str, int] = {}
        self._counter_lock = threading.Lock()      # U3: job_id y attempt únicos también con hilos
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
        # U5B: versiones aditivas (tablas y sidecars se crean de forma perezosa en la primera escritura versionada).
        self.versions = VersionRepository(self.layout.catalog_db, self.layout.versions, self.run.mode)
        self.preflight = preflight or KnownDocumentPreflight(
            RepositoryKnownDocumentLookup(self.manifests, self.catalog, self.cas, self.versions))

    # ------------------------------------------------------------------------------
    def run_discovery(self, request: DiscoveryRequest) -> RunReport:
        adapter = self.adapters[request.authority.upper()]
        report = RunReport(run_id=self.run.run_id)
        try:
            candidates = adapter.discover(request)
        except Exception as ex:      # U4: sin candidatos no se persiste nada; el fallo queda en la telemetría y se propaga
            self.telemetry.emit("adapter_discovery_failed", None, "ingest_runner", authority=request.authority,
                                error=sanitize_message(f"{type(ex).__name__}: {ex}"))
            raise
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
        with self._counter_lock:
            self._seq += 1   # job_id único y monótono dentro del run (no se reinicia entre autoridades)
            seq = self._seq
            self._attempts[cand.document_id] = attempt = self._attempts.get(cand.document_id, 0) + 1
        job = JobContext.for_candidate(self.run, seq, cand, attempt=attempt)   # attempt = nº de intento de ESTE documento en el run
        out = self._process_job(adapter, cand, job)
        out.attempt_id = job.attempt_id
        return out

    def _process_job(self, adapter: SourceAdapter, cand: DocumentCandidate, job: JobContext) -> JobOutcome:
        self._state(job, JobState.DISCOVERED, url=cand.source_url)

        # U1 guard LIVE (ADR-005): ningún candidato simulado/fixture avanza fuera de TEST/SANDBOX.
        try:
            assert_not_simulated(cand, self.run.mode)
        except SimulatedDataRejectedError as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.VALIDATION_REJECTED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value,
                              ErrorClass.VALIDATION_REJECTED.value, str(ex))

        # CNMV-U4: una señal oficial de sustitución/rectificación NO se resuelve sola: revisión manual, sin descarga ni reemplazo.
        if any(getattr(s, "kind", None) == POSSIBLE_REPUBLICATION for s in cand.replacement_signals):
            self._state(job, JobState.MANUAL_REVIEW, error_class=POSSIBLE_REPUBLICATION)
            return JobOutcome(job.job_id, job.document_id, JobState.MANUAL_REVIEW.value, POSSIBLE_REPUBLICATION,
                              "la fuente indica una posible sustitución del documento: revisión manual (sin descarga ni reemplazo)",
                              needs_manual_review=True)

        # U5A: preflight de SOLO LECTURA antes de cualquier lock, rate limiter, conexión, .part o CAS.
        pf = self._run_preflight(job, cand)
        if not (pf.may_download or pf.reuses_content):
            return self._preflight_terminal(job, pf)
        # ÚNICA autoridad de skip: KnownDocumentPreflight. No existe idempotencia por document_id + integridad local
        # (no prueba que la representación remota no haya cambiado); sin validador remoto se descarga y el UoW decide.

        try:
            lock_names = self._lock_names(cand)
        except DomainValidationError as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.VALIDATION_REJECTED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value,
                              ErrorClass.VALIDATION_REJECTED.value, str(ex))
        try:
            with ExitStack() as stack:
                for name in lock_names:        # orden global fijo (ver ``_lock_names``)
                    stack.enter_context(self.locks.acquire(name, timeout_s=self.lock_timeout_s))
                return self._process_locked(adapter, cand, job)
        except LockTimeout as ex:
            self._state(job, JobState.FAILED, error_class=ErrorClass.LOCKED.value, message=str(ex))
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.LOCKED.value, str(ex))

    # ------------------------------------------------------------------------------
    @staticmethod
    def _lock_names(cand: DocumentCandidate) -> List[str]:
        """Locks por documento en ORDEN GLOBAL FIJO (clase a clase): ``idk-`` < ``doc-`` < ``ver-`` < ``cas-``.
        · identidad lógica (id_scope=LOGICAL_DOCUMENT): ``idk-<hash(identity_key)>`` y luego el slot ``doc-<document_id>``;
        · id_scope=VERSION: el slot ``doc-<document_id>`` (serializa todas las versiones del slot) y luego
          ``ver-<hash(version_ref)>``;
        · sin identidad contratada: solo el slot, como antes.
        ``cas-<sha256>`` lo toma ``ContentAddressedRawStore`` dentro de ``promote``/``rollback_owned`` y es siempre el
        último. Cada clase se adquiere como mucho una vez y siempre en este orden => sin ciclos de espera entre workers
        de este runner. Las rutas de escritura de versiones exigen estar dentro de estos locks."""
        ident = resolve_identity(cand.authority, cand.document_id, cand.identity_contract, cand.source_document_id)

        def h(s: str) -> str:
            return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]
        names: List[str] = []
        if ident.identity_kind is IdentityKind.SOURCE_ID:
            names.append("idk-" + h(ident.identity_key))
        names.append(f"doc-{cand.document_id}")
        if ident.is_contracted and ident.id_scope is IdScope.VERSION and ident.version_ref:
            names.append("ver-" + h(ident.version_ref))
        return names

    _PREFLIGHT_EVENT = {
        PreflightStatus.REPUBLICATION_CONFIRMED: "PREFLIGHT_REPUBLICATION_CONFIRMED",
        PreflightStatus.REUSE_EXISTING_CONTENT: "PREFLIGHT_REUSE_CONTENT",
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

    def _adapter_failure(self, job: JobContext, ex: BaseException) -> JobOutcome:
        text = sanitize_message(f"fallo del adapter: {type(ex).__name__}: {ex}")
        self._state(job, JobState.FAILED, error_class=ErrorClass.UNKNOWN.value, message=text, failure_stage="ADAPTER")
        return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.UNKNOWN.value, text,
                          failure_stage="ADAPTER")

    def _blob_referenced(self, sha256: str) -> bool:
        """¿Alguna versión (de cualquier identidad) usa este blob? Falla cerrado: ante la duda, el blob se conserva."""
        try:
            return bool(self.versions.list_versions_by_sha256(sha256))
        except Exception:
            return True

    def _abort_promotion(self, job: JobContext, promo, klass: ErrorClass, message: str, *, failure_stage: Optional[str],
                         uow=None, force_recovery: bool = False) -> JobOutcome:
        """Cierra un intento fallido DESPUÉS de promover: revierte solo lo demostrablemente propio del CAS/raw
        (``rollback_owned``; el ``UnitOfWork`` nunca toca el CAS) y decide FAILED vs RECOVERY_REQUIRED.
        RECOVERY_REQUIRED = la compensación del manifiesto/catálogo falló, el estado previo era parcial, o queda un
        blob/vista raw sin propiedad demostrable (``orphaned_cas_*``): requiere reconciliación manual."""
        rb = self.cas.rollback_owned(promo, keep_blob=self._blob_referenced(promo.sha256))
        comp_errors = [sanitize_message(e) for e in (uow.compensation_errors if uow else ())]
        recovery = bool(comp_errors) or bool(uow and uow.recovery_required) or not rb.clean or force_recovery
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
        # la integridad del blob la vuelve a comprobar el mismo lookup que usó el preflight (el runner no verifica por su cuenta)
        reuse = pf.reuses_content and self.preflight.lookup.blob_is_intact(pf.reuse_sha256)
        if not (pf.may_download or pf.reuses_content):
            return self._preflight_terminal(job, pf)
        self._state(job, JobState.QUEUED)
        try:
            meta = adapter.fetch_metadata(cand)
        except Exception as ex:      # U4: un adapter defectuoso no tumba el run; aún no se ha tocado CAS/manifiesto/catálogo
            return self._adapter_failure(job, ex)
        staging = self.layout.staging / job.run_id / job.document_id
        if reuse:
            # U5B: mismo contenido ya en el CAS (hash esperado autoritativo y blob íntegro): sin transporte. Se copia el
            # blob a staging y se sigue el flujo normal (validación local -> promote(dedup) -> registros).
            staging.mkdir(parents=True, exist_ok=True)
            staged = staging / meta.file_name
            shutil.copy2(self.cas.blob_path(pf.reuse_sha256), staged)
            dl = DownloadResult(ok=True, staged_path=str(staged), sha256=pf.reuse_sha256, size_bytes=staged.stat().st_size)
            self.telemetry.emit("cas_reuse", job, "ingest_runner", sha256=pf.reuse_sha256)
        else:
            build = getattr(adapter, "build_download_request", None)
            from mod_01_ingestion.src.unified.models import DownloadRequest
            try:
                dreq = build(cand, meta, staging) if build else DownloadRequest(
                    url=meta.resolved_url, staging_dir=str(staging), file_name=meta.file_name,
                    expected_sha256=meta.expected_sha256, headers=meta.headers)
            except Exception as ex:
                return self._adapter_failure(job, ex)

            if (cand.transport_url is not None and dreq.transport_url is None
                    and strip_url(dreq.url) == strip_url(cand.source_url)):
                dreq = dataclasses.replace(dreq, transport_url=cand.transport_url)      # CNMV-U4: solo en memoria
            self._state(job, JobState.DOWNLOADING, url=dreq.url)
            dl = self.download.download(dreq, job)
            if not dl.ok:
                self._state(job, JobState.FAILED, error_class=dl.error_class, status=dl.http_status)
                return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, dl.error_class, dl.error_message)
        ident = resolve_identity(cand.authority, cand.document_id, cand.identity_contract, cand.source_document_id)
        if ident.is_contracted and cand.expected_sha256 and str(cand.expected_sha256).lower() != str(dl.sha256).lower():
            Path(dl.staged_path).unlink(missing_ok=True)
            self._state(job, JobState.FAILED, error_class=ErrorClass.CHECKSUM_MISMATCH.value, failure_stage="DOWNLOAD")
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.CHECKSUM_MISMATCH.value,
                              "el contenido obtenido no coincide con el hash esperado del candidato")

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

        if ident.is_contracted:
            return self._finalize_versioned(cand, job, meta, dl, val, pf, ident)
        failed, promo = self._legacy_commit(cand, job, meta, dl, val)
        if failed is not None:
            return failed
        self._state(job, JobState.COMPLETED, sha256=dl.sha256, raw_path=promo.raw_path, deduplicated=promo.deduplicated)
        return JobOutcome(job.job_id, job.document_id, JobState.COMPLETED.value, raw_path=promo.raw_path, sha256=dl.sha256)

    # ------------------------------------------------------------------------------
    def _raw_relpath(self, cand: DocumentCandidate, meta) -> Path:
        return Path(f"{cand.country_code}_{cand.authority}") / str(cand.fiscal_year) / _safe(cand.issuer_id) / meta.file_name

    def _legacy_commit(self, cand: DocumentCandidate, job: JobContext, meta, dl, val):
        """Promoción + manifiesto/catálogo en UNA unidad de trabajo (U4). Devuelve ``(resultado_fallido | None, promo)``.
        Camino histórico, sin cambios de comportamiento."""
        self._state(job, JobState.PROMOTING)
        promo = self.cas.promote(Path(dl.staged_path), dl.sha256, self._raw_relpath(cand, meta))

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
                deduplicated=promo.deduplicated, registration_number=cand.registration_number,
                declared_resource_kind=cand.declared_resource_kind)
        except Exception as ex:      # modelo inválido: antes se propagaba dejando el raw promovido sin registro
            return self._abort_promotion(job, promo, ErrorClass.MANIFEST_FAILED, str(ex), failure_stage="MANIFEST"), promo

        uow = ManifestCatalogUnitOfWork(self.manifests, self.catalog, mode=self.run.mode)
        catalog_record = CatalogRecord(
            document_id=job.document_id, run_id=job.run_id, job_id=job.job_id, authority=cand.authority,
            country_code=cand.country_code, issuer_id=cand.issuer_id, fiscal_year=cand.fiscal_year,
            doc_type=cand.doc_type, sha256=dl.sha256, raw_path=promo.raw_path,
            manifest_path=str(uow.final_manifest_path(record)), status=record.status, size_bytes=dl.size_bytes)
        result = uow.execute(record, catalog_record, on_phase=lambda p: self._state(job, JobState[p]))
        if not result.ok:
            return self._abort_promotion(job, promo, ErrorClass(result.error_class or ErrorClass.UNKNOWN.value),
                                         result.message or "", failure_stage=result.failure_stage, uow=result), promo

        Path(dl.staged_path).unlink(missing_ok=True)
        return None, promo

    # ------------------------------------------------------------------------------
    def _first_version_status(self, cand: DocumentCandidate, dl, ident: ResolvedIdentity) -> VersionStatus:
        """``initial_version_policy`` del contrato (por defecto NONE => nunca CURRENT automático)."""
        policy = ident.contract.initial_version_policy
        if policy is InitialVersionPolicy.TRUST_FIRST_VALIDATED:
            return VersionStatus.CURRENT
        if (policy is InitialVersionPolicy.REQUIRE_AUTHORITATIVE_HASH and ident.contract.expected_sha256_authority
                and cand.expected_sha256 and str(cand.expected_sha256).lower() == dl.sha256):
            return VersionStatus.CURRENT
        return VersionStatus.UNCONFIRMED

    def _finalize_versioned(self, cand: DocumentCandidate, job: JobContext, meta, dl, val, pf: PreflightOutcome,
                            ident: ResolvedIdentity) -> JobOutcome:
        """Registro con identidad contratada (U5B). Se ejecuta DENTRO de los locks de ``_lock_names``.

        * Versión PRIMARIA (el slot histórico no existe o ya tiene estos mismos bytes): camino legacy completo
          (raw + manifiesto + catálogo) y después la versión. Si lo segundo falla NO se revierte lo ya confirmado:
          ``RECOVERY_REQUIRED`` (sin atomicidad distribuida); la siguiente ejecución vuelve a registrar la versión.
        * Versión ADICIONAL (otros bytes que los del slot): nunca toca manifiesto/catálogo legacy. ``CURRENT`` solo con
          republicación confirmada por contrato (se crea vista raw con sufijo de hash); si no, ``UNCONFIRMED``: sin vista
          raw, solo blob CAS + sidecar + tabla, y el estado ``CURRENT`` previo no cambia."""
        existing = self.versions.list_versions(ident.identity_key)
        known = next((v for v in existing if v["sha256"] == dl.sha256), None)
        legacy_m = self.manifests.get(cand.authority, cand.fiscal_year, cand.document_id)
        legacy_c = self.catalog.get(cand.document_id)
        legacy_sha = (legacy_m or {}).get("sha256") or (legacy_c[1] if legacy_c else None)
        primary = (legacy_m is None and legacy_c is None) or legacy_sha == dl.sha256

        if pf.status is PreflightStatus.REPUBLICATION_CONFIRMED:
            status = VersionStatus.CURRENT
        elif known is not None:
            status = VersionStatus(known["status"]) if known.get("status") else VersionStatus.UNCONFIRMED
        elif not existing:
            status = self._first_version_status(cand, dl, ident)
        else:
            status = VersionStatus.UNCONFIRMED
        supersede = status is VersionStatus.CURRENT and pf.status is PreflightStatus.REPUBLICATION_CONFIRMED
        ev = cand.republication_evidence.canonical_json() if cand.republication_evidence is not None else None
        fact = DocumentVersion(
            identity_key=ident.identity_key, sha256=dl.sha256, identity_kind=ident.identity_kind.value,
            authority=cand.authority, document_id=cand.document_id, size_bytes=dl.size_bytes,
            normalizer_version=ident.contract.normalizer_version, version_ref=ident.version_ref,
            revision=cand.source_revision, contract_id=ident.contract.contract_id,
            contract_version=ident.contract.contract_version, source_document_id_raw=ident.raw_id, evidence_json=ev,
            first_observed_at=utc_now(), run_id=job.run_id, job_id=job.job_id)
        event_ev = json.dumps({"preflight": pf.reason_code, "policy": ident.contract.initial_version_policy.value},
                              sort_keys=True)

        if primary:
            failed, promo = self._legacy_commit(cand, job, meta, dl, val)
            if failed is not None:
                return failed
            reg = self.versions.register_version(fact, status, cas_path=promo.cas_path, supersede_current=supersede,
                                                 evidence_json=event_ev)
            if not reg.ok:
                return self._version_failure(job, reg, dl, promo=None)
            self._observe(job, ident, cand, dl, pf)
            self._state(job, JobState.COMPLETED, sha256=dl.sha256, raw_path=promo.raw_path,
                        deduplicated=promo.deduplicated, version_status=reg.status)
            return JobOutcome(job.job_id, job.document_id, JobState.COMPLETED.value, raw_path=promo.raw_path,
                              sha256=dl.sha256, version_status=reg.status)

        view = status is VersionStatus.CURRENT
        self._state(job, JobState.PROMOTING)
        try:
            # sin vista raw, el pin (clave estable derivada de la identidad) es la referencia durable del blob
            pin_key = hashlib.sha256(ident.identity_key.encode("utf-8")).hexdigest()[:32]
            promo = self.cas.promote(Path(dl.staged_path), dl.sha256, self._raw_relpath(cand, meta) if view else None,
                                     create_view=view, pin_key=None if view else pin_key)
        except Exception as ex:          # p. ej. CasPinError: promoción fallida CERRADA, nada queda desprotegido
            Path(dl.staged_path).unlink(missing_ok=True)
            text = sanitize_message(f"promoción CAS fallida: {type(ex).__name__}: {ex}")
            self._state(job, JobState.FAILED, error_class=ErrorClass.UNKNOWN.value, message=text, failure_stage="CAS")
            return JobOutcome(job.job_id, job.document_id, JobState.FAILED.value, ErrorClass.UNKNOWN.value, text,
                              sha256=dl.sha256, failure_stage="CAS")
        reg = self.versions.register_version(fact, status, cas_path=promo.cas_path, supersede_current=supersede,
                                             evidence_json=event_ev)
        if not reg.ok:
            return self._version_failure(job, reg, dl, promo=promo)
        Path(dl.staged_path).unlink(missing_ok=True)
        self._observe(job, ident, cand, dl, pf)
        if status is VersionStatus.UNCONFIRMED:
            self._state(job, JobState.MANUAL_REVIEW, reason_code="UNCONFIRMED_VERSION_RETAINED", sha256=dl.sha256,
                        version_status=reg.status, cas_blob_retained=True)
            return JobOutcome(job.job_id, job.document_id, JobState.MANUAL_REVIEW.value, message=sanitize_message(
                "versión conservada como UNCONFIRMED (sin vista raw); la versión CURRENT no cambia"),
                sha256=dl.sha256, needs_manual_review=True, version_status=reg.status)
        self._state(job, JobState.COMPLETED, sha256=dl.sha256, raw_path=promo.raw_path, version_status=reg.status,
                    superseded=reg.superseded_sha256)
        return JobOutcome(job.job_id, job.document_id, JobState.COMPLETED.value, raw_path=promo.raw_path,
                          sha256=dl.sha256, version_status=reg.status)

    def _version_failure(self, job: JobContext, reg: RegisterResult, dl, promo) -> JobOutcome:
        """Cierra un registro de versión fallido. Con ``promo`` (versión adicional) revierte solo lo demostrablemente propio
        del CAS; sin ``promo`` (versión primaria, legacy ya confirmado) no revierte nada y exige reconciliación."""
        klass = ErrorClass.INVARIANT_VIOLATION if reg.outcome in ("CONFLICT", "RECOVERY_REQUIRED") else ErrorClass.CATALOG_FAILED
        detail = reg.message + (f" | diferencias: {','.join(reg.differences)}" if reg.differences else "")
        if reg.compensation_errors:
            detail += " | COMPENSACIÓN INCOMPLETA: " + "; ".join(reg.compensation_errors)
        forced = reg.outcome == "RECOVERY_REQUIRED" or promo is None
        if promo is not None:
            return self._abort_promotion(job, promo, klass, detail, failure_stage="VERSION", force_recovery=forced)
        text = sanitize_message(detail + " | el registro legacy ya estaba confirmado: no se revierte; reconciliar versión")
        self._state(job, JobState.RECOVERY_REQUIRED, error_class=klass.value, message=text, failure_stage="VERSION",
                    recovery_required=True)
        return JobOutcome(job.job_id, job.document_id, JobState.RECOVERY_REQUIRED.value, klass.value, text,
                          sha256=dl.sha256, needs_manual_review=True, failure_stage="VERSION")

    def _observe(self, job: JobContext, ident: ResolvedIdentity, cand: DocumentCandidate, dl, pf: PreflightOutcome) -> None:
        """Observación append-only (best-effort): un fallo aquí se registra en telemetría y no altera el resultado."""
        res = self.versions.record_observation(Observation(
            run_id=job.run_id, job_id=job.job_id, identity_key=ident.identity_key, sha256=dl.sha256,
            expected_sha256=(str(cand.expected_sha256).lower() if cand.expected_sha256 else None),
            preflight_status=pf.status.value))
        if not res.ok:
            self.telemetry.emit("version_observation_failed", job, "ingest_runner", outcome=res.outcome,
                                message=res.message)

def _safe(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)
