"""
U4 — ManifestCatalogUnitOfWork: único punto que hace consistentes manifiesto y catálogo (ADR-004).

    inspect existing -> prepare manifest -> prepare catalog -> validate invariant -> commit   (éxito: ``COMMITTED``)
                                 \\__ cualquier fallo -> compensate -> resultado tipado

Semántica de resultados (ver audits/UNIFIED_DOWNLOAD_U4_2026-10-09/02_RECOVERY_REQUIRED_MATRIX.csv):
- ``COMMITTED``: manifiesto y catálogo consistentes y confirmados (``idempotent=True`` si ya lo estaban: sin escrituras).
- ``FAILED_*``: falló una fase y la compensación se completó: no queda estado parcial.
- ``RECOVERY_REQUIRED``: la compensación falló o el estado previo es parcial (solo manifiesto / solo catálogo): queda
  una combinación que esta unidad NO restaura sola. Conserva ``failure_stage``/``error_class``; ``needs_manual_review``.
- Mismo ``document_id`` con distinto sha256 => ``FAILED_INVARIANT`` con violación ``CONFLICT`` y SIN escribir nada.
Esta unidad nunca toca el raw ni el CAS (los blobs los gestiona ``ContentAddressedRawStore.rollback_owned`` con recibo de
propiedad) y no emite telemetría (el llamador observa las fases con ``on_phase``). Una instancia = un documento.
Los fallos de infraestructura se devuelven como resultado; solo el uso incorrecto de la API lanza
``InvalidStateTransitionError``.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from mod_01_ingestion.src.unified.domain.enums import ErrorClass, ExecutionMode, UnitOfWorkStatus
from mod_01_ingestion.src.unified.domain.errors import InvalidStateTransitionError, sanitize_message
from mod_01_ingestion.src.unified.domain.models import CatalogRecord, ManifestRecord, UnitOfWorkOutcome
from mod_01_ingestion.src.unified.domain.policy import assert_manifest_allowed
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository

PhaseHook = Callable[[str], None]
_STAGE = {UnitOfWorkStatus.FAILED_MANIFEST: "MANIFEST", UnitOfWorkStatus.FAILED_CATALOG: "CATALOG",
          UnitOfWorkStatus.FAILED_INVARIANT: "INVARIANT", UnitOfWorkStatus.FAILED_COMMIT: "COMMIT"}


class _Phase(str, Enum):
    NEW = "NEW"
    MANIFEST_PREPARED = "MANIFEST_PREPARED"
    CATALOG_PREPARED = "CATALOG_PREPARED"
    VALIDATED = "VALIDATED"
    COMMITTED = "COMMITTED"
    COMPENSATED = "COMPENSATED"


class ExistingState(str, Enum):
    """Estado previo del documento antes de escribir."""
    ABSENT = "ABSENT"                  # ni manifiesto ni catálogo: flujo normal
    IDENTICAL = "IDENTICAL"            # ambos lados con el mismo registro: éxito idempotente
    CONFLICT = "CONFLICT"              # mismo document_id con distinto sha256
    ONLY_MANIFEST = "ONLY_MANIFEST"    # parcial: falta el catálogo
    ONLY_CATALOG = "ONLY_CATALOG"      # parcial: falta el manifiesto


class ManifestCatalogUnitOfWork:
    def __init__(self, manifests: ManifestRepository, catalog: CatalogRepository,
                 mode: Optional[ExecutionMode] = None):
        self.manifests = manifests
        self.catalog = catalog
        # Se aplican AMBAS políticas: la de esta unidad (``mode``; por defecto el del repositorio de manifiestos) y la
        # propia de cada repositorio en ``stage/commit/upsert``. Ninguna puede rebajar a la otra.
        self.mode = ExecutionMode(mode) if mode is not None else manifests.mode
        self._failure_status = UnitOfWorkStatus.FAILED_MANIFEST
        self._phase = _Phase.NEW
        self._manifest: Optional[ManifestRecord] = None
        self._catalog_record: Optional[CatalogRecord] = None
        self._pending: Optional[Path] = None
        self._cataloged = False
        self._final: Optional[Path] = None
        self._error_class: Optional[str] = None
        self._message: Optional[str] = None

    # ------------------------------------------------------------------ utilidades
    def final_manifest_path(self, manifest: ManifestRecord) -> Path:
        return self.manifests.path_for(manifest.authority, manifest.fiscal_year, manifest.document_id)

    def _require(self, *phases: _Phase, op: str) -> None:
        if self._phase not in phases:
            raise InvalidStateTransitionError(f"{op}() no permitido en fase {self._phase.value}")

    def _doc_id(self) -> str:
        return (self._manifest.document_id if self._manifest else
                self._catalog_record.document_id if self._catalog_record else "?")

    def _fail(self, status: UnitOfWorkStatus, klass: ErrorClass, ex: BaseException,
              violations: Tuple[str, ...] = ()) -> UnitOfWorkOutcome:
        """Registra la causa, compensa y devuelve ``FAILED_*`` (compensación completa) o ``RECOVERY_REQUIRED``."""
        self._failure_status, self._error_class, self._message = status, klass.value, str(ex)
        out = self.compensate()
        out.invariant_violations = violations
        return out

    # ------------------------------------------------------------------ estado previo
    def inspect_existing(self, manifest: ManifestRecord) -> ExistingState:
        """Lee (sin escribir) lo que ya hay de este documento en ambos lados y lo clasifica."""
        prior_m = self.manifests.get(manifest.authority, manifest.fiscal_year, manifest.document_id)
        prior_c = self.catalog.get(manifest.document_id)
        if prior_m is None and prior_c is None:
            return ExistingState.ABSENT
        if prior_m is None:      # parcial; pero con otro hash es un CONFLICTO de versión, no una simple reparación
            return ExistingState.CONFLICT if prior_c[1] != manifest.sha256 else ExistingState.ONLY_CATALOG
        if prior_c is None:
            return ExistingState.CONFLICT if prior_m.get("sha256") != manifest.sha256 else ExistingState.ONLY_MANIFEST
        same_hash = prior_m.get("sha256") == manifest.sha256 and prior_c[1] == manifest.sha256
        if not same_hash:
            return ExistingState.CONFLICT
        same_rest = (prior_m.get("raw_path") == manifest.raw_path and prior_c[3] == manifest.raw_path
                     and prior_m.get("doc_type") == manifest.doc_type and prior_m.get("status") == manifest.status
                     and prior_c[2] == manifest.status)
        return ExistingState.IDENTICAL if same_rest else ExistingState.CONFLICT

    # ------------------------------------------------------------------ fases
    def prepare_manifest(self, manifest: ManifestRecord) -> Optional[UnitOfWorkOutcome]:
        """Valida la política y deja el manifiesto en ``.pending``. Devuelve un resultado SOLO si falla."""
        self._require(_Phase.NEW, op="prepare_manifest")
        self._manifest = manifest
        try:
            assert_manifest_allowed(manifest, self.mode)
            self._pending = self.manifests.stage(manifest)
        except Exception as ex:      # frontera de infraestructura: se tipifica, no se propaga
            return self._fail(UnitOfWorkStatus.FAILED_MANIFEST, ErrorClass.MANIFEST_FAILED, ex)
        self._phase = _Phase.MANIFEST_PREPARED
        return None

    def prepare_catalog(self, catalog_record: CatalogRecord) -> Optional[UnitOfWorkOutcome]:
        self._require(_Phase.MANIFEST_PREPARED, op="prepare_catalog")
        self._catalog_record = catalog_record
        try:
            self.catalog.upsert(catalog_record)
            self._cataloged = True
        except Exception as ex:
            return self._fail(UnitOfWorkStatus.FAILED_CATALOG, ErrorClass.CATALOG_FAILED, ex)
        self._phase = _Phase.CATALOG_PREPARED
        return None

    def validate_invariant(self) -> Tuple[str, ...]:
        """Comprueba que lo preparado en manifiesto y catálogo es coherente. Devuelve las violaciones (vacío = OK)."""
        self._require(_Phase.CATALOG_PREPARED, op="validate_invariant")
        m, c = self._manifest, self._catalog_record
        assert m is not None and c is not None
        v: List[str] = []
        for name in ("document_id", "run_id", "job_id", "authority", "country_code", "issuer_id", "fiscal_year",
                     "doc_type", "sha256", "raw_path", "size_bytes", "status"):
            if getattr(m, name) != getattr(c, name):
                v.append(f"{name}: manifiesto={getattr(m, name)!r} catálogo={getattr(c, name)!r}")
        expected = str(self.final_manifest_path(m))
        if c.manifest_path != expected:
            v.append("manifest_path: el catálogo no apunta al manifiesto definitivo esperado")
        if self._pending is None or not Path(self._pending).exists():
            v.append("el manifiesto pendiente no existe en disco")
        try:
            row = self.catalog.get(c.document_id)       # lo realmente persistido en el catálogo
        except Exception as ex:
            row = None
            v.append(f"no se pudo leer el catálogo: {type(ex).__name__}")
        if row is None:
            v.append("el catálogo no contiene el documento tras preparar")
        elif row[1] != m.sha256:
            v.append("sha256: el catálogo persistido difiere del manifiesto")
        if not v:
            self._phase = _Phase.VALIDATED
        return tuple(v)

    def commit(self) -> UnitOfWorkOutcome:
        """Promueve el manifiesto pendiente a definitivo (último paso, atómico por ``os.replace``)."""
        self._require(_Phase.VALIDATED, op="commit")
        assert self._pending is not None and self._manifest is not None
        try:
            self._final = self.manifests.commit(self._pending)
        except Exception as ex:
            # Clasificación histórica del runner: un fallo en este punto era CATALOG_FAILED.
            return self._fail(UnitOfWorkStatus.FAILED_COMMIT, ErrorClass.CATALOG_FAILED, ex)
        self._pending = None
        self._phase = _Phase.COMMITTED
        return UnitOfWorkOutcome(status=UnitOfWorkStatus.COMMITTED, document_id=self._manifest.document_id,
                                 manifest_path=str(self._final))

    def compensate(self) -> UnitOfWorkOutcome:
        """Deshace en orden inverso lo preparado. Idempotente. Un error de compensación convierte el resultado en
        ``RECOVERY_REQUIRED`` (conservando la fase y la clase de error originales); nunca se oculta."""
        if self._phase is _Phase.COMMITTED:
            raise InvalidStateTransitionError("compensate() no permitido tras COMMITTED")
        errors: List[str] = []
        if self._cataloged and self._catalog_record is not None:
            try:
                self.catalog.delete(self._catalog_record.document_id)
                self._cataloged = False
            except Exception as ex:
                errors.append(sanitize_message(f"catalog.delete: {type(ex).__name__}: {ex}"))
        if self._pending is not None:
            try:
                self.manifests.abort(self._pending)
                self._pending = None
            except Exception as ex:
                errors.append(sanitize_message(f"manifests.abort: {type(ex).__name__}: {ex}"))
        self._phase = _Phase.COMPENSATED
        status = UnitOfWorkStatus.RECOVERY_REQUIRED if errors else self._failure_status
        return UnitOfWorkOutcome(
            status=status, document_id=self._doc_id(), error_class=self._error_class, message=self._message,
            compensated=not errors, compensation_errors=tuple(errors), failure_stage=_STAGE.get(self._failure_status),
            recovery_reason="la compensación falló: quedan manifiesto y/o catálogo sin restaurar" if errors else None)

    # ------------------------------------------------------------------ orquestación completa
    def execute(self, manifest: ManifestRecord, catalog_record: CatalogRecord,
                on_phase: Optional[PhaseHook] = None) -> UnitOfWorkOutcome:
        """inspect -> prepare manifest -> prepare catalog -> validate invariant -> commit, compensando ante cualquier fallo."""
        hook = on_phase or (lambda _p: None)
        self._manifest = manifest
        try:
            existing = self.inspect_existing(manifest)
        except Exception as ex:
            self._phase = _Phase.COMPENSATED
            return UnitOfWorkOutcome(
                status=UnitOfWorkStatus.RECOVERY_REQUIRED, document_id=manifest.document_id,
                error_class=ErrorClass.CATALOG_FAILED.value, message=sanitize_message(ex), failure_stage="INSPECT",
                recovery_reason="no se pudo determinar el estado previo del documento")
        if existing is ExistingState.IDENTICAL:
            self._phase = _Phase.COMMITTED
            return UnitOfWorkOutcome(status=UnitOfWorkStatus.COMMITTED, document_id=manifest.document_id,
                                     manifest_path=str(self.final_manifest_path(manifest)), idempotent=True)
        if existing is ExistingState.CONFLICT:
            self._phase = _Phase.COMPENSATED
            return UnitOfWorkOutcome(
                status=UnitOfWorkStatus.FAILED_INVARIANT, document_id=manifest.document_id,
                error_class=ErrorClass.INVARIANT_VIOLATION.value, failure_stage="INVARIANT", compensated=True,
                message="CONFLICT: el document_id ya existe con otro sha256/contenido; no se sobrescribe",
                invariant_violations=("CONFLICT: document_id existente con registro distinto",))
        if existing in (ExistingState.ONLY_MANIFEST, ExistingState.ONLY_CATALOG):
            self._phase = _Phase.COMPENSATED
            side = "manifiesto" if existing is ExistingState.ONLY_MANIFEST else "catálogo"
            return UnitOfWorkOutcome(
                status=UnitOfWorkStatus.RECOVERY_REQUIRED, document_id=manifest.document_id,
                error_class=ErrorClass.INVARIANT_VIOLATION.value, failure_stage="INSPECT",
                message=f"estado parcial previo: solo existe el {side}",
                recovery_reason=f"solo {side} presente; no se repara automáticamente")
        hook("MANIFESTING")
        failed = self.prepare_manifest(manifest)
        if failed:
            return failed
        hook("CATALOGING")
        failed = self.prepare_catalog(catalog_record)
        if failed:
            return failed
        violations = self.validate_invariant()
        if violations:
            return self._fail(UnitOfWorkStatus.FAILED_INVARIANT, ErrorClass.INVARIANT_VIOLATION,
                              ValueError("; ".join(violations)), violations)
        return self.commit()
