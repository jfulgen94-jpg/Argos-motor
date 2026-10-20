"""
CNMV-U4 — Entrega token-safe: referencia estable persistible vs URL de transporte efímera. Offline: httpx.MockTransport, raíces en
tmp_path, sockets bloqueados y SOLO URLs/tokens sintéticos (ninguno es un token real de CNMV).
"""
import ast
import copy
import dataclasses
import json
import logging
import pickle
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.configured_adapter import ConfiguredAdapter
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, record_outcome
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.models import DocumentCandidate, DownloadRequest, ManifestRecord
from mod_01_ingestion.src.unified.domain.republication import (
    POSSIBLE_REPUBLICATION, ReplacementSignal, indicates_replacement, replacement_signal)
from mod_01_ingestion.src.unified.domain.transport import (
    SecretLeakError, StableReference, TransportUrl, TransportViolation, assert_no_secret, authorized_transport, find_secret,
    redact_text, sanitize_payload, split_url, strip_url)
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest, RunContext
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.repositories import ManifestRepository
from mod_01_ingestion.src.unified.source_config import parse_source_configs
from mod_01_ingestion.tests.test_unified_source_config import config, source

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
TOK = "SYNTHTOKEN9f3a7c1b"
SIG = "SYNTHSIG42"
FULL = f"https://www.cnmv.es/webservices/verdocumento/ver?e={TOK}%2bAAA&sig={SIG}#frag"
STABLE = "https://www.cnmv.es/webservices/verdocumento/ver"
PDF = b"%PDF-1.4\n" + b"1 0 obj << /Type /Catalog >> endobj\n" * 40 + b"%%EOF\n"
LEAKS = (TOK, SIG, "?e=", "verdocumento/ver?", "sig=", "#frag", "REDIRTOK")


def ok(content=PDF, ctype="application/pdf"):
    return httpx.Response(200, content=content, headers={"content-type": ctype})


class Site:
    def __init__(self, handler=None):
        self.requests, self.handler = [], handler or (lambda r: ok())

    def __call__(self, request):
        self.requests.append(request)
        out = self.handler(request)
        if isinstance(out, Exception):
            raise out
        return out

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=True)


def make_runner(tmp_path, site, records=None, configured=True, mode=ExecutionMode.TEST):
    layout = DataLayout(tmp_path / "root")
    rec = records or [{"ticker": "TEF", "name": "Telefonica", "fiscal_year": 2020, "doc_type": "CNMV_ANNUAL_REPORT", "url": FULL}]
    adapter = CNMVAdapter(lambda req: list(rec))
    if configured:
        cfg = parse_source_configs(config(source("CNMV", "ES", ["www.cnmv.es"]))).get("CNMV")
        adapter = ConfiguredAdapter(adapter, cfg)
    svc = DownloadService(client=site.client(), sleep=lambda s: None, initial_backoff_s=0.0, max_retries=1,
                          rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    runner = UnifiedIngestRunner(layout, {"CNMV": adapter}, download=svc, run=RunContext(data_root=str(layout.root), mode=mode))
    return runner, layout


def and_clean_ok(blob):
    assert_clean(blob)
    return True


def run_all(runner):
    return runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes


def tree_bytes(root):
    return b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())


def assert_clean(blob):
    text = blob.decode("utf-8", errors="ignore") if isinstance(blob, bytes) else str(blob)
    for leak in LEAKS:
        assert leak not in text, leak


# ================================================================= 1. la descarga usa el token en memoria y no deja rastro
def test_tokenized_url_is_used_in_memory_and_leaves_no_trace_anywhere(tmp_path):
    site = Site()
    runner, layout = make_runner(tmp_path, site)
    (out,) = run_all(runner)
    assert out.state == "COMPLETED"
    # la petición REAL sí llevó el token (se usó de verdad en memoria)…
    assert len(site.requests) == 1 and TOK in str(site.requests[0].url) and SIG in str(site.requests[0].url)
    # …pero no hay rastro en NINGÚN archivo de la raíz (manifiesto, catálogo DuckDB, telemetría, staging, CAS, versiones…)
    assert_clean(tree_bytes(layout.root))
    mf = next(layout.manifests.rglob("*.json"))
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data["source_url"] == STABLE and data["final_url"] == STABLE and "?" not in json.dumps(data)
    # ledger, informe, sidecar de versiones y resultado tipado
    led = CoverageLedger(layout.catalog_db, ExecutionMode.TEST)
    cand = runner.adapters["CNMV"].discover(DiscoveryRequest(authority="CNMV"))[0]
    record_outcome(led, cand, out, run_id="r1")
    assert_clean(json.dumps([r.key.as_tuple() for r in led.list()]) + repr(led.list()))
    assert_clean(json.dumps(out.to_dict(), default=str) + repr(out))
    assert_clean(tree_bytes(layout.root))
    assert not list(layout.versions.rglob("*"))                                     # SLOT_ONLY: sin sidecars de versión


# ================================================================= 2. repr / str / serialización accidental del wrapper
def test_wrapper_never_exposes_the_token_by_repr_str_format_json_pickle_or_copy():
    t = TransportUrl(FULL)
    for rendered in (repr(t), str(t), f"{t}", "{}".format(t), "%s" % t, "%r" % t, repr([t]), str({"u": t}), repr((t,))):
        assert_clean(rendered)
    assert t.host == "www.cnmv.es" and t.safe_path == "/webservices/verdocumento/ver" and t.stable_url == STABLE
    with pytest.raises(TypeError):
        json.dumps(t)
    assert_clean(json.dumps({"x": t}, default=str))
    with pytest.raises(TransportViolation):
        pickle.dumps(t)
    with pytest.raises(TransportViolation):
        t.__reduce_ex__(4)
    assert copy.copy(t) is t and copy.deepcopy(t) is t                              # nunca se duplica el valor
    assert t == t and t != TransportUrl(FULL) and hash(t) == hash(t)                # no comparable por URL completa
    with pytest.raises(TransportViolation):
        t.extra = 1
    c = DocumentCandidate(authority="CNMV", country_code="ES", issuer_id="TEF", fiscal_year=2020, doc_type="X", source_url=FULL)
    d = DownloadRequest(url=FULL, staging_dir="s", file_name="a.pdf")
    for obj in (c, d):
        assert_clean(repr(obj) + str(obj) + json.dumps(obj.to_dict(), default=str) + json.dumps(dataclasses.asdict(obj), default=str))
        assert obj.transport_url is not None
    assert c.source_url == STABLE and d.url == STABLE
    assert_clean(sanitize_payload({"a": t, "b": [t, FULL], "c": {"d": f"fallo en {FULL}"}}).__repr__())


# ================================================================= 3. persistir una URL tokenizada falla cerrado
def test_persisting_a_tokenized_url_fails_closed_everywhere(tmp_path):
    t = TransportUrl(FULL)
    for bad in (FULL, {"u": FULL}, [FULL], t, {"x": [t]}, f"msg {FULL}", "Authorization: Bearer abcdefgh12345",
                "Cookie: sid=abc", "https://h/p?token=abc", "https://h/p?X-Amz-Signature=abc", "https://u:pw@h/p", "see sig=abc123",
                "https://www.cnmv.es/a?x=1", "https://www.cnmv.es/a#f"):
        with pytest.raises(SecretLeakError):
            assert_no_secret(bad, "prueba")
    for fine in (STABLE, "https://www.cnmv.es/AUDITA/2019/18290.pdf", "token=<redacted>", "Cookie banner", {"nreg": "18760"}):
        assert_no_secret(fine, "prueba")
    layout = DataLayout(tmp_path / "r")
    man = ManifestRepository(layout, mode=ExecutionMode.TEST)
    base = dict(manifest_version="1.0.0", document_id="CNMV_TEF_2020_X", run_id="r", job_id="j", authority="CNMV", country_code="ES",
                issuer_id="TEF", fiscal_year=2020, doc_type="X", source_url=STABLE, final_url=None, raw_path="raw/a.pdf",
                cas_path="cas/x", sha256="a" * 64, size_bytes=1, mime_type=None, http_status=200, status="RAW_VALIDATED",
                completeness_status="OK")
    for over in ({"source_url": FULL}, {"final_url": FULL}, {"source_page_url": FULL}, {"source_url": t}):
        with pytest.raises(SecretLeakError):
            man.stage(ManifestRecord(**{**base, **over}))
    assert not list((tmp_path / "r").rglob("*.json"))                                # nada llegó a disco
    man.stage(ManifestRecord(**base))                                                 # la referencia estable sí
    led = CoverageLedger(tmp_path / "l.duckdb", ExecutionMode.TEST)
    key = CoverageKey("ES", "CNMV", "TEF", 2020, "X")
    led.record(key, "NEEDS_REVIEW", evidence={"method": "m", "ref": FULL})          # una URL de evidencia se guarda SIN query ni token
    assert led.get(key).evidence["ref"] == STABLE and and_clean_ok(json.dumps(led.get(key).evidence))
    with pytest.raises(SecretLeakError):                                            # pero una TransportUrl nunca entra
        led.record(CoverageKey("ES", "CNMV", "TEF", 2021, "X"), "NEEDS_REVIEW", evidence={"method": "m", "ref": t})
    with pytest.raises(SecretLeakError):
        led.record(key, "NEEDS_REVIEW", reason=f"token={TOK}")
    assert len(led.list()) == 1
    from mod_01_ingestion.src.unified import pilot_runner
    from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot
    root = UnifiedDataRoot(tmp_path / "pilot", ExecutionMode.PILOT).initialize()
    with pytest.raises(SecretLeakError):
        pilot_runner._write_report(root, {"reference": "x", "url": FULL})
    assert not list((root.layout.reports / "pilot").rglob("pilot_run_x.json"))


def test_telemetry_payloads_are_redacted_and_fail_closed(tmp_path):
    runner, layout = make_runner(tmp_path, Site())
    t = TransportUrl(FULL)
    runner.telemetry.emit("probe", None, "test", transport=t, url=FULL, message=f"fallo en {FULL}", nested={"a": [t, FULL]},
                          header="Authorization: Bearer abcdefgh12345", note="token=abc123xyz")
    ev = [e for e in runner.telemetry.read_all() if e["event"] == "probe"][0]
    assert ev["transport"] == "www.cnmv.es/webservices/verdocumento/ver" and ev["url"] == STABLE
    assert_clean(json.dumps(ev))
    assert "abcdefgh12345" not in json.dumps(ev) and "abc123xyz" not in json.dumps(ev)
    assert_clean(runner.telemetry.path.read_bytes())


# ================================================================= 4. redirecciones
def test_a_tokenized_redirect_is_used_in_memory_and_final_url_is_not_persisted(tmp_path):
    def handler(request):
        if request.url.path.endswith("/ver"):
            return httpx.Response(302, headers={"location": "https://www.cnmv.es/otro/destino?e=REDIRTOK123456&sig=REDIRSIG"})
        return ok()
    site = Site(handler)
    runner, layout = make_runner(tmp_path, site)
    (out,) = run_all(runner)
    assert out.state == "COMPLETED" and len(site.requests) == 2 and "REDIRTOK123456" in str(site.requests[1].url)
    blob = tree_bytes(layout.root)
    assert_clean(blob)
    for leak in (b"REDIRTOK123456", b"REDIRSIG"):
        assert leak not in blob
    mf = json.loads(next(layout.manifests.rglob("*.json")).read_text(encoding="utf-8"))
    assert mf["final_url"] == "https://www.cnmv.es/otro/destino"                      # solo host/path
    events = [e for e in runner.telemetry.read_all() if e["event"] == "http_response"]
    assert events and all("?" not in e["url"] for e in events) and "REDIRTOK" not in json.dumps(events)


def test_a_redirect_to_a_foreign_host_is_rejected_without_leaking(tmp_path):
    site = Site(lambda r: httpx.Response(302, headers={"location": "https://evil.example.org/x?e=REDIRTOK123456"}) if "cnmv" in r.url.host else ok())
    runner, layout = make_runner(tmp_path, site)
    (out,) = run_all(runner)
    assert out.state == "FAILED" and out.error_class == "REDIRECT_NOT_ALLOWED"
    assert_clean(json.dumps(out.to_dict()) + tree_bytes(layout.root).decode("utf-8", errors="ignore"))
    assert "REDIRTOK" not in json.dumps(out.to_dict()) and "REDIRTOK" not in tree_bytes(layout.root).decode("utf-8", errors="ignore")


# ================================================================= 5. errores, timeouts, validación, cuarentena y rollback
@pytest.mark.parametrize("response", [
    httpx.Response(403, content=b"forbidden"), httpx.Response(404, content=b"nope"), httpx.Response(500, content=b"err"),
    httpx.ConnectError(f"cannot connect to {FULL}"), httpx.ReadTimeout(f"timeout reading {FULL}"),
    httpx.UnsupportedProtocol(f"unsupported {FULL}")])
def test_http_errors_and_timeouts_never_expose_the_token(tmp_path, response):
    site = Site(lambda r: response)
    runner, layout = make_runner(tmp_path, site)
    (out,) = run_all(runner)
    assert out.state == "FAILED"
    blob = json.dumps(out.to_dict(), default=str) + repr(out) + json.dumps(runner.telemetry.read_all(), default=str)
    assert_clean(blob)
    assert_clean(tree_bytes(layout.root))


def test_exceptions_and_tracebacks_never_contain_the_real_url(tmp_path):
    import traceback
    svc = DownloadService(client=Site(lambda r: httpx.ConnectError(f"cannot connect to {FULL}")).client(), sleep=lambda s: None,
                          max_retries=1, initial_backoff_s=0.0, rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    req = DownloadRequest(url=FULL, staging_dir=str(tmp_path / "s"), file_name="a.pdf")
    res = svc.download(req)
    assert not res.ok and res.error_class == "NETWORK"
    assert_clean(res.error_message + (res.final_url or "") + repr(res))
    from mod_01_ingestion.src.unified.download_service import DownloadFailure
    try:
        raise DownloadFailure(f"fallo en {FULL}", __import__("mod_01_ingestion.src.unified.models", fromlist=["ErrorClass"]).ErrorClass.NETWORK)
    except DownloadFailure as ex:
        assert_clean("".join(traceback.format_exception(ex)))
    try:
        TransportUrl(FULL).reveal()
    except TransportViolation as ex:
        assert_clean("".join(traceback.format_exception(ex)))


def test_validation_rejection_quarantine_and_rollback_do_not_leak(tmp_path):
    html = Site(lambda r: ok(b"<html>not a pdf at all, padding padding padding padding padding</html>" * 3, "text/html"))
    runner, layout = make_runner(tmp_path / "q", html)
    (out,) = run_all(runner)
    assert out.state == "QUARANTINED"
    assert_clean(json.dumps(out.to_dict()) + tree_bytes(layout.root).decode("utf-8", errors="ignore"))
    assert list(layout.quarantine.rglob("*.quarantine_reason.json"))
    # rollback: el manifiesto falla con un mensaje que contiene la URL real
    runner2, layout2 = make_runner(tmp_path / "rb", Site())

    def boom(rec):
        raise RuntimeError(f"fallo de disco al escribir {FULL}")
    runner2.manifests.stage = boom
    (out2,) = run_all(runner2)
    assert out2.state in ("FAILED", "RECOVERY_REQUIRED")
    assert_clean(json.dumps(out2.to_dict(), default=str) + json.dumps(runner2.telemetry.read_all(), default=str))
    assert_clean(tree_bytes(layout2.root))


def test_httpx_request_logs_are_redacted(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore")
    runner, _ = make_runner(tmp_path, Site())
    run_all(runner)
    assert_clean(caplog.text)


# ================================================================= 6. URL directa sin token / con query inocua
def test_direct_urls_keep_working_and_are_persisted_without_query_or_fragment(tmp_path):
    direct = "https://www.cnmv.es/AUDITA/2019/18290.pdf"
    site = Site()
    runner, layout = make_runner(tmp_path / "a", site, [{"ticker": "TEF", "name": "T", "fiscal_year": 2019, "doc_type": "CNMV_ANNUAL_REPORT", "url": direct}])
    c = runner.adapters["CNMV"].discover(DiscoveryRequest(authority="CNMV"))[0]
    assert c.transport_url is None and c.source_url == direct                         # sin secretos no hace falta transporte
    (out,) = run_all(runner)
    assert out.state == "COMPLETED" and str(site.requests[0].url) == direct
    assert json.loads(next(layout.manifests.rglob("*.json")).read_text(encoding="utf-8"))["source_url"] == direct
    # con una query "inocua" y un fragmento: se envían, pero NO se persisten
    q = direct + "?lang=es&v=2#top"
    site2 = Site()
    runner2, layout2 = make_runner(tmp_path / "b", site2, [{"ticker": "TEF", "name": "T", "fiscal_year": 2019, "doc_type": "CNMV_ANNUAL_REPORT", "url": q}])
    (out2,) = run_all(runner2)
    assert out2.state == "COMPLETED" and "lang=es" in str(site2.requests[0].url)
    blob = tree_bytes(layout2.root)
    assert b"lang=es" not in blob and b"#top" not in blob and b"?v=2" not in blob
    assert json.loads(next(layout2.manifests.rglob("*.json")).read_text(encoding="utf-8"))["source_url"] == direct


def test_stable_reference_and_split_helpers():
    assert split_url(STABLE) == (STABLE, None)
    s, tu = split_url(FULL)
    assert s == STABLE and isinstance(tu, TransportUrl)
    assert strip_url("https://u:p@www.cnmv.es:443/a/b?x=1#f") == "https://www.cnmv.es:443/a/b"
    ref = StableReference.from_url(FULL, authority="CNMV", issuer_id="TEF", fiscal_year=2020, registration_number="18760",
                                   document_family="ANNUAL_FINANCIAL_REPORT", declared_resource_kind="XHTML+ZIP",
                                   observed_at="2026-10-13T00:00:00+00:00")
    assert ref.stable_url == STABLE and ref.to_dict()["registration_number"] == "18760"
    assert_clean(json.dumps(ref.to_dict()))
    with pytest.raises(SecretLeakError):
        StableReference(authority="CNMV", issuer_id="TEF", fiscal_year=2020, registration_number=None, document_family="X",
                        declared_resource_kind=None, stable_host="www.cnmv.es", stable_path="/a?e=ABCDEFGH", observed_at="x")
    assert find_secret(redact_text(f"fallo {FULL} Authorization: Bearer abcdefgh12345 token=abcd1234")) is None


# ================================================================= 7. uso fuera de operación autorizada
def test_transport_url_can_only_be_revealed_inside_an_authorized_operation():
    t = TransportUrl(FULL)
    with pytest.raises(TransportViolation):
        t.reveal()
    with authorized_transport():
        assert TOK in t.reveal()
        seen = []

        def other():
            try:
                t.reveal()
                seen.append("LEAK")
            except TransportViolation:
                seen.append("blocked")
        th = threading.Thread(target=other)
        th.start()
        th.join()
        assert seen == ["blocked"]                                                    # otro hilo no hereda la autorización
    with pytest.raises(TransportViolation):
        t.reveal()


# ================================================================= 8. señal de sustitución
def test_replacement_signal_is_possible_republication_never_confirmed_and_never_overwrites(tmp_path):
    assert indicates_replacement("Certificado del secretario del consejo sobre la sustitución del informe financiero anual")
    assert not indicates_replacement("Certificado del secretario del consejo sobre la formulación y firma del informe financiero anual")
    sig = replacement_signal("Certificado sobre la sustitución del informe financiero anual", source="CNMV_IFA", registration_number="20484",
                             observed_at="2026-10-13T00:00:00+00:00")
    assert sig.kind == POSSIBLE_REPUBLICATION == "POSSIBLE_REPUBLICATION"
    with pytest.raises(Exception):
        ReplacementSignal("REPUBLICATION_CONFIRMED", "CNMV_IFA", "1", "x", "2026-10-13T00:00:00+00:00")
    with pytest.raises(SecretLeakError):
        ReplacementSignal(POSSIBLE_REPUBLICATION, "CNMV_IFA", "1", f"ver {FULL}", "2026-10-13T00:00:00+00:00")
    # el runner NO descarga ni reemplaza: revisión manual, ledger NEEDS_REVIEW
    direct = "https://www.cnmv.es/AUDITA/2019/18290.pdf"
    site = Site()
    runner, layout = make_runner(tmp_path, site, [{"ticker": "TEF", "name": "T", "fiscal_year": 2019, "doc_type": "CNMV_ANNUAL_REPORT", "url": direct}])
    (first,) = run_all(runner)
    assert first.state == "COMPLETED"
    raw = next((layout.raw).rglob("*.pdf"))
    before = (raw.read_bytes(), raw.stat().st_mtime_ns)
    cand = runner.adapters["CNMV"].discover(DiscoveryRequest(authority="CNMV"))[0]
    flagged = dataclasses.replace(cand, replacement_signals=(sig,))
    n = len(site.requests)
    out = runner.process_candidate(runner.adapters["CNMV"], flagged)
    assert out.state == "MANUAL_REVIEW" and out.error_class == POSSIBLE_REPUBLICATION and out.needs_manual_review
    assert len(site.requests) == n                                                    # sin una sola petición más
    assert (raw.read_bytes(), raw.stat().st_mtime_ns) == before                       # la versión previa no se toca
    led = CoverageLedger(layout.catalog_db, ExecutionMode.TEST)
    key = CoverageKey.from_candidate(cand)
    record_outcome(led, cand, first, run_id="r")
    res = record_outcome(led, flagged, out, run_id="r")
    assert res.status.value == "NEEDS_REVIEW"
    assert "REPUBLICATION_CONFIRMED" not in json.dumps(out.to_dict()) + tree_bytes(layout.root).decode("utf-8", errors="ignore")
    assert led.get(key).status.value == "NEEDS_REVIEW"


# ================================================================= 9. CNMV-U3 sigue bloqueado
def test_cnmv_u3_keeps_30_needs_review_cells_and_cannot_feed_downloads(tmp_path):
    from mod_01_ingestion.tests.test_unified_cnmv_u3 import run as u3_run
    root, site, out, f = u3_run(tmp_path)
    cells = out["cells"]
    assert len(cells) == 30 and {c["ledger_status"] for c in cells} == {"NEEDS_REVIEW"}
    assert {c["status"] for c in cells} == {"DISCOVERED_TOKENIZED"} and {c["cross_class"] for c in cells} == {"TOKENIZED_REQUIRES_APPROVAL"}
    assert all(c["republication_status"] in ("NONE_OBSERVED", POSSIBLE_REPUBLICATION) for c in cells)
    assert out["documents_downloaded"] == 0 and not [q for q in site.requests if "verdocumento" in q.url.path]
    for name in ("cnmv_u3.py", "cnmv_evidence.py"):
        tree = ast.parse((UNIFIED / name).read_text(encoding="utf-8"))
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | \
                   {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not ({"TransportUrl", "DownloadRequest", "DocumentCandidate", "DownloadService", "UnifiedIngestRunner"} & imported), name


# ================================================================= 10. arquitectura
DOMAIN = UNIFIED / "domain"


def test_domain_layer_stays_pure_with_no_io_http_or_cycles():
    forbidden = {"httpx", "requests", "socket", "urllib3", "duckdb", "shutil", "subprocess", "sqlite3"}
    for f in sorted(DOMAIN.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert m.split(".")[0] not in forbidden and m != "urllib.request", (f.name, m)
            assert not m.startswith("mod_01_ingestion.src.unified") or m.startswith("mod_01_ingestion.src.unified.domain"), (f.name, m)
    for name in ("transport.py", "republication.py"):
        text = (DOMAIN / name).read_text(encoding="utf-8")
        assert "open(" not in text and ".write" not in text and "mkdir" not in text and "os." not in text, name
    # transport no depende de models (sin ciclo): importarlo solo no carga models ni httpx
    code = ("import sys; import mod_01_ingestion.src.unified.domain.transport as t;"
            "print('httpx' in sys.modules, 'mod_01_ingestion.src.unified.domain.models' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True).stdout.split()
    assert out == ["False", "False"], out


def test_only_the_download_service_reveals_the_transport_url():
    users = []
    for f in sorted(UNIFIED.rglob("*.py")):
        if "reveal(" in f.read_text(encoding="utf-8") and f.name != "transport.py":
            users.append(f.name)
    assert users == ["download_service.py"], users


def test_defense_in_depth_guards_catch_what_redaction_misses(tmp_path):
    runner, _ = make_runner(tmp_path, Site())
    with pytest.raises(SecretLeakError):                       # la redacción no conoce este parámetro: la guarda de telemetría cierra
        runner.telemetry.emit("probe2", None, "test", note="x-amz-signature=abcdef123456")
    assert not [e for e in runner.telemetry.read_all() if e["event"] == "probe2"]
    for bad in ("page.aspx?e=ABCDEFGH1234", "...&e=ABCDEFGH1234", "foo;e=ABCDEFGH1234"):
        assert find_secret(bad) is not None, bad
    from mod_01_ingestion.src.unified.domain.errors import sanitize_message
    msg = sanitize_message(f"fallo en {FULL} y en https://www.cnmv.es/x?y=1#z")
    assert "?" not in msg and "#" not in msg and "<redacted>" not in msg and TOK not in msg and "https://www.cnmv.es/x" in msg
