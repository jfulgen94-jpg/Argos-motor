"""
U4 (ES + US) — migración al pipeline unificado mediante adapters que producen candidatos comunes. SANDBOX/REPLAY offline:
fixtures JSON, HTTP simulado (``ReplayHttp``), sockets bloqueados y todo bajo tmp_path. No se descarga nada real.
"""
import ast
import dataclasses
import hashlib
import json
import random
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified import migration_evidence as me
from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.adapters.common import (
    CandidateContractError, assert_common_candidate, sanitize_source_url)
from mod_01_ingestion.src.unified.adapters.replay import ReplayFixtureError, ReplayLinkProvider
from mod_01_ingestion.src.unified.adapters.sec_edgar import SECAdapter
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode, SourceType
from mod_01_ingestion.src.unified.domain.versions import (
    InitialVersionPolicy, IdScope, SourceIdentityContract, resolve_identity)
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.router import SourceRouter, UnroutableSourceError
from mod_01_ingestion.src.unified.sandbox_replay import ReplayHttp, SandboxViolation, make_sandbox_runner
from mod_01_ingestion.tests.test_unified_ingest import make_zip

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
ES_ZIP = make_zip("ES-U4")                     # bytes FIJOS (make_zip lleva marca de tiempo)
US_HTML = ("<html><head><title>Apple Inc. Form 10-K annual report</title></head><body>"
           + "".join(f"<p>Item {i}. Consolidated financial statements and management discussion of operations.</p>"
                     for i in range(1, 120)) + "</body></html>").encode("utf-8")
ES_RECORD = {"lei": "LEI_ES_1", "ticker": "SAN", "name": "Banco X", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
             "url": "https://www.cnmv.es/pkg/san2023.zip?token=SECRETTOKEN&sig=abc123&year=2023#frag",
             "page_url": "https://www.cnmv.es/ficha?access_token=zzz"}
US_RECORD = {"cik": "320193", "name": "Apple Inc.", "ticker": "AAPL", "accessionNumber": "0000320193-23-000106",
             "form": "10-K", "reportDate": "2023-09-30", "filingDate": "2023-11-03", "primaryDocument": "aapl-20230930.htm"}
US_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
ES_URL = "https://www.cnmv.es/pkg/san2023.zip?year=2023"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sub(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return p


def write_fixture(tmp_path, name, records):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"records": records}), encoding="utf-8")
    return p


def build(tmp_path, es=(ES_RECORD,), us=(US_RECORD,), **sec_kw):
    es_adapter = CNMVAdapter(ReplayLinkProvider(write_fixture(tmp_path, "es", list(es))))
    us_adapter = SECAdapter([ReplayLinkProvider(write_fixture(tmp_path, "us", list(us)))], **sec_kw)
    return SourceRouter({"CNMV": es_adapter, "SEC": us_adapter}), es_adapter, us_adapter


def replay():
    return (ReplayHttp(["www.cnmv.es", "www.sec.gov"]).add("https://www.cnmv.es/pkg/san2023.zip", ES_ZIP, content_type="application/zip")
            .add(US_URL, US_HTML, content_type="text/html"))


def sandbox(tmp_path, router=None, http=None, **kw):
    router = router or build(tmp_path)[0]
    http = http or replay()
    return make_sandbox_runner(tmp_path / "root", router, http, **kw), http


def run_all(runner):
    return [runner.run_discovery(DiscoveryRequest(authority=a)).outcomes for a in ("CNMV", "SEC")]


# ================================================================= adapters -> candidato común
def test_es_adapter_produces_the_common_candidate_from_a_replay_fixture(tmp_path):
    router, es, us = build(tmp_path)
    (c,) = router.discover(DiscoveryRequest(authority="CNMV"))
    assert (c.authority, c.country_code, c.source, c.source_type) == ("CNMV", "ES", "CNMV", SourceType.OFFICIAL_OAM)
    assert (c.issuer_id, c.issuer_lei, c.fiscal_year, c.doc_type) == ("LEI_ES_1", "LEI_ES_1", 2023, "ESEF_PACKAGE")
    assert c.source_url == ES_URL.split("?")[0] and "?" not in c.source_url and "#" not in c.source_url   # CNMV-U4: referencia estable
    assert c.transport_url is not None and "?year=2023" not in repr(c)                              # la URL completa solo vive en memoria
    assert c.source_page_url == "https://www.cnmv.es/ficha"
    assert c.identity_contract is None and c.source_document_id is None                          # sin identidad inventada
    assert_common_candidate(c, authority="CNMV", country_code="ES", allowed_domains=es.allowed_domains)


def test_us_adapter_produces_the_common_candidate_from_a_replay_fixture(tmp_path):
    bad = [dict(US_RECORD, form="10-Q"), dict(US_RECORD, accessionNumber="no-es-accesion"),
           dict(US_RECORD, cik="abc"), dict(US_RECORD, primaryDocument="../x.htm"), dict(US_RECORD, reportDate="n/a")]
    router, es, us = build(tmp_path, us=[US_RECORD] + bad)
    (c,) = router.discover(DiscoveryRequest(authority="SEC"))
    assert (c.authority, c.country_code, c.source, c.source_type) == ("SEC", "US", "SEC", SourceType.REGULATOR_API)
    assert (c.issuer_id, c.fiscal_year, c.doc_type, c.ticker) == ("0000320193", 2023, "10-K", "AAPL")
    assert c.source_url == US_URL and c.source_page_url.endswith("/000032019323000106/")
    assert c.source_document_id == "0000320193-23-000106" and c.identity_contract is None
    assert sorted(why for _, why in us.rejected) == sorted([
        "formulario no anual: 10-Q", "accessionNumber inválido", "cik inválido", "primaryDocument no permitido",
        "ejercicio fiscal no determinable"])
    assert not resolve_identity(c.authority, c.document_id, c.identity_contract, c.source_document_id).is_contracted


def test_sanitize_source_url_removes_credentials_fragment_and_secret_params():
    assert sanitize_source_url("https://u:p@h.test:8443/a/b.pdf?x=1&token=T&Sig=S&y=2#f") == "https://h.test:8443/a/b.pdf?x=1&y=2"
    assert sanitize_source_url("https://h.test/a") == "https://h.test/a" and sanitize_source_url("sin-esquema") == "sin-esquema"


def test_replay_provider_is_deterministic_read_only_and_validates_the_fixture(tmp_path):
    p = write_fixture(tmp_path, "x", [ES_RECORD])
    prov = ReplayLinkProvider(p)
    first = list(prov(DiscoveryRequest(authority="CNMV")))
    first[0]["lei"] = "MUTADO"
    assert list(prov(DiscoveryRequest(authority="CNMV")))[0]["lei"] == "LEI_ES_1"             # devuelve copias
    for bad in ('{"records": "no"}', "[1, 2]", "no es json"):
        q = tmp_path / "bad.json"
        q.write_text(bad, encoding="utf-8")
        with pytest.raises(ReplayFixtureError):
            ReplayLinkProvider(q)
    with pytest.raises(ReplayFixtureError):
        ReplayLinkProvider(tmp_path / "no_existe.json")


# ================================================================= router determinista
def test_router_selects_the_right_adapter_deterministically(tmp_path):
    router, es, us = build(tmp_path)
    assert router.route(authority="cnmv") is es and router.route(authority="SEC") is us
    assert router.route(country_code="es") is es and router.route(country_code="US") is us
    assert router.authorities() == ["CNMV", "SEC"]
    for kw in ({"authority": "AMF"}, {"country_code": "FR"}, {}):
        with pytest.raises(UnroutableSourceError):
            router.route(**kw)
    other_es = CNMVAdapter(lambda r: [])
    other_es.authority = "OTRA_ES"
    amb = SourceRouter({"CNMV": es, "OTRA_ES": other_es})
    with pytest.raises(UnroutableSourceError):
        amb.route(country_code="ES")                                                           # ambiguo: exige autoridad
    assert amb.route(authority="OTRA_ES") is other_es
    with pytest.raises(UnroutableSourceError):
        SourceRouter({"CNMV": us})                                                              # clave != autoridad del adapter


def test_router_output_does_not_depend_on_provider_order(tmp_path):
    recs = [dict(US_RECORD, cik=str(c), accessionNumber=f"000000000{c}-23-000001") for c in (5, 3, 9, 1)]
    r1, *_ = build(sub(tmp_path, "a"), us=recs)
    r2, *_ = build(sub(tmp_path, "b"), us=list(reversed(recs)))
    a = [c.issuer_id for c in r1.discover(DiscoveryRequest(authority="SEC"))]
    b = [c.issuer_id for c in r2.discover(DiscoveryRequest(authority="SEC"))]
    assert a == b == sorted(a)
    shuffled = recs[:]
    random.Random(3).shuffle(shuffled)
    r3, *_ = build(sub(tmp_path, "c"), us=shuffled)
    assert [c.issuer_id for c in r3.discover(DiscoveryRequest(authority="SEC"))] == a


class BadAdapter:
    authority, country_code, name, allowed_domains = "XX1", "ES", "XX1", ("www.cnmv.es",)
    source_type = SourceType.OFFICIAL_OAM

    def __init__(self, **over):
        self.source_type = over.pop("adapter_source_type", SourceType.OFFICIAL_OAM)
        self.over = over

    def discover(self, request):
        from mod_01_ingestion.src.unified.models import DocumentCandidate
        base = dict(authority="XX1", country_code="ES", issuer_id="E1", fiscal_year=2023, doc_type="ANNUAL",
                    source_url="https://www.cnmv.es/a.pdf", source_type=SourceType.OFFICIAL_OAM)
        base.update(self.over)
        return [DocumentCandidate(**base)]

    def fetch_metadata(self, candidate):
        raise NotImplementedError


@pytest.mark.parametrize("over,why", [
    ({"authority": "OTRA"}, "autoridad"), ({"country_code": "FR"}, "país"),
    ({"source_url": "http://www.cnmv.es/a.pdf"}, "https"), ({"source_url": "https://evil.test/a.pdf"}, "allowed_domains"),
    ({"source_url": "https://www.cnmv.es.evil.test/a.pdf"}, "allowed_domains"),
    ({"source_type": None, "adapter_source_type": None}, "source_type")])
def test_router_rejects_candidates_that_break_the_common_contract(over, why):
    adapter = BadAdapter(**over)
    # se parte de un adapter coherente y el candidato que emite es el que incumple
    router = SourceRouter({"XX1": adapter})
    with pytest.raises(CandidateContractError) as ex:
        router.discover(DiscoveryRequest(authority="XX1"))
    assert why in str(ex.value)


# ================================================================= pipeline completo en SANDBOX
def test_candidates_travel_preflight_runner_cas_manifest_catalog_uow_and_telemetry(tmp_path):
    runner, http = sandbox(tmp_path)
    es_out, us_out = run_all(runner)
    assert [o.state for o in es_out + us_out] == ["COMPLETED", "COMPLETED"]
    assert (es_out[0].sha256, us_out[0].sha256) == (sha(ES_ZIP), sha(US_HTML))
    layout = runner.layout
    assert runner.catalog.count() == 2 and len(list(layout.manifests.rglob("*.json"))) == 2
    assert len([p for p in layout.cas.rglob("*") if p.is_file()]) == 2
    mans = {json.loads(p.read_text(encoding="utf-8"))["authority"]: json.loads(p.read_text(encoding="utf-8"))
            for p in layout.manifests.rglob("*.json")}
    assert mans["CNMV"]["source_url"] == ES_URL.split("?")[0] and mans["SEC"]["source_url"] == US_URL     # el manifiesto guarda la referencia estable
    assert mans["SEC"]["country_code"] == "US" and mans["CNMV"]["country_code"] == "ES"
    events = runner.telemetry.read_all()
    names = {e["event"] for e in events}
    assert {"PREFLIGHT_STARTED", "PREFLIGHT_PROCEED", "state_transition", "download_completed", "http_response"} <= names
    assert [e for e in events if e["event"] == "state_transition" and e.get("state") == "COMPLETED"]
    blob = json.dumps(events) + json.dumps(mans)
    for leak in ("SECRETTOKEN", "abc123", "access_token", "token=", "sig=", "#frag", "zzz"):
        assert leak not in blob, leak                                                           # sin query ni tokens
    assert UnifiedReconciler(layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    assert set(http.calls) == {"https://www.cnmv.es/pkg/san2023.zip", US_URL.split("?")[0]} and http.misses == []


def test_second_run_without_a_validator_is_idempotent_and_leaves_one_effect_per_document(tmp_path):
    runner, http = sandbox(tmp_path)
    run_all(runner)
    again = run_all(runner)
    assert [o.state for o in again[0] + again[1]] == ["COMPLETED", "COMPLETED"]               # re-descarga, el UoW no duplica
    assert runner.catalog.count() == 2 and len(list(runner.layout.manifests.rglob("*.json"))) == 2


def test_missing_identity_stays_slot_only_and_never_creates_version_state(tmp_path):
    runner, http = sandbox(tmp_path)
    run_all(runner)
    assert runner.versions.list_all_versions() == [] and not runner.layout.versions.exists()
    (c,) = runner.adapters["SEC"].discover(DiscoveryRequest(authority="SEC"))
    assert c.source_document_id and not resolve_identity(c.authority, c.document_id, c.identity_contract,
                                                         c.source_document_id).is_contracted


def test_an_approved_contract_gives_the_us_candidate_a_version_scoped_identity(tmp_path):
    ct = SourceIdentityContract(contract_id="sec-accession-synthetic", contract_version="1", authority="SEC",
                                namespace="sec-accession", id_scope=IdScope.VERSION,
                                initial_version_policy=InitialVersionPolicy.TRUST_FIRST_VALIDATED)
    router, *_ = build(tmp_path, identity_contract=ct)
    runner, http = sandbox(tmp_path, router=router)
    out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out.state == "COMPLETED" and out.version_status == "CURRENT"
    (v,) = runner.versions.list_all_versions()
    assert v["version_ref"].startswith("VR|") and v["source_document_id_raw"] == "0000320193-23-000106"
    again = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert again.state == "SKIPPED_ALREADY_PRESENT"                                            # id de versión persistido + blob íntegro


def test_authoritative_expected_sha256_enables_cas_reuse_without_transport(tmp_path):
    ct = SourceIdentityContract(contract_id="sec-synthetic", contract_version="1", authority="SEC", namespace="sec",
                                id_scope=IdScope.VERSION, expected_sha256_authority=True,
                                initial_version_policy=InitialVersionPolicy.TRUST_FIRST_VALIDATED)
    other = dict(US_RECORD, cik="789019", name="Otra Co", accessionNumber="0000789019-23-000050",
                 primaryDocument="otra-20230630.htm", sha256=sha(US_HTML))
    first = dict(US_RECORD, sha256=sha(US_HTML))
    router, *_ = build(tmp_path, us=[first, other], identity_contract=ct)
    other_url = "https://www.sec.gov/Archives/edgar/data/789019/000078901923000050/otra-20230630.htm"
    http = replay().add(other_url, b"CONTENIDO QUE NO DEBE DESCARGARSE", content_type="text/html")
    runner, _ = sandbox(tmp_path, router=router, http=http)
    outs = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes
    assert [o.state for o in outs] == ["COMPLETED", "COMPLETED"] and {o.sha256 for o in outs} == {sha(US_HTML)}
    assert other_url not in http.calls                                                          # la segunda NO tocó la red
    assert len([p for p in runner.layout.cas.rglob("*") if p.is_file()]) == 1                  # un blob compartido
    assert len(runner.versions.list_versions_by_sha256(sha(US_HTML))) == 2                      # dos identidades, sin fusionar
    assert any(e["event"] == "cas_reuse" for e in runner.telemetry.read_all())
    # sin la bandera de hash autoritativo NO hay reutilización: se descarga
    ct2 = dataclasses.replace(ct, expected_sha256_authority=False)
    b = sub(tmp_path, "b")
    router2, *_ = build(b, us=[first, other], identity_contract=ct2)
    http2 = replay().add(other_url, US_HTML, content_type="text/html")
    runner2, _ = sandbox(b, router=router2, http=http2)
    runner2.run_discovery(DiscoveryRequest(authority="SEC"))
    assert other_url in http2.calls


# ================================================================= fallos de adapter y de red: sin corrupción
def test_adapter_failures_do_not_corrupt_manifest_catalog_or_cas(tmp_path):
    router, es, us = build(tmp_path)
    runner, http = sandbox(tmp_path, router=router)
    real = es.fetch_metadata
    es.fetch_metadata = lambda c: (_ for _ in ()).throw(RuntimeError("adapter roto"))
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == "FAILED" and out.failure_stage == "ADAPTER" and "adapter roto" in out.message
    assert http.calls == [] and runner.catalog.count() == 0 and not list(runner.layout.manifests.rglob("*"))
    assert not [p for p in runner.layout.cas.rglob("*") if p.is_file()]
    es.fetch_metadata = real
    assert runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0].state == "COMPLETED"   # el run sigue sano
    us._providers = [lambda req: (_ for _ in ()).throw(OSError("fixture caído"))]
    before = runner.catalog.count()
    with pytest.raises(OSError):
        runner.run_discovery(DiscoveryRequest(authority="SEC"))
    assert runner.catalog.count() == before
    assert [e for e in runner.telemetry.read_all() if e["event"] == "adapter_discovery_failed"]
    assert UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile().clean


def test_replay_miss_or_foreign_host_is_a_network_failure_without_side_effects(tmp_path):
    http = ReplayHttp(["www.cnmv.es"]).add("https://www.cnmv.es/otra.zip", b"x")                 # la URL de la ficha no está registrada
    runner, _ = sandbox(tmp_path, http=http)
    es_out, us_out = run_all(runner)
    assert es_out[0].state == "FAILED" and es_out[0].error_class == "NETWORK"
    assert us_out[0].state == "FAILED" and us_out[0].error_class == "NETWORK"                    # www.sec.gov no permitido en este replay
    assert len(http.misses) >= 2 and runner.catalog.count() == 0
    assert not [p for p in runner.layout.raw.rglob("*") if p.is_file()]


# ================================================================= guardas del sandbox
def test_sandbox_refuses_live_pilot_operational_roots_and_real_http(tmp_path, monkeypatch):
    router, *_ = build(tmp_path)
    ops = tmp_path / "operativo"                                      # raíz "operativa" SINTÉTICA (nunca una ruta real de datos)
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(ops))
    for mode in (ExecutionMode.LIVE, ExecutionMode.PILOT):
        with pytest.raises(SandboxViolation):
            make_sandbox_runner(tmp_path / "r1", router, replay(), mode=mode)
    with pytest.raises(SandboxViolation):
        make_sandbox_runner(ops / "sandbox_u4", router, replay())
    assert not ops.exists()                                                                       # ni se intentó crear
    from mod_01_ingestion.src.unified.persistence_guard import is_operational_location
    assert is_operational_location("D:/ARGOS_DATA/cualquier/ruta")                              # solo evaluación de cadenas, sin disco
    with pytest.raises(SandboxViolation):
        make_sandbox_runner(tmp_path / "r2", router, object())
    from mod_01_ingestion.src.unified.models import RunContext
    with pytest.raises(SandboxViolation):
        make_sandbox_runner(tmp_path / "r3", router, replay(), run=RunContext(mode=ExecutionMode.LIVE))
    assert not (tmp_path / "r1").exists() and not (tmp_path / "r2").exists() and not (tmp_path / "r3").exists()


# ================================================================= evidencia de migración frente a legacy
def test_structured_comparison_with_legacy_records_is_evidence_only(tmp_path):
    runner, http = sandbox(tmp_path)
    es_cands = runner.adapters["CNMV"].discover(DiscoveryRequest(authority="CNMV"))
    us_cands = runner.adapters["SEC"].discover(DiscoveryRequest(authority="SEC"))
    es_out, us_out = run_all(runner)
    new_rows = [me.normalize_new(es_cands[0], es_out[0]), me.normalize_new(us_cands[0], us_out[0])]
    legacy = [{"source": "CNMV", "issuer_lei": "LEI_ES_1", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
               "sha256_hash": sha(ES_ZIP), "status": "RAW"},                                       # forma de legacy_bridge
              {"authority": "SEC", "issuer_id": "0000320193", "fiscal_year": 2023, "doc_type": "10-K", "sha256": "ab" * 32},
              {"source": "BAFIN", "issuer_lei": "X", "fiscal_year": 2022, "doc_type": "ANNUAL_REPORT"}]
    cmp = me.compare_with_legacy(new_rows, legacy)
    st = {i.key[0]: i for i in cmp.items}
    assert st["CNMV"].status == "MATCH" and st["SEC"].status == "DIFFERENT" and st["SEC"].differences == ("sha256",)
    assert st["BAFIN"].status == "ONLY_LEGACY" and cmp.summary == {"MATCH": 1, "DIFFERENT": 1, "ONLY_LEGACY": 1}
    assert not cmp.equivalent and json.loads(json.dumps(cmp.to_dict()))["summary"]["DIFFERENT"] == 1
    only_new = me.compare_with_legacy(new_rows, [])
    assert {i.status for i in only_new.items} == {"ONLY_NEW"}


def test_new_modules_respect_the_layering_and_never_import_legacy_runners():
    banned = ("descarga", "es_cnmv_client", "de_bafin_client", "robust_downloader", "legacy_bridge")
    for name in ("router.py", "sandbox_replay.py", "migration_evidence.py", "adapters/common.py", "adapters/replay.py",
                 "adapters/sec_edgar.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if any(b in m for b in banned)], (name, mods)
    for layer in ("domain", "application"):
        for f in (UNIFIED / layer).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            assert "unified.router" not in text and "sandbox_replay" not in text and "sec_edgar" not in text
