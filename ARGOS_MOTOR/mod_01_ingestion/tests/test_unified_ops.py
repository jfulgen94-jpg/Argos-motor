"""
U5C — Operación y observabilidad en SANDBOX: informes de canario persistidos, retención, scheduler determinista, estado
operativo, alertas activas y aprobación auditada de configuración/contratos. Todo sintético y offline (replay, DuckDB temporal,
sockets bloqueados, relojes inyectados). No hay tráfico real.
"""
import ast
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.adapters.replay import ReplayLinkProvider
from mod_01_ingestion.src.unified.approvals import (
    ApprovalError, ApprovalRegistry, config_content, contract_content, fingerprint, resolve_active_configs, submit_configs)
from mod_01_ingestion.src.unified.canary import Alert, CanaryReport, run_canary
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore, ReportStoreError, RetentionPolicy, report_status
from mod_01_ingestion.src.unified.canary_scheduler import CanaryScheduler, SchedulerError, iso_of
from mod_01_ingestion.src.unified.configured_adapter import configure_adapters
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, LedgerStatus as L
from mod_01_ingestion.src.unified.models import DiscoveryRequest
from mod_01_ingestion.src.unified.ops_status import operational_status, render_text
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.router import SourceRouter
from mod_01_ingestion.src.unified.sandbox_replay import SandboxViolation, make_sandbox_runner
from mod_01_ingestion.src.unified.source_config import parse_source_configs
from mod_01_ingestion.tests.test_unified_coverage import AUTHS, K, six
from mod_01_ingestion.tests.test_unified_ingest import base_site, make_runner
from mod_01_ingestion.tests.test_unified_source_config import (
    ES_DOMAINS, US_DOMAINS, config, contract_dict, source)
from mod_01_ingestion.tests.test_unified_u4_es_us import build as build_es_us, replay as replay_es_us, sub
from mod_01_ingestion.tests.test_unified_u4_eu import FR_REC

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
T0 = 1_800_000_000.0


def env(tmp_path, **kw):
    runner, http, ledger, ads = six(tmp_path, **kw)
    store = CanaryReportStore(runner.layout.catalog_db, telemetry=runner.telemetry)
    return runner, http, ledger, ads, store


def rep(authority="CNMV", finished="2026-10-13T10:00:00+00:00", alerts=(), counts=None, started=None):
    r = CanaryReport(authority=authority, country_code="ES", mode="SANDBOX", started_at=started or finished,
                     finished_at=finished, counts=counts or {"found": 1, "promoted": 1})
    r.alerts = list(alerts)
    return r


def db_fingerprint(*paths):
    out = {}
    for base in paths:
        for p in sorted(Path(base).rglob("*")) if Path(base).is_dir() else []:
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ================================================================= informes: persistir y consultar
def test_canary_report_is_persisted_and_queried(tmp_path):
    runner, http, led, ads, store = env(tmp_path)
    r = run_canary(runner, "SEC", expected=[K["SEC"]], ledger=led, clock=lambda: "2026-10-13T10:00:00+00:00")
    saved = store.save(r, run_id=runner.run.run_id, trigger="MANUAL")
    assert saved["created"] and saved["status"] == "OK"
    (got,) = store.latest("sec")
    assert got["authority"] == "SEC" and got["run_id"] == runner.run.run_id and got["trigger"] == "MANUAL" and got["ok"]
    assert got["counts"]["promoted"] == 1 and got["alerts"] == [] and got["coverage"]["coverage_ratio"] == 1.0
    assert got["started_at"] == got["finished_at"] == "2026-10-13T10:00:00+00:00" and got["mode"] == "SANDBOX"
    again = store.save(r, run_id=runner.run.run_id, trigger="MANUAL")
    assert not again["created"] and again["report_id"] == saved["report_id"] and store.count() == 1       # idempotente
    r.counts["promoted"] = 99
    with pytest.raises(ReportStoreError):
        store.save(r, run_id=runner.run.run_id, trigger="MANUAL")                            # nunca se sobrescribe
    with pytest.raises(ReportStoreError):
        store.save(r, run_id="x", trigger="DIARIO")
    with pytest.raises(ReportStoreError):
        store.save(CanaryReport("SEC", "US", "SANDBOX", ""), run_id="x")
    assert any(e["event"] == "canary_report_saved" for e in runner.telemetry.read_all())


def test_status_is_derived_from_alert_severity_and_history_is_ordered(tmp_path):
    store = CanaryReportStore(tmp_path / "ops.duckdb")
    assert report_status(rep()) == "OK" and report_status(rep(alerts=[Alert("W", "WARN", "m")])) == "WARN"
    assert report_status(rep(alerts=[Alert("W", "WARN", "m"), Alert("E", "ERROR", "m")])) == "ERROR"
    for i in range(5):
        store.save(rep("CNMV", f"2026-10-13T10:00:0{i}+00:00"), run_id="r")
    store.save(rep("SEC", "2026-10-13T09:00:00+00:00", [Alert("E", "ERROR", "m")]), run_id="r")
    assert [h["finished_at"][-14:-6] for h in store.history("CNMV", limit=3)] == ["10:00:04", "10:00:03", "10:00:02"]
    last = store.latest_per_source()
    assert set(last) == {"CNMV", "SEC"} and last["SEC"]["status"] == "ERROR" and last["CNMV"]["finished_at"].endswith("10:00:04+00:00")
    assert store.count() == 6 and store.count("cnmv") == 5


def test_reads_of_an_empty_store_never_create_the_database(tmp_path):
    store = CanaryReportStore(tmp_path / "no" / "ops.duckdb")
    assert store.latest("CNMV") == [] and store.latest_per_source() == {} and store.active_alerts() == [] and store.count() == 0
    reg = ApprovalRegistry(tmp_path / "no" / "ops.duckdb")
    assert reg.status("a", "SOURCE_CONFIG", "1") is None and reg.pending() == [] and reg.history("a") == []
    assert not (tmp_path / "no").exists()


# ================================================================= retención
def test_retention_is_configurable_and_never_touches_operational_data(tmp_path):
    runner, http, led, ads, store = env(tmp_path)
    run_canary(runner, "CNMV", expected=[K["CNMV"]], ledger=led)
    run_canary(runner, "SEC", expected=[K["SEC"]], ledger=led)
    for a in ("CNMV", "SEC"):
        for d in range(1, 6):
            store.save(rep(a, f"2026-10-0{d}T10:00:00+00:00"), run_id="r")
    cat, led_rows = runner.catalog.count(), len(led.list())
    files = db_fingerprint(runner.layout.manifests, runner.layout.raw, runner.layout.cas)
    assert store.apply_retention(RetentionPolicy(keep_last=2), now="2026-10-13T00:00:00+00:00") == 6
    assert store.count("CNMV") == store.count("SEC") == 2 and store.latest("CNMV")[0]["finished_at"].startswith("2026-10-05")
    assert runner.catalog.count() == cat and len(led.list()) == led_rows                       # catálogo y ledger intactos
    assert db_fingerprint(runner.layout.manifests, runner.layout.raw, runner.layout.cas) == files    # y ningún archivo
    # por antigüedad, pero el último de cada fuente SIEMPRE se conserva
    assert store.apply_retention(RetentionPolicy(keep_last=50, max_age_days=1), now="2026-12-01T00:00:00+00:00") == 2
    assert store.count("CNMV") == store.count("SEC") == 1
    assert store.apply_retention(RetentionPolicy(), now="2030-01-01T00:00:00+00:00") == 0
    for bad in ({"keep_last": 0}, {"keep_last": True}, {"max_age_days": 0}, {"max_age_days": "7"}):
        with pytest.raises(ReportStoreError):
            RetentionPolicy(**bad)
    assert any(e["event"] == "canary_reports_pruned" for e in runner.telemetry.read_all())


# ================================================================= scheduler determinista
def test_scheduler_runs_sandbox_canaries_only_when_due_and_respects_intervals(tmp_path):
    runner, http, led, ads, store = env(tmp_path)
    s = CanaryScheduler(runner, store, intervals={"AMF": 100, "cnmv": 300}, ledger=led, expected={a: [K[a]] for a in AUTHS})
    assert s.due(T0) == ["AMF", "CNMV"] and store.count() == 0 and s.next_due("AMF") is None       # due() no ejecuta nada
    assert [x["authority"] for x in s.tick(T0)] == ["AMF", "CNMV"]
    assert {x["authority"] for x in store.latest_per_source().values()} == {"AMF", "CNMV"}
    assert s.tick(T0 + 50) == [] and s.due(T0 + 99) == []
    assert [x["authority"] for x in s.tick(T0 + 100)] == ["AMF"]
    assert s.tick(T0 + 199) == [] and [x["authority"] for x in s.tick(T0 + 200)] == ["AMF"]
    assert s.due(T0 + 299) == []
    assert s.due(T0 + 300) == ["AMF", "CNMV"]
    assert [x["authority"] for x in s.tick(T0 + 300)] == ["AMF", "CNMV"]
    assert s.next_due("AMF") == T0 + 400 and s.next_due("CNMV") == T0 + 600
    last = store.latest("AMF")[0]
    assert last["trigger"] == "SCHEDULED" and last["finished_at"] == iso_of(T0 + 300) and last["ok"]
    manual = s.run_now(["amf"], now=T0 + 301)
    assert [m["authority"] for m in manual] == ["AMF"] and store.latest("AMF")[0]["trigger"] == "MANUAL"
    assert s.next_due("AMF") == T0 + 401                                                           # la manual cuenta como última
    other = CanaryScheduler(runner, store, intervals={"AMF": 100, "CNMV": 300})                   # nuevo proceso: mismo almacén
    assert other.due(T0 + 350) == [] and other.due(T0 + 401) == ["AMF"] and other.due(T0 + 700) == ["AMF", "CNMV"]
    assert any(e["event"] == "canary_scheduler_run" for e in runner.telemetry.read_all())


def test_scheduler_validates_its_configuration_and_refuses_non_sandbox_runners(tmp_path):
    runner, http, led, ads, store = env(tmp_path)
    for bad in ({"XX": 10}, {"AMF": 0}, {"AMF": -5}, {"AMF": True}, {"AMF": "10"}, {}):
        with pytest.raises(SchedulerError):
            CanaryScheduler(runner, store, intervals=bad)
    s = CanaryScheduler(runner, store, intervals={"AMF": 10})
    with pytest.raises(SchedulerError):
        s.run_now(["ZZ"])
    live, _, _ = make_runner(tmp_path / "live", base_site())
    with pytest.raises(SandboxViolation):
        CanaryScheduler(live, store, intervals={"CNMV": 10})


def test_each_source_is_isolated_in_the_scheduler(tmp_path, monkeypatch):
    runner, http, led, ads, store = env(tmp_path)
    ads["CONSOB"]._providers = [lambda req: (_ for _ in ()).throw(OSError("fixture IT caído"))]
    real = runner.process_candidate

    def flaky(adapter, cand):
        if cand.authority == "SEC":
            raise RuntimeError("fallo inesperado")
        return real(adapter, cand)
    monkeypatch.setattr(runner, "process_candidate", flaky)
    s = CanaryScheduler(runner, store, intervals={a: 60 for a in AUTHS}, ledger=led, expected={a: [K[a]] for a in AUTHS})
    s.tick(T0)
    by = store.latest_per_source()
    assert set(by) == set(AUTHS)
    assert [a["code"] for a in by["CONSOB"]["alerts"]] == ["DISCOVERY_FAILED"] and by["CONSOB"]["status"] == "ERROR"
    assert [a["code"] for a in by["SEC"]["alerts"]] == ["CANARY_CRASHED"]
    assert all(by[a]["status"] == "OK" for a in ("CNMV", "BAFIN", "AMF", "AFM"))
    assert led.get(K["CONSOB"]).status is L.SOURCE_UNAVAILABLE and led.get(K["AMF"]).status is L.PROMOTED
    # un fallo al persistir una fuente no impide guardar las demás ni la retención
    monkeypatch.undo()
    orig = store.save

    def save(report, **kw):
        if report.authority == "AFM":
            raise RuntimeError("disco lleno")
        return orig(report, **kw)
    monkeypatch.setattr(store, "save", save)
    s2 = CanaryScheduler(runner, store, intervals={a: 60 for a in AUTHS}, retention=RetentionPolicy(keep_last=1))
    saved = s2.run_now(now=T0 + 500)
    assert sorted(x["authority"] for x in saved) == sorted(set(AUTHS) - {"AFM"})
    assert s2.errors and s2.errors[0]["authority"] == "AFM" and "disco lleno" in s2.errors[0]["error"]
    assert all(store.count(a) == 1 for a in set(AUTHS) - {"AFM"})                                 # retención aplicada tras guardar


# ================================================================= alertas activas y estado operativo
def test_active_alerts_are_queried_with_their_first_seen_and_clear_when_fixed(tmp_path):
    runner, http, led, ads, store = env(tmp_path, fr=[])
    s = CanaryScheduler(runner, store, intervals={"AMF": 10, "CNMV": 10}, ledger=led)
    s.tick(T0)
    s.tick(T0 + 10)
    alerts = store.active_alerts()
    assert [(a["authority"], a["code"], a["severity"]) for a in alerts] == [("AMF", "ZERO_RESULTS_UNEXPECTED", "ERROR")]
    assert alerts[0]["first_seen"] == iso_of(T0) and alerts[0]["report_id"] == store.latest("AMF")[0]["report_id"]
    ads["AMF"]._providers = [ReplayLinkProvider([FR_REC])]
    s.tick(T0 + 20)
    assert store.active_alerts() == [] and store.latest("AMF")[0]["status"] == "OK"
    ads["AMF"]._providers = [ReplayLinkProvider([])]
    s.tick(T0 + 30)
    assert store.active_alerts()[0]["first_seen"] == iso_of(T0 + 30)                               # racha nueva: first_seen nuevo


def test_operational_status_shows_last_run_metrics_alerts_coverage_and_attention_states(tmp_path):
    runner, http, led, ads, store = env(tmp_path, fr=[])
    exp = {a: [K[a]] for a in AUTHS}
    s = CanaryScheduler(runner, store, intervals={a: 60 for a in ("CNMV", "SEC", "AMF", "BAFIN")}, ledger=led, expected=exp)
    s.tick(T0)
    led.expect([K["CONSOB"], K["AFM"]])
    led.record(K["CONSOB"], L.NEEDS_REVIEW, reason="x")
    led.record(K["AFM"], L.CONFLICT, reason="y")
    led.record(CoverageKey("DE", "BAFIN", "OTRO", 2023, "ESEF_PACKAGE"), L.SOURCE_UNAVAILABLE, reason="z")
    before = hashlib.sha256(Path(runner.layout.catalog_db).read_bytes()).hexdigest()
    st = operational_status(store, led, authorities=AUTHS, now_iso=iso_of(T0 + 30), stale_after_s=100,
                            reconciler=UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions))
    assert hashlib.sha256(Path(runner.layout.catalog_db).read_bytes()).hexdigest() == before        # solo lectura
    assert st.overall == "ERROR" and st.integrity["clean"] and st.integrity["documents_checked"] == 3
    src = st.sources
    assert src["SEC"].status == "OK" and src["SEC"].metrics["promoted"] == 1 and src["SEC"].last_report["trigger"] == "SCHEDULED"
    assert src["AMF"].status == "ERROR" and {a["code"] for a in src["AMF"].active_alerts} == {
        "ZERO_RESULTS_UNEXPECTED", "MISSING_EXPECTED"}
    assert src["CONSOB"].status == "NEVER_RUN" and src["CONSOB"].attention["NEEDS_REVIEW"] == 1
    assert src["AFM"].attention["CONFLICT"] == 1 and src["BAFIN"].attention["SOURCE_UNAVAILABLE"] == 1
    assert src["SEC"].coverage["coverage_ratio"] == 1.0 and src["SEC"].country_code == "US"
    assert [k["key"][1] for k in st.attention_keys["CONFLICT"]] == ["AFM"] and st.attention_keys["NEEDS_REVIEW"][0]["reason"] == "x"
    stale = operational_status(store, led, authorities=["SEC"], now_iso=iso_of(T0 + 5000), stale_after_s=100)
    assert stale.sources["SEC"].status == "STALE" and stale.overall == "STALE"
    text = render_text(st)
    assert "SEC (US) OK" in text and "ZERO_RESULTS_UNEXPECTED" in text and "global=ERROR" in text
    json.dumps(st.to_dict())
    Path(runner.catalog.get(led.get(K["SEC"]).document_id)[3]).write_bytes(b"alterado")
    bad = operational_status(store, led, authorities=["SEC"], now_iso=iso_of(T0 + 30), reconciler=UnifiedReconciler(
        runner.layout, runner.catalog, runner.cas, runner.versions))
    assert bad.overall == "ERROR" and not bad.integrity["clean"] and "RAW_HASH_MISMATCH" in bad.integrity["findings_by_code"]


# ================================================================= aprobación de configuración y contratos
def two_source_configs(inline_contract_approved=True):
    return parse_source_configs(config(
        source("CNMV", "ES", ES_DOMAINS),
        source("SEC", "US", US_DOMAINS, identity_contract=contract_dict() if inline_contract_approved else
               contract_dict(approval={"status": "PENDING", "ref": "x"}))))


def fresh(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return p


def pipeline_with(tmp_path, active):
    _, es, us = build_es_us(sub(tmp_path, "src"))
    router = SourceRouter(configure_adapters({"CNMV": es, "SEC": us}, active))
    return make_sandbox_runner(tmp_path / "root", router, replay_es_us())


def test_nothing_is_activated_without_an_explicit_approval(tmp_path):
    cfgs = two_source_configs()
    assert cfgs.get("SEC").contract is not None and cfgs.get("SEC").declared_contract is not None   # declarado en el archivo...
    reg = ApprovalRegistry(tmp_path / "ap.duckdb")
    r0 = resolve_active_configs(cfgs, reg)                                   # ...pero sin registro NO se activa nada
    assert r0.active.sources == () and r0.pending == {"cnmv_sandbox:SOURCE_CONFIG": "NOT_SUBMITTED",
                                                      "sec_sandbox:SOURCE_CONFIG": "NOT_SUBMITTED"}
    out = submit_configs(cfgs, reg, "alice")
    assert out == {"cnmv_sandbox:SOURCE_CONFIG": "PENDING_APPROVAL", "sec_sandbox:SOURCE_CONFIG": "PENDING_APPROVAL",
                   "sec_sandbox:IDENTITY_CONTRACT": "PENDING_APPROVAL"}
    assert submit_configs(cfgs, reg, "alice") == out                          # idempotente
    r1 = resolve_active_configs(cfgs, reg)
    assert r1.active.sources == () and set(r1.pending.values()) == {"PENDING_APPROVAL"}
    assert len(reg.pending()) == 3 and len(reg.history("sec_sandbox", "IDENTITY_CONTRACT")) == 1


def test_approval_activates_only_what_was_approved_and_changes_are_audited(tmp_path):
    cfgs = two_source_configs()
    reg = ApprovalRegistry(tmp_path / "ap.duckdb")
    submit_configs(cfgs, reg, "alice")
    for who, ref in (("alice", "TICKET-1"), ("bob", ""), ("", "TICKET-1")):                  # mismo aprobador / sin referencia
        with pytest.raises(ApprovalError):
            reg.approve("sec_sandbox", "SOURCE_CONFIG", cfgs.config_version, who, ref)
    reg.approve("cnmv_sandbox", "SOURCE_CONFIG", cfgs.config_version, "bob", "TICKET-1")
    reg.approve("sec_sandbox", "SOURCE_CONFIG", cfgs.config_version, "bob", "TICKET-2")
    r = resolve_active_configs(cfgs, reg)
    assert [s.source_id for s in r.active.sources] == ["cnmv_sandbox", "sec_sandbox"]
    sec = r.active.get("SEC")
    assert sec.contract is None and sec.contract_status == "PENDING_APPROVAL"               # el contrato sigue pendiente
    assert r.pending == {"sec_sandbox:IDENTITY_CONTRACT": "PENDING_APPROVAL"}
    runner = pipeline_with(fresh(tmp_path, "a"), r.active)
    out = runner.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out.state == "COMPLETED" and out.version_status is None and runner.versions.list_all_versions() == []   # SLOT_ONLY
    reg.approve("sec_sandbox", "IDENTITY_CONTRACT", "1", "bob", "TICKET-3")
    r2 = resolve_active_configs(cfgs, reg)
    assert r2.pending == {} and r2.active.get("SEC").contract_status == "ACTIVE" and r2.active.get("SEC").contract is not None
    runner2 = pipeline_with(fresh(tmp_path, "b"), r2.active)
    out2 = runner2.run_discovery(DiscoveryRequest(authority="SEC")).outcomes[0]
    assert out2.state == "COMPLETED" and out2.version_status == "CURRENT"                   # con aprobación: identidad por contrato
    hist = reg.history("sec_sandbox", "IDENTITY_CONTRACT")
    assert [(h["action"], h["from_status"], h["to_status"], h["actor"], h["ref"]) for h in hist] == [
        ("SUBMIT", None, "PENDING_APPROVAL", "alice", None), ("APPROVE", "PENDING_APPROVAL", "APPROVED", "bob", "TICKET-3")]


def test_a_change_after_approval_revocation_and_rejection_deactivate_and_are_audited(tmp_path):
    cfgs = two_source_configs()
    reg = ApprovalRegistry(tmp_path / "ap.duckdb")
    submit_configs(cfgs, reg, "alice")
    reg.approve("cnmv_sandbox", "SOURCE_CONFIG", cfgs.config_version, "bob", "T-1")
    reg.approve("sec_sandbox", "SOURCE_CONFIG", cfgs.config_version, "bob", "T-2")
    reg.approve("sec_sandbox", "IDENTITY_CONTRACT", "1", "bob", "T-3")
    assert resolve_active_configs(cfgs, reg).pending == {}
    sec = cfgs.get("SEC")
    changed = dataclasses.replace(sec, timeout_s=sec.timeout_s + 1)                          # alguien cambia la configuración
    assert not reg.is_active("sec_sandbox", "SOURCE_CONFIG", cfgs.config_version, config_content(changed))
    tampered = dataclasses.replace(cfgs, sources=(cfgs.get("CNMV"), changed))
    r = resolve_active_configs(tampered, reg)
    assert [s.source_id for s in r.active.sources] == ["cnmv_sandbox"] and r.pending["sec_sandbox:SOURCE_CONFIG"] == "APPROVED"
    with pytest.raises(ApprovalError):
        reg.submit("sec_sandbox", "SOURCE_CONFIG", cfgs.config_version, config_content(changed), "alice")   # versión inmutable
    reg.revoke("sec_sandbox", "IDENTITY_CONTRACT", "1", "carol", "contrato en revisión")
    r2 = resolve_active_configs(cfgs, reg)
    assert r2.active.get("SEC").contract is None and r2.pending == {"sec_sandbox:IDENTITY_CONTRACT": "REVOKED"}
    for fn, args in ((reg.approve, ("bob", "T-9")), (reg.revoke, ("bob", "x")), (reg.reject, ("bob", "x"))):
        with pytest.raises(ApprovalError):
            fn("sec_sandbox", "IDENTITY_CONTRACT", "1", *args)                               # REVOKED es final
    reg.submit("sec_sandbox", "IDENTITY_CONTRACT", "2", {"contract_version": "2"}, "alice")
    reg.reject("sec_sandbox", "IDENTITY_CONTRACT", "2", "bob", "evidencia insuficiente")
    assert reg.status("sec_sandbox", "IDENTITY_CONTRACT", "2") == "REJECTED"
    h = reg.history("sec_sandbox", "IDENTITY_CONTRACT", "1")
    assert [x["action"] for x in h] == ["SUBMIT", "APPROVE", "REVOKE"] and h[-1]["reason"] == "contrato en revisión"
    for bad in (("", "SOURCE_CONFIG", "1"), ("a", "OTRO", "1"), ("a", "SOURCE_CONFIG", "")):
        with pytest.raises(ApprovalError):
            reg.submit(*bad, {}, "alice")
    with pytest.raises(ApprovalError):
        reg.approve("no-existe", "SOURCE_CONFIG", "1", "bob", "T")


def test_inline_approval_in_the_file_is_ignored_unless_explicitly_accepted(tmp_path):
    cfgs = two_source_configs()
    reg = ApprovalRegistry(tmp_path / "ap.duckdb")
    submit_configs(cfgs, reg, "alice")
    for sid in ("cnmv_sandbox", "sec_sandbox"):
        reg.approve(sid, "SOURCE_CONFIG", cfgs.config_version, "bob", "T-1")
    assert resolve_active_configs(cfgs, reg).active.get("SEC").contract is None
    inline = resolve_active_configs(cfgs, reg, accept_inline_approval=True)
    assert inline.active.get("SEC").contract is not None and inline.active.get("SEC").contract_status == "ACTIVE"
    pend = two_source_configs(inline_contract_approved=False)
    assert resolve_active_configs(pend, reg, accept_inline_approval=True).active.get("SEC").contract is None


def test_approval_fingerprints_are_stable_and_content_sensitive():
    cfgs = two_source_configs()
    c = cfgs.get("SEC").declared_contract
    assert fingerprint(contract_content(c)) == fingerprint(dict(reversed(list(contract_content(c).items()))))
    assert fingerprint(contract_content(c)) != fingerprint(contract_content(dataclasses.replace(c, contract_version="2")))
    assert contract_content(c)["allowed_evidence_kinds"] == ["REVISION_NUMBER"]


# ================================================================= integración con telemetría, ledger y reconciliador
def test_ops_components_feed_telemetry_without_secrets_and_keep_the_pipeline_consistent(tmp_path):
    runner, http, led, ads, store = env(tmp_path)
    reg = ApprovalRegistry(runner.layout.catalog_db, telemetry=runner.telemetry)
    cfgs = two_source_configs()
    submit_configs(cfgs, reg, "alice")
    reg.approve("cnmv_sandbox", "SOURCE_CONFIG", cfgs.config_version, "bob", "REF-SECRETA-123")
    s = CanaryScheduler(runner, store, intervals={a: 60 for a in AUTHS}, ledger=led, expected={a: [K[a]] for a in AUTHS},
                        retention=RetentionPolicy(keep_last=10))
    s.tick(T0)
    events = runner.telemetry.read_all()
    names = {e["event"] for e in events}
    assert {"canary_report", "canary_report_saved", "canary_scheduler_run", "coverage_status", "config_approval_changed"} <= names
    approval = [e for e in events if e["event"] == "config_approval_changed" and e["action"] == "APPROVE"][0]
    assert approval["actor"] == "bob" and approval["to_status"] == "APPROVED"
    assert "REF-SECRETA-123" not in json.dumps(events) and "token=" not in json.dumps(events)    # la referencia no va a telemetría
    assert UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    st = operational_status(store, led, authorities=AUTHS, now_iso=iso_of(T0 + 1))
    assert st.overall == "OK" and all(x.coverage["coverage_ratio"] == 1.0 for x in st.sources.values())
    assert runner.catalog.count() == 6 and len(led.list()) == 6                                  # el catálogo y el ledger coinciden


def test_new_ops_modules_keep_the_layering_and_never_import_legacy_code():
    banned = ("descarga", "es_cnmv_client", "de_bafin_client", "robust_downloader", "legacy_bridge")
    for name in ("_dbutil.py", "canary_reports.py", "canary_scheduler.py", "ops_status.py", "approvals.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if any(b in m for b in banned)], (name, mods)
        assert "threading" not in mods and "subprocess" not in mods and "socket" not in mods       # sin hilos ni daemon
    for layer in ("domain", "application"):
        for f in (UNIFIED / layer).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            assert not any(m in text for m in ("canary_reports", "canary_scheduler", "ops_status", "unified.approvals"))
