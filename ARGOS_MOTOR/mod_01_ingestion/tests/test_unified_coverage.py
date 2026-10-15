"""
Coverage Ledger + canarios en SANDBOX/REPLAY. Todo sintético y offline: fixtures JSON, HTTP simulado (``ReplayHttp``), DuckDB
temporal bajo tmp_path, sockets bloqueados y relojes inyectados. No se descarga nada real.
"""
import ast
import itertools
import json
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.adapters.replay import ReplayLinkProvider
from mod_01_ingestion.src.unified.canary import Alert, CanaryReport, run_canaries, run_canary
from mod_01_ingestion.src.unified.coverage_ledger import (
    CoverageKey, CoverageLedger, LedgerError, LedgerFinding, LedgerStatus as L, apply_cross_check, cross_check_ledger,
    resolve_transition, status_from_outcome)
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.versions import IdScope, InitialVersionPolicy, SourceIdentityContract
from mod_01_ingestion.src.unified.models import PipelineResult
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.router import SourceRouter
from mod_01_ingestion.src.unified.sandbox_replay import ReplayHttp, SandboxViolation, make_sandbox_runner
from mod_01_ingestion.tests.test_unified_ingest import make_runner, base_site
from mod_01_ingestion.tests.test_unified_u4_es_us import ES_ZIP, US_HTML, US_URL, build as build_es_us, sub, write_fixture
from mod_01_ingestion.tests.test_unified_u4_eu import HOSTS, PAYLOADS, adapters4

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
K = {"CNMV": CoverageKey("ES", "CNMV", "LEI_ES_1", 2023, "ESEF_PACKAGE"),
     "SEC": CoverageKey("US", "SEC", "0000320193", 2023, "10-K"),
     "BAFIN": CoverageKey("DE", "BAFIN", "DE_LEI_1", 2023, "ESEF_PACKAGE"),
     "AMF": CoverageKey("FR", "AMF", "FR_LEI_1", 2023, "URD"),
     "CONSOB": CoverageKey("IT", "CONSOB", "IT0000000001", 2023, "ESEF_PACKAGE"),
     "AFM": CoverageKey("NL", "AFM", "NLCO", 2023, "ANNUAL_REPORT")}
AUTHS = list(K)


def clock():
    n = itertools.count(1)
    return lambda: f"2026-10-13T10:00:{next(n):02d}+00:00"


def six(tmp_path, *, es_us_kw=None, http=None, **adapter_kw):
    """Runner SANDBOX con las 6 fuentes (ES, US, DE, FR, IT, NL) y su HTTP de replay."""
    _, es, us = build_es_us(sub(tmp_path, "esus"), **(es_us_kw or {}))
    ads = {**adapters4(sub(tmp_path, "eu"), **adapter_kw), "CNMV": es, "SEC": us}
    if http is None:
        http = ReplayHttp(HOSTS + ["www.cnmv.es", "www.sec.gov"])
        for url, data, ctype in PAYLOADS.values():
            http.add(url, data, content_type=ctype)
        http.add("https://www.cnmv.es/pkg/san2023.zip", ES_ZIP, content_type="application/zip")
        http.add(US_URL, US_HTML, content_type="text/html")
    runner = make_sandbox_runner(tmp_path / "root", SourceRouter(ads), http)
    ledger = CoverageLedger(runner.layout.catalog_db, ExecutionMode.SANDBOX, telemetry=runner.telemetry, clock=clock())
    return runner, http, ledger, ads


# ================================================================= ledger: crear / actualizar sin duplicar
def test_ledger_creates_and_updates_states_without_duplicating(tmp_path):
    led = CoverageLedger(tmp_path / "l.duckdb", clock=clock())
    k = K["CNMV"]
    assert led.expect([k, k]) == 1 and led.expect([k]) == 0                       # idempotente
    assert led.get(k).status is L.UNKNOWN and led.get(k).expected
    r1 = led.record(k, L.FOUND, document_id="d1")
    r2 = led.record(k, L.VALIDATED, document_id="d1")
    r3 = led.record(k, L.PROMOTED, document_id="d1", sha256="ab" * 32)
    assert [r.status for r in (r1, r2, r3)] == [L.FOUND, L.VALIDATED, L.PROMOTED] and all(r.changed for r in (r1, r2, r3))
    n_events = len(led.events(k))
    again = led.record(k, L.PROMOTED, document_id="d1", sha256="ab" * 32)
    assert not again.changed and again.applied and len(led.events(k)) == n_events        # mismo dato: ni fila ni evento nuevos
    assert len(led.list()) == 1 and [e["status"] for e in led.events(k)] == ["UNKNOWN", "FOUND", "VALIDATED", "PROMOTED"]
    assert led.get(k).sha256 == "ab" * 32 and led.get(k).expected


def test_reads_never_create_the_database(tmp_path):
    led = CoverageLedger(tmp_path / "no" / "l.duckdb")
    assert led.list() == [] and led.get(K["AFM"]) is None and led.events(K["AFM"]) == []
    assert led.coverage().expected == 0 and led.coverage().coverage_ratio is None
    assert not (tmp_path / "no").exists()


@pytest.mark.parametrize("current,new,result,applied", [
    (None, L.FOUND, L.FOUND, True), (L.UNKNOWN, L.NOT_PUBLISHED, L.NOT_PUBLISHED, True),
    (L.FOUND, L.VALIDATED, L.VALIDATED, True), (L.VALIDATED, L.FOUND, L.VALIDATED, False),
    (L.PROMOTED, L.FOUND, L.PROMOTED, False), (L.PROMOTED, L.VALIDATED, L.PROMOTED, False),
    (L.PROMOTED, L.SOURCE_UNAVAILABLE, L.PROMOTED, False), (L.PROMOTED, L.UNKNOWN, L.PROMOTED, False),
    (L.PROMOTED, L.NOT_PUBLISHED, L.CONFLICT, True), (L.PROMOTED, L.CONFLICT, L.CONFLICT, True),
    (L.PROMOTED, L.NEEDS_REVIEW, L.NEEDS_REVIEW, True), (L.PROMOTED, L.PROMOTED, L.PROMOTED, True),
    (L.CONFLICT, L.PROMOTED, L.CONFLICT, False), (L.CONFLICT, L.FOUND, L.CONFLICT, False),
    (L.NEEDS_REVIEW, L.FOUND, L.NEEDS_REVIEW, False), (L.NEEDS_REVIEW, L.SOURCE_UNAVAILABLE, L.NEEDS_REVIEW, False),
    (L.NEEDS_REVIEW, L.PROMOTED, L.PROMOTED, True), (L.NEEDS_REVIEW, L.CONFLICT, L.CONFLICT, True),
    (L.NOT_PUBLISHED, L.FOUND, L.FOUND, True), (L.NOT_PUBLISHED, L.SOURCE_UNAVAILABLE, L.NOT_PUBLISHED, False),
    (L.SOURCE_UNAVAILABLE, L.PROMOTED, L.PROMOTED, True), (L.SOURCE_UNAVAILABLE, L.FOUND, L.FOUND, True)])
def test_transition_matrix(current, new, result, applied):
    got, ok, _ = resolve_transition(current, new)
    assert (got, ok) == (result, applied)


def test_conflict_is_sticky_until_explicitly_resolved_and_outages_never_erase_a_promotion(tmp_path):
    led = CoverageLedger(tmp_path / "l.duckdb", clock=clock())
    k = K["SEC"]
    led.record(k, L.PROMOTED, document_id="d", sha256="ab" * 32)
    out = led.record(k, L.SOURCE_UNAVAILABLE, reason="NETWORK")
    assert not out.applied and led.get(k).status is L.PROMOTED and out.changed             # el rechazo queda auditado
    n = len(led.events(k))
    assert not led.record(k, L.SOURCE_UNAVAILABLE, reason="NETWORK").changed and len(led.events(k)) == n   # y no se duplica
    c = led.record_not_published(k, {"method": "index-scan", "ref": "run-1"}, "2026-10-13T08:00:00+00:00")
    assert c.status is L.CONFLICT and led.get(k).reason == "NOT_PUBLISHED_CONTRADICTS_PROMOTED"
    assert not led.record(k, L.PROMOTED, document_id="d").applied and led.get(k).status is L.CONFLICT
    assert led.record(k, L.PROMOTED, document_id="d", resolve_conflict=True).status is L.PROMOTED


# ================================================================= no publicación: evidencia y fecha
def test_not_published_requires_evidence_and_a_check_date_and_is_queryable(tmp_path):
    led = CoverageLedger(tmp_path / "l.duckdb", clock=clock())
    k = K["AFM"]
    for ev, when in ((None, "2026-10-13T08:00:00+00:00"), ({}, "2026-10-13T08:00:00+00:00"), ({"method": "x"}, "2026-10-13T08:00:00+00:00"),
                     ({"method": "", "ref": "r"}, "2026-10-13T08:00:00+00:00"), ({"method": "m", "ref": "r"}, None),
                     ({"method": "m", "ref": "r"}, "2026-10-13T08:00:00"), ({"method": "m", "ref": "r"}, "mañana")):
        with pytest.raises(LedgerError):
            led.record(k, L.NOT_PUBLISHED, evidence=ev, checked_at=when)
    assert led.get(k) is None                                                                # nada se registró a medias
    r = led.record_not_published(k, {"method": "portal-search", "ref": "https://www.afm.nl/buscar?token=SECRETO&q=x#f"},
                                 "2026-10-13T10:30:00+02:00")
    assert r.status is L.NOT_PUBLISHED and r.applied
    rec = led.get(k)
    assert rec.evidence["ref"] == "https://www.afm.nl/buscar" and "SECRETO" not in json.dumps(rec.evidence)      # CNMV-U4: la query se elimina por completo
    assert led.last_non_publication_check(k) == "2026-10-13T08:30:00+00:00"                  # normalizada a UTC
    again = led.record_not_published(k, {"method": "portal-search", "ref": "https://www.afm.nl/buscar?token=OTRO&q=x#f"},
                                     "2026-10-14T08:00:00+00:00")
    assert not again.changed and led.last_non_publication_check(k) == "2026-10-14T08:00:00+00:00"   # solo se refresca la fecha
    appeared = led.record(k, L.FOUND, document_id="d")
    assert appeared.status is L.FOUND and appeared.reason == "APPEARED_AFTER_NOT_PUBLISHED"


def test_keys_are_validated_and_normalized():
    for bad in (("", "A", "i", 2023, "t"), ("ES", "A", "i", 1800, "t"), ("ES", "A", "i", True, "t"), ("ES", "A", " ", 2023, "t")):
        with pytest.raises(LedgerError):
            CoverageKey(*bad)
    assert CoverageKey("es", "cnmv", " X ", 2023, "esef_package").as_tuple() == ("ES", "CNMV", "X", 2023, "ESEF_PACKAGE")


# ================================================================= cálculo de cobertura
def test_coverage_is_computed_from_expected_and_found(tmp_path):
    led = CoverageLedger(tmp_path / "l.duckdb", clock=clock())
    led.expect(K.values())
    for a in ("CNMV", "SEC", "BAFIN"):
        led.record(K[a], L.PROMOTED, document_id=a)
    led.record_not_published(K["AMF"], {"method": "m", "ref": "r"}, "2026-10-13T08:00:00+00:00")
    led.record(K["CONSOB"], L.NEEDS_REVIEW, reason="x")
    led.record(CoverageKey("NL", "AFM", "OTRO", 2023, "ANNUAL_REPORT"), L.FOUND)           # fuera del universo esperado
    s = led.coverage()
    assert s.expected == 6 and s.promoted == 3 and s.not_published == 1 and s.unexpected_found == 1 and s.open_keys == 2
    assert s.by_status == {"NEEDS_REVIEW": 1, "NOT_PUBLISHED": 1, "PROMOTED": 3, "UNKNOWN": 1}
    assert s.coverage_ratio == pytest.approx(3 / 5) and s.accounted_ratio == pytest.approx(4 / 6)
    assert led.coverage(authority="sec").to_dict()["coverage_ratio"] == 1.0 and led.coverage(country_code="nl").expected == 1
    assert led.coverage(fiscal_year=2022).expected == 0
    assert [r.key.authority for r in led.list(status=L.PROMOTED)] == ["BAFIN", "CNMV", "SEC"]
    assert len(led.list(expected_only=True)) == 6 and len(led.list()) == 7
    json.dumps(s.to_dict())


# ================================================================= canario: informe estructurado desde replay
def test_canary_suite_for_all_six_sources_produces_a_structured_report_and_feeds_the_ledger(tmp_path):
    runner, http, led, ads = six(tmp_path)
    suite = run_canaries(runner, AUTHS, expected={a: [K[a]] for a in AUTHS}, ledger=led, clock=clock())
    assert suite.ok and suite.alerts == [] and set(suite.reports) == set(AUTHS)
    for a, r in suite.reports.items():
        assert r.counts["found"] == r.counts["valid"] == r.counts["promoted"] == 1, (a, r.counts)
        assert r.counts["errors"] == r.counts["conflicts"] == r.counts["skipped"] == r.counts["missing_expected"] == 0
        assert r.country_code == K[a].country_code and r.mode == "SANDBOX" and r.coverage["coverage_ratio"] == 1.0
        assert r.items[0]["ledger_status"] == "PROMOTED" and r.items[0]["attempt_id"]
    assert {r.key.authority: r.status for r in led.list()} == {a: L.PROMOTED for a in AUTHS}
    assert led.coverage().coverage_ratio == 1.0 and led.coverage().accounted_ratio == 1.0
    json.loads(json.dumps(suite.to_dict()))
    events = runner.telemetry.read_all()
    assert len([e for e in events if e["event"] == "canary_report"]) == 6
    assert len([e for e in events if e["event"] == "coverage_status"]) >= 6
    rep = UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile()
    assert rep.clean and cross_check_ledger(led, runner.catalog, rep) == []
    again = run_canaries(runner, AUTHS, expected={a: [K[a]] for a in AUTHS}, ledger=led, clock=clock())
    assert again.ok and all(r.counts["promoted"] == 1 for r in again.reports.values())      # segunda pasada estable
    assert len(led.list()) == 6 and all(len(led.events(K[a])) == 3 for a in AUTHS)          # sin eventos duplicados


def test_unexpected_zero_results_raise_an_alert_and_leave_expected_keys_unknown(tmp_path):
    runner, http, led, ads = six(tmp_path, fr=[])
    r = run_canary(runner, "AMF", expected=[K["AMF"]], ledger=led, clock=clock())
    assert not r.ok and r.counts["found"] == 0
    assert {a.code for a in r.alerts} >= {"ZERO_RESULTS_UNEXPECTED", "MISSING_EXPECTED"}
    assert [a for a in r.alerts if a.code == "ZERO_RESULTS_UNEXPECTED"][0].severity == "ERROR"
    assert led.get(K["AMF"]).status is L.UNKNOWN and r.coverage["expected"] == 1 and r.coverage["coverage_ratio"] == 0.0
    quiet = run_canary(runner, "AMF", expected=[], ledger=led, expect_results=False, clock=clock())
    assert quiet.ok and quiet.alerts == []                                                    # cero resultados esperado: sin alerta
    below = run_canary(runner, "CNMV", min_found=3, clock=clock())
    assert [a.code for a in below.alerts] == ["FOUND_BELOW_MINIMUM"] and below.ok


def test_missing_and_unexpected_documents_are_reported_and_tracked_in_the_ledger(tmp_path):
    runner, http, led, ads = six(tmp_path)
    ghost = CoverageKey("DE", "BAFIN", "DE_LEI_1", 2022, "ESEF_PACKAGE")
    r = run_canary(runner, "BAFIN", expected=[ghost], ledger=led, clock=clock())
    codes = {a.code: a for a in r.alerts}
    assert {"MISSING_EXPECTED", "UNEXPECTED_FOUND"} <= set(codes) and r.ok                    # avisos, no errores
    assert codes["MISSING_EXPECTED"].details["keys"] == [list(ghost.as_tuple())]
    assert led.get(ghost).status is L.UNKNOWN and not led.get(K["BAFIN"]).expected and led.get(K["BAFIN"]).status is L.PROMOTED
    assert led.coverage(authority="BAFIN").unexpected_found == 1


# ================================================================= aislamiento de fallos
def test_a_failing_source_does_not_corrupt_the_ledger_or_affect_the_others(tmp_path):
    runner, http, led, ads = six(tmp_path)
    ads["CONSOB"]._providers = [lambda req: (_ for _ in ()).throw(OSError("fixture IT caído"))]
    suite = run_canaries(runner, AUTHS, expected={a: [K[a]] for a in AUTHS}, ledger=led, clock=clock())
    assert not suite.ok
    bad = suite.reports["CONSOB"]
    assert [a.code for a in bad.alerts] == ["DISCOVERY_FAILED"] and bad.discovery_error.startswith("OSError")
    assert {a: r.ok for a, r in suite.reports.items() if a != "CONSOB"} == {a: True for a in AUTHS if a != "CONSOB"}
    assert led.get(K["CONSOB"]).status is L.SOURCE_UNAVAILABLE and led.get(K["CONSOB"]).reason == "DISCOVERY_FAILED"
    assert all(led.get(K[a]).status is L.PROMOTED for a in AUTHS if a != "CONSOB")
    assert runner.catalog.count() == 5
    assert UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    ads["CONSOB"]._providers = [ReplayLinkProvider(write_fixture(sub(tmp_path, "it2"), "it", [
        {"isin": "IT0000000001", "name": "Societa IT", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
         "url": "https://www.consob.it/pkg/it2023.zip"}]))]
    healed = run_canary(runner, "CONSOB", expected=[K["CONSOB"]], ledger=led, clock=clock())
    assert healed.ok and led.get(K["CONSOB"]).status is L.PROMOTED                           # SOURCE_UNAVAILABLE no es definitivo


def test_network_failures_are_source_unavailable_and_never_erase_a_previous_promotion(tmp_path):
    runner, http, led, ads = six(tmp_path)
    assert run_canary(runner, "AFM", expected=[K["AFM"]], ledger=led, clock=clock()).ok
    http._routes.clear()                                                                      # la fuente "se cae"
    r = run_canary(runner, "AFM", ledger=led, clock=clock())
    assert not r.ok and r.counts["errors"] == 1 and {a.code for a in r.alerts} >= {"ZERO_PROMOTED", "HIGH_ERROR_RATE"}
    assert led.get(K["AFM"]).status is L.PROMOTED                                             # la caída no borra lo promovido
    assert any(e["status"] == "SOURCE_UNAVAILABLE" and not e["applied"] for e in led.events(K["AFM"]))


def test_a_crash_in_one_canary_or_in_the_ledger_is_isolated_per_source(tmp_path, monkeypatch):
    runner, http, led, ads = six(tmp_path)
    real = runner.process_candidate

    def flaky(adapter, cand):
        if cand.authority == "SEC":
            raise RuntimeError("fallo inesperado")
        return real(adapter, cand)
    monkeypatch.setattr(runner, "process_candidate", flaky)
    suite = run_canaries(runner, ["SEC", "CNMV"], ledger=led, clock=clock())
    assert [a.code for a in suite.reports["SEC"].alerts] == ["CANARY_CRASHED"] and suite.reports["CNMV"].ok
    monkeypatch.undo()
    monkeypatch.setattr(led, "record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger caído")))
    r = run_canary(runner, "BAFIN", ledger=led, clock=clock())
    assert r.counts["promoted"] == 1 and "LEDGER_ERROR" in {a.code for a in r.alerts} and not r.ok   # el canario sigue y lo avisa


def test_canaries_refuse_to_run_outside_sandbox_and_report_unknown_authorities(tmp_path):
    live, _, _ = make_runner(tmp_path, base_site())                  # LIVE por defecto
    with pytest.raises(SandboxViolation):
        run_canary(live, "CNMV")
    with pytest.raises(SandboxViolation):
        run_canaries(live, ["CNMV"])
    s = tmp_path / "s"
    s.mkdir()
    runner, http, led, ads = six(s)
    assert [a.code for a in run_canary(runner, "XX", ledger=led).alerts] == ["UNKNOWN_AUTHORITY"]


# ================================================================= integración con identidad, versiones y reconciliador
def test_ledger_follows_identity_versions_and_unconfirmed_content(tmp_path):
    ct = SourceIdentityContract(contract_id="sec-synthetic", contract_version="1", authority="SEC", namespace="sec",
                                id_scope=IdScope.VERSION, initial_version_policy=InitialVersionPolicy.TRUST_FIRST_VALIDATED)
    runner, http, led, ads = six(tmp_path, es_us_kw={"identity_contract": ct})
    run_canary(runner, "SEC", ledger=led, clock=clock())
    rec = led.get(K["SEC"])
    assert rec.status is L.PROMOTED and rec.version_status == "CURRENT" and rec.identity_key.startswith("SLOT|")
    assert led.get(K["CNMV"]) is None                                                         # no se tocó otra fuente
    run_canary(runner, "CNMV", ledger=led, clock=clock())
    assert led.get(K["CNMV"]).identity_key is None                                           # sin contrato no se inventa identidad


@pytest.mark.parametrize("state,klass,extra,expected", [
    ("COMPLETED", None, {}, L.PROMOTED), ("SKIPPED_ALREADY_PRESENT", None, {}, L.PROMOTED),
    ("MANUAL_REVIEW", None, {"version_status": "UNCONFIRMED"}, L.VALIDATED), ("MANUAL_REVIEW", None, {}, L.NEEDS_REVIEW),
    ("QUARANTINED", "CORRUPT_ARCHIVE", {}, L.NEEDS_REVIEW), ("CONFLICT", None, {}, L.CONFLICT),
    ("FAILED", "INVARIANT_VIOLATION", {}, L.CONFLICT), ("RECOVERY_REQUIRED", None, {}, L.NEEDS_REVIEW),
    ("FAILED", "NETWORK", {}, L.SOURCE_UNAVAILABLE), ("FAILED", "HTTP_TRANSIENT", {}, L.SOURCE_UNAVAILABLE),
    ("FAILED", "TIMEOUT", {}, L.SOURCE_UNAVAILABLE), ("FAILED", "UNKNOWN", {"failure_stage": "ADAPTER"}, L.SOURCE_UNAVAILABLE),
    ("FAILED", "HTTP_PERMANENT", {}, L.NEEDS_REVIEW), ("FAILED", "SIZE_EXCEEDED", {}, L.NEEDS_REVIEW)])
def test_outcome_to_ledger_status_mapping(state, klass, extra, expected):
    assert status_from_outcome(PipelineResult("j", "d", state, klass, **extra))[0] is expected


def test_cross_check_with_catalog_and_reconciler_detects_and_downgrades_contradictions(tmp_path):
    runner, http, led, ads = six(tmp_path)
    run_canaries(runner, AUTHS, expected={a: [K[a]] for a in AUTHS}, ledger=led, clock=clock())
    runner.catalog.delete(led.get(K["CNMV"]).document_id)                                    # promovido sin catálogo
    runner.catalog._exec("UPDATE unified_catalog SET sha256 = ? WHERE document_id = ?", ["cd" * 32, led.get(K["SEC"]).document_id])
    Path(runner.catalog.get(led.get(K["AMF"]).document_id)[3]).write_bytes(b"alterado")      # raw corrupto
    rep = UnifiedReconciler(runner.layout, runner.catalog, runner.cas, runner.versions).reconcile()
    found = {(f.code, f.key.authority) for f in cross_check_ledger(led, runner.catalog, rep)}
    assert ("LEDGER_PROMOTED_WITHOUT_CATALOG", "CNMV") in found and ("LEDGER_SHA_MISMATCH", "SEC") in found
    assert ("LEDGER_PROMOTED_BUT_RECONCILER_FLAGGED", "AMF") in found
    before = {r.key.authority: r.status for r in led.list()}
    assert all(s is L.PROMOTED for s in before.values())                                      # cross_check NO cambia nada
    n = apply_cross_check(led, cross_check_ledger(led, runner.catalog, rep), run_id="x")
    after = {r.key.authority: r.status for r in led.list()}
    assert n >= 3 and {a for a, s in after.items() if s is L.NEEDS_REVIEW} == {"CNMV", "SEC", "AMF"}
    assert after["BAFIN"] is L.PROMOTED
    empty = CoverageLedger(tmp_path / "otro.duckdb")
    assert {f.code for f in cross_check_ledger(empty, runner.catalog)} == {"CATALOG_UNTRACKED_BY_LEDGER"}
    assert LedgerFinding("X", None, "d").code == "X"


def test_ledger_telemetry_has_no_tokens_and_unchanged_records_emit_nothing(tmp_path):
    runner, http, led, ads = six(tmp_path)
    run_canary(runner, "AMF", ledger=led, clock=clock())
    n = len([e for e in runner.telemetry.read_all() if e["event"] == "coverage_status"])
    run_canary(runner, "AMF", ledger=led, clock=clock())
    assert len([e for e in runner.telemetry.read_all() if e["event"] == "coverage_status"]) == n   # segunda pasada: sin eventos
    led.record_not_published(CoverageKey("NL", "AFM", "ZZ", 2023, "ANNUAL_REPORT"),
                             {"method": "m", "ref": "https://www.afm.nl/x?token=TOPSECRET"}, "2026-10-13T08:00:00+00:00")
    blob = json.dumps(runner.telemetry.read_all()) + json.dumps([r.evidence for r in led.list() if r.evidence])
    for leak in ("TOPSECRET", "FRTOKEN", "SESSION1", "token="):
        assert leak not in blob, leak


def test_new_modules_keep_the_layering_and_never_import_legacy_code():
    banned = ("descarga", "es_cnmv_client", "de_bafin_client", "robust_downloader", "legacy_bridge")
    for name in ("coverage_ledger.py", "canary.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [m for m in mods if any(b in m for b in banned)], (name, mods)
    for layer in ("domain", "application"):
        for f in (UNIFIED / layer).rglob("*.py"):
            text = f.read_text(encoding="utf-8")
            assert "coverage_ledger" not in text and "unified.canary" not in text
    assert Alert("X", "WARN", "m").to_dict()["code"] == "X" and CanaryReport("A", None, "SANDBOX", "t").ok
