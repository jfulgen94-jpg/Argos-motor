"""
U4 — ManifestCatalogUnitOfWork + reversión segura del CAS: orden, invariante, compensación, RECOVERY_REQUIRED,
idempotencia/conflictos y propiedad de blobs. Offline, todo bajo ``tmp_path``. Los repositorios usan modo TEST salvo en
los tests que verifican explícitamente la política LIVE (marcados en su nombre).
"""
import ast
import json
import warnings
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified import ingest_runner as runner_module
from mod_01_ingestion.src.unified import persistence_guard
from mod_01_ingestion.src.unified.application import ports
from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore, file_sha256
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain.enums import ErrorClass, ExecutionMode, PipelineStatus, UnitOfWorkStatus
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, InvalidStateTransitionError
from mod_01_ingestion.src.unified.domain.models import CatalogRecord, ManifestRecord, UnitOfWorkOutcome
from mod_01_ingestion.src.unified.lock_manager import LockManager
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified.unit_of_work import ExistingState, ManifestCatalogUnitOfWork

SHA = "ef" * 32
S = UnitOfWorkStatus


def records(manifests: ManifestRepository, **over):
    m = dict(manifest_version="1.0.0", document_id="CNMV_L1_2023_ESEF", run_id="r1", job_id="j1", authority="CNMV",
             country_code="ES", issuer_id="L1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
             source_url="https://example.test/a.zip", final_url=None, raw_path="raw/a.zip", cas_path="cas/x",
             sha256=SHA, size_bytes=10, mime_type=None, http_status=200, status="RAW_VALIDATED",
             completeness_status="OK")
    m.update(over)
    manifest = ManifestRecord(**m)
    cat = CatalogRecord(document_id=manifest.document_id, run_id="r1", job_id="j1", authority="CNMV", country_code="ES",
                        issuer_id="L1", fiscal_year=2023, doc_type=manifest.doc_type, sha256=manifest.sha256,
                        raw_path=manifest.raw_path,
                        manifest_path=str(manifests.path_for("CNMV", 2023, manifest.document_id)),
                        status=manifest.status, size_bytes=10)
    return manifest, cat


@pytest.fixture
def env(tmp_path):
    layout = DataLayout(tmp_path / "root")
    manifests = ManifestRepository(layout, mode=ExecutionMode.TEST)
    catalog = CatalogRepository(layout.catalog_db, mode=ExecutionMode.TEST)
    return layout, manifests, catalog


def state(layout, catalog, doc="CNMV_L1_2023_ESEF"):
    return {"final": [p.name for p in layout.manifests.rglob("*.json")],
            "pending": [p.name for p in layout.manifests.rglob("*.pending")],
            "catalog_row": catalog.get(doc)}


def boom(msg):
    def f(*a, **k):
        raise OSError(msg)
    return f


# =============================================================== éxito y orden
def test_happy_path_commits_consistently_and_returns_typed_outcome(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert isinstance(out, UnitOfWorkOutcome) and out.ok and out.committed and out.status is S.COMMITTED
    assert out.error_class is None and not out.compensated and not out.needs_manual_review and not out.idempotent
    s = state(layout, catalog)
    assert s["final"] == [f"{m.document_id}.json"] and s["pending"] == [] and s["catalog_row"][1] == SHA
    assert json.loads(Path(out.manifest_path).read_text())["sha256"] == SHA
    json.dumps(out.to_dict())


def test_order_is_inspect_stage_upsert_validate_commit_and_phases_reported(env):
    layout, manifests, catalog = env
    calls = []
    for obj, names in ((manifests, ("stage", "commit", "abort")), (catalog, ("upsert", "delete", "get"))):
        for n in names:
            orig = getattr(obj, n)
            setattr(obj, n, (lambda f, nn: (lambda *a, **k: (calls.append(nn), f(*a, **k))[1]))(orig, n))
    phases = []
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c, on_phase=phases.append)
    assert out.ok and phases == ["MANIFESTING", "CATALOGING"]
    assert calls == ["get", "stage", "upsert", "get", "commit"]   # inspect, stage, upsert, validate(get), commit LO ÚLTIMO


# =============================================================== fallos con compensación COMPLETA => FAILED_*
def test_manifest_prepare_failure_leaves_nothing(env, monkeypatch):
    layout, manifests, catalog = env
    monkeypatch.setattr(manifests, "stage", boom("disk full"))
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_MANIFEST and out.error_class == ErrorClass.MANIFEST_FAILED.value
    assert out.compensated and out.failure_stage == "MANIFEST" and not out.committed and not out.needs_manual_review
    assert state(layout, catalog) == {"final": [], "pending": [], "catalog_row": None}


def test_catalog_prepare_failure_aborts_pending_manifest(env, monkeypatch):
    layout, manifests, catalog = env
    monkeypatch.setattr(catalog, "upsert", boom("duckdb locked"))
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_CATALOG and out.error_class == ErrorClass.CATALOG_FAILED.value and out.compensated
    assert state(layout, catalog) == {"final": [], "pending": [], "catalog_row": None}


def test_commit_failure_with_complete_compensation_is_failed_commit(env, monkeypatch):
    layout, manifests, catalog = env
    monkeypatch.setattr(manifests, "commit", boom("rename failed"))
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_COMMIT and out.error_class == "CATALOG_FAILED" and out.failure_stage == "COMMIT"
    assert out.compensated and not out.needs_manual_review
    assert state(layout, catalog) == {"final": [], "pending": [], "catalog_row": None}


def test_invariant_violation_blocks_commit_and_compensates(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    c.sha256 = "aa" * 32
    c.manifest_path = "otra/ruta.json"
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_INVARIANT and out.error_class == ErrorClass.INVARIANT_VIOLATION.value
    assert any(v.startswith("sha256") for v in out.invariant_violations)
    assert any(v.startswith("manifest_path") for v in out.invariant_violations)
    assert out.compensated and state(layout, catalog) == {"final": [], "pending": [], "catalog_row": None}


def test_invariant_detects_catalog_that_persisted_something_else(env, monkeypatch):
    layout, manifests, catalog = env
    orig = catalog.upsert

    def corrupting_upsert(rec):
        rec.sha256 = "bb" * 32
        orig(rec)
        rec.sha256 = SHA
    monkeypatch.setattr(catalog, "upsert", corrupting_upsert)
    m, c = records(manifests)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_INVARIANT and any("catálogo persistido" in v for v in out.invariant_violations)
    assert state(layout, catalog)["catalog_row"] is None


def test_live_policy_simulated_record_rejected_before_any_file(tmp_path):
    layout = DataLayout(tmp_path / "root")
    manifests = ManifestRepository(layout, mode=ExecutionMode.LIVE)          # LIVE a propósito: se prueba su política
    catalog = CatalogRepository(layout.catalog_db, mode=ExecutionMode.LIVE)
    m, c = records(manifests, doc_type="SIMULATED")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    assert out.status is S.FAILED_MANIFEST and "SIMULATED" in out.message
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before and catalog.count() == 0


# =============================================================== RECOVERY_REQUIRED
def _assert_recovery(out, stage, klass):
    assert out.status is S.RECOVERY_REQUIRED
    assert out.needs_manual_review and out.recovery_required and not out.committed and not out.ok
    assert out.failure_stage == stage and out.error_class == klass            # causa original conservada
    assert out.status is not S.FAILED_COMMIT and not out.compensated


@pytest.mark.parametrize("inject,stage,klass", [
    ("commit+catalog.delete", "COMMIT", "CATALOG_FAILED"),
    ("commit+manifests.abort", "COMMIT", "CATALOG_FAILED"),
    ("commit+both", "COMMIT", "CATALOG_FAILED"),
    ("upsert+manifests.abort", "CATALOG", "CATALOG_FAILED"),
    ("invariant+catalog.delete", "INVARIANT", "INVARIANT_VIOLATION"),
])
def test_compensation_failure_is_recovery_required(env, monkeypatch, inject, stage, klass):
    layout, manifests, catalog = env
    if inject.startswith("commit"):
        monkeypatch.setattr(manifests, "commit", boom("rename failed"))
    if inject.startswith("upsert"):
        monkeypatch.setattr(catalog, "upsert", boom("duckdb locked"))
    m, c = records(manifests)
    if inject.startswith("invariant"):
        c.sha256 = "aa" * 32
    if inject.endswith(("catalog.delete", "both")):
        monkeypatch.setattr(catalog, "delete", boom("duckdb gone"))
    if inject.endswith(("manifests.abort", "both")):
        monkeypatch.setattr(manifests, "abort", boom("unlink denied"))
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c)
    _assert_recovery(out, stage, klass)
    assert out.compensation_errors
    expected = {"catalog.delete": 1, "manifests.abort": 1, "both": 2}.get(inject.split("+")[-1])
    assert len(out.compensation_errors) == expected
    if inject.endswith("catalog.delete"):
        assert state(layout, catalog)["pending"] == []        # aun así se intentó abortar el manifiesto pendiente
    if inject.endswith("manifests.abort"):
        assert state(layout, catalog)["catalog_row"] is None  # y se borró la fila de catálogo


def test_outcome_invariants_are_enforced_by_the_model():
    with pytest.raises(DomainValidationError):                 # errores de compensación => RECOVERY_REQUIRED
        UnitOfWorkOutcome(S.FAILED_COMMIT, "d", compensation_errors=("x",), failure_stage="COMMIT")
    with pytest.raises(DomainValidationError):                 # RECOVERY_REQUIRED sin causa original
        UnitOfWorkOutcome(S.RECOVERY_REQUIRED, "d")
    with pytest.raises(DomainValidationError):                 # COMMITTED no admite errores
        UnitOfWorkOutcome(S.COMMITTED, "d", error_class="X")
    ok = UnitOfWorkOutcome(S.RECOVERY_REQUIRED, "d", failure_stage="COMMIT", compensation_errors=("x",))
    assert ok.needs_manual_review and not ok.committed
    assert UnitOfWorkOutcome(S.RECOVERY_REQUIRED, "d", error_class="CATALOG_FAILED").needs_manual_review


def test_compensate_is_idempotent_and_clean_failure_is_not_recovery(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    uow = ManifestCatalogUnitOfWork(manifests, catalog)
    uow.prepare_manifest(m)
    uow.prepare_catalog(c)
    first, second = uow.compensate(), uow.compensate()
    assert first.compensated and second.compensated and first.status is S.FAILED_MANIFEST
    assert not first.needs_manual_review
    assert state(layout, catalog) == {"final": [], "pending": [], "catalog_row": None}


def test_recovery_required_is_a_terminal_public_pipeline_state():
    from mod_01_ingestion.src.unified.domain.enums import ALLOWED_TRANSITIONS
    assert PipelineStatus.RECOVERY_REQUIRED.value == "RECOVERY_REQUIRED"
    assert ALLOWED_TRANSITIONS[PipelineStatus.RECOVERY_REQUIRED] == frozenset()
    for src in (PipelineStatus.PROMOTING, PipelineStatus.MANIFESTING, PipelineStatus.CATALOGING):
        assert PipelineStatus.RECOVERY_REQUIRED in ALLOWED_TRANSITIONS[src]


# =============================================================== idempotencia y conflictos
def test_identical_record_on_both_sides_is_unambiguous_idempotent_success(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c).ok
    final = next(layout.manifests.rglob("*.json"))
    before = (final.read_bytes(), final.stat().st_mtime_ns, catalog.count())
    m2, c2 = records(manifests, run_id="r2", job_id="j2")
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, c2)
    assert out.status is S.COMMITTED and out.idempotent and out.committed and not out.needs_manual_review
    assert (final.read_bytes(), final.stat().st_mtime_ns, catalog.count()) == before     # sin escrituras
    assert state(layout, catalog)["pending"] == []


def test_same_document_id_with_different_sha256_is_an_unambiguous_conflict(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c).ok
    final = next(layout.manifests.rglob("*.json"))
    before = final.read_bytes()
    m2, c2 = records(manifests, sha256="12" * 32)
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, c2)
    assert out.status is S.FAILED_INVARIANT and out.error_class == ErrorClass.INVARIANT_VIOLATION.value
    assert any(v.startswith("CONFLICT") for v in out.invariant_violations) and not out.committed
    assert final.read_bytes() == before and catalog.get(m.document_id)[1] == SHA     # la versión previa se conserva
    assert state(layout, catalog)["pending"] == []


@pytest.mark.parametrize("missing", ["catalog", "manifest"])
def test_partial_previous_state_is_recovery_required_not_committed(env, missing):
    layout, manifests, catalog = env
    m, c = records(manifests)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c).ok
    if missing == "catalog":
        catalog.delete(m.document_id)
    else:
        next(layout.manifests.rglob("*.json")).unlink()
    snapshot = state(layout, catalog)
    out = ManifestCatalogUnitOfWork(manifests, catalog).inspect_existing(m)
    assert out is (ExistingState.ONLY_MANIFEST if missing == "catalog" else ExistingState.ONLY_CATALOG)
    m2, c2 = records(manifests, run_id="r2", job_id="j2")
    res = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, c2)
    assert res.status is S.RECOVERY_REQUIRED and res.needs_manual_review and not res.committed and not res.idempotent
    assert res.failure_stage == "INSPECT" and res.recovery_reason
    assert state(layout, catalog) == snapshot                   # no repara ni escribe nada por su cuenta


@pytest.mark.parametrize("missing", ["catalog", "manifest"])
def test_partial_state_with_different_hash_is_a_conflict(env, missing):
    layout, manifests, catalog = env
    m, c = records(manifests)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, c).ok
    catalog.delete(m.document_id) if missing == "catalog" else next(layout.manifests.rglob("*.json")).unlink()
    m2, c2 = records(manifests, sha256="34" * 32)
    res = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, c2)
    assert res.status is S.FAILED_INVARIANT and any(v.startswith("CONFLICT") for v in res.invariant_violations)


def test_no_partial_situation_ever_reports_committed_without_restoration(env, monkeypatch):
    layout, manifests, catalog = env
    for inject in ("stage", "upsert", "commit"):
        mm = ManifestRepository(DataLayout(layout.root / inject), mode=ExecutionMode.TEST)
        cc = CatalogRepository(DataLayout(layout.root / inject).catalog_db, mode=ExecutionMode.TEST)
        target = {"stage": mm, "upsert": cc, "commit": mm}[inject]
        monkeypatch.setattr(target, inject, boom("x"))
        m, c = records(mm)
        out = ManifestCatalogUnitOfWork(mm, cc).execute(m, c)
        assert not out.committed
        assert state(DataLayout(layout.root / inject), cc) == {"final": [], "pending": [], "catalog_row": None}


# =============================================================== API y contrato
def test_granular_api_and_misuse(env):
    layout, manifests, catalog = env
    m, c = records(manifests)
    uow = ManifestCatalogUnitOfWork(manifests, catalog)
    with pytest.raises(InvalidStateTransitionError):
        uow.prepare_catalog(c)
    with pytest.raises(InvalidStateTransitionError):
        uow.commit()
    assert uow.prepare_manifest(m) is None and uow.prepare_catalog(c) is None
    assert uow.validate_invariant() == ()
    with pytest.raises(InvalidStateTransitionError):
        uow.prepare_manifest(m)
    assert uow.commit().ok
    with pytest.raises(InvalidStateTransitionError):
        uow.compensate()


def test_implementation_satisfies_port_and_never_touches_the_cas(env):
    layout, manifests, catalog = env
    assert isinstance(ManifestCatalogUnitOfWork(manifests, catalog), ports.ManifestCatalogUnitOfWork)
    src = Path(__import__("mod_01_ingestion.src.unified.unit_of_work", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any("cas_store" in i for i in imported)
    assert not any(isinstance(n, ast.Attribute) and n.attr in ("unlink", "rmtree", "remove", "rollback", "rollback_owned")
                   for n in ast.walk(tree))


# =============================================================== modo de los tests de inyección de fallos
def test_failure_injection_tests_use_non_productive_mode_and_isolated_roots(tmp_path):
    from mod_01_ingestion.tests.test_unified_ingest import FailingCatalog, FailingManifests
    layout = DataLayout(tmp_path / "data_root")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)             # sin DeprecationWarning (modo explícito)
        fm = FailingManifests(layout, mode=ExecutionMode.TEST)
        fc = FailingCatalog(layout.catalog_db, mode=ExecutionMode.TEST)
    assert fm.mode is ExecutionMode.TEST and fc.mode is ExecutionMode.TEST
    assert not persistence_guard.is_operational_location(layout.root)
    assert not persistence_guard.is_operational_location(fc.db_path)
    assert persistence_guard.is_authorized_sandbox_location(layout.root)
    assert fc.db_path.is_relative_to(tmp_path) and layout.manifests.is_relative_to(tmp_path)
    src = (Path(__file__).parent / "test_unified_ingest.py").read_text(encoding="utf-8")
    assert "mode=ExecutionMode.LIVE" not in src                         # ningún test focalizado fuerza LIVE


# =============================================================== integración con el runner
def test_runner_delegates_to_unit_of_work_and_keeps_state_sequence(tmp_path, monkeypatch):
    from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner
    from mod_01_ingestion.src.unified.models import DiscoveryRequest
    seen = []
    orig = ManifestCatalogUnitOfWork.execute
    monkeypatch.setattr(ManifestCatalogUnitOfWork, "execute",
                        lambda self, *a, **k: (seen.append(self.mode), orig(self, *a, **k))[1])
    runner, layout, _ = make_runner(tmp_path, base_site())
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "COMPLETED" and seen == [ExecutionMode.LIVE]
    states = [e["state"] for e in runner.telemetry.read_all() if e["event"] == "state_transition"]
    assert states == ["DISCOVERED", "QUEUED", "DOWNLOADING", "VALIDATING", "PROMOTING", "MANIFESTING", "CATALOGING",
                      "COMPLETED"]


def test_runner_recovery_required_when_compensation_fails_with_redacted_telemetry(tmp_path, monkeypatch):
    from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner
    from mod_01_ingestion.src.unified.models import DiscoveryRequest
    runner, layout, _ = make_runner(tmp_path, base_site())
    monkeypatch.setattr(runner.manifests, "commit", boom("rename failed"))
    monkeypatch.setattr(runner.catalog, "delete", boom("duckdb gone password=hunter2 token=abc123"))
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "RECOVERY_REQUIRED" and out.needs_manual_review and out.error_class == "CATALOG_FAILED"
    assert out.failure_stage == "COMMIT" and "COMPENSACIÓN INCOMPLETA" in out.message
    ev = [e for e in runner.telemetry.read_all() if e.get("state") == "RECOVERY_REQUIRED"][-1]
    assert ev["recovery_required"] is True and ev["uow_status"] == "RECOVERY_REQUIRED" and ev["compensation_errors"]
    blob = json.dumps(runner.telemetry.read_all()) + out.message
    assert "hunter2" not in blob and "abc123" not in blob                   # redactado
    assert not any(p.is_file() for p in layout.raw.rglob("*"))              # el raw propio sí se revierte (propiedad demostrada)


def test_runner_partial_state_reports_recovery_required_and_clean_failures_stay_failed(tmp_path):
    from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner, make_zip
    from mod_01_ingestion.src.unified.models import DiscoveryRequest
    payload = make_zip()                          # bytes fijos: make_zip() lleva marcas de tiempo y variaría entre llamadas
    runner, layout, _ = make_runner(tmp_path, base_site(zip_bytes=payload))
    runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    doc = "CNMV_LEI_ES_1_2023_ESEF_PACKAGE"
    runner.manifests.path_for("CNMV", 2023, doc).unlink()                  # queda solo el catálogo
    runner2, _, _ = make_runner(tmp_path, base_site(zip_bytes=payload))
    out = runner2.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "RECOVERY_REQUIRED" and out.needs_manual_review and out.failure_stage == "INSPECT"
    assert runner.catalog.get(doc) is not None                              # no se tocó el catálogo existente


# =============================================================== CAS: propiedad demostrable antes de borrar
def _store(tmp_path):
    layout = DataLayout(tmp_path / "root").ensure()
    return layout, ContentAddressedRawStore(layout, LockManager(layout.locks))


def _stage(tmp_path, name, data=b"contenido de prueba " * 20):
    p = tmp_path / "staged" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(data)
    return p, file_sha256(p)


def test_cas_A_preexisting_blob_survives_rollback(tmp_path):
    layout, cas = _store(tmp_path)
    s1, sha = _stage(tmp_path, "a.bin")
    first = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    s2, _ = _stage(tmp_path, "b.bin")
    second = cas.promote(s2, sha, Path("ES_CNMV/2023/b.bin"))
    assert second.deduplicated and second.receipt is None                    # no es propietario
    rb = cas.rollback_owned(second)
    assert rb.blob_state == "PREEXISTING_LEFT" and rb.raw_view_state == "REMOVED" and rb.clean
    assert Path(first.cas_path).exists() and Path(first.raw_path).exists() and not Path(second.raw_path).exists()


def test_cas_B_shared_blob_survives_rollback(tmp_path):
    layout, cas = _store(tmp_path)
    s1, sha = _stage(tmp_path, "a.bin")
    owner = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    assert owner.receipt is not None and owner.link_mode == "hardlink"
    s2, _ = _stage(tmp_path, "b.bin")
    other = cas.promote(s2, sha, Path("ES_CNMV/2023/b.bin"))                # otro documento enlaza el mismo blob
    rb = cas.rollback_owned(owner)
    assert rb.blob_state == "SHARED_LEFT" and rb.clean and rb.raw_view_state == "REMOVED"
    assert Path(owner.cas_path).exists() and Path(other.raw_path).exists()
    assert file_sha256(Path(other.raw_path)) == sha                         # la otra referencia sigue íntegra


def test_cas_C_new_blob_without_proof_is_left_orphan(tmp_path):
    layout, cas = _store(tmp_path)
    s1, sha = _stage(tmp_path, "a.bin")
    promo = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    promo.receipt = None                                                    # sin recibo => sin prueba de propiedad
    promo.deduplicated = False
    rb = cas.rollback_owned(promo)
    assert rb.blob_state == "UNPROVEN_ORPHAN" and not rb.clean
    assert rb.orphaned_sha256 == sha and rb.orphaned_path == f"cas/{sha[:2]}/{sha}"      # ruta relativa, sin datos personales
    assert Path(promo.cas_path).exists()                                    # NO se borra


def test_cas_C2_copy_mode_and_replaced_blob_are_unproven(tmp_path, monkeypatch):
    layout, cas = _store(tmp_path)
    s1, sha = _stage(tmp_path, "a.bin")
    promo = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    promo.link_mode = "copy"                                                # no hay prueba de exclusividad con copias
    assert cas.rollback_owned(promo).blob_state == "UNPROVEN_ORPHAN" and Path(promo.cas_path).exists()
    layout2, cas2 = _store(tmp_path / "second")
    s2, sha2 = _stage(tmp_path / "second", "z.bin")
    p2 = cas2.promote(s2, sha2, Path("ES_CNMV/2023/z.bin"))
    blob = Path(p2.cas_path)
    blob.unlink()
    blob.write_bytes(b"sustituido tras la promocion")                       # identidad distinta a la del recibo
    rb = cas2.rollback_owned(p2)
    assert rb.blob_state == "UNPROVEN_ORPHAN" and blob.exists()


def test_cas_D_reliable_receipt_allows_safe_rollback(tmp_path):
    layout, cas = _store(tmp_path)
    s1, sha = _stage(tmp_path, "a.bin")
    promo = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    assert promo.receipt and promo.receipt.created_blob and not promo.deduplicated
    rb = cas.rollback_owned(promo)
    assert rb.blob_state == "REMOVED" and rb.raw_view_state == "REMOVED" and rb.clean
    assert not Path(promo.cas_path).exists() and not Path(promo.raw_path).exists()
    assert s1.exists()                                                      # el staged nunca se toca
    again = cas.rollback_owned(promo)                                       # idempotente
    assert again.clean and again.blob_state == "REMOVED"


def _runner_with_invalid_manifest(tmp_path, monkeypatch):
    from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner
    from mod_01_ingestion.src.unified.models import DiscoveryRequest
    runner, layout, _ = make_runner(tmp_path, base_site())
    monkeypatch.setattr(runner_module, "ManifestRecord", lambda **kw: (_ for _ in ()).throw(ValueError("registro inválido")))
    return runner, layout, DiscoveryRequest(authority="CNMV")


def test_runner_invalid_manifest_record_new_blob_with_receipt_rolls_back_cleanly(tmp_path, monkeypatch):
    runner, layout, req = _runner_with_invalid_manifest(tmp_path, monkeypatch)
    out = runner.run_discovery(req).outcomes[0]
    assert out.state == "FAILED" and out.error_class == "MANIFEST_FAILED" and not out.needs_manual_review
    assert not any(p.is_file() for p in layout.raw.rglob("*")) and not any(p.is_file() for p in layout.cas.rglob("*"))


def test_runner_invalid_manifest_record_without_ownership_proof_is_recovery_required(tmp_path, monkeypatch):
    runner, layout, req = _runner_with_invalid_manifest(tmp_path, monkeypatch)
    orig = runner.cas.promote

    def promote_without_receipt(*a, **k):
        p = orig(*a, **k)
        p.receipt = None
        return p
    monkeypatch.setattr(runner.cas, "promote", promote_without_receipt)
    out = runner.run_discovery(req).outcomes[0]
    assert out.state == "RECOVERY_REQUIRED" and out.needs_manual_review and out.failure_stage == "MANIFEST"
    assert out.orphaned_cas_sha256 and out.orphaned_cas_path.startswith("cas/")
    assert any(p.is_file() for p in layout.cas.rglob("*"))                  # el blob NO se borró
    assert not any(p.is_file() for p in layout.raw.rglob("*"))              # la vista raw propia sí
    ev = [e for e in runner.telemetry.read_all() if e.get("state") == "RECOVERY_REQUIRED"][-1]
    assert ev["orphaned_cas_sha256"] == out.orphaned_cas_sha256 and ev["cas_blob_state"] == "UNPROVEN_ORPHAN"
    assert str(tmp_path) not in json.dumps(ev)                              # sin rutas absolutas personales


def test_runner_invalid_manifest_record_preexisting_blob_remains(tmp_path, monkeypatch):
    from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner, make_zip, provider_for
    from mod_01_ingestion.src.unified.models import DiscoveryRequest
    payload = make_zip()                          # bytes fijos (make_zip lleva marcas de tiempo)
    runner, layout, _ = make_runner(tmp_path, base_site(zip_bytes=payload))
    assert runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0].state == "COMPLETED"
    blobs = sorted(p for p in layout.cas.rglob("*") if p.is_file())
    runner2, _, _ = make_runner(tmp_path, base_site(zip_bytes=payload))
    runner2.adapters["CNMV"]._provider = provider_for([
        {"lei": "L9", "ticker": "ZZZ", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
         "url": "https://cnmv.test/pkg/san2023.zip"}])                    # mismo contenido, otro documento
    monkeypatch.setattr(runner_module, "ManifestRecord", lambda **kw: (_ for _ in ()).throw(ValueError("registro inválido")))
    out = runner2.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "FAILED" and not out.needs_manual_review          # limpio: el blob no era nuestro
    assert sorted(p for p in layout.cas.rglob("*") if p.is_file()) == blobs
    assert len([p for p in layout.raw.rglob("*") if p.is_file()]) == 1     # solo la vista del primer documento
