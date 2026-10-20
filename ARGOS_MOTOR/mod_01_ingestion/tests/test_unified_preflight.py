"""
U5A — KnownDocumentPreflight: decisión previa a la descarga (PF01..PF25). Offline y determinista (fakes, spies,
``httpx.MockTransport``); sin red, sin sleeps; todo bajo ``tmp_path`` y en modo TEST salvo PF24 (política LIVE sin I/O operativo).
"""
import hashlib
import json
import socket

import pytest

from mod_01_ingestion.src.unified.application.preflight import KnownDocumentPreflight, safe_url
from mod_01_ingestion.src.unified.application import ports
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, PreflightMatch as M, PreflightStatus as S
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.models import (
    CatalogRecord, DocumentCandidate, ManifestRecord, PreflightOutcome, RunContext, SourceMetadata)
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified.unit_of_work import ManifestCatalogUnitOfWork
from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner, make_zip

SHA = "ab" * 32
OTHER = "cd" * 32
CTX = RunContext(run_id="run-pf", started_at="2026-10-10T10:00:00+00:00", mode=ExecutionMode.TEST)
URL = "https://example.test/files/report.zip?token=SECRETTOKEN&api_key=SECRETKEY"


def cand(**kw):
    base = dict(authority="CNMV", country_code="ES", issuer_id="LEI1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
                source_url=URL, issuer_lei="LEI1")
    base.update(kw)
    return DocumentCandidate(**base)


def rec(c=None, sha=SHA, **over):
    c = c or cand()
    r = dict(document_id=c.document_id, sha256=sha, status="RAW_VALIDATED", authority=c.authority,
             fiscal_year=c.fiscal_year, doc_type=c.doc_type, issuer_id=c.issuer_id, issuer_lei=c.issuer_lei,
             raw_path="raw/x/report.zip", source_url=URL)
    r.update(over)
    return r


class FakeLookup:
    """Solo lectura por construcción: no expone ningún método de escritura."""

    def __init__(self, manifests=(), catalogs=(), by_sha=(), intact=True):
        self.manifests = {(r["authority"], r["fiscal_year"], r["document_id"]): r for r in manifests}
        self.catalogs = {r["document_id"]: r for r in catalogs}
        self.by_sha, self.intact = list(by_sha), intact
        self.calls = []

    def get_manifest(self, authority, fiscal_year, document_id):
        self.calls.append("get_manifest")
        return self.manifests.get((authority, fiscal_year, document_id))

    def get_catalog(self, document_id):
        self.calls.append("get_catalog")
        return self.catalogs.get(document_id)

    def find_by_sha256(self, sha256):
        self.calls.append("find_by_sha256")
        return [r for r in self.by_sha if r["sha256"] == sha256]

    def content_is_intact(self, record):
        self.calls.append("content_is_intact")
        return self.intact


def run(lookup, c=None):
    return KnownDocumentPreflight(lookup).evaluate(c or cand(), CTX)


# =============================================================== decisión pura (PF01-PF15)
def test_pf01_nothing_registered_proceeds():
    out = run(FakeLookup())
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "NO_MATCH" and out.matched_by is M.NONE
    assert not out.needs_manual_review and out.may_download and not out.skips_download


def test_pf02_manifest_and_catalog_agree_with_expected_sha_is_skipped():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup([rec(c)], [rec(c)]), c)
    assert out.status is S.SKIPPED_ALREADY_PRESENT and out.matched_by is M.SHA256 and out.skips_download
    assert out.existing_sha256 == SHA and out.expected_sha256 == SHA


def test_pf02b_registered_but_content_unverified_is_not_skipped():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup([rec(c)], [rec(c)], intact=False), c)
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "REGISTERED_CONTENT_UNVERIFIED"


def test_pf03_expected_hash_already_registered_under_compatible_identity_is_skipped_without_new_record():
    c = cand(expected_sha256=SHA)
    other = rec(c, document_id="CNMV_SAN_2023_ESEF_PACKAGE", issuer_id="SAN")          # mismo emisor (LEI), otra clave
    lk = FakeLookup(by_sha=[other])
    out = run(lk, c)
    assert out.status is S.SKIPPED_ALREADY_PRESENT and out.matched_by is M.SHA256 and out.reason_code == "CONTENT_ALREADY_REGISTERED"
    assert out.document_id == c.document_id and out.existing_catalog["document_id"] == "CNMV_SAN_2023_ESEF_PACKAGE"


def test_pf04_manifest_without_catalog_is_recovery_required():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup([rec(c)], []), c)
    assert out.status is S.RECOVERY_REQUIRED and out.needs_manual_review and out.reason_code == "PARTIAL_MANIFEST_ONLY"
    assert not out.may_download


def test_pf05_catalog_without_manifest_is_recovery_required():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup([], [rec(c)]), c)
    assert out.status is S.RECOVERY_REQUIRED and out.needs_manual_review and out.reason_code == "PARTIAL_CATALOG_ONLY"
    out2 = run(FakeLookup([], [rec(c, sha=OTHER)]), c)
    assert out2.status is S.RECOVERY_REQUIRED and out2.reason_code == "PARTIAL_CATALOG_ONLY_HASH_DIFFERS"


def test_pf06_manifest_and_catalog_disagree_on_hash_is_conflict():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup([rec(c, sha=SHA)], [rec(c, sha=OTHER)]), c)
    assert out.status is S.CONFLICT and out.reason_code == "MANIFEST_CATALOG_HASH_MISMATCH" and out.needs_manual_review


def test_pf07_same_document_id_different_expected_hash_is_possible_republication_with_traceability():
    c = cand(expected_sha256=OTHER, source_document_id="SRC-77")
    out = run(FakeLookup([rec(c, sha=SHA)], [rec(c, sha=SHA)]), c)
    assert out.status is S.POSSIBLE_REPUBLICATION and out.may_download and not out.skips_download
    assert (out.document_id, out.existing_sha256, out.expected_sha256) == (c.document_id, SHA, OTHER)
    assert out.source_document_id == "SRC-77" and out.fiscal_year == 2023 and out.discovered_at == CTX.started_at
    assert out.reason_code == "SAME_DOCUMENT_ID_DIFFERENT_EXPECTED_HASH" and not out.needs_manual_review


def test_pf08_same_document_id_without_expected_hash_never_skips_on_id_alone():
    c = cand()
    out = run(FakeLookup([rec(c)], [rec(c)]), c)
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "NO_VERIFIABLE_HASH_DOCUMENT_ID_MATCH"
    assert out.matched_by is M.DOCUMENT_ID and not out.skips_download
    with pytest.raises(DomainValidationError):                       # y el modelo lo impide por construcción
        PreflightOutcome(S.SKIPPED_ALREADY_PRESENT, "X", "d", matched_by=M.DOCUMENT_ID)


def test_pf09_same_file_name_only_proceeds():
    c = cand()
    elsewhere = rec(c, document_id="CNMV_OTHER_2022_ESEF_PACKAGE", fiscal_year=2022, issuer_id="OTHER", raw_path="raw/y/report.zip")
    out = run(FakeLookup(by_sha=[elsewhere]), c)
    assert out.status is S.PROCEED_DOWNLOAD and out.matched_by is M.NONE


def test_pf10_same_url_only_is_not_a_strong_skip():
    c = cand(expected_sha256=None)
    same_url = rec(c, document_id="CNMV_OTHER_2023_ESEF_PACKAGE", issuer_id="OTHER", sha256=OTHER)
    out = run(FakeLookup(manifests=[same_url], catalogs=[same_url], by_sha=[same_url]), c)
    assert out.status is S.PROCEED_DOWNLOAD and not out.skips_download


def test_pf11_entity_incompatible_is_conflict():
    c = cand(expected_sha256=SHA, entity_id="entity:lei:AAA")
    r = rec(c, entity_id="entity:lei:BBB")
    out = run(FakeLookup([r], [r]), c)
    assert out.status is S.CONFLICT and out.reason_code == "IDENTITY_INCOMPATIBLE:entity_id" and out.needs_manual_review
    other = rec(c, document_id="CNMV_X_2023_ESEF_PACKAGE", issuer_lei="ZZZ")           # mismo hash bajo otra entidad (LEI)
    out2 = run(FakeLookup(by_sha=[other]), c)
    assert out2.status is S.CONFLICT and out2.reason_code.startswith("CONTENT_REGISTERED_UNDER_INCOMPATIBLE_IDENTITY")


def test_pf12_instrument_incompatible_is_manual_review():
    c = cand(expected_sha256=SHA, instrument_id="instrument:isin:ES0113900J37")
    r = rec(c, instrument_id="instrument:isin:US0378331005")
    out = run(FakeLookup([r], [r]), c)
    assert out.status is S.MANUAL_REVIEW and out.needs_manual_review and "instrument_id" in out.reason_code


def test_pf13_period_incompatible_is_conflict():
    c = cand(expected_sha256=SHA)
    r = rec(c, fiscal_year=2022)
    lk = FakeLookup([r], [r])
    lk.manifests = {(c.authority, c.fiscal_year, c.document_id): r}            # registrado bajo la clave del candidato
    assert run(lk, c).status is S.CONFLICT
    out = run(FakeLookup(by_sha=[rec(c, document_id="CNMV_L_2022_ESEF_PACKAGE", fiscal_year=2022)]), c)
    assert out.status is S.CONFLICT and "fiscal_year" in out.reason_code


def test_pf14_document_type_incompatible_is_conflict():
    c = cand(expected_sha256=SHA)
    out = run(FakeLookup(by_sha=[rec(c, document_id="CNMV_L_2023_IAGC", doc_type="IAGC")]), c)
    assert out.status is S.CONFLICT and "doc_type" in out.reason_code
    out2 = run(FakeLookup(by_sha=[rec(c, document_id="X_2023", authority="BAFIN")]), c)
    assert out2.status is S.CONFLICT and "authority" in out2.reason_code


def test_pf15_source_document_id_without_a_source_contract_has_no_authority():
    """U5B: el booleano ``source_id_is_version_stable`` se retiró; un id sin contrato de la fuente nunca autoriza un skip."""
    c = cand(source_document_id="SRC-1")
    r = rec(c)
    out = run(FakeLookup([r], [r]), c)
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "NO_VERIFIABLE_HASH_DOCUMENT_ID_MATCH"
    with pytest.raises(TypeError):
        cand(source_id_is_version_stable=True)                       # el campo ya no existe


def test_preflight_is_deterministic_and_lookup_is_read_only():
    c = cand(expected_sha256=SHA)
    lk = FakeLookup([rec(c)], [rec(c)])
    assert run(lk, c) == run(lk, c)
    assert not [m for m in dir(lk) if m.startswith(("put", "write", "save", "upsert", "stage", "commit", "delete"))]
    assert isinstance(lk, ports.KnownDocumentLookup)


# =============================================================== integración con el runner (PF16-PF25)
class StubAdapter:
    authority, country_code, name, allowed_domains = "CNMV", "ES", "CNMV", ()

    def __init__(self, candidates):
        self._c = candidates

    def discover(self, request):
        return list(self._c)

    def fetch_metadata(self, candidate):
        return SourceMetadata(resolved_url=candidate.source_url, file_name="san2023.zip", extension=".zip",
                              expected_kind="ZIP", authority_rules={"allowed_kinds": ["ZIP"], "min_size_bytes": 64})


PKG = "https://cnmv.test/pkg/san2023.zip"


def committed_runner(tmp_path):
    """Un runner con un documento ya COMPLETED; devuelve (runner, layout, site, sha, candidato_base)."""
    payload = make_zip()
    site = base_site(zip_bytes=payload)
    runner, layout, _ = make_runner(tmp_path, site)
    assert runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0].state == "COMPLETED"
    sha = hashlib.sha256(payload).hexdigest()
    base = dict(authority="CNMV", country_code="ES", issuer_id="LEI_ES_1", fiscal_year=2023, doc_type="ESEF_PACKAGE",
                source_url=PKG, issuer_lei="LEI_ES_1")
    return runner, layout, site, sha, base


def tree_snapshot(layout):
    snap = {}
    for sub in (layout.manifests, layout.raw, layout.cas, layout.staging, layout.quarantine):
        for p in sorted(sub.rglob("*")) if sub.exists() else []:
            if p.is_file():
                snap[str(p)] = (p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    snap["catalog"] = hashlib.sha256(layout.catalog_db.read_bytes()).hexdigest()
    return snap


def forbid(monkeypatch, runner, hit):
    def trap(name):
        def f(*a, **k):
            hit.append(name)
            raise AssertionError(f"{name} no debe invocarse tras un skip del preflight")
        return f
    monkeypatch.setattr(runner.download, "download", trap("downloader"))
    monkeypatch.setattr(runner.cas, "promote", trap("cas.promote"))
    monkeypatch.setattr(ManifestCatalogUnitOfWork, "execute", trap("unit_of_work"))
    monkeypatch.setattr(DomainRateLimiter, "slot", trap("rate_limiter"))
    monkeypatch.setattr(runner.locks, "acquire", trap("lock"))
    monkeypatch.setattr(runner.manifests, "stage", trap("manifests.stage"))
    monkeypatch.setattr(runner.catalog, "upsert", trap("catalog.upsert"))


def test_pf16_to_pf20_skip_happens_before_any_io_or_write(tmp_path, monkeypatch):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=sha)])
    calls_before, snap = len(site.calls), tree_snapshot(layout)
    staging_before = sorted(str(p) for p in layout.staging.rglob("*"))
    hit = []
    forbid(monkeypatch, runner, hit)
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "SKIPPED_ALREADY_PRESENT" and not out.needs_manual_review and out.sha256 == sha     # PF15/16
    assert len(site.calls) == calls_before and hit == []                       # PF16 sin descarga; PF18 sin CAS; PF19 sin UoW
    assert not list(layout.staging.rglob("*.part"))                            # PF17 sin .part
    assert sorted(str(p) for p in layout.staging.rglob("*")) == staging_before  # ni siquiera directorios nuevos
    assert tree_snapshot(layout) == snap                                       # PF20 ni manifiesto, ni catálogo, ni raw, ni CAS


def test_pf20_evaluate_with_real_repositories_does_not_create_or_modify_anything(tmp_path):
    layout = DataLayout(tmp_path / "root")
    manifests = ManifestRepository(layout, mode=ExecutionMode.TEST)
    catalog = CatalogRepository(layout.catalog_db, mode=ExecutionMode.TEST)
    from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore
    from mod_01_ingestion.src.unified.lock_manager import LockManager
    from mod_01_ingestion.src.unified.preflight_lookup import RepositoryKnownDocumentLookup
    cas = ContentAddressedRawStore(layout, LockManager(layout.locks))
    before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_path.rglob("*"))
    pf = KnownDocumentPreflight(RepositoryKnownDocumentLookup(manifests, catalog, cas))
    assert pf.evaluate(cand(expected_sha256=SHA), CTX).status is S.PROCEED_DOWNLOAD
    assert sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_path.rglob("*")) == before
    assert not layout.manifests.exists()                                       # no crea directorios


def test_pf21_no_sockets_are_opened(tmp_path, monkeypatch):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=sha)])

    def deny(*a, **k):
        raise RuntimeError("red bloqueada")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    assert runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0].state == "SKIPPED_ALREADY_PRESENT"


@pytest.mark.parametrize("breakage,state,reason", [
    ("manifest_only", "RECOVERY_REQUIRED", "PARTIAL_MANIFEST_ONLY"),
    ("catalog_only", "RECOVERY_REQUIRED", "PARTIAL_CATALOG_ONLY"),
])
def test_runner_partial_state_stops_before_download(tmp_path, monkeypatch, breakage, state, reason):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    doc = DocumentCandidate(**base).document_id
    if breakage == "manifest_only":
        runner.catalog.delete(doc)
    else:
        runner.manifests.path_for("CNMV", 2023, doc).unlink()
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=sha)])
    snap, n, hit = tree_snapshot(layout), len(site.calls), []
    forbid(monkeypatch, runner, hit)
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == state and out.needs_manual_review and out.failure_stage == "PREFLIGHT" and hit == []
    assert len(site.calls) == n and tree_snapshot(layout) == snap              # conserva el estado existente tal cual
    ev = [e for e in runner.telemetry.read_all() if e["event"] == "PREFLIGHT_RECOVERY_REQUIRED"][-1]
    assert ev["reason_code"] == reason and ev["matched_by"] == "NONE"


def test_runner_conflict_and_manual_review_are_typed_and_do_not_download(tmp_path, monkeypatch):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**{**base, "issuer_lei": "OTRO_LEI"}, expected_sha256=sha)])
    n, hit = len(site.calls), []
    forbid(monkeypatch, runner, hit)
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "CONFLICT" and out.needs_manual_review and out.error_class == "INVARIANT_VIOLATION" and hit == []
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=sha, instrument_id="instrument:isin:X")])
    # el registro de producción no almacena instrument_id => no hay incompatibilidad demostrable: se salta por hash
    assert runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0].state == "SKIPPED_ALREADY_PRESENT"
    assert len(site.calls) == n


def test_pf22_two_workers_pass_preflight_unit_of_work_keeps_final_idempotence(tmp_path):
    layout = DataLayout(tmp_path / "root")
    manifests = ManifestRepository(layout, mode=ExecutionMode.TEST)
    catalog = CatalogRepository(layout.catalog_db, mode=ExecutionMode.TEST)
    lk = FakeLookup()
    c = cand(expected_sha256=SHA)
    a, b = run(lk, c), run(lk, c)                                              # ambos ven «no existe»
    assert a.status is b.status is S.PROCEED_DOWNLOAD
    m, cr = _records(manifests, SHA)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, cr).committed             # worker A confirma
    m2, cr2 = _records(manifests, SHA, run_id="rB", job_id="jB")
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, cr2)                      # worker B llega tarde
    assert out.committed and out.idempotent


def test_pf23_two_workers_pass_preflight_unit_of_work_keeps_conflict(tmp_path):
    layout = DataLayout(tmp_path / "root")
    manifests = ManifestRepository(layout, mode=ExecutionMode.TEST)
    catalog = CatalogRepository(layout.catalog_db, mode=ExecutionMode.TEST)
    assert run(FakeLookup(), cand(expected_sha256=OTHER)).status is S.PROCEED_DOWNLOAD
    m, cr = _records(manifests, SHA)
    assert ManifestCatalogUnitOfWork(manifests, catalog).execute(m, cr).committed
    m2, cr2 = _records(manifests, OTHER, run_id="rB", job_id="jB")
    out = ManifestCatalogUnitOfWork(manifests, catalog).execute(m2, cr2)
    assert not out.committed and out.status.value == "FAILED_INVARIANT"
    assert any(v.startswith("CONFLICT") for v in out.invariant_violations)


def _records(manifests, sha, **over):
    c = cand()
    kw = dict(manifest_version="1.0.0", document_id=c.document_id, run_id="rA", job_id="jA", authority="CNMV",
              country_code="ES", issuer_id="LEI1", fiscal_year=2023, doc_type="ESEF_PACKAGE", source_url="https://example.test/a.zip",
              final_url=None, raw_path="raw/a.zip", cas_path="cas/x", sha256=sha, size_bytes=1, mime_type=None,
              http_status=200, status="RAW_VALIDATED", completeness_status="OK")
    kw.update(over)
    m = ManifestRecord(**kw)
    cr = CatalogRecord(document_id=m.document_id, run_id=m.run_id, job_id=m.job_id, authority="CNMV", country_code="ES",
                       issuer_id="LEI1", fiscal_year=2023, doc_type="ESEF_PACKAGE", sha256=sha, raw_path="raw/a.zip",
                       manifest_path=str(manifests.path_for("CNMV", 2023, m.document_id)), status="RAW_VALIDATED", size_bytes=1)
    return m, cr


def test_runner_possible_republication_downloads_but_unit_of_work_refuses_to_overwrite(tmp_path):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    new_bytes = make_zip("REPUBLICADO")
    new_sha = hashlib.sha256(new_bytes).hexdigest()
    site2 = base_site(zip_bytes=new_bytes)
    runner2, _, _ = make_runner(tmp_path, site2)
    runner2.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=new_sha, source_document_id="SRC-1")])
    prev_manifest = next(layout.manifests.rglob("*.json")).read_bytes()
    out = runner2.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert len(site2.calls) == 1                                               # el preflight permitió la descarga
    assert out.state == "FAILED" and out.error_class == "INVARIANT_VIOLATION"  # U5A no resuelve el versionado (U5B)
    assert next(layout.manifests.rglob("*.json")).read_bytes() == prev_manifest   # la versión previa no se sobrescribe
    assert runner2.catalog.get("CNMV_LEI_ES_1_2023_ESEF_PACKAGE")[1] == sha
    ev = [e for e in runner2.telemetry.read_all() if e["event"] == "PREFLIGHT_REPUBLICATION"]
    assert ev and ev[0]["reason_code"] == "SAME_DOCUMENT_ID_DIFFERENT_EXPECTED_HASH" and ev[0]["matched_by"] == "DOCUMENT_ID"


# =============================================================== U5A corrección: única autoridad de skip
@pytest.mark.parametrize("label,lookup_kw,cand_kw", [
    ("A_same_document_id_no_hash", dict(), {}),
    ("D_intact_raw_no_remote_validator", dict(intact=True), {}),
    ("C_source_id_without_contract", dict(), dict(source_document_id="SRC-1")),
])
def test_no_remote_validator_proceeds_even_with_matching_manifest_catalog_and_intact_raw(label, lookup_kw, cand_kw):
    c = cand(**cand_kw)
    out = run(FakeLookup([rec(c)], [rec(c)], **lookup_kw), c)
    assert out.status is S.PROCEED_DOWNLOAD and out.reason_code == "NO_VERIFIABLE_HASH_DOCUMENT_ID_MATCH", label
    assert not out.skips_download


def test_same_url_only_proceeds():                                         # E
    c = cand()
    other = rec(c, document_id="CNMV_OTRO_DOC", issuer_id="LEI2", issuer_lei="LEI2")      # misma source_url, otro documento
    assert run(FakeLookup([other], [other], by_sha=[other]), c).status is S.PROCEED_DOWNLOAD


def test_same_file_name_only_proceeds():                                   # F
    c = cand(source_url="https://example.test/files/report.zip")
    other = rec(c, document_id="CNMV_OTRO_DOC", raw_path="raw/otro/report.zip", source_url="https://otro.test/report.zip")
    assert run(FakeLookup([other], [other]), c).status is S.PROCEED_DOWNLOAD


def test_matching_hash_with_different_document_id_still_requires_identity_not_url_or_name():
    c = cand(expected_sha256=SHA)
    same_url_other_hash = rec(c, sha=OTHER, document_id="CNMV_X")
    assert run(FakeLookup(by_sha=[same_url_other_hash]), c).status is S.PROCEED_DOWNLOAD


def test_runner_without_remote_validator_downloads_again_and_never_emits_legacy_skip(tmp_path):    # A, D, I, J
    runner, layout, site, sha, base = committed_runner(tmp_path)
    n = len(site.calls)
    manifest_before = next(layout.manifests.rglob("*.json")).read_bytes()
    for _ in range(2):                                                          # J: dos ejecuciones sin hash
        out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
        assert out.state == "COMPLETED" and out.sha256 == sha                  # I: PROCEED no se convierte en skip
    assert len(site.calls) == n + 2
    assert next(layout.manifests.rglob("*.json")).read_bytes() == manifest_before   # el UoW no duplica ni reescribe
    assert len(list(layout.manifests.rglob("*.json"))) == 1 and runner.catalog.get("CNMV_LEI_ES_1_2023_ESEF_PACKAGE")[1] == sha
    states = {e.get("state") for e in runner.telemetry.read_all() if e["event"] == "state_transition"}
    assert "SKIPPED_DUPLICATE" not in states and "SKIPPED_ALREADY_PRESENT" not in states
    ev = [e["event"] for e in runner.telemetry.read_all() if e["event"].startswith("PREFLIGHT")]
    assert ev[-2:] == ["PREFLIGHT_STARTED", "PREFLIGHT_PROCEED"]


def test_runner_same_hash_skip_has_single_terminal_event_and_no_legacy_alias(tmp_path):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=sha)])
    mark = len(runner.telemetry.read_all())
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "SKIPPED_ALREADY_PRESENT"
    new = runner.telemetry.read_all()[mark:]
    assert len([e for e in new if e["event"] == "PREFLIGHT_SKIPPED"]) == 1
    terminal = [e for e in new if e["event"] == "state_transition" and str(e.get("state", "")).startswith("SKIPPED")]
    assert [e["state"] for e in terminal] == ["SKIPPED_ALREADY_PRESENT"]
    assert not [e for e in new if e["event"] in ("http_response", "download_attempt")]


def test_runner_different_expected_hash_is_possible_republication_not_skip(tmp_path):            # C (runner)
    runner, layout, site, sha, base = committed_runner(tmp_path)
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**base, expected_sha256=OTHER)])
    n = len(site.calls)
    runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    assert len(site.calls) == n + 1
    assert [e for e in runner.telemetry.read_all() if e["event"] == "PREFLIGHT_REPUBLICATION"]


def test_preflight_never_skips_by_url_or_name_in_source():
    import inspect
    from mod_01_ingestion.src.unified.application import preflight as mod
    src = inspect.getsource(mod.KnownDocumentPreflight)
    for forbidden in ("source_url ==", "file_name ==", "raw_path ==", "basename"):
        assert forbidden not in src


def test_runner_has_no_independent_skip_decision():
    import inspect
    from mod_01_ingestion.src.unified import ingest_runner as mod
    src = inspect.getsource(mod)
    assert "JobState.SKIPPED_DUPLICATE" not in src and "cas.verify" not in src
    assert src.count("JobState.SKIPPED_ALREADY_PRESENT") == 2        # mapa de traducción + conteo de la telemetría


def test_telemetry_url_loses_query_and_the_manifest_only_accepts_the_stable_reference(tmp_path):
    secret = "https://example.test/a.zip?token=SECRETTOKEN&sig=abc123#frag"
    c = DocumentCandidate(authority="CNMV", country_code="ES", issuer_id="LEI1", fiscal_year=2023,
                          doc_type="ESEF_PACKAGE", source_url=secret)
    assert c.source_url == "https://example.test/a.zip"                         # CNMV-U4: el candidato solo conserva la referencia estable
    assert c.transport_url is not None and "SECRETTOKEN" not in repr(c) + str(c.to_dict())      # la URL completa vive solo en memoria
    from mod_01_ingestion.src.unified.domain.transport import SecretLeakError
    with pytest.raises(SecretLeakError):                                         # un manifiesto con query/token se rechaza (fail-closed)
        ManifestRepository(DataLayout(tmp_path / "r0"), mode=ExecutionMode.TEST).stage(
            _records(ManifestRepository(DataLayout(tmp_path / "r0"), mode=ExecutionMode.TEST), SHA, source_url=secret)[0])
    m, _ = _records(ManifestRepository(DataLayout(tmp_path / "r"), mode=ExecutionMode.TEST), SHA, source_url=c.source_url)
    assert m.source_url == "https://example.test/a.zip"
    runner, *_ = committed_runner(tmp_path / "t")
    runner.telemetry.emit("probe", None, "test", url=secret, final_url=secret, other="x")
    ev = [e for e in runner.telemetry.read_all() if e["event"] == "probe"][0]
    blob = json.dumps(ev)
    assert "?" not in ev["url"] and "?" not in ev["final_url"] and "#" not in blob
    for leak in ("SECRETTOKEN", "abc123", "token="):
        assert leak not in blob


def test_pf24_simulated_stays_forbidden_in_live_and_is_rejected_before_preflight(tmp_path, monkeypatch):
    runner, layout, site, sha, base = committed_runner(tmp_path)                    # el runner usa RunContext por defecto = LIVE
    assert runner.run.mode is ExecutionMode.LIVE
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**{**base, "doc_type": "SIMULATED"})])
    called = []
    monkeypatch.setattr(runner.preflight, "evaluate", lambda *a, **k: called.append(1))
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "FAILED" and out.error_class == "VALIDATION_REJECTED" and called == []


def test_pf25_events_and_messages_are_redacted(tmp_path):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    secret_url = PKG + "?token=SECRETTOKEN&api_key=SECRETKEY&sig=abc123"
    runner.adapters["CNMV"] = StubAdapter([DocumentCandidate(**{**base, "source_url": secret_url}, expected_sha256=sha)])
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    blob = json.dumps(runner.telemetry.read_all()) + json.dumps(out.to_dict())
    for leak in ("SECRETTOKEN", "SECRETKEY", "abc123", "token=", "api_key"):
        assert leak not in blob, leak
    pf_events = [e for e in runner.telemetry.read_all() if e["event"].startswith("PREFLIGHT")]
    assert {e["event"] for e in pf_events} >= {"PREFLIGHT_STARTED", "PREFLIGHT_SKIPPED"}
    for e in pf_events:
        assert {"run_id", "job_id", "document_id"} <= set(e)
        if e["event"] != "PREFLIGHT_STARTED":
            assert {"status", "matched_by", "reason_code"} <= set(e)
    assert safe_url(secret_url) == PKG


def test_preflight_lookup_failure_is_fail_closed_manual_review(tmp_path, monkeypatch):
    runner, layout, site, sha, base = committed_runner(tmp_path)
    n = len(site.calls)
    monkeypatch.setattr(runner.preflight.lookup, "get_catalog", lambda d: (_ for _ in ()).throw(OSError("db locked")))
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "MANUAL_REVIEW" and out.needs_manual_review and len(site.calls) == n
    ev = [e for e in runner.telemetry.read_all() if e["event"] == "PREFLIGHT_MANUAL_REVIEW"][-1]
    assert ev["reason_code"] == "PREFLIGHT_LOOKUP_ERROR:OSError"


def test_preflight_events_follow_documented_names_and_states_are_terminal():
    from mod_01_ingestion.src.unified.domain.enums import ALLOWED_TRANSITIONS, PipelineStatus as P
    for st in (P.SKIPPED_ALREADY_PRESENT, P.RECOVERY_REQUIRED, P.CONFLICT, P.MANUAL_REVIEW):
        assert st in ALLOWED_TRANSITIONS[P.DISCOVERED] and ALLOWED_TRANSITIONS[st] == frozenset()
