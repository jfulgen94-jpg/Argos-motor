"""
U5F — Ejecución autorizada del piloto CNMV TEF 2019 con transporte HTTP SIMULADO (httpx.MockTransport): offline, raíz en tmp_path,
sockets bloqueados. La ejecución real pasa ``client=None``; aquí nunca se usa la raíz D: ni la red.
"""
import ast
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import pilot_runner as pr
from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus
from mod_01_ingestion.src.unified.data_root import DEFAULT_PILOT_ROOT, UnifiedDataRoot
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.pilot_runner import (
    AUTH_PHRASE, PilotAuthorization, PilotRunError, complete_artifacts, evaluate_gate, run_pilot, slot_only_blockers)
from mod_01_ingestion.src.unified.cnmv_pilot import load_artifacts

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
URL = "https://www.cnmv.es/AUDITA/2019/18290.pdf"
UA = "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com"
PDF = b"%PDF-1.4\n" + b"1 0 obj << /Type /Catalog >> endobj\n" * 40 + b"%%EOF\n"
NOW = "2099-01-01T00:00:00+00:00"


def auth(**over):
    d = dict(phrase=AUTH_PHRASE, requester="José Fulgencio Molina", approver="Francisca Garcia",
             reference="CNMV-PILOT-TEF-2019-001", user_agent=UA)
    d.update(over)
    return PilotAuthorization(**d)


class Site:
    """Servidor simulado: registra cada petición y responde según una cola de respuestas."""
    def __init__(self, *responses):
        self.queue = list(responses) or [httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})]
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item.status_code, content=item.content, headers=item.headers)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


def ok():
    return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})


def run(tmp_path, site, **kw):
    sleeps = []
    kw.setdefault("now", pr._now)
    rep = run_pilot(auth(), root_path=tmp_path / "unified_pilot", client=site.client(), sleep=sleeps.append, **kw)
    return rep, sleeps


def tree(base):
    return {p.relative_to(base).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(Path(base).rglob("*")) if p.is_file()}


# ================================================================= autorización
def test_authorization_is_validated():
    assert auth().contact == "j.fulgen94@gmail.com"
    for bad in (dict(phrase="autorizo piloto cnmv tef 2019"), dict(phrase=""), dict(approver="José Fulgencio Molina"),
                dict(approver="  josé fulgencio molina "), dict(reference=""), dict(user_agent="Stater-ARGOS-MOTOR/1.0"),
                dict(user_agent="Stater todo@x.es")):
        with pytest.raises(PilotRunError):
            auth(**bad)


# ================================================================= camino feliz
def test_authorized_pilot_downloads_exactly_one_pdf_and_records_everything(tmp_path):
    legacy = tmp_path / "legacy" / "raw" / "ES_CNMV"
    (legacy / "2019").mkdir(parents=True)
    (legacy / "2019" / "keep.pdf").write_bytes(b"historic")
    before_legacy = tree(legacy)
    site = Site(ok())
    rep, sleeps = run(tmp_path, site)
    root = tmp_path / "unified_pilot"
    assert rep["downloaded"] and rep["outcome"]["state"] == "COMPLETED" and rep["gate"]["allowed"]
    # una sola petición, al dominio y con el User-Agent autorizados, sin credenciales
    assert len(site.requests) == 1 and str(site.requests[0].url) == URL
    assert site.requests[0].headers["user-agent"] == UA and site.requests[0].method == "GET"
    assert "authorization" not in {k.lower() for k in site.requests[0].headers} and "cookie" not in site.requests[0].headers
    # hash, raw, CAS, manifiesto, catálogo, ledger y telemetría
    sha = hashlib.sha256(PDF).hexdigest()
    assert rep["outcome"]["sha256"] == sha and rep["outcome"]["size_bytes"] == len(PDF)
    assert (root / "cas" / sha[:2] / sha).read_bytes() == PDF
    raws = [p for p in (root / "raw").rglob("*") if p.is_file()]
    assert len(raws) == 1 and raws[0].read_bytes() == PDF and raws[0].name == "tef_2019_cnmv_annual_report.pdf"
    assert any(p.is_file() for p in (root / "manifests").rglob("*"))
    ledger = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    rec = ledger.get(CoverageKey("ES", "CNMV", "TEF", 2019, "CNMV_ANNUAL_REPORT"))
    assert rec.status is LedgerStatus.PROMOTED and rec.sha256 == sha and rec.expected
    assert any(p.is_file() and p.stat().st_size > 0 for p in (root / "telemetry").rglob("*"))
    written = json.loads((root / "reports" / "pilot" / "pilot_run_CNMV-PILOT-TEF-2019-001.json").read_text(encoding="utf-8"))
    assert written["outcome"]["sha256"] == sha and written["control_comparison"]["sha256_matches_local_control"] is False
    # identidad SLOT_ONLY: ningún contrato enviado ni activado
    reg = ApprovalRegistry(root / "catalog" / "unified_catalog.duckdb")
    art = complete_artifacts(load_artifacts(), auth(), root)
    assert reg.status("cnmv_pilot", "IDENTITY_CONTRACT", art.contract["contract_version"]) is None
    assert not [p for p in reg.pending()]
    hist = reg.history("cnmv_pilot", "SOURCE_CONFIG") + reg.history("pilot:CNMV", "PILOT_PLAN")
    assert {(e["action"], e["actor"]) for e in hist} == {("SUBMIT", "José Fulgencio Molina"), ("APPROVE", "Francisca Garcia")}
    assert {e["ref"] for e in hist if e["action"] == "APPROVE"} == {"CNMV-PILOT-TEF-2019-001"}
    # el canario fue SANDBOX y OK; no se usó la raíz del piloto para él
    (c,) = CanaryReportStore(root / "catalog" / "unified_catalog.duckdb").latest("CNMV")
    assert c["mode"] == "SANDBOX" and c["status"] == "OK"
    # el árbol histórico simulado no cambia
    assert tree(legacy) == before_legacy
    assert slot_only_blockers(art, reg) == []


def test_second_run_is_idempotent_and_makes_no_request(tmp_path):
    site = Site(ok())
    run(tmp_path, site)
    before = tree(tmp_path / "unified_pilot" / "raw")
    site2 = Site(ok())
    rep, _ = run(tmp_path, site2)
    assert len(site2.requests) == 0 and rep["outcome"]["state"] == "SKIPPED_ALREADY_PRESENT"
    assert rep["skipped"] == "LEDGER_ALREADY_PROMOTED" and rep["outcome"]["sha256"] == hashlib.sha256(PDF).hexdigest()
    assert tree(tmp_path / "unified_pilot" / "raw") == before


# ================================================================= fallos: sin reintentos fuera de lo autorizado
def test_http_403_is_needs_review_with_a_single_request(tmp_path):
    site = Site(httpx.Response(403, content=b"forbidden"))
    rep, sleeps = run(tmp_path, site)
    assert len(site.requests) == 1 and not rep["downloaded"] and sleeps == []
    assert rep["outcome"]["state"] == "FAILED" and rep["outcome"]["ledger_status"] == "NEEDS_REVIEW"
    assert any(s["step"] == "needs_review" for s in rep["steps"])
    assert not [p for p in (tmp_path / "unified_pilot" / "raw").rglob("*") if p.is_file()]


@pytest.mark.parametrize("first", [429, 503])
def test_429_and_503_get_exactly_one_retry(tmp_path, first):
    site = Site(httpx.Response(first, content=b"slow down"), ok())
    rep, sleeps = run(tmp_path, site, retry_wait_s=15.0)
    assert len(site.requests) == 2 and rep["downloaded"] and 15.0 in sleeps
    site2 = Site(httpx.Response(first, content=b"x"))
    rep2, _ = run(tmp_path / "b", site2)
    assert len(site2.requests) == 2 and not rep2["downloaded"]                 # nunca un tercer intento


@pytest.mark.parametrize("response", [httpx.Response(500, content=b"x"), httpx.Response(502, content=b"x"),
                                      httpx.Response(504, content=b"x"), httpx.Response(404, content=b"x"),
                                      httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
def test_other_failures_are_never_retried(tmp_path, response):
    if isinstance(response, httpx.Response):
        site = Site(response)
    else:
        site = Site(response)
    rep, sleeps = run(tmp_path, site)
    assert len(site.requests) == 1 and not rep["downloaded"] and sleeps == []


def test_oversize_wrong_content_and_foreign_redirect_are_not_promoted(tmp_path):
    big = Site(httpx.Response(200, content=b"x", headers={"content-type": "application/pdf",
                                                           "content-length": str(65 * 1024 * 1024)}))
    r1, _ = run(tmp_path / "a", big)
    assert r1["outcome"]["error_class"] == "SIZE_EXCEEDED" and not r1["downloaded"]
    html = Site(httpx.Response(200, content=b"<html>not a pdf</html>" * 10, headers={"content-type": "text/html"}))
    r2, _ = run(tmp_path / "b", html)
    assert not r2["downloaded"] and r2["outcome"]["state"] in ("QUARANTINED", "FAILED", "MANUAL_REVIEW")
    redirect = Site(httpx.Response(302, headers={"location": "https://evil.example.org/x.pdf"}), ok())
    r3, _ = run(tmp_path / "c", redirect)
    assert not r3["downloaded"] and all(str(q.url).startswith("https://www.cnmv.es/") for q in redirect.requests[:1])
    for sub in ("a", "b", "c"):
        assert not [p for p in (tmp_path / sub / "unified_pilot" / "raw").rglob("*") if p.is_file()]


# ================================================================= puerta cerrada => cero tráfico
def test_a_closed_gate_makes_no_request(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "_sandbox_canary", lambda store, run_id: {"report_id": "none", "status": "SKIPPED", "alerts": []})
    site = Site(ok())
    rep, _ = run(tmp_path, site)
    assert not rep["gate"]["allowed"] and "CANARY_MISSING" in rep["gate"]["blockers"]
    assert site.requests == [] and not rep["downloaded"]


def test_a_stale_canary_closes_the_gate_and_no_request_is_made(tmp_path):
    site = Site(ok())
    rep, _ = run(tmp_path, site, now=lambda: NOW)                    # reloj en el futuro: el canario recién hecho queda obsoleto
    assert rep["gate"]["blockers"] == ["CANARY_STALE"] and site.requests == [] and not rep["downloaded"]


def test_gate_requires_approvals_root_and_a_fresh_ok_canary(tmp_path):
    root = UnifiedDataRoot(tmp_path / "r", ExecutionMode.PILOT)
    art = complete_artifacts(load_artifacts(), auth(), root.path)
    reg = ApprovalRegistry(tmp_path / "a.duckdb")
    store = CanaryReportStore(tmp_path / "c.duckdb")
    d = evaluate_gate(art, reg, store, root, now_iso=NOW)
    assert not d.allowed and {"SOURCE_CONFIG_NOT_SUBMITTED", "PILOT_PLAN_NOT_SUBMITTED", "ROOT_NOT_INITIALIZED",
                              "CANARY_MISSING"} <= set(d.blockers)
    # sin completar los marcadores el piloto tampoco abre
    pending = load_artifacts()
    assert any(b.startswith("CONFIG_MARKER") for b in slot_only_blockers(pending, reg))


def test_budget_blocks_a_second_document_and_other_sources(tmp_path):
    from mod_01_ingestion.src.unified.pilot import PilotBudget, PilotLimitExceeded
    plan = complete_artifacts(load_artifacts(), auth(), tmp_path / "r").pilot_plan()
    b = PilotBudget(plan)
    b.start()
    b.begin_document("CNMV", URL)
    for call in (lambda: b.begin_document("CNMV", URL), lambda: b.begin_document("SEC", "https://www.sec.gov/x"),
                 lambda: b.begin_document("CNMV", "https://evil.example.org/x.pdf")):
        with pytest.raises(PilotLimitExceeded):
            call()


# ================================================================= seguridad del entorno
def test_default_root_is_d_and_tests_never_use_it(tmp_path):
    import inspect
    assert inspect.signature(run_pilot).parameters["root_path"].default == DEFAULT_PILOT_ROOT
    with pytest.raises(Exception):
        run_pilot(auth(), root_path=Path("D:/ARGOS_DATA/raw/ES_CNMV/pilot"), client=Site(ok()).client())
    with pytest.raises(Exception):
        run_pilot(auth(), root_path=Path("relative/root"), client=Site(ok()).client())


def test_sandbox_canary_never_writes_into_the_pilot_root(tmp_path):
    store = CanaryReportStore(tmp_path / "c.duckdb")
    out = pr._sandbox_canary(store, "r1")
    assert out["status"] == "OK"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["c.duckdb"] or {p.name for p in tmp_path.iterdir()} <= {"c.duckdb", "c.duckdb.wal"}


def test_runner_module_has_no_credentials_or_raw_network_libraries():
    text = (UNIFIED / "pilot_runner.py").read_text(encoding="utf-8")
    tree_ = ast.parse(text)
    mods = [n.module for n in ast.walk(tree_) if isinstance(n, ast.ImportFrom) and n.module] + \
           [a.name for n in ast.walk(tree_) if isinstance(n, ast.Import) for a in n.names]
    assert not {m.split(".")[0] for m in mods} & {"requests", "urllib", "socket", "subprocess"}
    assert not any(isinstance(n, ast.Attribute) and n.attr == "environ" for n in ast.walk(tree_))
    for other in ("pilot.py", "cnmv_pilot.py", "ingest_runner.py", "download_service.py"):
        assert "pilot_runner" not in (UNIFIED / other).read_text(encoding="utf-8")
