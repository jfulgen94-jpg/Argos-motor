"""
CNMV-U2 — Lote autorizado de 9 documentos con transporte HTTP SIMULADO: offline, raíz en tmp_path, sockets bloqueados.
"""
import ast
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import pilot_batch as pb
from mod_01_ingestion.src.unified.approvals import ApprovalRegistry
from mod_01_ingestion.src.unified.cnmv_pilot import load_artifacts
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.pilot_batch import BATCH_PHRASE, EXPECTED, BatchError, expected_url, load_batch, run_batch
from mod_01_ingestion.src.unified.pilot_runner import PilotAuthorization, AUTH_PHRASE, complete_artifacts

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
UA = "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com"


def pdf(ticker, fy):
    return b"%PDF-1.4\n" + f"1 0 obj << /Title ({ticker} {fy}) >> endobj\n".encode() * 40 + b"%%EOF\n"


DOCS = {expected_url(fy, nreg): pdf(t, fy) for t, fy, nreg in EXPECTED}


class Site:
    def __init__(self, overrides=None):
        self.requests, self.overrides, self.counts = [], overrides or {}, {}

    def __call__(self, request):
        self.requests.append(request)
        url = str(request.url)
        self.counts[url] = self.counts.get(url, 0) + 1
        ov = self.overrides.get(url)
        if ov is not None:
            item = ov[min(self.counts[url], len(ov)) - 1] if isinstance(ov, list) else ov
            if isinstance(item, Exception):
                raise item
            return item
        if url in DOCS:
            return httpx.Response(200, content=DOCS[url], headers={"content-type": "application/pdf"})
        return httpx.Response(404)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


def setup(tmp_path, sizes=None):
    root = UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT).initialize()
    art = complete_artifacts(load_artifacts(), PilotAuthorization(AUTH_PHRASE, "José Fulgencio Molina", "Francisca Garcia",
                                                                  "CNMV-PILOT-TEF-2019-001", UA), root.path)
    reg = ApprovalRegistry(root.layout.catalog_db)
    s = art.subjects()["SOURCE_CONFIG"]
    reg.submit(s["subject_id"], "SOURCE_CONFIG", s["version"], s["content"], "José Fulgencio Molina")
    reg.approve(s["subject_id"], "SOURCE_CONFIG", s["version"], "Francisca Garcia", "CNMV-PILOT-TEF-2019-001")
    cands = [{"ticker": t, "fiscal_year": fy, "nreg": nreg, "url": expected_url(fy, nreg),
              "head_content_length": (sizes or {}).get((t, fy), len(DOCS[expected_url(fy, nreg)])),
              "head_last_modified": "Thu, 21 Feb 2019 07:30:24 GMT", "head_confirmed_pdf": True} for t, fy, nreg in EXPECTED]
    cands.append({"ticker": "TEF", "fiscal_year": 2019, "nreg": "18290", "url": expected_url(2019, "18290"),
                  "head_content_length": 23864356, "head_last_modified": "x", "head_confirmed_pdf": True})
    d = root.layout.reports / "pilot" / "discovery"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cnmv_u1_candidates.json").write_text(json.dumps(cands), encoding="utf-8")
    return root


def go(tmp_path, site=None, phrase=BATCH_PHRASE, **kw):
    site = site or Site()
    root = setup(tmp_path) if not (tmp_path / "unified_pilot").exists() else UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT)
    sleeps = []
    rep = run_batch(phrase, root_path=root.path, client=site.client(), sleep=sleeps.append, **kw)
    return root, site, rep, sleeps


def tree(base):
    return {p.relative_to(base).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(Path(base).rglob("*")) if p.is_file()}


# ================================================================= autorización y lote exacto
def test_batch_requires_the_exact_phrase_and_the_exact_nine_documents(tmp_path):
    root = setup(tmp_path)
    site = Site()
    for bad in ("autorizo lote cnmv 2018-2019 9 documentos", pb.BATCH_PHRASE + " ", "AUTORIZO PILOTO CNMV TEF 2019", ""):
        with pytest.raises(BatchError, match="frase"):
            run_batch(bad, root_path=root.path, client=site.client(), sleep=lambda s: None)
    assert site.requests == []
    items = load_batch(root.path)
    assert len(items) == 9 and ("TEF", 2019) not in {(i.ticker, i.fiscal_year) for i in items}
    assert {i.url for i in items} == {expected_url(fy, n) for _, fy, n in EXPECTED}
    p = root.layout.reports / "pilot" / "discovery" / "cnmv_u1_candidates.json"
    good = json.loads(p.read_text(encoding="utf-8"))
    for mutate in (lambda c: c[0].update(url="https://www.cnmv.es/AUDITA/2018/99999.pdf"), lambda c: c[0].update(nreg="1"),
                   lambda c: c.pop(1), lambda c: c[2].update(head_confirmed_pdf=False), lambda c: c[3].update(head_content_length=0)):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(BatchError):
            load_batch(root.path)


def test_not_initialized_root_or_unapproved_config_stops_before_any_request(tmp_path):
    with pytest.raises(BatchError):
        run_batch(BATCH_PHRASE, root_path=tmp_path / "nope", client=Site().client())
    root = UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT).initialize()
    (root.layout.reports / "pilot" / "discovery").mkdir(parents=True)
    site = Site()
    ok = setup(tmp_path / "other")
    (root.layout.reports / "pilot" / "discovery" / "cnmv_u1_candidates.json").write_bytes(
        (ok.layout.reports / "pilot" / "discovery" / "cnmv_u1_candidates.json").read_bytes())
    rep = run_batch(BATCH_PHRASE, root_path=root.path, client=site.client(), sleep=lambda s: None)
    assert rep["stopped"] == "SOURCE_CONFIG_NOT_APPROVED" and site.requests == []


# ================================================================= camino feliz
def test_nine_documents_are_downloaded_exactly_once_each_and_recorded(tmp_path):
    legacy = tmp_path / "legacy" / "ES_CNMV" / "2018"
    legacy.mkdir(parents=True)
    (legacy / "keep.pdf").write_bytes(b"historic")
    before = tree(tmp_path / "legacy")
    root, site, rep, sleeps = go(tmp_path)
    urls = [str(q.url) for q in site.requests]
    assert sorted(urls) == sorted(DOCS) and len(urls) == 9 and all(q.method == "GET" for q in site.requests)
    assert expected_url(2019, "18290") not in urls                                    # TEF 2019 ya descargado: fuera del lote
    assert all(q.headers["user-agent"] == UA and "cookie" not in q.headers and "authorization" not in q.headers
               for q in site.requests)
    assert rep["downloaded"] == 9 and rep["stopped"] is None and rep["authorization_status"].startswith("OWNER_AUTHORIZED")
    assert all(d["state"] == "COMPLETED" and d["size_matches_discovery"] and d["ledger_status"] == "PROMOTED" for d in rep["documents"])
    led = CoverageLedger(root.layout.catalog_db, ExecutionMode.PILOT)
    assert {r.status.value for r in led.list() if r.key.issuer_id != "TEF" or r.key.fiscal_year == 2018} >= {"PROMOTED"}
    for t, fy, n in EXPECTED:
        rec = led.get(CoverageKey("ES", "CNMV", t, fy, "CNMV_ANNUAL_REPORT"))
        sha = hashlib.sha256(DOCS[expected_url(fy, n)]).hexdigest()
        assert rec.status.value == "PROMOTED" and rec.sha256 == sha
        assert (root.path / "cas" / sha[:2] / sha).read_bytes() == DOCS[expected_url(fy, n)]
    raws = sorted(p.name for p in (root.path / "raw").rglob("*.pdf"))
    assert len(raws) == 9 and "tef_2018_cnmv_annual_report.pdf" in raws
    assert len([p for p in (root.path / "manifests").rglob("*.json")]) == 9
    assert tree(tmp_path / "legacy") == before
    assert json.loads((root.layout.reports / "pilot" / f"batch_{pb.BATCH_REF}.json").read_text(encoding="utf-8"))["downloaded"] == 9
    assert rep["budget"]["max_documents"] == 9 and rep["budget"]["max_total_bytes"] >= rep["budget"]["expected_total_bytes"]


def test_second_run_makes_no_request(tmp_path):
    go(tmp_path)
    root, site, rep, _ = go(tmp_path)
    assert site.requests == [] and rep["downloaded"] == 0 and {d["state"] for d in rep["documents"]} == {"SKIPPED_ALREADY_PROMOTED"}


def test_hash_is_compared_with_the_local_copy_read_only(tmp_path, monkeypatch):
    from mod_01_ingestion.src.unified import cnmv_discovery as cd
    ckout = tmp_path / "checkout"
    (ckout / "audits" / "manifests").mkdir(parents=True)
    legacy = tmp_path / "legacy"
    for fy in (2018, 2019):
        recs = []
        for t, y, n in EXPECTED:
            if y != fy:
                continue
            f = legacy / str(fy) / f"A1_{t}" / f"{t}_{fy}_ANUAL.pdf"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(DOCS[expected_url(y, n)] if t != "SAN" else b"different local content")
            recs.append({"ticker": t, "url": expected_url(y, n), "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                         "size_bytes": f.stat().st_size, "path": str(f)})
        (ckout / "audits" / "manifests" / f"MANIFEST_CNMV_{fy}.json").write_text(json.dumps({"manifest": recs}), encoding="utf-8")
    monkeypatch.setattr(cd, "ARGOS_MOTOR", ckout)
    monkeypatch.setattr(cd, "LEGACY_ROOT", str(legacy).lower().replace("/", "\\") if False else __import__("os").path.normcase(str(legacy)))
    before = tree(legacy)
    _, _, rep, _ = go(tmp_path)
    got = {(d["ticker"], d["fiscal_year"]): d["hash_vs_local"] for d in rep["documents"]}
    assert got[("SAN", 2018)] == got[("SAN", 2019)] == "DIFFERENT"
    assert {v for k, v in got.items() if k[0] != "SAN"} == {"MATCH"}
    assert tree(legacy) == before


# ================================================================= interruptor y presupuestos
def test_first_403_stops_the_batch_and_the_rest_are_never_requested(tmp_path):
    third = expected_url(*EXPECTED[2][1:])
    site = Site({third: httpx.Response(403, content=b"no")})
    root, site, rep, _ = go(tmp_path, site)
    assert rep["stopped"] == "HTTP_403" and len(site.requests) == 3 and rep["downloaded"] == 2
    states = [d["state"] for d in rep["documents"]]
    assert states[:2] == ["COMPLETED"] * 2 and states[2] == "FAILED" and states[3:] == ["NOT_ATTEMPTED"] * 6
    led = CoverageLedger(root.layout.catalog_db, ExecutionMode.PILOT)
    assert led.get(CoverageKey("ES", "CNMV", "SAN", 2019, "CNMV_ANNUAL_REPORT")).status.value == "NEEDS_REVIEW"


def test_two_consecutive_failures_stop_but_one_failure_does_not(tmp_path):
    u = [expected_url(*e[1:]) for e in EXPECTED]
    one = Site({u[1]: httpx.Response(404)})
    _, s1, r1, _ = go(tmp_path / "a", one)
    assert r1["stopped"] is None and r1["downloaded"] == 8 and len(s1.requests) == 9
    two = Site({u[1]: httpx.Response(404), u[2]: httpx.Response(500, content=b"x")})
    _, s2, r2, _ = go(tmp_path / "b", two)
    assert r2["stopped"] == "CONSECUTIVE_FAILURES" and len(s2.requests) == 3 and r2["downloaded"] == 1


def test_429_gets_one_retry_and_a_second_429_counts_as_failure(tmp_path):
    u = [expected_url(*e[1:]) for e in EXPECTED]
    site = Site({u[0]: [httpx.Response(429, content=b"slow"), httpx.Response(200, content=DOCS[u[0]], headers={"content-type": "application/pdf"})]})
    _, s, rep, sleeps = go(tmp_path / "a", site, retry_wait_s=15.0)
    assert s.counts[u[0]] == 2 and rep["downloaded"] == 9 and 15.0 in sleeps
    bad = Site({u[0]: httpx.Response(429, content=b"slow")})
    _, s2, r2, _ = go(tmp_path / "b", bad)
    assert s2.counts[u[0]] == 2 and r2["documents"][0]["state"] == "FAILED" and len(s2.requests) == 2 + 8


def test_size_mismatch_with_discovery_is_flagged_and_total_bytes_budget_stops(tmp_path):
    u0 = expected_url(*EXPECTED[0][1:])
    setup(tmp_path, sizes={("TEF", 2018): 5})
    _, _, rep, _ = go(tmp_path)
    assert rep["documents"][0]["size_matches_discovery"] is False                         # se marca, no se oculta
    root2 = setup(tmp_path / "b")
    big = len(DOCS[u0]) * 40
    site = Site({u0: httpx.Response(200, content=DOCS[u0], headers={"content-type": "application/pdf"})})
    import mod_01_ingestion.src.unified.pilot_batch as m
    orig = m.BYTES_MARGIN
    m.BYTES_MARGIN = 0.5                                                                  # presupuesto de ~la mitad de lo esperado
    try:
        _, _, rep2, _ = go(tmp_path / "b", site)
    finally:
        m.BYTES_MARGIN = orig
    assert rep2["stopped"] == "PILOT_TOTAL_BYTES" and 3 <= rep2["downloaded"] <= 6 and big and root2
    assert any(d["state"] == "NOT_ATTEMPTED" for d in rep2["documents"])


def test_architecture_no_new_network_stack_and_no_other_module_depends_on_it():
    text = (UNIFIED / "pilot_batch.py").read_text(encoding="utf-8")
    tree_ = ast.parse(text)
    mods = [n.module for n in ast.walk(tree_) if isinstance(n, ast.ImportFrom) and n.module] + \
           [a.name for n in ast.walk(tree_) if isinstance(n, ast.Import) for a in n.names]
    assert not {m.split(".")[0] for m in mods} & {"requests", "urllib", "socket", "subprocess", "shutil"}
    assert ".unlink(" not in text and "rmtree" not in text and "ES_CNMV" not in text.replace("raw/ES_CNMV", "")
    for other in ("pilot_runner.py", "cnmv_discovery.py", "ingest_runner.py", "download_service.py"):
        assert "pilot_batch" not in (UNIFIED / other).read_text(encoding="utf-8")
