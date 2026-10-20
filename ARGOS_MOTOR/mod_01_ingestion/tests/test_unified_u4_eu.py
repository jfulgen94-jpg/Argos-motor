"""
U4 (DE + FR + IT + NL) — migración al pipeline unificado en SANDBOX/REPLAY. DE reutiliza el ``BaFinAdapter`` existente; FR, IT y
NL usan la base común nueva. Fixtures JSON, HTTP simulado (``ReplayHttp``), sockets bloqueados, todo bajo tmp_path y sin
contrato de identidad (todos los candidatos son ``SLOT_ONLY``). No se descarga nada real.
"""
import ast
import json
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified import migration_evidence as me
from mod_01_ingestion.src.unified.adapters.bafin import BaFinAdapter
from mod_01_ingestion.src.unified.adapters.common import CandidateContractError, assert_common_candidate
from mod_01_ingestion.src.unified.adapters.eu_oam import AFMAdapter, AMFAdapter, CONSOBAdapter
from mod_01_ingestion.src.unified.adapters.replay import ReplayLinkProvider
from mod_01_ingestion.src.unified.configured_adapter import configure_adapters
from mod_01_ingestion.src.unified.domain.enums import SourceType
from mod_01_ingestion.src.unified.domain.versions import resolve_identity
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.router import SourceRouter, UnroutableSourceError
from mod_01_ingestion.src.unified.sandbox_replay import ReplayHttp, make_sandbox_runner
from mod_01_ingestion.src.unified.source_adapter import get_adapter, registered_authorities
from mod_01_ingestion.src.unified.source_config import parse_source_configs
from mod_01_ingestion.tests.test_unified_ingest import make_pdf, make_zip
from mod_01_ingestion.tests.test_unified_u4_es_us import build as build_es_us, sha, sub, write_fixture

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
ZIP_DE, ZIP_IT = make_zip("DE-U4"), make_zip("IT-U4")           # bytes FIJOS por módulo (make_zip lleva marca de tiempo)
PDF_FR, PDF_NL = make_pdf(30), make_pdf(31)
DE_REC = {"lei": "DE_LEI_1", "ticker": "SAP", "name": "SAP SE", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
          "url": "https://filings.xbrl.org/pkg/sap2023.zip?token=DETOKEN&sig=de1#x"}
FR_REC = {"lei": "FR_LEI_1", "name": "Societe FR", "fiscal_year": 2023, "doc_type": "URD",
          "url": "https://bdif.amf-france.org/docs/urd2023.pdf?access_token=FRTOKEN",
          "page_url": "https://bdif.amf-france.org/fiche?sid=SESSION1"}
IT_REC = {"isin": "IT0000000001", "name": "Societa IT", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
          "url": "https://www.consob.it/pkg/it2023.zip?key=ITKEY"}
NL_REC = {"ticker": "NLCO", "name": "NL Co", "fiscal_year": 2023, "doc_type": "ANNUAL_REPORT",
          "url": "https://www.afm.nl/docs/ar2023.pdf?password=NLPASS"}
SECRETS = ("DETOKEN", "FRTOKEN", "SESSION1", "ITKEY", "NLPASS", "token=", "sig=", "key=", "password=", "sid=")
PAYLOADS = {"BAFIN": ("https://filings.xbrl.org/pkg/sap2023.zip", ZIP_DE, "application/zip"),
            "AMF": ("https://bdif.amf-france.org/docs/urd2023.pdf", PDF_FR, "application/pdf"),
            "CONSOB": ("https://www.consob.it/pkg/it2023.zip", ZIP_IT, "application/zip"),
            "AFM": ("https://www.afm.nl/docs/ar2023.pdf", PDF_NL, "application/pdf")}
HOSTS = ["filings.xbrl.org", "bdif.amf-france.org", "www.consob.it", "www.afm.nl"]


def adapters4(tmp_path, de=(DE_REC,), fr=(FR_REC,), it=(IT_REC,), nl=(NL_REC,)):
    prov = lambda name, recs: ReplayLinkProvider(write_fixture(tmp_path, name, list(recs)))
    return {"BAFIN": BaFinAdapter([prov("de", de)]), "AMF": AMFAdapter(prov("fr", fr)),
            "CONSOB": CONSOBAdapter(prov("it", it)), "AFM": AFMAdapter(prov("nl", nl))}


def replay4():
    http = ReplayHttp(HOSTS)
    for url, data, ctype in PAYLOADS.values():
        http.add(url, data, content_type=ctype)
    return http


def sandbox4(tmp_path, adapters=None, http=None, **kw):
    router = SourceRouter(adapters or adapters4(tmp_path))
    http = http or replay4()
    return make_sandbox_runner(tmp_path / "root", router, http, **kw), http


def run_each(runner, authorities=("BAFIN", "AMF", "CONSOB", "AFM")):
    return {a: runner.run_discovery(DiscoveryRequest(authority=a)).outcomes[0] for a in authorities}


# ================================================================= adapters -> candidato común
@pytest.mark.parametrize("authority,country,fy_doc,issuer,source_url", [
    ("BAFIN", "DE", "ESEF_PACKAGE", "DE_LEI_1", "https://filings.xbrl.org/pkg/sap2023.zip"),
    ("AMF", "FR", "URD", "FR_LEI_1", "https://bdif.amf-france.org/docs/urd2023.pdf"),
    ("CONSOB", "IT", "ESEF_PACKAGE", "IT0000000001", "https://www.consob.it/pkg/it2023.zip"),
    ("AFM", "NL", "ANNUAL_REPORT", "NLCO", "https://www.afm.nl/docs/ar2023.pdf")])
def test_each_adapter_produces_the_common_candidate_from_a_replay_fixture(tmp_path, authority, country, fy_doc, issuer, source_url):
    ads = adapters4(tmp_path)
    router = SourceRouter(ads)
    (c,) = router.discover(DiscoveryRequest(authority=authority))
    assert (c.authority, c.country_code, c.source, c.doc_type, c.fiscal_year) == (authority, country, authority, fy_doc, 2023)
    assert c.issuer_id == issuer and c.source_url == source_url
    assert c.source_type is SourceType.OFFICIAL_INDEX and "?" not in c.source_url and "#" not in c.source_url
    assert c.identity_contract is None and not resolve_identity(c.authority, c.document_id, None, c.source_document_id).is_contracted
    assert_common_candidate(c, authority=authority, country_code=country, allowed_domains=ads[authority].allowed_domains)
    if authority == "AMF":
        assert c.source_page_url == "https://bdif.amf-france.org/fiche"


def test_new_adapters_reject_bad_records_with_a_reason_instead_of_aborting(tmp_path):
    bad = [dict(FR_REC, lei=None, ticker=None, isin=None), dict(FR_REC, doc_type="XYZ"), dict(FR_REC, fiscal_year="n/a"),
           dict(FR_REC, url="ftp://bdif.amf-france.org/x.pdf"), dict(FR_REC, doc_type="  ")]
    ads = adapters4(tmp_path, fr=[FR_REC] + bad)
    cands = ads["AMF"].discover(DiscoveryRequest(authority="AMF"))
    assert len(cands) == 1
    assert sorted(why for _, why in ads["AMF"].rejected) == sorted([
        "sin identificador de emisor (lei/isin/ticker)", "tipo documental no aceptado: XYZ", "ejercicio fiscal no determinable",
        "candidato inválido: InvalidCandidateError", "tipo documental no aceptado: ?"])
    assert all("token" not in ref for ref, _ in ads["AMF"].rejected)


def test_each_authority_only_returns_its_own_candidates_and_the_registry_knows_all_of_them(tmp_path):
    router = SourceRouter(adapters4(tmp_path))
    for a, country in (("BAFIN", "DE"), ("AMF", "FR"), ("CONSOB", "IT"), ("AFM", "NL")):
        cands = router.discover(DiscoveryRequest(authority=a))
        assert {c.authority for c in cands} == {a} and {c.country_code for c in cands} == {country}
    assert {"BAFIN", "AMF", "CONSOB", "AFM"} <= set(registered_authorities())
    for a in ("AMF", "CONSOB", "AFM"):
        assert get_adapter(a).authority == a


# ================================================================= router ampliado
def test_router_selects_the_right_adapter_for_all_six_authorities_and_rejects_ambiguity(tmp_path):
    es_us_router, es, us = build_es_us(sub(tmp_path, "esus"))
    ads = adapters4(tmp_path)
    router = SourceRouter({**ads, "CNMV": es, "SEC": us})
    assert router.authorities() == sorted(["AFM", "AMF", "BAFIN", "CNMV", "CONSOB", "SEC"])
    for country, authority in (("DE", "BAFIN"), ("FR", "AMF"), ("IT", "CONSOB"), ("NL", "AFM"), ("ES", "CNMV"), ("US", "SEC")):
        assert router.route(country_code=country.lower()).authority == authority
        assert router.route(authority=authority.lower()) is router.route(authority=authority)
    for kw in ({"authority": "FCA"}, {"country_code": "PT"}, {}):
        with pytest.raises(UnroutableSourceError):
            router.route(**kw)
    twin = AMFAdapter([])
    twin.authority, twin.country_code = "AMF2", "DE"
    amb = SourceRouter({**ads, "AMF2": twin})
    with pytest.raises(UnroutableSourceError):
        amb.route(country_code="DE")                                                       # dos adapters DE: exige autoridad
    assert amb.route(authority="AMF2") is twin
    with pytest.raises(UnroutableSourceError):
        SourceRouter({"FR": ads["AMF"]})                                                    # clave distinta de la autoridad
    with pytest.raises(UnroutableSourceError):
        SourceRouter({"AMF": ads["AMF"], "amf": ads["AMF"]})                                # autoridad duplicada


def test_router_order_is_independent_of_the_provider_order(tmp_path):
    recs = [dict(NL_REC, ticker=t, url=f"https://www.afm.nl/docs/{t}.pdf") for t in ("ZZ", "AA", "MM")]
    a = SourceRouter({"AFM": AFMAdapter(ReplayLinkProvider(write_fixture(sub(tmp_path, "a"), "nl", recs)))})
    b = SourceRouter({"AFM": AFMAdapter(ReplayLinkProvider(write_fixture(sub(tmp_path, "b"), "nl", recs[::-1])))})
    assert [c.issuer_id for c in a.discover(DiscoveryRequest(authority="AFM"))] == ["AA", "MM", "ZZ"] \
        == [c.issuer_id for c in b.discover(DiscoveryRequest(authority="AFM"))]


def test_router_rejects_a_candidate_on_a_host_outside_the_adapter_domains(tmp_path):
    ads = adapters4(tmp_path, fr=[dict(FR_REC, url="https://evil.test/docs/urd2023.pdf")])
    with pytest.raises(CandidateContractError):
        SourceRouter(ads).discover(DiscoveryRequest(authority="AMF"))


# ================================================================= pipeline completo en SANDBOX
def test_candidates_of_all_four_countries_travel_the_whole_unified_pipeline(tmp_path):
    runner, http = sandbox4(tmp_path)
    outs = run_each(runner)
    assert {a: o.state for a, o in outs.items()} == {"BAFIN": "COMPLETED", "AMF": "COMPLETED", "CONSOB": "COMPLETED",
                                                     "AFM": "COMPLETED"}
    assert {a: o.sha256 for a, o in outs.items()} == {a: sha(v[1]) for a, v in PAYLOADS.items()}
    layout = runner.layout
    assert runner.catalog.count() == 4 and len(list(layout.manifests.rglob("*.json"))) == 4
    assert len([p for p in layout.cas.rglob("*") if p.is_file()]) == 4 and len([p for p in layout.raw.rglob("*") if p.is_file()]) == 4
    mans = {m["authority"]: m for m in (json.loads(p.read_text(encoding="utf-8")) for p in layout.manifests.rglob("*.json"))}
    assert {a: m["country_code"] for a, m in mans.items()} == {"BAFIN": "DE", "AMF": "FR", "CONSOB": "IT", "AFM": "NL"}
    assert all(m["source_url"] == PAYLOADS[a][0] for a, m in mans.items())                 # URL saneada en el manifiesto
    names = {e["event"] for e in runner.telemetry.read_all()}
    assert {"PREFLIGHT_STARTED", "PREFLIGHT_PROCEED", "state_transition", "download_completed"} <= names
    assert UnifiedReconciler(layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    assert set(http.calls) == {v[0] for v in PAYLOADS.values()} and http.misses == []


def test_without_an_approved_contract_every_new_candidate_is_slot_only_and_no_version_state_exists(tmp_path):
    runner, http = sandbox4(tmp_path)
    run_each(runner)
    assert runner.versions.list_all_versions() == [] and not runner.layout.versions.exists()
    for a in ("BAFIN", "AMF", "CONSOB", "AFM"):
        (c,) = runner.adapters[a].discover(DiscoveryRequest(authority=a))
        assert c.identity_contract is None


def test_second_run_is_idempotent_for_all_four_countries(tmp_path):
    runner, http = sandbox4(tmp_path)
    run_each(runner)
    manifests = sorted(p.read_bytes() for p in runner.layout.manifests.rglob("*.json"))
    again = run_each(runner)
    assert {o.state for o in again.values()} == {"COMPLETED"}                                # re-descarga: el UoW no duplica nada
    assert runner.catalog.count() == 4 and sorted(p.read_bytes() for p in runner.layout.manifests.rglob("*.json")) == manifests
    assert len([p for p in runner.layout.raw.rglob("*") if p.is_file()]) == 4


def test_a_failing_adapter_does_not_corrupt_manifest_catalog_or_cas_and_the_others_keep_working(tmp_path):
    ads = adapters4(tmp_path)
    runner, http = sandbox4(tmp_path, adapters=ads)
    ads["AMF"].fetch_metadata = lambda c: (_ for _ in ()).throw(RuntimeError("AMF roto"))
    fr = runner.run_discovery(DiscoveryRequest(authority="AMF")).outcomes[0]
    assert fr.state == "FAILED" and fr.failure_stage == "ADAPTER" and "AMF roto" in fr.message
    assert runner.catalog.count() == 0 and not list(runner.layout.manifests.rglob("*.json"))
    assert not [p for p in runner.layout.cas.rglob("*") if p.is_file()] and not any("amf-france" in c for c in http.calls)
    assert runner.run_discovery(DiscoveryRequest(authority="BAFIN")).outcomes[0].state == "COMPLETED"
    ads["CONSOB"]._providers = [lambda req: (_ for _ in ()).throw(OSError("fixture IT caído"))]
    before = runner.catalog.count()
    with pytest.raises(OSError):
        runner.run_discovery(DiscoveryRequest(authority="CONSOB"))
    assert runner.catalog.count() == before
    assert [e for e in runner.telemetry.read_all() if e["event"] == "adapter_discovery_failed"]
    assert UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile().clean


def test_telemetry_and_manifests_carry_no_query_strings_or_tokens(tmp_path):
    runner, http = sandbox4(tmp_path)
    run_each(runner)
    blob = json.dumps(runner.telemetry.read_all()) + "".join(
        p.read_text(encoding="utf-8") for p in runner.layout.manifests.rglob("*.json"))
    for leak in SECRETS:
        assert leak not in blob, leak
    assert "?" not in json.dumps([e.get("url") for e in runner.telemetry.read_all() if e.get("url")])


def test_replay_miss_in_one_country_is_a_network_failure_without_side_effects(tmp_path):
    http = ReplayHttp(HOSTS).add(*PAYLOADS["BAFIN"][:2], content_type="application/zip")        # solo DE está registrado
    runner, _ = sandbox4(tmp_path, http=http)
    outs = run_each(runner)
    assert outs["BAFIN"].state == "COMPLETED"
    assert {outs[a].error_class for a in ("AMF", "CONSOB", "AFM")} == {"NETWORK"}
    assert runner.catalog.count() == 1 and len(http.misses) >= 3


def test_configured_sources_apply_user_agent_domains_and_limits_to_the_four_countries(tmp_path):
    def src(auth, country, domains):
        return {"source_id": f"{auth.lower()}_sandbox", "authority": auth, "country_code": country, "allowed_domains": domains,
                "user_agent": "STATER-Sandbox/1.0", "contact": "data-ops@stater-sandbox.test", "timeout_s": 9}
    cfg = parse_source_configs({"schema_version": "1", "config_version": "2026-10-sandbox", "sources": [
        src("BAFIN", "DE", ["filings.xbrl.org"]), src("AMF", "FR", ["bdif.amf-france.org"]),
        src("CONSOB", "IT", ["www.consob.it"]), src("AFM", "NL", ["www.afm.nl"])]})
    runner, http = sandbox4(tmp_path, adapters=configure_adapters(adapters4(tmp_path), cfg))
    assert {o.state for o in run_each(runner).values()} == {"COMPLETED"}
    assert {r["headers"]["user-agent"] for r in http.requests} == {"STATER-Sandbox/1.0 (data-ops@stater-sandbox.test)"}
    assert {r["timeout"]["read"] for r in http.requests} == {9.0}


# ================================================================= evidencia de migración frente a legacy
def test_structured_legacy_comparison_across_the_four_countries_is_evidence_only(tmp_path):
    runner, http = sandbox4(tmp_path)
    cands = {a: runner.adapters[a].discover(DiscoveryRequest(authority=a))[0] for a in PAYLOADS}
    outs = run_each(runner)
    rows = [me.normalize_new(cands[a], outs[a]) for a in PAYLOADS]
    legacy = [{"source": "BAFIN", "issuer_lei": "DE_LEI_1", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
               "sha256_hash": sha(ZIP_DE)},                                                    # coincide
              {"authority": "AMF", "issuer_id": "FR_LEI_1", "fiscal_year": 2023, "doc_type": "URD", "sha256": "ab" * 32},
              {"source": "CONSOB", "issuer_id": "IT0000000001", "fiscal_year": 2022, "doc_type": "RFA"}]   # otro ejercicio/tipo
    cmp = me.compare_with_legacy(rows, legacy)
    by = {(i.key[0], i.key[2]): i.status for i in cmp.items}
    assert by[("BAFIN", 2023)] == "MATCH" and by[("AMF", 2023)] == "DIFFERENT"
    assert by[("CONSOB", 2023)] == "ONLY_NEW" and by[("CONSOB", 2022)] == "ONLY_LEGACY" and by[("AFM", 2023)] == "ONLY_NEW"
    assert cmp.summary == {"MATCH": 1, "DIFFERENT": 1, "ONLY_NEW": 2, "ONLY_LEGACY": 1} and not cmp.equivalent
    json.dumps(cmp.to_dict())


def test_new_adapter_modules_respect_the_layering_and_never_import_legacy_code():
    banned = ("descarga", "es_cnmv_client", "de_bafin_client", "robust_downloader", "legacy_bridge")
    for name in ("adapters/standard.py", "adapters/eu_oam.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if any(b in m for b in banned)], (name, mods)
        assert not [m for m in mods if m.split(".")[-1] in ("cas_store", "repositories")]
    for layer in ("domain", "application"):
        for f in (UNIFIED / layer).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            assert "eu_oam" not in text and "adapters.standard" not in text
