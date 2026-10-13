"""
U4 — Configuración versionada por fuente y contratos de identidad cargables. TODO sintético: ningún valor describe a CNMV ni a
la SEC reales (dominios aparte), ningún contrato real se activa, y no hay red (replay) ni datos operativos.
"""
import ast
import copy
import dataclasses
import json
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.configured_adapter import ConfiguredAdapter, configure_adapters
from mod_01_ingestion.src.unified.domain.enums import PreflightStatus as S
from mod_01_ingestion.src.unified.domain.versions import EvidenceKind, IdScope, RepublicationEvidence
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.router import SourceRouter
from mod_01_ingestion.src.unified.sandbox_replay import ReplayHttp, make_sandbox_runner
from mod_01_ingestion.src.unified.source_config import ConfigError, load_source_configs, parse_source_configs
from mod_01_ingestion.tests.test_unified_u4_es_us import ES_RECORD, US_HTML, US_URL, build, replay
from mod_01_ingestion.tests.test_unified_versions import Env, cand

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
ES_DOMAINS, US_DOMAINS = ["www.cnmv.es", "cnmv.es"], ["www.sec.gov", "sec.gov"]


def source(authority, country, domains, **over):
    d = {"source_id": f"{authority.lower()}_sandbox", "authority": authority, "country_code": country,
         "allowed_domains": list(domains), "user_agent": "STATER-Sandbox/1.0", "contact": "data-ops@stater-sandbox.test",
         "rate": {"min_interval_s": 2.0, "max_concurrent": 1}, "timeout_s": 7, "max_bytes": 5_000_000, "max_total_s": 120,
         "retries": {"max_retries": 2, "retry_statuses": [403]}}
    d.update(over)
    return d


def config(*sources, **top):
    d = {"schema_version": "1", "config_version": "2026-10-sandbox",
         "sources": list(sources) or [source("CNMV", "ES", ES_DOMAINS), source("SEC", "US", US_DOMAINS)]}
    d.update(top)
    return d


def contract_dict(**over):
    d = {"contract_id": "synthetic-sec-accession", "contract_version": "1", "namespace": "synthetic-ns", "id_scope": "VERSION",
         "initial_version_policy": "TRUST_FIRST_VALIDATED", "allowed_evidence_kinds": ["REVISION_NUMBER"],
         "expected_sha256_authority": False, "approval": {"status": "APPROVED", "ref": "SYNTHETIC-TEST-APPROVAL"}}
    d.update(over)
    return d


# ================================================================= configuración válida / inválida
def test_valid_config_parses_with_defaults_derived_values_and_no_active_contract():
    cs = parse_source_configs(config())
    sec = cs.get("sec")
    assert cs.config_version == "2026-10-sandbox" and [s.authority for s in cs.sources] == ["CNMV", "SEC"]
    assert sec.allowed_domains == ("www.sec.gov", "sec.gov") and sec.timeout_s == 7.0 and sec.max_bytes == 5_000_000
    assert sec.effective_user_agent == "STATER-Sandbox/1.0 (data-ops@stater-sandbox.test)"
    assert sec.retry_statuses == (403,) and sec.max_retries == 2 and sec.contract is None and sec.contract_status == "NONE"
    assert cs.rate_overrides()["www.sec.gov"] == {"max_concurrent": 1, "min_interval_s": 2.0}
    minimal = parse_source_configs(config(source("CNMV", "ES", ES_DOMAINS, rate={}, retries={}, timeout_s=60)))
    assert minimal.sources[0].max_retries == 4 and minimal.sources[0].retry_statuses == ()


def mutate(path, value):
    """Devuelve una copia de la configuración válida con ``path`` (p. ej. 'sources.0.timeout_s') sustituido; ``DEL`` borra."""
    d = copy.deepcopy(config())
    cur = d
    keys = path.split(".")
    for k in keys[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = keys[-1]
    if isinstance(value, str) and value == "DEL":
        cur.pop(last)
    elif isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value
    return d


INVALID = [
    ("schema_version", "2"), ("config_version", "DEL"), ("config_version", " "), ("sources", []), ("sources", "x"), ("extra", 1),
    ("sources.0.alowed_domains", ["x.es"]),                                              # clave desconocida (typo)
    ("sources.0.source_id", "UPPER"), ("sources.0.source_id", "x"), ("sources.0.country_code", "ESP"),
    ("sources.0.authority", ""), ("sources.0.allowed_domains", []), ("sources.0.allowed_domains", "cnmv.es"),
    ("sources.0.allowed_domains", ["*.cnmv.es"]), ("sources.0.allowed_domains", ["https://www.cnmv.es"]),
    ("sources.0.allowed_domains", ["WWW.CNMV.ES"]), ("sources.0.allowed_domains", ["www.cnmv.es:8443"]),
    ("sources.0.user_agent", "DEL"), ("sources.0.user_agent", "a\nb"), ("sources.0.user_agent", "x" * 201),
    ("sources.0.user_agent", "Bearer abcdefghijklmnop"), ("sources.0.contact", "DEL"), ("sources.0.contact", "no-es-correo"),
    ("sources.0.contact", "yo@example.com"), ("sources.0.contact", "todo@stater-sandbox.test"),
    ("sources.0.contact", "https://user:pw@stater-sandbox.test/c"),
    ("sources.0.timeout_s", 0), ("sources.0.timeout_s", 601), ("sources.0.timeout_s", True), ("sources.0.timeout_s", "7"),
    ("sources.0.max_bytes", 0), ("sources.0.max_bytes", 1.5), ("sources.0.max_bytes", 5 * 1024 ** 3),
    ("sources.0.max_total_s", 0), ("sources.0.max_total_s", 90000),
    ("sources.0.rate.max_concurrent", 0), ("sources.0.rate.min_interval_s", -1), ("sources.0.rate.burst", 3),
    ("sources.0.retries.max_retries", -1), ("sources.0.retries.max_retries", 11),
    ("sources.0.retries.retry_statuses", [200]), ("sources.0.retries.retry_statuses", [True]),
    ("sources.0.retries.retry_statuses", ["403"]), ("sources.0.retries.retry_statuses", "403"),
    ("sources.0.rate.cookie", "x"), ("sources.0.password", "x"),                         # credenciales en claves
    ("sources.0.user_agent", "ruta D:/ARGOS_DATA/secreto"), ("sources.0.contact", "/etc/passwd"),   # rutas operativas
]


@pytest.mark.parametrize("path,value", INVALID)
def test_invalid_config_fails_closed(path, value):
    with pytest.raises(ConfigError):
        parse_source_configs(mutate(path, value))


def test_duplicates_and_conflicting_rates_are_rejected():
    a, b = source("CNMV", "ES", ES_DOMAINS), source("SEC", "US", US_DOMAINS)
    with pytest.raises(ConfigError):
        parse_source_configs(config(a, dict(b, source_id="cnmv_sandbox")))
    with pytest.raises(ConfigError):
        parse_source_configs(config(a, dict(b, authority="CNMV", source_id="otra")))
    with pytest.raises(ConfigError):
        parse_source_configs(config(a, source("X", "US", ["cnmv.es"], rate={"min_interval_s": 9.0, "max_concurrent": 1})))


def test_loading_from_files_is_fail_closed_and_refuses_operational_locations(tmp_path, monkeypatch):
    good = tmp_path / "sources.json"
    good.write_text(json.dumps(config()), encoding="utf-8")
    assert len(load_source_configs(good).sources) == 2
    for name, text in (("bad.json", "{no es json"), ("big.json", " " * ((1 << 20) + 5))):
        (tmp_path / name).write_text(text, encoding="utf-8")
        with pytest.raises(ConfigError):
            load_source_configs(tmp_path / name)
    with pytest.raises(ConfigError):
        load_source_configs(tmp_path / "no_existe.json")
    ops = tmp_path / "operativo"
    ops.mkdir()
    (ops / "sources.json").write_text(json.dumps(config()), encoding="utf-8")
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(ops))
    with pytest.raises(ConfigError):
        load_source_configs(ops / "sources.json")


# ================================================================= contratos de identidad desde configuración
def test_contract_requires_version_known_scope_and_approval_to_be_active():
    for bad in ({"contract_version": ""}, {"contract_version": None}, {"id_scope": "GLOBAL"}, {"normalizer_version": "v9"},
                {"allowed_evidence_kinds": ["INVENTADA"]}, {"initial_version_policy": "REQUIRE_AUTHORITATIVE_HASH"},
                {"approval": {"status": "APPROVED", "ref": "x", "firmado": True}}, {"namespace": ""}, {"extra": 1}):
        with pytest.raises(ConfigError):
            parse_source_configs(config(source("SEC", "US", US_DOMAINS, identity_contract=contract_dict(**bad))))
    c_ok = parse_source_configs(config(source("SEC", "US", US_DOMAINS, identity_contract=contract_dict()))).get("SEC")
    assert c_ok.contract_status == "ACTIVE" and c_ok.contract.id_scope is IdScope.VERSION
    assert c_ok.contract.authority == "SEC" and c_ok.contract.contract_version == "1"
    for approval in ({}, {"status": "PENDING", "ref": "x"}, {"status": "APPROVED", "ref": ""}, {"status": "APPROVED"}):
        pend = parse_source_configs(config(source("SEC", "US", US_DOMAINS, identity_contract=contract_dict(approval=approval))))
        assert pend.get("SEC").contract is None and pend.get("SEC").contract_status == "PENDING_APPROVAL"    # declarado != activo


def router_for(tmp_path, cfg_dict, **build_kw):
    router, es, us = build(tmp_path, **build_kw)
    configs = parse_source_configs(cfg_dict)
    adapters = configure_adapters({"CNMV": es, "SEC": us}, configs)
    return SourceRouter(adapters), adapters, configs


def run_sec(tmp_path, cfg_dict, http=None, **kw):
    router, adapters, configs = router_for(tmp_path, cfg_dict)
    http = http or replay()
    runner = make_sandbox_runner(tmp_path / "root", router, http, **kw)
    return runner, http, adapters


def test_without_an_approved_contract_the_identity_is_slot_only(tmp_path):
    for label, src in (("sin", source("SEC", "US", US_DOMAINS)),
                       ("pendiente", source("SEC", "US", US_DOMAINS, identity_contract=contract_dict(approval={"status": "PENDING", "ref": "x"})))):
        d = tmp_path / label
        d.mkdir()
        runner, http, adapters = run_sec(d, config(source("CNMV", "ES", ES_DOMAINS), src))
        out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
        assert out.state == "COMPLETED" and out.version_status is None
        assert runner.versions.list_all_versions() == [] and not runner.layout.versions.exists()
        (c,) = runner.adapters["SEC"].discover(DiscoveryRequest(authority="SEC"))
        assert c.identity_contract is None and c.source_document_id            # el id viaja como metadato, sin autoridad


def test_es_candidates_without_a_source_id_stay_slot_only_even_with_an_approved_contract(tmp_path):
    cfg = config(source("CNMV", "ES", ES_DOMAINS, identity_contract=contract_dict(id_scope="LOGICAL_DOCUMENT")),
                 source("SEC", "US", US_DOMAINS))
    router, adapters, _ = router_for(tmp_path, cfg)
    (c,) = router.discover(DiscoveryRequest(authority="CNMV"))
    assert c.identity_contract is None and c.source_document_id is None         # nada que contratar: no se inventa un id


@pytest.mark.parametrize("scope,second_run_state", [("VERSION", "SKIPPED_ALREADY_PRESENT"), ("LOGICAL_DOCUMENT", "COMPLETED")])
def test_synthetic_version_and_logical_contracts_behave_differently_on_a_rerun(tmp_path, scope, second_run_state):
    cfg = config(source("CNMV", "ES", ES_DOMAINS),
                 source("SEC", "US", US_DOMAINS, identity_contract=contract_dict(id_scope=scope)))
    runner, http, _ = run_sec(tmp_path, cfg)
    first = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert first.state == "COMPLETED" and first.version_status == "CURRENT"
    n = len(http.calls)
    second = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert second.state == second_run_state
    assert len(http.calls) == n + (0 if second_run_state.startswith("SKIPPED") else 1)       # LOGICAL nunca salta por el id solo
    (v,) = runner.versions.list_all_versions()
    assert v["contract_id"] == "synthetic-sec-accession" and v["normalizer_version"] == "v1"


def test_changing_the_contract_version_or_the_stored_normalizer_requires_manual_review_without_download(tmp_path):
    cfg1 = config(source("CNMV", "ES", ES_DOMAINS), source("SEC", "US", US_DOMAINS, identity_contract=contract_dict()))
    runner, http, _ = run_sec(tmp_path, cfg1)
    assert runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0].state == "COMPLETED"
    n = len(http.calls)
    cfg2 = config(source("CNMV", "ES", ES_DOMAINS),
                  source("SEC", "US", US_DOMAINS, identity_contract=contract_dict(contract_version="2")))
    runner2, _, _ = run_sec(tmp_path, cfg2, http=http)
    out = runner2.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out.state == "MANUAL_REVIEW" and out.needs_manual_review and len(http.calls) == n
    ev = [e for e in runner2.telemetry.read_all() if e["event"] == "PREFLIGHT_MANUAL_REVIEW"][-1]
    assert ev["reason_code"] == "IDENTITY_POLICY_VERSION_MISMATCH"
    # normalizador registrado distinto del vigente (tabla Y sidecar coherentes entre sí)
    (v,) = runner.versions.list_all_versions()
    with runner.versions._connect() as con:
        con.execute("UPDATE unified_document_versions SET normalizer_version = 'v0'")
    side = runner.versions.sidecar_path(v["identity_key"], v["sha256"])
    data = json.loads(side.read_text(encoding="utf-8"))
    data["facts"]["normalizer_version"] = "v0"
    side.write_text(json.dumps(data), encoding="utf-8")
    runner3, _, _ = run_sec(tmp_path, cfg1, http=http)
    out3 = runner3.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out3.state == "MANUAL_REVIEW" and len(http.calls) == n


def test_evidence_not_allowed_by_the_configured_contract_does_not_confirm_a_republication(tmp_path):
    ct = parse_source_configs(config(source("CNMV", "ES", ES_DOMAINS, identity_contract=contract_dict(
        contract_id="synthetic-es", id_scope="LOGICAL_DOCUMENT")), source("SEC", "US", US_DOMAINS))).get("CNMV").contract
    env = Env(tmp_path)
    sha_a = env.put_blob(b"A" * 300)
    base = cand(identity_contract=ct, source_document_id="DOC-1")
    env.register(base, "DOC-1", sha_a, revision=1)
    new = dict(expected_sha256="cd" * 32, source_revision=2)
    allowed = RepublicationEvidence(EvidenceKind.REVISION_NUMBER, "2", "synthetic-es", "1")
    not_allowed = RepublicationEvidence(EvidenceKind.SUPERSEDES_REF, "x", "synthetic-es", "1")
    assert env.run(dataclasses.replace(base, republication_evidence=allowed, **new)).status is S.REPUBLICATION_CONFIRMED
    assert env.run(dataclasses.replace(base, republication_evidence=not_allowed, **new)).status is S.POSSIBLE_REPUBLICATION


# ================================================================= dominios, User-Agent y límites aplicados
def test_config_can_only_narrow_the_domains_the_adapter_declares(tmp_path):
    router, es, us = build(tmp_path)
    cs = parse_source_configs(config())
    with pytest.raises(ConfigError):
        ConfiguredAdapter(us, parse_source_configs(config(source("SEC", "US", ["www.sec.gov", "otro.sec.gov"]))).get("SEC"))
    with pytest.raises(ConfigError):
        ConfiguredAdapter(es, cs.get("SEC"))                                           # autoridad/país que no corresponden
    with pytest.raises(ConfigError):
        configure_adapters({"CNMV": es}, cs)                                           # configuración sin adapter: no se ignora
    narrowed = ConfiguredAdapter(us, parse_source_configs(config(source("SEC", "US", ["www.sec.gov"]))).get("SEC"))
    assert narrowed.allowed_domains == ("www.sec.gov",) and us.allowed_domains == ("www.sec.gov", "sec.gov")


def test_narrowed_domains_make_the_router_reject_candidates_on_the_dropped_host(tmp_path):
    rec = dict(ES_RECORD, url="https://cnmv.es/pkg/san2023.zip")                        # válido para el adapter, no para la config
    cfg = config(source("CNMV", "ES", ["www.cnmv.es"]), source("SEC", "US", US_DOMAINS))
    router, adapters, _ = router_for(tmp_path, cfg, es=[rec])
    from mod_01_ingestion.src.unified.adapters.common import CandidateContractError
    with pytest.raises(CandidateContractError):
        router.discover(DiscoveryRequest(authority="CNMV"))


def test_user_agent_timeout_and_limits_reach_the_simulated_http(tmp_path):
    runner, http, adapters = run_sec(tmp_path, config())
    runner.run_discovery(DiscoveryRequest(authority="SEC"))
    (req,) = [r for r in http.requests if r["url"] == US_URL]
    assert req["headers"]["user-agent"] == "STATER-Sandbox/1.0 (data-ops@stater-sandbox.test)"
    assert req["timeout"]["read"] == 7.0 and req["timeout"]["connect"] == 7.0
    (c,) = adapters["SEC"].discover(DiscoveryRequest(authority="SEC"))
    meta = adapters["SEC"].fetch_metadata(c)
    d = adapters["SEC"].build_download_request(c, meta, tmp_path / "stg")
    assert (d.timeout_s, d.max_total_s, d.max_retries, d.retry_statuses, d.max_bytes) == (7, 120, 2, [403], 5_000_000)
    assert d.allowed_domains == ["www.sec.gov", "sec.gov"] and d.headers["User-Agent"].startswith("STATER-Sandbox/1.0")


def test_max_bytes_from_config_is_enforced(tmp_path):
    cfg = config(source("CNMV", "ES", ES_DOMAINS), source("SEC", "US", US_DOMAINS, max_bytes=1000))
    http = replay()
    runner, _, _ = run_sec(tmp_path, cfg, http=http)
    out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out.state == "FAILED" and out.error_class == "SIZE_EXCEEDED" and runner.catalog.count() == 0


def test_retry_policy_from_config_403_is_retried_only_when_configured(tmp_path):
    for statuses, expected_calls, klass in (([403], 3, "HTTP_TRANSIENT"), ([], 1, "HTTP_PERMANENT")):
        d = tmp_path / f"r{len(statuses)}"
        d.mkdir()
        cfg = config(source("CNMV", "ES", ES_DOMAINS),
                     source("SEC", "US", US_DOMAINS, retries={"max_retries": 2, "retry_statuses": statuses}))
        http = ReplayHttp(["www.cnmv.es", "www.sec.gov"]).add(US_URL, b"", status=403)
        runner, _, _ = run_sec(d, cfg, http=http)
        out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
        assert out.state == "FAILED" and out.error_class == klass and http.calls.count(US_URL) == expected_calls


def test_redirects_outside_the_configured_domains_are_refused(tmp_path):
    http = ReplayHttp(["www.cnmv.es", "www.sec.gov", "otro.test"]).add(
        US_URL, b"", status=302, headers={"location": "https://otro.test/x.htm"}).add("https://otro.test/x.htm", US_HTML)
    runner, _, _ = run_sec(tmp_path, config(), http=http)
    out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out.state == "FAILED" and out.error_class == "REDIRECT_NOT_ALLOWED" and runner.catalog.count() == 0


def test_configured_rate_overrides_drive_the_domain_rate_limiter():
    cs = parse_source_configs(config())
    now, waits = [0.0], []
    rl = DomainRateLimiter(overrides=cs.rate_overrides(), clock=lambda: now[0], sleep=waits.append)
    for url in ("https://www.sec.gov/a", "https://www.sec.gov/b", "https://www.cnmv.es/a"):
        with rl.slot(url):
            pass
    assert waits == [2.0]                                                              # solo el 2º acceso al mismo dominio espera
    assert rl._conf("www.sec.gov") == (1, 2.0)


def test_full_pipeline_with_configured_es_and_us_sources_is_consistent(tmp_path):
    runner, http, _ = run_sec(tmp_path, config())
    outs = [runner.run_discovery(DiscoveryRequest(authority=a)).outcomes[0].state for a in ("CNMV", "SEC")]
    assert outs == ["COMPLETED", "COMPLETED"]
    from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
    assert UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    assert {r["headers"]["user-agent"] for r in http.requests} == {"STATER-Sandbox/1.0 (data-ops@stater-sandbox.test)"}
    blob = json.dumps(runner.telemetry.read_all())
    assert "stater-sandbox.test" not in blob and "Bearer" not in blob                     # el contacto no se vuelca a telemetría


def test_new_modules_keep_the_layering_and_ship_no_real_source_configuration():
    banned = ("descarga", "es_cnmv_client", "de_bafin_client", "robust_downloader", "legacy_bridge")
    for name in ("source_config.py", "configured_adapter.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if any(b in m for b in banned)], (name, mods)
    for layer in ("domain", "application"):
        for f in (UNIFIED / layer).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            assert "source_config" not in text and "configured_adapter" not in text
    assert not list(UNIFIED.rglob("*sources*.json")) and not list((UNIFIED.parents[1] / "config").glob("*.json"))


def test_the_configured_user_agent_and_limits_win_even_over_an_adapter_that_builds_its_own_request(tmp_path):
    from mod_01_ingestion.src.unified.models import DownloadRequest

    class Rogue:
        authority, country_code, name = "SEC", "US", "SEC"
        allowed_domains = ("www.sec.gov", "sec.gov")
        source_type = None

        def build_download_request(self, candidate, metadata, staging_dir):
            return DownloadRequest(url=metadata.resolved_url, staging_dir=str(staging_dir), file_name=metadata.file_name,
                                   headers={"User-Agent": "Rogue/9"}, max_bytes=10 ** 12,
                                   allowed_domains=["www.sec.gov", "sec.gov", "evil.test"])
    router, es, us = build(tmp_path)
    (c,) = us.discover(DiscoveryRequest(authority="SEC"))
    meta = us.fetch_metadata(c)
    rogue = ConfiguredAdapter(Rogue(), parse_source_configs(config()).get("SEC"))
    d = rogue.build_download_request(c, meta, tmp_path / "stg")
    assert d.headers["User-Agent"].startswith("STATER-Sandbox/1.0") and d.max_bytes == 5_000_000
    assert d.allowed_domains == ["www.sec.gov", "sec.gov"]                                 # evil.test descartado: solo se estrecha
