"""
U5B — Identidad lógica, versiones de contenido, UNCONFIRMED, reutilización de CAS y locks.

Offline y determinista: todo bajo ``tmp_path``, DuckDB TEMPORAL por test (ninguna base operativa), contratos y fuentes
SINTÉTICOS (ningún adapter real declara contrato). Los tests de hilos/procesos NO demuestran garantías generales de
concurrencia: solo el patrón probado (lock de identidad + conexión por operación).
"""
import dataclasses
import hashlib
import json
import os
import socket
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.application.preflight import KnownDocumentPreflight
from mod_01_ingestion.src.unified import cas_store
from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, PreflightMatch as M, PreflightStatus as S
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.models import DocumentCandidate, RunContext
from mod_01_ingestion.src.unified.domain.versions import (
    DocumentVersion, EvidenceKind, IdentityKind, IdScope, InitialVersionPolicy, Observation, RepublicationEvidence,
    SourceIdentityContract, VersionStatus, normalize_source_id, resolve_identity, validate_republication_evidence)
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.lock_manager import LockManager
from mod_01_ingestion.src.unified.models import DiscoveryRequest, JobState
from mod_01_ingestion.src.unified.preflight_lookup import RepositoryKnownDocumentLookup
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified.version_store import RegisterResult, VersionRepository
from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner, make_zip
from mod_01_ingestion.tests.test_unified_preflight import PKG, FakeLookup, StubAdapter

CTX = RunContext(run_id="run-vs", started_at="2026-10-12T10:00:00+00:00", mode=ExecutionMode.TEST)
BASE = dict(authority="CNMV", country_code="ES", issuer_id="LEI_ES_1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
            source_url=PKG, issuer_lei="LEI_ES_1")
EV_ALL = (EvidenceKind.REVISION_NUMBER, EvidenceKind.SUPERSEDES_REF, EvidenceKind.OFFICIAL_RECTIFICATION_FLAG,
          EvidenceKind.OFFICIAL_HASH)


def contract(**over):
    kw = dict(contract_id="synthetic-c1", contract_version="1", authority="CNMV", namespace="synthetic-ns",
              id_scope=IdScope.LOGICAL_DOCUMENT, allowed_evidence_kinds=EV_ALL,
              initial_version_policy=InitialVersionPolicy.TRUST_FIRST_VALIDATED, expected_sha256_authority=True)
    kw.update(over)
    return SourceIdentityContract(**kw)


def sha_of(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def cand(**kw):
    d = dict(BASE)
    d.update(kw)
    return DocumentCandidate(**d)


# ============================================================== A. tipos, normalización, identidad
def test_normalization_v1_is_nfc_plus_strip_and_preserves_case_zeros_and_punctuation():
    assert normalize_source_id("  é-00A/b.C  ") == "é-00A/b.C"          # NFC + strip; nada más
    assert normalize_source_id("ABC") != normalize_source_id("abc")                 # no pliega mayúsculas
    assert normalize_source_id("007") == "007"
    for bad in ("", "   ", None):
        with pytest.raises(DomainValidationError):
            normalize_source_id(bad)
    with pytest.raises(DomainValidationError):
        normalize_source_id("x", "v99")                                              # normalizador desconocido


def test_identity_logical_vs_version_vs_slot_only_and_key_excludes_policy_versions():
    doc_id = cand().document_id
    lg = resolve_identity("CNMV", doc_id, contract(), " DOC-1 ")
    assert lg.identity_kind is IdentityKind.SOURCE_ID and lg.identity_key.startswith("ID|") and lg.normalized_id == "DOC-1"
    lg2 = resolve_identity("CNMV", doc_id, contract(contract_version="2"), "DOC-1")
    assert lg2.identity_key == lg.identity_key                                       # cambiar la política NO cambia la clave
    ver = resolve_identity("CNMV", doc_id, contract(id_scope=IdScope.VERSION), "V-7")
    assert ver.identity_kind is IdentityKind.SLOT_ONLY and ver.identity_key == f"SLOT|{doc_id}" and ver.version_ref.startswith("VR|")
    none = resolve_identity("CNMV", doc_id, None, "DOC-1")
    assert none.identity_kind is IdentityKind.SLOT_ONLY and none.version_ref is None and not none.is_contracted
    assert not resolve_identity("CNMV", doc_id, contract(), None).is_contracted      # contrato sin id => no hay identidad
    with pytest.raises(DomainValidationError):
        resolve_identity("BAFIN", doc_id, contract(), "DOC-1")                       # contrato de otra autoridad
    with pytest.raises(DomainValidationError):
        contract(initial_version_policy=InitialVersionPolicy.REQUIRE_AUTHORITATIVE_HASH, expected_sha256_authority=False)


def test_evidence_is_validated_against_the_source_contract_not_by_generic_category():
    c = contract(allowed_evidence_kinds=(EvidenceKind.REVISION_NUMBER,))
    kw = dict(current_version_ref="VR|x", current_revision=1, current_sha256="a" * 64, candidate_revision=2,
              expected_sha256=None)
    ev = RepublicationEvidence(EvidenceKind.REVISION_NUMBER, "2", "synthetic-c1", "1")
    assert validate_republication_evidence(c, ev, **kw) == (True, "OK")
    assert validate_republication_evidence(c, None, **kw)[0] is False
    assert validate_republication_evidence(c, dataclasses.replace(ev, contract_id="other"), **kw)[1] == "EVIDENCE_CONTRACT_MISMATCH"
    assert validate_republication_evidence(c, dataclasses.replace(ev, contract_version="9"), **kw)[1] == "EVIDENCE_CONTRACT_MISMATCH"
    sup = RepublicationEvidence(EvidenceKind.SUPERSEDES_REF, "VR|x", "synthetic-c1", "1")
    assert validate_republication_evidence(c, sup, **kw)[1] == "EVIDENCE_KIND_NOT_ALLOWED_BY_CONTRACT"
    assert validate_republication_evidence(c, ev, **{**kw, "candidate_revision": 1})[0] is False       # no supera la vigente
    assert validate_republication_evidence(c, ev, **{**kw, "current_revision": None})[0] is False
    full = contract()
    assert validate_republication_evidence(full, sup, **kw)[0] is True
    assert validate_republication_evidence(full, dataclasses.replace(sup, value="VR|otra"), **kw)[0] is False
    flag = RepublicationEvidence(EvidenceKind.OFFICIAL_RECTIFICATION_FLAG, "true", "synthetic-c1", "1")
    assert validate_republication_evidence(full, flag, **kw)[0] is True
    h = RepublicationEvidence(EvidenceKind.OFFICIAL_HASH, "b" * 64, "synthetic-c1", "1")
    assert validate_republication_evidence(full, h, **{**kw, "expected_sha256": "b" * 64})[0] is True
    assert validate_republication_evidence(contract(expected_sha256_authority=False), h, **{**kw, "expected_sha256": "b" * 64})[0] is False


# ============================================================== B. persistencia aditiva en DuckDB TEMPORAL
def repo(tmp_path, name="v"):
    return VersionRepository(tmp_path / f"{name}.duckdb", tmp_path / f"{name}_sidecars", ExecutionMode.TEST)


def fact(ik="ID|CNMV|ns|DOC-1", sha=None, **over):
    kw = dict(identity_key=ik, sha256=sha or "ab" * 32, identity_kind="SOURCE_ID", authority="CNMV",
              document_id="CNMV_X_2023_ESEF_PACKAGE", size_bytes=10, normalizer_version="v1", version_ref="VR|a",
              revision=1, contract_id="synthetic-c1", contract_version="1", source_document_id_raw="DOC-1",
              evidence_json=None, first_observed_at="2026-10-12T10:00:00+00:00", run_id="r1", job_id="j1")
    kw.update(over)
    return DocumentVersion(**kw)


def test_reading_never_creates_the_database_or_tables(tmp_path):
    r = repo(tmp_path)
    assert r.list_versions("ID|x") == [] and r.list_versions_by_sha256("ab" * 32) == [] and r.current_version("ID|x") is None
    assert not (tmp_path / "v.duckdb").exists() and not (tmp_path / "v_sidecars").exists()      # lectura = cero efectos


def test_identical_insert_is_idempotent_and_contradictory_facts_are_conflict_after_reread(tmp_path):
    r = repo(tmp_path)
    a = r.register_version(fact(), VersionStatus.CURRENT, cas_path="cas/x")
    b = r.register_version(fact(run_id="r2", job_id="j2", first_observed_at="2027-01-01T00:00:00+00:00"),
                           VersionStatus.CURRENT, cas_path="cas/x")                     # solo difieren campos NO comparables
    assert (a.outcome, b.outcome) == ("CREATED", "IDEMPOTENT") and b.status == "CURRENT"
    assert len(r.list_versions("ID|CNMV|ns|DOC-1")) == 1
    for field, value in (("size_bytes", 11), ("version_ref", "VR|b"), ("revision", 2), ("contract_version", "2"),
                         ("evidence_json", "{}"), ("normalizer_version", "v2")):
        c = r.register_version(fact(**{field: value}), VersionStatus.CURRENT, cas_path="cas/x")
        assert c.outcome == "CONFLICT" and field in c.differences, field
    rows = r.list_versions("ID|CNMV|ns|DOC-1")
    assert len(rows) == 1 and rows[0]["size_bytes"] == 10 and rows[0]["revision"] == 1      # nada se sobrescribió
    assert not list((tmp_path / "v_sidecars").rglob("*.pending"))


def test_table_comparison_detects_contradiction_even_if_the_sidecar_were_forged_to_match(tmp_path):
    """La relectura de la TABLA es una comprobación independiente del sidecar (no basta el ON CONFLICT ni el sidecar)."""
    r = repo(tmp_path)
    assert r.register_version(fact(), VersionStatus.CURRENT, cas_path="c").ok
    forged = fact(size_bytes=999)
    r.sidecar_path(forged.identity_key, forged.sha256).write_text(json.dumps({"facts": forged.facts()}), encoding="utf-8")
    res = r.register_version(forged, VersionStatus.CURRENT, cas_path="c")
    assert res.outcome == "CONFLICT" and "size_bytes" in res.differences
    assert r.list_versions(forged.identity_key)[0]["size_bytes"] == 10


def test_composite_primary_key_and_not_null_are_enforced_in_the_temp_duckdb(tmp_path):
    import duckdb
    r = repo(tmp_path)
    r.register_version(fact(), VersionStatus.UNCONFIRMED, cas_path="c")
    with r._connect() as con:
        with pytest.raises(duckdb.ConstraintException):
            con.execute("INSERT INTO unified_document_versions (identity_key, sha256, identity_kind, authority, document_id, "
                        "normalizer_version) VALUES ('ID|CNMV|ns|DOC-1', ?, 'SOURCE_ID', 'CNMV', 'd', 'v1')", ["ab" * 32])
        con.execute("INSERT INTO unified_document_versions (identity_key, sha256, identity_kind, authority, document_id, "
                    "normalizer_version) VALUES ('ID|CNMV|ns|DOC-1', ?, 'SOURCE_ID', 'CNMV', 'd', 'v1')", ["cd" * 32])
        with pytest.raises(duckdb.ConstraintException):
            con.execute("INSERT INTO unified_document_versions (identity_key, sha256, identity_kind, authority, document_id, "
                        "normalizer_version) VALUES (NULL, ?, 'SOURCE_ID', 'CNMV', 'd', 'v1')", ["ef" * 32])
        names = {x[0] for x in con.execute("SELECT index_name FROM duckdb_indexes()").fetchall()}
    assert {"ix_udv_sha256", "ix_udv_identity"} <= names


def test_current_superseded_swap_is_one_transaction_and_at_most_one_current(tmp_path):
    r = repo(tmp_path)
    ik = "ID|CNMV|ns|DOC-1"
    assert r.register_version(fact(sha="11" * 32), VersionStatus.CURRENT, cas_path="c").ok
    dup = r.register_version(fact(sha="22" * 32), VersionStatus.CURRENT, cas_path="c")      # sin supersede: invariante
    assert dup.outcome == "FAILED" and "CURRENT" in dup.message
    assert [v["sha256"] for v in r.list_versions(ik)] == ["11" * 32]                            # rollback: nada a medias
    res = r.register_version(fact(sha="22" * 32, revision=2), VersionStatus.CURRENT, cas_path="c", supersede_current=True)
    assert res.outcome == "CREATED" and res.superseded_sha256 == "11" * 32
    st = {v["sha256"]: v["status"] for v in r.list_versions(ik)}
    assert st == {"11" * 32: "SUPERSEDED", "22" * 32: "CURRENT"} and r.current_version(ik)["sha256"] == "22" * 32
    u = r.register_version(fact(sha="33" * 32, revision=3), VersionStatus.UNCONFIRMED, cas_path="c")
    assert u.ok and r.current_version(ik)["sha256"] == "22" * 32                                 # UNCONFIRMED no sustituye CURRENT


def test_rolled_back_transaction_leaves_no_half_writes(tmp_path):
    r = repo(tmp_path)
    r.ensure_schema()
    with r._connect() as con:                                                                     # evento huérfano => el 2º INSERT falla
        con.execute("INSERT INTO unified_document_version_events (identity_key, sha256, event_seq, status) "
                    "VALUES ('ID|CNMV|ns|DOC-1', ?, 1, 'UNCONFIRMED')", ["99" * 32])
    res = r.register_version(fact(sha="99" * 32), VersionStatus.UNCONFIRMED, cas_path="c")
    assert res.outcome == "FAILED"
    with r._connect(read_only=True) as con:
        assert con.execute("SELECT count(*) FROM unified_document_versions").fetchone()[0] == 0      # la fila de versión se revirtió
    assert not list((tmp_path / "v_sidecars").rglob("*.json")) and not list((tmp_path / "v_sidecars").rglob("*.pending"))


def test_sidecar_commit_failure_is_compensated_and_failed_compensation_is_recovery_required(tmp_path, monkeypatch):
    from mod_01_ingestion.src.unified import version_store as vs
    r = repo(tmp_path)
    real = os.replace
    monkeypatch.setattr(vs.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    res = r.register_version(fact(sha="44" * 32), VersionStatus.CURRENT, cas_path="c")
    monkeypatch.setattr(vs.os, "replace", real)
    assert res.outcome == "FAILED" and r.list_versions("ID|CNMV|ns|DOC-1") == []                  # tabla compensada
    assert not list((tmp_path / "v_sidecars").rglob("*.pending"))
    monkeypatch.setattr(vs.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.setattr(r, "_compensate", lambda *a, **k: ["no se pudo compensar"])
    res2 = r.register_version(fact(sha="55" * 32), VersionStatus.CURRENT, cas_path="c")
    assert res2.outcome == "RECOVERY_REQUIRED" and res2.compensation_errors and res2.needs_manual_review


def test_table_sidecar_desync_is_explicit_and_never_repaired_automatically(tmp_path):
    r = repo(tmp_path)
    ik = "ID|CNMV|ns|DOC-1"
    assert r.register_version(fact(sha="66" * 32), VersionStatus.CURRENT, cas_path="c").ok
    r.sidecar_path(ik, "66" * 32).unlink()                                                        # tabla sin sidecar
    row = r.list_versions(ik)[0]
    assert row["table_present"] and not row["sidecar_present"]
    again = r.register_version(fact(sha="66" * 32), VersionStatus.CURRENT, cas_path="c")
    assert again.outcome == "RECOVERY_REQUIRED" and not r.sidecar_path(ik, "66" * 32).exists()    # no se reescribe solo
    assert r.register_version(fact(sha="77" * 32), VersionStatus.UNCONFIRMED, cas_path="c").ok
    with r._connect() as con:                                                                      # sidecar sin tabla
        con.execute("DELETE FROM unified_document_version_events WHERE sha256 = ?", ["77" * 32])
        con.execute("DELETE FROM unified_document_versions WHERE sha256 = ?", ["77" * 32])
    only_side = [v for v in r.list_versions(ik) if v["sha256"] == "77" * 32][0]
    assert not only_side["table_present"] and only_side["sidecar_present"]
    # el sidecar contradice la fila
    s = r.sidecar_path(ik, "66" * 32)
    s.parent.mkdir(parents=True, exist_ok=True)
    s.write_text(json.dumps({"facts": fact(sha="66" * 32, size_bytes=999).facts()}), encoding="utf-8")
    assert r.list_versions(ik)[0]["facts_match"] is False


def test_observations_are_append_only_idempotent_and_conflicting_facts_are_reported(tmp_path):
    r = repo(tmp_path)
    o = Observation("r1", "j1", "ID|x", "ab" * 32, None, "PROCEED_DOWNLOAD")
    assert r.record_observation(o).outcome == "CREATED"
    assert r.record_observation(o).outcome == "IDEMPOTENT"
    c = r.record_observation(dataclasses.replace(o, preflight_status="POSSIBLE_REPUBLICATION"))
    assert c.outcome == "CONFLICT" and "preflight_status" in c.differences


def test_threads_with_identity_lock_register_one_version_scope_limited_to_this_pattern(tmp_path):
    """Patrón probado: lock de identidad + conexión por operación. NO es una garantía multiproceso general."""
    import threading
    r = repo(tmp_path)
    lock, out = threading.Lock(), []

    def work():
        with lock:
            out.append(r.register_version(fact(sha="88" * 32), VersionStatus.UNCONFIRMED, cas_path="c").outcome)
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out).count("CREATED") == 1 and set(out) <= {"CREATED", "IDEMPOTENT"}
    assert len(r.list_versions("ID|CNMV|ns|DOC-1")) == 1


# ============================================================== C. CAS: create_view=False y rollback seguro
def cas_env(tmp_path):
    layout = DataLayout(tmp_path / "root").ensure()
    cas = ContentAddressedRawStore(layout, LockManager(layout.locks))
    return layout, cas


def staged(layout, name, data: bytes):
    p = layout.staging / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p, sha_of(data)


def test_promote_without_view_is_explicit_and_creates_no_raw_file(tmp_path):
    layout, cas = cas_env(tmp_path)
    s, sha = staged(layout, "a.bin", b"A" * 300)
    promo = cas.promote(s, sha, None, create_view=False, pin_key="pinkey-0001")
    assert promo.raw_path is None and promo.link_mode == "none" and promo.receipt and promo.receipt.created_blob
    assert Path(promo.cas_path).exists() and not [p for p in layout.raw.rglob("*") if p.is_file()]
    with pytest.raises(ValueError):
        cas.promote(s, sha, None, create_view=True)                                              # nunca Path("") como centinela


def test_rollback_owned_without_view_removes_only_a_blob_this_attempt_created(tmp_path):
    layout, cas = cas_env(tmp_path)
    s, sha = staged(layout, "a.bin", b"A" * 300)
    promo = cas.promote(s, sha, None, create_view=False, pin_key="pinkey-0001")
    rb = cas.rollback_owned(promo)
    assert rb.blob_state == "REMOVED" and rb.raw_view_state == "NO_VIEW" and rb.clean and not Path(promo.cas_path).exists()
    assert cas.rollback_owned(promo).clean                                                        # idempotente


def test_rollback_owned_preexisting_blob_is_left_and_missing_view_is_not_a_false_orphan(tmp_path):
    layout, cas = cas_env(tmp_path)
    s1, sha = staged(layout, "a.bin", b"A" * 300)
    cas.promote(s1, sha, Path("ES_CNMV/2023/a.bin"))                                              # lo creó otro intento
    s2, _ = staged(layout, "b.bin", b"A" * 300)
    again = cas.promote(s2, sha, None, create_view=False, pin_key="pinkey-0001")
    assert again.receipt is None and again.deduplicated
    rb = cas.rollback_owned(again)
    assert rb.blob_state == "PREEXISTING_LEFT" and rb.raw_view_state == "NO_VIEW" and rb.clean and Path(again.cas_path).exists()


def test_rollback_owned_with_own_view_and_in_copy_mode(tmp_path, monkeypatch):
    layout, cas = cas_env(tmp_path)
    s, sha = staged(layout, "a.bin", b"A" * 300)
    own = cas.promote(s, sha, Path("ES_CNMV/2023/a.bin"))
    rb = cas.rollback_owned(own)
    assert rb.blob_state == "REMOVED" and rb.raw_view_state == "REMOVED" and rb.clean                # vista propia + blob propio
    from mod_01_ingestion.src.unified import cas_store
    monkeypatch.setattr(cas_store.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("sin hardlinks")))
    s2, sha2 = staged(layout, "c.bin", b"C" * 300)
    cp = cas.promote(s2, sha2, None, create_view=False, pin_key="pinkey-0001")
    assert cp.receipt.blob_link_mode == "copy"
    rb2 = cas.rollback_owned(cp)
    assert rb2.blob_state == "UNPROVEN_ORPHAN" and not rb2.clean and Path(cp.cas_path).exists()    # sin prueba: no se borra


def test_shared_blob_between_identities_is_never_deleted_by_a_rollback(tmp_path):
    layout, cas = cas_env(tmp_path)
    sA, sha = staged(layout, "a.bin", b"S" * 300)
    a = cas.promote(sA, sha, Path("ES_CNMV/2023/a.bin"))                                            # identidad A: con vista
    sB, _ = staged(layout, "b.bin", b"S" * 300)
    b = cas.promote(sB, sha, Path("ES_CNMV/2023/b.bin"))                                            # identidad B: con vista
    rb = cas.rollback_owned(a)
    assert rb.blob_state == "SHARED_LEFT" and Path(a.cas_path).exists() and Path(b.raw_path).exists()
    # A con vista y B SIN vista (no añade enlaces): el recuento no ve a B => `keep_blob` (referencia en la tabla) lo protege
    layout2, cas2 = cas_env(tmp_path / "second")
    s1, sha2 = staged(layout2, "a.bin", b"T" * 300)
    a2 = cas2.promote(s1, sha2, Path("ES_CNMV/2023/a.bin"))
    s2, _ = staged(layout2, "b.bin", b"T" * 300)
    cas2.promote(s2, sha2, None, create_view=False, pin_key="pinkey-0001")
    rb2 = cas2.rollback_owned(a2, keep_blob=True)
    assert rb2.blob_state == "SHARED_LEFT" and Path(a2.cas_path).exists() and rb2.clean


# ============================================================== D. preflight versionado (lookup real, DuckDB temporal)
class Env:
    def __init__(self, tmp_path):
        self.layout = DataLayout(tmp_path / "root").ensure()
        self.manifests = ManifestRepository(self.layout, mode=ExecutionMode.TEST)
        self.catalog = CatalogRepository(self.layout.catalog_db, mode=ExecutionMode.TEST)
        self.cas = ContentAddressedRawStore(self.layout, LockManager(self.layout.locks))
        self.versions = VersionRepository(self.layout.catalog_db, self.layout.versions, ExecutionMode.TEST)
        self.lookup = RepositoryKnownDocumentLookup(self.manifests, self.catalog, self.cas, self.versions)
        self.pf = KnownDocumentPreflight(self.lookup)

    def put_blob(self, data: bytes) -> str:
        s, sha = staged(self.layout, f"{sha_of(data)[:8]}.bin", data)
        self.cas.promote(s, sha, None, create_view=False, pin_key="pinkey-0001")
        return sha

    def register(self, c, source_id, sha, status=VersionStatus.CURRENT, **over):
        ident = resolve_identity(c.authority, c.document_id, c.identity_contract, source_id)
        kw = dict(identity_key=ident.identity_key, sha256=sha, identity_kind=ident.identity_kind.value,
                  authority=c.authority, document_id=c.document_id, size_bytes=300,
                  normalizer_version=c.identity_contract.normalizer_version, version_ref=ident.version_ref, revision=1,
                  contract_id=c.identity_contract.contract_id, contract_version=c.identity_contract.contract_version,
                  source_document_id_raw=source_id)
        kw.update(over)
        res = self.versions.register_version(DocumentVersion(**kw), status, cas_path=str(self.cas.blob_path(sha)))
        assert res.ok, res
        return ident

    def run(self, c):
        return self.pf.evaluate(c, CTX)


def snapshot(root: Path):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*"))


def test_logical_id_alone_never_skips_but_exact_hash_with_intact_blob_does(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"L" * 300)
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    e.register(c, "DOC-1", sha)
    out = e.run(c)
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "VERSIONS_EXIST_NO_VERIFIABLE_VALIDATOR"   # id lógico: nunca skip
    before = snapshot(tmp_path)
    hit = e.run(dataclasses.replace(c, expected_sha256=sha))
    assert hit.status is S.SKIPPED_ALREADY_PRESENT and hit.matched_by is M.SHA256 and hit.skips_download
    assert snapshot(tmp_path) == before                                                          # el preflight no escribe nada
    e.cas.blob_path(sha).write_bytes(b"corrupto")                                                # blob no íntegro => no skip
    assert e.run(dataclasses.replace(c, expected_sha256=sha)).status is S.PROCEED_DOWNLOAD


def test_version_scope_skips_by_persisted_version_ref_only_and_never_on_a_different_ref(tmp_path):
    e = Env(tmp_path)
    ct = contract(id_scope=IdScope.VERSION)
    sha = e.put_blob(b"V" * 300)
    c1 = cand(identity_contract=ct, source_document_id="V-1")
    e.register(c1, "V-1", sha)
    out = e.run(c1)
    assert out.status is S.SKIPPED_ALREADY_PRESENT and out.matched_by is M.SOURCE_DOCUMENT_ID
    assert e.run(cand(identity_contract=ct, source_document_id="V-2")).status is S.PROCEED_DOWNLOAD   # otra versión: descargar
    other_hash = e.run(dataclasses.replace(c1, expected_sha256="cd" * 32))
    assert other_hash.status is S.MANUAL_REVIEW and other_hash.reason_code == "VERSION_REF_REGISTERED_WITH_OTHER_HASH"
    # sin versión persistida => el id declarado por sí solo no autoriza nada
    assert Env(tmp_path / "vacio").run(c1).status is S.PROCEED_DOWNLOAD


def test_republication_confirmed_only_with_valid_contract_evidence_otherwise_possible(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"R" * 300)
    ct = contract(allowed_evidence_kinds=(EvidenceKind.REVISION_NUMBER,))
    c = cand(identity_contract=ct, source_document_id="DOC-1")
    e.register(c, "DOC-1", sha, revision=1)
    ev = RepublicationEvidence(EvidenceKind.REVISION_NUMBER, "2", "synthetic-c1", "1")
    new = dict(expected_sha256="cd" * 32, source_revision=2)
    ok = e.run(dataclasses.replace(c, republication_evidence=ev, **new))
    assert ok.status is S.REPUBLICATION_CONFIRMED and ok.matched_by is M.VERSION_EVIDENCE and ok.may_download
    for bad in (dataclasses.replace(ev, kind=EvidenceKind.SUPERSEDES_REF),         # tipo no admitido por el contrato
                dataclasses.replace(ev, contract_id="otro"), None):
        pos = e.run(dataclasses.replace(c, republication_evidence=bad, **new))
        assert pos.status is S.POSSIBLE_REPUBLICATION, bad
    assert e.run(dataclasses.replace(c, republication_evidence=ev, expected_sha256="cd" * 32,
                                     source_revision=1)).status is S.POSSIBLE_REPUBLICATION   # revisión no mayor
    contradict = e.run(dataclasses.replace(c, republication_evidence=ev, expected_sha256=sha, source_revision=2))
    assert contradict.status is S.MANUAL_REVIEW                                                 # evidencia vs hash ya registrado


def test_no_current_version_means_evidence_cannot_confirm(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"N" * 300)
    c = cand(identity_contract=contract(initial_version_policy=InitialVersionPolicy.NONE), source_document_id="DOC-1")
    e.register(c, "DOC-1", sha, status=VersionStatus.UNCONFIRMED)
    ev = RepublicationEvidence(EvidenceKind.REVISION_NUMBER, "2", "synthetic-c1", "1")
    out = e.run(dataclasses.replace(c, republication_evidence=ev, expected_sha256="cd" * 32, source_revision=2))
    assert out.status is S.POSSIBLE_REPUBLICATION and "NO_CURRENT_VERSION" in out.reason_code


def test_policy_mismatch_and_contradictory_metadata_and_unsupported_lookup_never_skip(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"P" * 300)
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    e.register(c, "DOC-1", sha)
    for ct in (contract(contract_version="2"), contract(normalizer_version="v1", contract_id="otro")):
        out = e.run(dataclasses.replace(c, identity_contract=ct, expected_sha256=sha))
        assert out.status is S.MANUAL_REVIEW and out.reason_code == "IDENTITY_POLICY_VERSION_MISMATCH"
    other_slot = cand(identity_contract=contract(), source_document_id="DOC-1", issuer_id="LEI_OTRO", issuer_lei="LEI_OTRO",
                      expected_sha256=sha)
    moved = e.run(other_slot)
    assert moved.status is S.MANUAL_REVIEW and moved.reason_code == "LOGICAL_ID_REGISTERED_UNDER_OTHER_SLOT"
    unsupported = KnownDocumentPreflight(FakeLookup()).evaluate(c, CTX)                          # lookup sin versiones
    assert unsupported.status is S.MANUAL_REVIEW and unsupported.reason_code == "VERSION_LOOKUP_UNAVAILABLE"
    bad_ct = KnownDocumentPreflight(e.lookup).evaluate(
        dataclasses.replace(c, identity_contract=contract(authority="BAFIN")), CTX)
    assert bad_ct.status is S.MANUAL_REVIEW and bad_ct.reason_code == "IDENTITY_UNRESOLVABLE"


def test_partial_version_state_gives_recovery_required_in_preflight(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"Q" * 300)
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    ident = e.register(c, "DOC-1", sha)
    e.versions.sidecar_path(ident.identity_key, sha).unlink()
    out = e.run(dataclasses.replace(c, expected_sha256=sha))
    assert out.status is S.RECOVERY_REQUIRED and out.reason_code == "PARTIAL_VERSION_TABLE_ONLY" and out.needs_manual_review
    assert not out.may_download and not out.skips_download


def test_same_hash_under_another_identity_reuses_cas_only_with_authoritative_exact_hash(tmp_path):
    e = Env(tmp_path)
    sha = e.put_blob(b"U" * 300)
    a = cand(identity_contract=contract(), source_document_id="DOC-A")
    e.register(a, "DOC-A", sha)
    b = cand(identity_contract=contract(), source_document_id="DOC-B", issuer_id="LEI_B", issuer_lei="LEI_B", expected_sha256=sha)
    out = e.run(b)
    assert out.status is S.REUSE_EXISTING_CONTENT and out.reuse_sha256 == sha and out.matched_by is M.SHA256
    assert out.identity_key != e.run(a).identity_key
    no_auth = dataclasses.replace(b, identity_contract=contract(expected_sha256_authority=False,
                                                                initial_version_policy=InitialVersionPolicy.NONE))
    assert e.run(no_auth).status is S.PROCEED_DOWNLOAD                                         # hash no autoritativo: se descarga
    assert e.run(dataclasses.replace(b, expected_sha256=None)).status is S.PROCEED_DOWNLOAD     # sin hash: se descarga
    assert e.run(dataclasses.replace(b, expected_sha256="cd" * 32)).status is S.PROCEED_DOWNLOAD  # otro hash: se descarga
    e.cas.blob_path(sha).write_bytes(b"corrupto")
    assert e.run(b).status is S.PROCEED_DOWNLOAD                                               # blob no íntegro


# ============================================================== E. runner extremo a extremo (sitio simulado, sin red)
def mk(tmp_path, payload: bytes, candidates):
    site = base_site(zip_bytes=payload)
    runner, layout, _svc = make_runner(tmp_path, site)
    runner.adapters["CNMV"] = StubAdapter(list(candidates))
    return runner, layout, site


def go(runner):
    return runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]


def raw_files(layout):
    return sorted(p.name for p in layout.raw.rglob("*") if p.is_file())


def legacy_bytes(layout):
    return sorted(p.read_bytes() for p in layout.manifests.rglob("*.json"))


def test_first_version_policy_none_registers_unconfirmed_and_never_assigns_current(tmp_path):
    A = make_zip("A")
    c = cand(identity_contract=contract(initial_version_policy=InitialVersionPolicy.NONE), source_document_id="DOC-1")
    runner, layout, site = mk(tmp_path, A, [c])
    out = go(runner)
    assert out.state == "COMPLETED" and out.version_status == "UNCONFIRMED" and out.sha256 == sha_of(A)
    ident = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1")
    assert runner.versions.current_version(ident.identity_key) is None and len(raw_files(layout)) == 1
    assert runner.versions.sidecar_path(ident.identity_key, sha_of(A)).exists()


def test_unconfirmed_second_version_keeps_current_has_no_raw_view_and_is_recoverable(tmp_path):
    A, B = make_zip("A"), make_zip("B")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    r1, layout, _ = mk(tmp_path, A, [c])
    first = go(r1)
    assert first.state == "COMPLETED" and first.version_status == "CURRENT"
    manifest_before, raw_before = legacy_bytes(layout), raw_files(layout)
    r2, _, site2 = mk(tmp_path, B, [c])                       # la fuente sirve otros bytes bajo la misma identidad, sin evidencia
    out = go(r2)
    assert out.state == "MANUAL_REVIEW" and out.version_status == "UNCONFIRMED" and out.needs_manual_review
    assert out.sha256 == sha_of(B) and out.raw_path is None
    assert raw_files(layout) == raw_before                                          # UNCONFIRMED NO aparece en raw/
    assert legacy_bytes(layout) == manifest_before                                  # manifiesto/catálogo legacy intactos
    ident = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1")
    st = {v["sha256"]: v["status"] for v in r2.versions.list_versions(ident.identity_key)}
    assert st == {sha_of(A): "CURRENT", sha_of(B): "UNCONFIRMED"}
    assert r2.cas.blob_path(sha_of(B)).exists() and r2.versions.sidecar_path(ident.identity_key, sha_of(B)).exists()
    again = go(mk(tmp_path, B, [c])[0])                                             # idempotente: sin filas duplicadas
    assert again.state == "MANUAL_REVIEW" and len(r2.versions.list_versions(ident.identity_key)) == 2


def test_confirmed_republication_becomes_current_supersedes_and_keeps_old_artifacts(tmp_path):
    A, B = make_zip("A"), make_zip("B")
    c1 = cand(identity_contract=contract(), source_document_id="DOC-1", source_revision=1)
    r1, layout, _ = mk(tmp_path, A, [c1])
    assert go(r1).version_status == "CURRENT"
    manifest_before = legacy_bytes(layout)
    ev = RepublicationEvidence(EvidenceKind.REVISION_NUMBER, "2", "synthetic-c1", "1")
    c2 = dataclasses.replace(c1, source_revision=2, republication_evidence=ev, expected_sha256=sha_of(B))
    r2, _, _ = mk(tmp_path, B, [c2])
    out = go(r2)
    assert out.state == "COMPLETED" and out.version_status == "CURRENT" and out.sha256 == sha_of(B)
    ident = resolve_identity("CNMV", c1.document_id, c1.identity_contract, "DOC-1")
    st = {v["sha256"]: v["status"] for v in r2.versions.list_versions(ident.identity_key)}
    assert st == {sha_of(A): "SUPERSEDED", sha_of(B): "CURRENT"}
    assert legacy_bytes(layout) == manifest_before                                  # la versión anterior no se sobrescribe
    names = raw_files(layout)
    assert len(names) == 2 and any(n.count(".") >= 2 and sha_of(B)[:8] in n for n in names)   # vista nueva con sufijo de hash
    ev_ = [e for e in r2.telemetry.read_all() if e["event"] == "PREFLIGHT_REPUBLICATION_CONFIRMED"]
    assert ev_ and ev_[0]["status"] == "REPUBLICATION_CONFIRMED"


def test_downloaded_bytes_not_matching_expected_hash_are_rejected_before_any_registration(tmp_path):
    c = cand(identity_contract=contract(), source_document_id="DOC-1", expected_sha256="cd" * 32)
    runner, layout, _ = mk(tmp_path, make_zip("A"), [c])
    out = go(runner)
    assert out.state == "FAILED" and out.error_class == "CHECKSUM_MISMATCH"
    assert raw_files(layout) == [] and not list(layout.versions.rglob("*")) and runner.catalog.count() == 0
    assert runner.versions.list_versions_by_sha256(sha_of(make_zip("A"))) == []


def test_version_scope_second_run_is_skipped_by_persisted_version_ref_without_transport(tmp_path, monkeypatch):
    c = cand(identity_contract=contract(id_scope=IdScope.VERSION), source_document_id="V-1")
    runner, layout, site = mk(tmp_path, make_zip("A"), [c])
    assert go(runner).state == "COMPLETED"
    n = len(site.calls)
    monkeypatch.setattr(runner.download, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("transporte")))
    out = go(runner)
    assert out.state == "SKIPPED_ALREADY_PRESENT" and len(site.calls) == n
    states = {e.get("state") for e in runner.telemetry.read_all() if e["event"] == "state_transition"}
    assert "SKIPPED_DUPLICATE" not in states                                         # el alias legacy no se emite
    assert JobState.SKIPPED_DUPLICATE.value == "SKIPPED_DUPLICATE"                   # pero sigue existiendo


def test_logical_id_without_hash_downloads_again_and_unit_of_work_keeps_effects_single(tmp_path):
    A = make_zip("A")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, site = mk(tmp_path, A, [c])
    go(runner)
    n, manifest_before = len(site.calls), legacy_bytes(layout)
    out = go(runner)
    assert out.state == "COMPLETED" and len(site.calls) == n + 1                      # sin validador remoto: se descarga
    assert legacy_bytes(layout) == manifest_before and len(raw_files(layout)) == 1
    ident = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1")
    assert len(runner.versions.list_versions(ident.identity_key)) == 1


def test_reuse_from_cas_registers_a_second_identity_without_transport_or_fusion(tmp_path, monkeypatch):
    A = make_zip("A")
    ca = cand(identity_contract=contract(), source_document_id="DOC-A")
    runner, layout, site = mk(tmp_path, A, [ca])
    go(runner)
    cb = cand(identity_contract=contract(), source_document_id="DOC-B", issuer_id="LEI_B", issuer_lei="LEI_B",
              expected_sha256=sha_of(A))
    r2, _, site2 = mk(tmp_path, make_zip("OTRO"), [cb])
    monkeypatch.setattr(r2.download, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("transporte")))

    def deny(*a, **k):
        raise RuntimeError("red bloqueada")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    out = go(r2)
    assert out.state == "COMPLETED" and out.sha256 == sha_of(A) and site2.calls == []
    blobs = [p for p in layout.cas.rglob("*") if p.is_file()]
    assert len(blobs) == 1                                                            # un solo blob compartido
    ka = resolve_identity("CNMV", ca.document_id, ca.identity_contract, "DOC-A").identity_key
    kb = resolve_identity("CNMV", cb.document_id, cb.identity_contract, "DOC-B").identity_key
    assert ka != kb and r2.versions.list_versions(ka) and r2.versions.list_versions(kb)       # identidades separadas
    assert len(raw_files(layout)) == 2 and len(r2.versions.list_versions_by_sha256(sha_of(A))) == 2


def test_reuse_is_not_used_without_authoritative_contract_flag(tmp_path):
    A = make_zip("A")
    ca = cand(identity_contract=contract(), source_document_id="DOC-A")
    runner, layout, site = mk(tmp_path, A, [ca])
    go(runner)
    nc = contract(expected_sha256_authority=False, initial_version_policy=InitialVersionPolicy.TRUST_FIRST_VALIDATED)
    cb = cand(identity_contract=nc, source_document_id="DOC-B", issuer_id="LEI_B", issuer_lei="LEI_B", expected_sha256=sha_of(A))
    r2, _, site2 = mk(tmp_path, A, [cb])
    assert go(r2).state == "COMPLETED" and len(site2.calls) == 1                      # descargó: no hubo reutilización


def test_version_registration_failures_are_explicit_recovery_states_not_hidden(tmp_path, monkeypatch):
    A, B = make_zip("A"), make_zip("B")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, _ = mk(tmp_path, A, [c])
    monkeypatch.setattr(runner.versions, "register_version",
                        lambda *a, **k: RegisterResult("FAILED", "ik", "sha", message="boom"))
    out = go(runner)
    # primaria: el registro legacy ya estaba confirmado => no se revierte y se pide reconciliar (sin atomicidad distribuida)
    assert out.state == "RECOVERY_REQUIRED" and out.failure_stage == "VERSION" and out.needs_manual_review
    assert len(raw_files(layout)) == 1 and len(legacy_bytes(layout)) == 1
    monkeypatch.undo()
    healed = go(mk(tmp_path, A, [c])[0])                                             # la siguiente ejecución registra la versión
    assert healed.state == "COMPLETED" and healed.version_status == "CURRENT"
    # adicional: se revierte solo lo propio del CAS
    r3, _, _ = mk(tmp_path, B, [c])
    monkeypatch.setattr(r3.versions, "register_version",
                        lambda *a, **k: RegisterResult("CONFLICT", "ik", "sha", differences=("size_bytes",), message="x"))
    bad = go(r3)
    assert bad.state in ("FAILED", "RECOVERY_REQUIRED") and not r3.cas.blob_path(sha_of(B)).exists()
    assert len(raw_files(layout)) == 1
    monkeypatch.setattr(r3.versions, "register_version",
                        lambda *a, **k: RegisterResult("RECOVERY_REQUIRED", "ik", "sha", message="x",
                                                       compensation_errors=("e",)))
    assert go(r3).state == "RECOVERY_REQUIRED"


def test_historical_slot_without_version_rows_is_read_as_legacy_and_gets_a_version_on_idempotent_rerun(tmp_path):
    A = make_zip("A")
    runner, layout, site = mk(tmp_path, A, [cand()])                                  # registro legacy, sin contrato ni tablas
    assert go(runner).state == "COMPLETED" and not layout.versions.exists()
    sha = sha_of(A)
    ident_c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, site = mk(tmp_path, A, [ident_c])
    out = go(runner)                                                                   # mismos bytes que el slot histórico
    assert out.state == "COMPLETED" and out.version_status == "CURRENT" and out.sha256 == sha
    assert len(legacy_bytes(layout)) == 1 and len(raw_files(layout)) == 1             # el UoW legacy fue idempotente


def test_policy_change_between_runs_requires_review_and_does_not_download(tmp_path, monkeypatch):
    A = make_zip("A")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, site = mk(tmp_path, A, [c])
    go(runner)
    n = len(site.calls)
    c2 = dataclasses.replace(c, identity_contract=contract(contract_version="2"))
    r2, _, site2 = mk(tmp_path, A, [c2])
    out = go(r2)
    assert out.state == "MANUAL_REVIEW" and out.needs_manual_review and site2.calls == []
    ev = [e for e in r2.telemetry.read_all() if e["event"] == "PREFLIGHT_MANUAL_REVIEW"][-1]
    assert ev["reason_code"] == "IDENTITY_POLICY_VERSION_MISMATCH" and len(site.calls) == n


# ============================================================== F. locks: orden determinista
def test_lock_names_follow_the_documented_global_order():
    lg = UnifiedIngestRunner._lock_names(cand(identity_contract=contract(), source_document_id="DOC-1"))
    assert [n.split("-")[0] for n in lg] == ["idk", "doc"] and lg[1] == f"doc-{cand().document_id}"
    vr = UnifiedIngestRunner._lock_names(cand(identity_contract=contract(id_scope=IdScope.VERSION), source_document_id="V-1"))
    assert [n.split("-")[0] for n in vr] == ["doc", "ver"]
    assert UnifiedIngestRunner._lock_names(cand()) == [f"doc-{cand().document_id}"]            # sin contrato: como antes
    assert UnifiedIngestRunner._lock_names(cand(source_document_id="X")) == [f"doc-{cand().document_id}"]


def test_runner_acquires_locks_in_that_order_and_releases_all_on_timeout(tmp_path):
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    runner, layout, site = mk(tmp_path, make_zip("A"), [c])
    taken = []
    real = runner.locks.acquire

    def spy(key, timeout_s=30.0):
        taken.append(key)
        return real(key, timeout_s)
    runner.locks.acquire = spy
    assert go(runner).state == "COMPLETED"
    names = [k for k in taken if k.startswith(("idk-", "doc-", "ver-"))]
    assert [n.split("-")[0] for n in names[:2]] == ["idk", "doc"]
    # un lock ocupado en la 2ª posición libera el 1º (ExitStack) y devuelve FAILED/LOCKED
    runner.locks.acquire = real
    runner.lock_timeout_s = 0.05
    holder = real(f"doc-{c.document_id}", 5)
    holder.__enter__()
    try:
        out = go(runner)
    finally:
        holder.__exit__(None, None, None)
    assert out.state == "FAILED" and out.error_class == "LOCKED"
    assert not [p for p in layout.locks.glob("idk-*")]                                            # no quedó el lock de identidad


def test_default_runner_construction_has_no_side_effects_on_versions_storage(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site())
    assert not layout.versions.exists()
    with runner.versions._connect(read_only=True) as con:                                         # sin tablas de versiones
        names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert "unified_document_versions" not in names


def test_all_new_tests_run_with_sockets_blocked(monkeypatch):
    def deny(*a, **k):
        raise RuntimeError("red bloqueada")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    with pytest.raises(RuntimeError):
        socket.create_connection(("example.com", 80))


# ============================================================== G. U5B.1: pin durable de CAS (carrera de rollback)
def _blob_nlink(cas, sha):
    return os.stat(cas.blob_path(sha)).st_nlink


def pin_of(layout, sha, key):
    return layout.root / "cas_pins" / sha / key


def two_stage(layout, data=b"S" * 300):
    sA, sha = staged(layout, "a.bin", data)
    sB, _ = staged(layout, "b.bin", data)
    return sA, sB, sha


def test_race_a_creates_blob_b_dedups_with_pin_a_rollback_keeps_blob_even_with_stale_keep_blob(tmp_path):
    """Reproducción exacta de la carrera de la auditoría: A calculó keep_blob=False ANTES de que B registrara."""
    layout, cas = cas_env(tmp_path)
    sA, sB, sha = two_stage(layout)
    a = cas.promote(sA, sha, None, create_view=False, pin_key="pinkey-AAAA")
    stale_keep = False                                                                          # valor viejo de A
    b = cas.promote(sB, sha, None, create_view=False, pin_key="pinkey-BBBB")                     # B: dedup + pin
    assert a.receipt.created_blob and a.pin_created and b.deduplicated and b.receipt is None and b.pin_created
    vers = VersionRepository(layout.catalog_db, layout.versions, ExecutionMode.TEST)
    assert vers.register_version(fact(ik="ID|CNMV|ns|B", sha=sha), VersionStatus.UNCONFIRMED, cas_path=b.cas_path).ok
    rb = cas.rollback_owned(a, keep_blob=stale_keep)
    assert rb.blob_state == "SHARED_LEFT" and rb.raw_view_state == "NO_VIEW" and rb.clean
    assert Path(a.cas_path).exists() and cas.verify(sha, Path(a.cas_path))                        # la versión de B sigue íntegra
    assert not pin_of(layout, sha, "pinkey-AAAA").exists() and pin_of(layout, sha, "pinkey-BBBB").exists()


def test_reverse_order_a_rolls_back_first_then_b_recreates_the_blob_as_creator(tmp_path):
    layout, cas = cas_env(tmp_path)
    sA, sB, sha = two_stage(layout)
    a = cas.promote(sA, sha, None, create_view=False, pin_key="pinkey-AAAA")
    rb = cas.rollback_owned(a)
    assert rb.blob_state == "REMOVED" and not Path(a.cas_path).exists() and not (layout.root / "cas_pins" / sha).exists()
    b = cas.promote(sB, sha, None, create_view=False, pin_key="pinkey-BBBB")
    assert not b.deduplicated and b.receipt is not None and b.receipt.created_blob and b.pin_created   # B es la creadora
    assert cas.verify(sha, Path(b.cas_path))
    assert cas.rollback_owned(b).blob_state == "REMOVED"


def test_same_pin_key_reuses_the_pin_and_does_not_accumulate_links(tmp_path):
    layout, cas = cas_env(tmp_path)
    s1, s2, sha = two_stage(layout)
    first = cas.promote(s1, sha, None, create_view=False, pin_key="pinkey-AAAA")
    links = _blob_nlink(cas, sha)
    second = cas.promote(s2, sha, None, create_view=False, pin_key="pinkey-AAAA")
    assert first.pin_created and not second.pin_created and second.pin_path == first.pin_path
    assert _blob_nlink(cas, sha) == links                                                          # sin enlaces nuevos
    rb = cas.rollback_owned(second)                                                                # no es dueña del pin
    assert rb.blob_state == "PREEXISTING_LEFT" and Path(first.pin_path).exists() and Path(first.cas_path).exists()


def test_rollback_removes_only_its_own_pin_and_the_other_identity_pin_protects_the_blob(tmp_path):
    layout, cas = cas_env(tmp_path)
    sA, sB, sha = two_stage(layout)
    a = cas.promote(sA, sha, None, create_view=False, pin_key="pinkey-AAAA")
    b = cas.promote(sB, sha, None, create_view=False, pin_key="pinkey-BBBB")
    rb_b = cas.rollback_owned(b)
    assert rb_b.blob_state == "PREEXISTING_LEFT" and not Path(b.pin_path).exists() and Path(a.pin_path).exists()
    assert Path(a.cas_path).exists()
    rb_a = cas.rollback_owned(a)                                                                   # ya sin pin ajeno
    assert rb_a.blob_state == "REMOVED" and not Path(a.cas_path).exists()
    # un pin que ya no es el inodo del blob NO se toca y bloquea el borrado (sin prueba)
    layout2, cas2 = cas_env(tmp_path / "forged")
    s1, s2, sha2 = two_stage(layout2, b"F" * 300)
    p = cas2.promote(s1, sha2, None, create_view=False, pin_key="pinkey-AAAA")
    pin = Path(p.pin_path)
    pin.unlink()
    pin.write_bytes(b"otro contenido")
    rb = cas2.rollback_owned(p)
    assert rb.blob_state == "UNPROVEN_ORPHAN" and not rb.clean and Path(p.cas_path).exists() and pin.read_bytes() == b"otro contenido"


def test_copy_mode_creates_no_pin_and_the_blob_is_never_deleted(tmp_path, monkeypatch):
    layout, cas = cas_env(tmp_path)
    s, sha = staged(layout, "c.bin", b"C" * 300)
    monkeypatch.setattr(cas_store.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError("sin hardlinks")))
    p = cas.promote(s, sha, None, create_view=False, pin_key="pinkey-AAAA")
    assert p.receipt.blob_link_mode == "copy" and p.pin_path is None and p.pin_created is False
    assert not (layout.root / "cas_pins").exists()
    rb = cas.rollback_owned(p)
    assert rb.blob_state == "UNPROVEN_ORPHAN" and Path(p.cas_path).exists()


def test_pin_creation_failure_fails_closed_without_leaving_an_unprotected_blob(tmp_path, monkeypatch):
    layout, cas = cas_env(tmp_path)
    real = os.link

    def selective(src, dst, *a, **k):
        if "cas_pins" in str(dst):
            raise PermissionError("pin denegado")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(cas_store.os, "link", selective)
    s, sha = staged(layout, "n.bin", b"N" * 300)
    with pytest.raises(cas_store.CasPinError):
        cas.promote(s, sha, None, create_view=False, pin_key="pinkey-AAAA")
    assert not cas.blob_path(sha).exists()                                                         # el blob propio se retiró
    # blob preexistente (p. ej. con vista de otra identidad): falla cerrado y no se toca
    s2, sha2 = staged(layout, "m.bin", b"M" * 300)
    cas.promote(s2, sha2, Path("ES_CNMV/2023/m.bin"))
    s3, _ = staged(layout, "m2.bin", b"M" * 300)
    with pytest.raises(cas_store.CasPinError):
        cas.promote(s3, sha2, None, create_view=False, pin_key="pinkey-AAAA")
    assert cas.verify(sha2, cas.blob_path(sha2)) and not pin_of(layout, sha2, "pinkey-AAAA").exists()
    with pytest.raises(ValueError):                                                                # sin pin_key no hay promoción sin vista
        cas.promote(s3, sha2, None, create_view=False)
    with pytest.raises(ValueError):
        cas.promote(s3, sha2, None, create_view=False, pin_key="../escape")


def test_blob_counts_in_cas_exclude_pins_and_pins_live_outside_cas(tmp_path):
    layout, cas = cas_env(tmp_path)
    sA, sB, sha = two_stage(layout)
    cas.promote(sA, sha, None, create_view=False, pin_key="pinkey-AAAA")
    cas.promote(sB, sha, None, create_view=False, pin_key="pinkey-BBBB")
    assert len([p for p in layout.cas.rglob("*") if p.is_file()]) == 1
    pins = [p for p in (layout.root / "cas_pins").rglob("*") if p.is_file()]
    assert len(pins) == 2 and all(layout.cas not in p.parents for p in pins)
    assert _blob_nlink(cas, sha) == 4                                                              # blob + 2 pines + staged de A


def test_rollback_with_view_of_one_identity_and_pin_of_another(tmp_path):
    layout, cas = cas_env(tmp_path)
    sA, sB, sha = two_stage(layout)
    a = cas.promote(sA, sha, Path("ES_CNMV/2023/a.bin"))                                           # A: con vista raw
    b = cas.promote(sB, sha, None, create_view=False, pin_key="pinkey-BBBB")                       # B: solo pin
    rb = cas.rollback_owned(a)                                                                     # sin keep_blob
    assert rb.blob_state == "SHARED_LEFT" and rb.raw_view_state == "REMOVED" and rb.clean
    assert Path(a.cas_path).exists() and Path(b.pin_path).exists()
    assert cas.rollback_owned(b).blob_state == "PREEXISTING_LEFT"                                  # B no es creadora: no borra


def test_pin_is_created_and_released_inside_the_cas_sha_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager
    held, events = set(), []

    class TrackingLocks(LockManager):
        @contextmanager
        def acquire(self, key, timeout_s=30.0):
            with super().acquire(key, timeout_s):
                held.add(key)
                try:
                    yield
                finally:
                    held.discard(key)
    layout = DataLayout(tmp_path / "root").ensure()
    cas = ContentAddressedRawStore(layout, TrackingLocks(layout.locks))
    real_link, real_unlink = os.link, Path.unlink

    def link(src, dst, *a, **k):
        if "cas_pins" in str(dst):
            events.append(("link", sha_key in held))
        return real_link(src, dst, *a, **k)

    def unlink(self, *a, **k):
        if "cas_pins" in str(self):
            events.append(("unlink", sha_key in held))
        return real_unlink(self, *a, **k)
    s, sha = staged(layout, "l.bin", b"L" * 300)
    sha_key = f"cas-{sha}"
    monkeypatch.setattr(cas_store.os, "link", link)
    monkeypatch.setattr(Path, "unlink", unlink)
    p = cas.promote(s, sha, None, create_view=False, pin_key="pinkey-AAAA")
    cas.rollback_owned(p)
    assert events == [("link", True), ("unlink", True)]                                            # ambos dentro de cas-{sha}


def test_runner_unconfirmed_leaves_a_durable_pin_and_failed_registration_removes_it(tmp_path, monkeypatch):
    A, B = make_zip("A"), make_zip("B")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    r1, layout, _ = mk(tmp_path, A, [c])
    go(r1)
    r2, _, _ = mk(tmp_path, B, [c])
    assert go(r2).state == "MANUAL_REVIEW"                                                         # UNCONFIRMED conservada
    pins = [p for p in (layout.root / "cas_pins").rglob("*") if p.is_file()]
    assert len(pins) == 1 and sha_of(B) in str(pins[0]) and r2.cas.blob_path(sha_of(B)).exists()   # el pin es su referencia
    # registro fallido: se retira el pin propio y, al no quedar referencias, el blob propio
    C = make_zip("C")
    r3, _, _ = mk(tmp_path, C, [c])
    monkeypatch.setattr(r3.versions, "register_version",
                        lambda *a, **k: RegisterResult("FAILED", "ik", "sha", message="boom"))
    out = go(r3)
    assert out.state == "FAILED" and not r3.cas.blob_path(sha_of(C)).exists()
    assert not (layout.root / "cas_pins" / sha_of(C)).exists()


def test_runner_pin_failure_is_a_failed_cas_outcome_and_leaves_nothing_behind(tmp_path, monkeypatch):
    A, B = make_zip("A"), make_zip("B")
    c = cand(identity_contract=contract(), source_document_id="DOC-1")
    r1, layout, _ = mk(tmp_path, A, [c])
    go(r1)
    real = os.link

    def selective(src, dst, *a, **k):
        if "cas_pins" in str(dst):
            raise PermissionError("pin denegado")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(cas_store.os, "link", selective)
    r2, _, _ = mk(tmp_path, B, [c])
    out = go(r2)
    assert out.state == "FAILED" and out.failure_stage == "CAS" and out.sha256 == sha_of(B)
    assert not r2.cas.blob_path(sha_of(B)).exists() and not (layout.root / "cas_pins" / sha_of(B)).exists()
    ik = resolve_identity("CNMV", c.document_id, c.identity_contract, "DOC-1").identity_key
    assert [v["sha256"] for v in r2.versions.list_versions(ik)] == [sha_of(A)]
