"""
U3 — Ejecución segura del pipeline unificado: ids consistentes, concurrencia en un proceso, CAS idempotente, no sobrescritura
de históricos, reconciliador (solo lectura) y recuperación tras fallos intermedios.

Offline y determinista: tmp_path, DuckDB temporal, fuentes simuladas (``httpx.MockTransport``), sockets bloqueados en la
validación. Los tests con hilos prueban UN proceso con el lock de identidad/slot; NO demuestran garantías multiproceso.
"""
import hashlib
import os
import threading
import time
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.models import JobContext, RunContext
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.repositories import (
    CatalogRepository, HistoricalOverwriteError, ManifestRepository)
from mod_01_ingestion.src.unified.unit_of_work import ManifestCatalogUnitOfWork
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.tests.test_unified_ingest import make_zip
from mod_01_ingestion.tests.test_unified_versions import (
    cand, contract, go, mk, raw_files, sha_of, staged, cas_env, legacy_bytes)
from mod_01_ingestion.src.unified.domain.versions import resolve_identity


# bytes FIJOS por módulo: ``make_zip`` lleva marca de tiempo y dos llamadas pueden diferir (flaky)
ZIP_A, ZIP_B = make_zip("A"), make_zip("B")


class Crash(BaseException):
    """Simula la muerte del proceso a mitad (no es una Exception: ningún ``except Exception`` del pipeline la captura)."""


def reconciler(runner):
    return UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions)


def tree(layout):
    """Huella del estado persistente (sin telemetría ni locks, que cambian por diseño)."""
    out = {}
    for sub in (layout.manifests, layout.raw, layout.cas, layout.staging, layout.quarantine, layout.versions,
                layout.root / "cas_pins"):
        if sub.exists():
            for p in sorted(sub.rglob("*")):
                if p.is_file():
                    out[str(p)] = (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    if layout.catalog_db.exists():
        out["catalog"] = hashlib.sha256(layout.catalog_db.read_bytes()).hexdigest()
    return out


# ================================================================= run_id / job_id / attempt_id
def test_run_job_attempt_ids_are_consistent_in_events_and_outcomes(tmp_path):
    c = cand()
    runner, layout, _ = mk(tmp_path, ZIP_A, [c, c])               # el mismo documento dos veces en el run
    rep = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    o1, o2 = rep.outcomes
    assert o1.job_id != o2.job_id and o1.job_id.startswith(runner.run.run_id) and o2.job_id.startswith(runner.run.run_id)
    assert (o1.attempt_id, o2.attempt_id) == (f"{o1.job_id}#a1", f"{o2.job_id}#a2")          # intento 1 y 2 del documento
    for o in rep.outcomes:
        evs = [e for e in runner.telemetry.read_all() if e["job_id"] == o.job_id]
        assert evs and {e["run_id"] for e in evs} == {runner.run.run_id}
        assert {e["attempt_id"] for e in evs} == {o.attempt_id}                              # un único attempt_id por job
        assert {e["document_id"] for e in evs} == {o.document_id}
    j = JobContext.for_candidate(RunContext(run_id="run-x", started_at="2026-10-12T10:00:00+00:00"), 7, c, attempt=3)
    assert j.job_id == "run-x:000007" and j.attempt_id == "run-x:000007#a3"
    with pytest.raises(DomainValidationError):
        JobContext.for_candidate(RunContext(run_id="run-x", started_at="2026-10-12T10:00:00+00:00"), 1, c, attempt=0)


def test_threads_get_unique_job_ids_and_consistent_attempt_numbers(tmp_path):
    c = cand()
    runner, layout, _ = mk(tmp_path, ZIP_A, [c])
    ad, out, errs = runner.adapters["CNMV"], [], []

    def work():
        try:
            out.append(runner.process_candidate(ad, c))
        except Exception as ex:                                           # pragma: no cover
            errs.append(repr(ex))
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(out) == 8
    assert len({o.job_id for o in out}) == 8 and sorted(int(o.attempt_id.rsplit("#a", 1)[1]) for o in out) == list(range(1, 9))


# ================================================================= concurrencia en un proceso
def test_threads_same_document_leave_exactly_one_effect(tmp_path):
    c = cand()
    runner, layout, _ = mk(tmp_path, ZIP_A, [c])
    ad, out = runner.adapters["CNMV"], []
    ts = [threading.Thread(target=lambda: out.append(runner.process_candidate(ad, c))) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert {o.state for o in out} == {"COMPLETED"}                                   # el UoW hace idempotentes a los demás
    assert len(list(layout.manifests.rglob("*.json"))) == 1 and len(raw_files(layout)) == 1
    assert runner.catalog.count() == 1 and len([p for p in layout.cas.rglob("*") if p.is_file()]) == 1
    assert not list(layout.manifests.rglob("*.pending")) and reconciler(runner).reconcile().clean


def test_threads_distinct_documents_share_one_cas_blob(tmp_path):
    cands = [cand(fiscal_year=y) for y in range(2018, 2024)]
    runner, layout, _ = mk(tmp_path, ZIP_A, cands)
    ad, out = runner.adapters["CNMV"], []
    ts = [threading.Thread(target=lambda c=c: out.append(runner.process_candidate(ad, c))) for c in cands]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert {o.state for o in out} == {"COMPLETED"} and runner.catalog.count() == 6
    assert len(list(layout.manifests.rglob("*.json"))) == 6 and len([p for p in layout.cas.rglob("*") if p.is_file()]) == 1
    assert reconciler(runner).reconcile().clean


def test_threads_same_contracted_identity_register_one_version(tmp_path):
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, _ = mk(tmp_path, ZIP_A, [c])
    ad, out = runner.adapters["CNMV"], []
    ts = [threading.Thread(target=lambda: out.append(runner.process_candidate(ad, c))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert {o.state for o in out} == {"COMPLETED"}
    ik = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1").identity_key
    vs = runner.versions.list_versions(ik)
    assert len(vs) == 1 and vs[0]["status"] == "CURRENT" and len(list(layout.versions.rglob("*.json"))) == 1
    assert reconciler(runner).reconcile().clean


def test_identity_lock_serializes_the_same_identity_in_one_process(tmp_path):
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, _ = mk(tmp_path, ZIP_A, [c])
    ad, state = runner.adapters["CNMV"], {"inside": 0, "peak": 0}
    gate, real = threading.Lock(), runner._process_locked

    def spy(*a, **k):
        with gate:
            state["inside"] += 1
            state["peak"] = max(state["peak"], state["inside"])
        try:
            time.sleep(0.03)
            return real(*a, **k)
        finally:
            with gate:
                state["inside"] -= 1
    runner._process_locked = spy
    ts = [threading.Thread(target=lambda: runner.process_candidate(ad, c)) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert state["peak"] == 1                                                         # nunca dos dentro del lock de identidad


# ================================================================= rate limiter por dominio
def test_rate_limiter_is_per_domain_and_used_by_the_download_service(tmp_path):
    now, waits = [0.0], []
    rl = DomainRateLimiter(max_concurrent_per_domain=1, min_interval_s=1.0, clock=lambda: now[0], sleep=waits.append)
    with rl.slot("https://a.test/x"):
        pass
    with rl.slot("https://b.test/x"):
        pass                                                                          # otro dominio: sin espera
    assert waits == []
    with rl.slot("https://a.test/y"):
        pass                                                                          # mismo dominio: respeta el intervalo
    assert len(waits) == 1 and abs(waits[0] - 1.0) < 1e-6
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    seen = []

    class Recording(DomainRateLimiter):
        def slot(self, url):
            seen.append(self.domain_of(url))
            return super().slot(url)
    runner.download.rate_limiter = Recording(min_interval_s=0, sleep=lambda s: None)
    assert go(runner).state == "COMPLETED" and seen == ["cnmv.test"]


# ================================================================= CAS idempotente y no sobrescritura histórica
def test_cas_promotion_is_idempotent(tmp_path):
    layout, cas = cas_env(tmp_path)
    data = b"I" * 400
    s1, sha = staged(layout, "a.bin", data)
    first = cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))
    links = os.stat(first.cas_path).st_nlink
    for n in range(2):
        s, _ = staged(layout, f"again{n}.bin", data)
        again = cas.promote(s, sha, Path("ES_CNMV/2023/a.bin"))
        assert again.raw_path == first.raw_path and again.link_mode == "existing" and again.deduplicated
    assert Path(first.raw_path).read_bytes() == data and os.stat(first.cas_path).st_nlink == links
    assert len([p for p in layout.cas.rglob("*") if p.is_file()]) == 1 and len([p for p in layout.raw.rglob("*") if p.is_file()]) == 1


def test_cas_never_overwrites_a_historical_raw_with_different_content(tmp_path):
    layout, cas = cas_env(tmp_path)
    s1, sha1 = staged(layout, "a.bin", b"OLD" * 200)
    old = cas.promote(s1, sha1, Path("ES_CNMV/2023/a.bin"))
    before = Path(old.raw_path).read_bytes()
    s2, sha2 = staged(layout, "b.bin", b"NEW" * 200)
    new = cas.promote(s2, sha2, Path("ES_CNMV/2023/a.bin"))                          # misma ruta lógica, otro contenido
    assert new.raw_path != old.raw_path and sha2[:8] in Path(new.raw_path).name       # versión con sufijo de hash
    assert Path(old.raw_path).read_bytes() == before and Path(old.cas_path).exists()


def test_repositories_refuse_to_overwrite_a_historical_record(tmp_path):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    assert go(runner).state == "COMPLETED"
    doc = cand().document_id
    final = runner.manifests.path_for("CNMV", 2023, doc)
    before, catalog_before = final.read_bytes(), runner.catalog.get(doc)
    import json
    forged = json.loads(before)
    forged["sha256"] = "ab" * 32
    from mod_01_ingestion.src.unified.models import ManifestRecord, CatalogRecord
    rec = ManifestRecord(**{k: v for k, v in forged.items() if k in ManifestRecord.__dataclass_fields__})
    with pytest.raises(HistoricalOverwriteError):
        runner.manifests.stage(rec)                                                   # antes de crear ningún fichero
    assert not list(layout.manifests.rglob("*.pending")) and final.read_bytes() == before
    pending = final.with_name(final.name + ".pending")
    pending.write_text(json.dumps(forged), encoding="utf-8")                          # .pending forjado
    with pytest.raises(HistoricalOverwriteError):
        runner.manifests.commit(pending)
    assert final.read_bytes() == before
    pending.unlink()
    crec = CatalogRecord(document_id=doc, run_id="r", job_id="j", authority="CNMV", country_code="ES", issuer_id="LEI_ES_1",
                         fiscal_year=2023, doc_type="ESEF_PACKAGE", sha256="ab" * 32, raw_path="x", manifest_path="y",
                         status="RAW_VALIDATED", size_bytes=1)
    with pytest.raises(HistoricalOverwriteError):
        runner.catalog.upsert(crec)
    assert runner.catalog.get(doc) == catalog_before


def test_rerun_with_different_bytes_does_not_overwrite_history(tmp_path):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    assert go(runner).state == "COMPLETED"
    manifests, raws, catalog = legacy_bytes(layout), raw_files(layout), runner.catalog.get(cand().document_id)
    r2, _, _ = mk(tmp_path, ZIP_B, [cand()])
    out = go(r2)
    assert out.state == "FAILED" and out.error_class == "INVARIANT_VIOLATION"
    assert legacy_bytes(layout) == manifests and raw_files(layout) == raws and r2.catalog.get(cand().document_id) == catalog
    assert len([p for p in layout.cas.rglob("*") if p.is_file()]) == 1                  # el blob nuevo se revirtió
    assert reconciler(r2).reconcile().clean


# ================================================================= reconciliador (solo lectura)
@pytest.fixture
def one_doc(tmp_path):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    assert go(runner).state == "COMPLETED"
    return runner, layout


def test_reconciler_is_clean_after_a_consistent_run_and_reads_without_side_effects(one_doc):
    runner, layout = one_doc
    before = tree(layout)
    rep = reconciler(runner).reconcile()
    assert rep.clean and rep.documents_checked == 1 and not rep.findings
    assert tree(layout) == before                                                      # solo lectura


def _doc(runner):
    return cand().document_id


def _stray_pending(runner):
    p = runner.manifests.path_for("CNMV", 2023, "otro_doc").with_name("otro_doc.json.pending")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


def _stray_blob(layout):
    d = layout.cas / "zz"
    d.mkdir(parents=True, exist_ok=True)
    (d / ("ef" * 32)).write_bytes(b"x")


MUTATIONS = {
    "MANIFEST_ONLY": lambda r, l: r.catalog.delete(_doc(r)),
    "CATALOG_ONLY": lambda r, l: r.manifests.path_for("CNMV", 2023, _doc(r)).unlink(),
    "RAW_MISSING": lambda r, l: Path(r.catalog.get(_doc(r))[3]).unlink(),
    "RAW_HASH_MISMATCH": lambda r, l: Path(r.catalog.get(_doc(r))[3]).write_bytes(b"alterado"),
    "CAS_BLOB_MISSING": lambda r, l: r.cas.blob_path(r.catalog.get(_doc(r))[1]).unlink(),
    "RAW_ORPHAN": lambda r, l: (l.raw / "ES_CNMV" / "huerfano.bin").write_bytes(b"sin registro"),
    "PENDING_MANIFEST": lambda r, l: _stray_pending(r),
    "HASH_MISMATCH_MANIFEST_CATALOG": lambda r, l: r.catalog._exec(
        "UPDATE unified_catalog SET sha256 = ? WHERE document_id = ?", ["cd" * 32, _doc(r)]),
    "FIELD_MISMATCH": lambda r, l: r.catalog._exec(
        "UPDATE unified_catalog SET status = 'OTRO' WHERE document_id = ?", [_doc(r)]),
    "CAS_ORPHAN": lambda r, l: _stray_blob(l),
}


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_reconciler_detects_each_desynchronization_without_repairing_it(one_doc, code):
    runner, layout = one_doc
    (layout.raw / "ES_CNMV").mkdir(parents=True, exist_ok=True)
    MUTATIONS[code](runner, layout)
    before = tree(layout)
    rep = reconciler(runner).reconcile()
    assert code in rep.codes() and not rep.clean, rep.codes()
    f = rep.by_code()[code][0]
    assert f.severity in ("ERROR", "WARN") and f.suggested_action                       # acción sugerida, nunca ejecutada
    assert tree(layout) == before                                                       # no repara ni borra nada


def test_reconciler_checks_versions_pins_and_sidecars(tmp_path):
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, _ = mk(tmp_path, ZIP_A, [c])
    assert go(runner).state == "COMPLETED" and reconciler(runner).reconcile().clean
    ik = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1").identity_key
    sha = sha_of(ZIP_A)
    side = runner.versions.sidecar_path(ik, sha)
    keep = side.read_bytes()
    side.unlink()
    assert "VERSION_TABLE_ONLY" in reconciler(runner).reconcile().codes()
    side.write_bytes(keep)
    import json
    forged = json.loads(keep)
    forged["facts"]["size_bytes"] = 999
    side.write_text(json.dumps(forged), encoding="utf-8")
    assert "VERSION_FACTS_MISMATCH" in reconciler(runner).reconcile().codes()
    side.write_bytes(keep)
    with runner.versions._connect() as con:
        con.execute("DELETE FROM unified_document_version_events"); con.execute("DELETE FROM unified_document_versions")
    assert "VERSION_SIDECAR_ONLY" in reconciler(runner).reconcile().codes()
    # pin huérfano (crash entre promote y registro): se informa, no se borra
    layout2, cas2 = cas_env(tmp_path / "pins")
    s, sha2 = staged(layout2, "p.bin", b"P" * 300)
    cas2.promote(s, sha2, None, create_view=False, pin_key="pinkey-AAAA")
    rep = UnifiedReconciler(layout2, CatalogRepository(layout2.catalog_db, mode=ExecutionMode.TEST), cas2,
                            runner.versions.__class__(layout2.catalog_db, layout2.versions, ExecutionMode.TEST)).reconcile()
    assert {"PIN_ORPHAN", "CAS_ORPHAN"} <= rep.codes() and (layout2.root / "cas_pins" / sha2 / "pinkey-AAAA").exists()


# ================================================================= recuperación tras fallo intermedio
def _crash_then_rerun(tmp_path, monkeypatch, target, attr, expected_codes):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])

    def boom(*a, **k):
        raise Crash()
    monkeypatch.setattr(target, attr, boom)
    with pytest.raises(Crash):
        go(runner)
    codes = reconciler(runner).reconcile().codes()
    monkeypatch.undo()
    return codes, layout


def test_crash_after_cas_promotion_before_unit_of_work_converges_on_rerun(tmp_path, monkeypatch):
    codes, layout = _crash_then_rerun(tmp_path, monkeypatch, ManifestCatalogUnitOfWork, "execute", None)
    assert {"RAW_ORPHAN"} <= codes and not (codes & {"MANIFEST_ONLY", "CATALOG_ONLY"})
    r2, _, _ = mk(tmp_path, ZIP_A, [cand()])
    assert go(r2).state == "COMPLETED"                                                  # la promoción dedup adopta lo existente
    assert reconciler(r2).reconcile().clean and len(raw_files(layout)) == 1


def test_crash_between_manifest_stage_and_catalog_converges_on_rerun(tmp_path, monkeypatch):
    codes, layout = _crash_then_rerun(tmp_path, monkeypatch, CatalogRepository, "upsert", None)
    assert "PENDING_MANIFEST" in codes
    r2, _, _ = mk(tmp_path, ZIP_A, [cand()])
    assert go(r2).state == "COMPLETED" and reconciler(r2).reconcile().clean            # el .pending se reescribe


def test_crash_between_catalog_and_manifest_commit_is_explicit_and_not_auto_repaired(tmp_path, monkeypatch):
    codes, layout = _crash_then_rerun(tmp_path, monkeypatch, ManifestRepository, "commit", None)
    assert {"CATALOG_ONLY", "PENDING_MANIFEST"} <= codes
    r2, _, _ = mk(tmp_path, ZIP_A, [cand()])
    before = tree(layout)
    out = go(r2)
    assert out.state == "RECOVERY_REQUIRED" and out.needs_manual_review                 # estado parcial: sin reparación automática
    assert tree(layout) == before and r2.catalog.get(cand().document_id) is not None
    assert {"CATALOG_ONLY", "PENDING_MANIFEST"} <= reconciler(r2).reconcile().codes()


def test_classified_catalog_failure_rolls_back_and_a_rerun_converges(tmp_path, monkeypatch):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    real = CatalogRepository.upsert
    calls = {"n": 0}

    def flaky(self, rec):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("catálogo caído")
        return real(self, rec)
    monkeypatch.setattr(CatalogRepository, "upsert", flaky)
    assert go(runner).state == "FAILED"
    assert reconciler(runner).reconcile().clean and raw_files(layout) == []             # compensado: sin huérfanos
    assert go(runner).state == "COMPLETED" and reconciler(runner).reconcile().clean


def test_skip_has_no_side_effects_and_leaves_the_reconciler_clean(tmp_path):
    A = ZIP_A
    runner, layout, _ = mk(tmp_path, A, [cand()])
    assert go(runner).state == "COMPLETED"
    before = tree(layout)
    r2, _, site2 = mk(tmp_path, A, [cand(expected_sha256=sha_of(A))])
    assert go(r2).state == "SKIPPED_ALREADY_PRESENT" and site2.calls == []
    assert tree(layout) == before and reconciler(r2).reconcile().clean


# ================================================================= regresiones halladas por la concurrencia (U3)
def test_lock_manager_treats_windows_permission_error_on_exclusive_create_as_busy(tmp_path, monkeypatch):
    from mod_01_ingestion.src.unified import lock_manager as lm
    mgr = lm.LockManager(tmp_path / "locks", poll_s=0.001)
    real, calls = os.open, {"n": 0}

    def flaky(path, flags, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("borrado pendiente")                                   # lo que da Windows con O_EXCL
        return real(path, flags, *a, **k)
    monkeypatch.setattr(lm.os, "open", flaky)
    with mgr.acquire("doc-x", timeout_s=2):
        assert calls["n"] >= 2                                                           # reintentó en lugar de propagar
    assert not list((tmp_path / "locks").glob("*.lock"))


def test_data_layout_ignores_the_intermittent_extended_path_prefix(tmp_path):
    from mod_01_ingestion.src.unified.config import DataLayout as DL
    assert str(DL._plain(Path(r"\\?\C:\a\b"))) == r"C:\a\b"
    layout = DL(tmp_path / "root").ensure()
    inside = layout.cas / "ab" / ("ab" * 32)
    assert layout.assert_inside(inside)
    with pytest.raises(Exception):
        layout.assert_inside(tmp_path / "fuera" / "x")


def test_threads_can_open_the_same_duckdb_file_without_handle_conflicts(tmp_path):
    runner, layout, _ = mk(tmp_path, ZIP_A, [cand()])
    errs = []

    def hammer():
        try:
            for _ in range(15):
                runner.catalog.count()
                runner.catalog.list_records()
                runner.versions.list_versions("ID|x")
                runner.catalog.get("nada")
        except BaseException as ex:                                                       # pragma: no cover
            errs.append(repr(ex))
    ts = [threading.Thread(target=hammer) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == []
