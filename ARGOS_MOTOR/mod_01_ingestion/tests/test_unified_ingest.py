"""
FASE 4 — Suite de no regresión del núcleo unificado. Sin red real (httpx.MockTransport),
todo bajo ``tmp_path``. Cada test está mapeado en 08_UNIFICATION_TEST_MATRIX.csv (UT-xx).
"""
import io
import json
import os
import threading
import zipfile
import zlib
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.document_completeness_validator import DocumentCompletenessValidator
from mod_01_ingestion.src.unified.adapters.bafin import BaFinAdapter
from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.config import DataLayout, PathPolicyError, resolve_layout
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.lock_manager import LockManager, LockTimeout
from mod_01_ingestion.src.unified.models import DiscoveryRequest, DownloadRequest, JobState
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.repositories import CatalogRepository, ManifestRepository
from mod_01_ingestion.src.unified.source_adapter import SourceAdapter, get_adapter, registered_authorities
from mod_01_ingestion.src.unified.telemetry import REQUIRED_FIELDS


# ---------------------------------------------------------------- fixtures sintéticas de TEST
def make_pdf(pages: int = 12, tag: str = "A") -> bytes:
    body = b"%PDF-1.7\n" + b"".join(b"%d 0 obj\n<< /Type /Page /X %s >>\nendobj\n" % (i, tag.encode()) for i in range(pages))
    return body + b"%%EOF\n"


def make_zip(tag: str = "A") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.xhtml", f"<html><body>informe {tag} " + "x" * 400 + "</body></html>")
        zf.writestr("taxonomy.xsd", "<schema/>" + tag)
    return buf.getvalue()


def make_corrupt_zip() -> bytes:
    data = bytearray(make_zip("C"))
    for i in range(40, min(len(data) - 80, 140)):   # destruye el flujo deflate
        data[i] ^= 0xFF
    return bytes(data)


ERROR_HTML = b"<html><head><title>Error 404 not found</title></head><body><h1>Error</h1></body></html>"


class FakeSite:
    """Servidor simulado: ruta -> lista de respuestas (la última se repite)."""

    def __init__(self, routes):
        self.routes = {k: (v if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, dict(request.headers)))
        seq = self.routes.get(request.url.path)
        if seq is None:
            return httpx.Response(404, content=b"nope")
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return item


def client_for(site) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(site), follow_redirects=True)


def ok(content: bytes, ctype="application/octet-stream", **headers):
    return httpx.Response(200, content=content, headers={"content-type": ctype, **headers})


def provider_for(records):
    return lambda req: list(records)


def make_runner(tmp_path, site, adapters=None, **kw):
    layout = DataLayout(tmp_path / "data_root")
    svc = DownloadService(client=client_for(site), sleep=lambda s: None, initial_backoff_s=0.0, max_retries=3,
                          rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    cnmv = CNMVAdapter(provider_for([
        {"lei": "LEI_ES_1", "ticker": "SAN", "name": "Banco X", "fiscal_year": 2023, "doc_type": "ESEF_PACKAGE",
         "url": "https://cnmv.test/pkg/san2023.zip"}]))
    bafin = BaFinAdapter([provider_for([
        {"ticker": "SAP", "isin": "DE0007164600", "name": "SAP", "fiscal_year": 2023, "doc_type": "ANNUAL_REPORT",
         "url": "https://eqs.test/ar/sap2023.pdf"}])])
    runner = UnifiedIngestRunner(layout, adapters or {"CNMV": cnmv, "BAFIN": bafin}, download=svc, **kw)
    return runner, layout, svc


def base_site(zip_bytes=None, pdf_bytes=None):
    return FakeSite({"/pkg/san2023.zip": ok(zip_bytes or make_zip(), "application/zip"),
                     "/ar/sap2023.pdf": ok(pdf_bytes or make_pdf(), "application/pdf")})


def run_both(runner):
    a = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    b = runner.run_discovery(DiscoveryRequest(authority="BAFIN"))
    return a, b


# ---------------------------------------------------------------- UT-01..04: vertical slice, mismo servicio
def test_ut01_ut02_vertical_slice_two_authorities_same_core(tmp_path):
    runner, layout, svc = make_runner(tmp_path, base_site())
    a, b = run_both(runner)
    assert a.outcomes[0].state == JobState.COMPLETED.value
    assert b.outcomes[0].state == JobState.COMPLETED.value
    for o in (a.outcomes[0], b.outcomes[0]):
        assert Path(o.raw_path).exists()
        assert (layout.cas / o.sha256[:2] / o.sha256).exists()
    assert runner.catalog.count() == 2


def test_ut03_same_download_service_for_both_authorities(tmp_path, monkeypatch):
    runner, _, svc = make_runner(tmp_path, base_site())
    for ad in runner.adapters.values():       # los adapters no tienen lógica de descarga propia
        assert not hasattr(ad, "download") and not hasattr(ad, "downloader")
    seen = []
    orig = DownloadService.download

    def spy(self, req, job=None):
        seen.append((id(self), job.authority))
        return orig(self, req, job)
    monkeypatch.setattr(DownloadService, "download", spy)
    run_both(runner)
    assert {a for _, a in seen} == {"CNMV", "BAFIN"}
    assert len({i for i, _ in seen}) == 1 and seen[0][0] == id(svc)    # UNA instancia, dos autoridades


def test_ut04_same_manifest_and_telemetry_schema(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site())
    run_both(runner)
    mans = [json.loads(p.read_text(encoding="utf-8")) for p in layout.manifests.rglob("*.json")]
    assert len(mans) == 2
    assert set(mans[0].keys()) == set(mans[1].keys())
    assert {m["authority"] for m in mans} == {"CNMV", "BAFIN"}
    for ev in runner.telemetry.read_all():
        for f in REQUIRED_FIELDS:
            assert f in ev
    jobs = {e["job_id"] for e in runner.telemetry.read_all() if e["job_id"]}
    assert len(jobs) == 2 and all(j.startswith(runner.run.run_id) for j in jobs)


# ---------------------------------------------------------------- UT-05 idempotencia
def test_ut05_idempotence_no_redownload(tmp_path):
    site = base_site()
    runner, layout, _ = make_runner(tmp_path, site)
    run_both(runner)
    n_calls = len(site.calls)
    a, b = run_both(runner)
    assert a.outcomes[0].state == JobState.SKIPPED_DUPLICATE.value
    assert b.outcomes[0].state == JobState.SKIPPED_DUPLICATE.value
    assert len(site.calls) == n_calls
    assert len([p for p in layout.raw.rglob("*") if p.is_file()]) == 2


# ---------------------------------------------------------------- UT-06/07 ZIP corrupto, HTML disfrazado
def test_ut06_corrupt_zip_quarantined_no_raw(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site(zip_bytes=make_corrupt_zip()))
    a = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    assert a.outcomes[0].state == JobState.QUARANTINED.value
    assert not any(layout.raw.rglob("*.zip"))
    assert list(layout.quarantine.rglob("*.quarantine_reason.json"))


def test_ut06b_defect01_zlib_error_does_not_crash_validator(tmp_path, monkeypatch):
    p = tmp_path / "x.zip"
    p.write_bytes(make_zip())

    def boom(self):
        raise zlib.error("Error -3 while decompressing data: invalid stored block lengths")
    monkeypatch.setattr(zipfile.ZipFile, "testzip", boom)
    res = DocumentCompletenessValidator().validate_document(p)
    assert res["should_quarantine"] and res["completeness_status"] == "INVALID_FORMAT"


def test_ut07_disguised_html_error_page(tmp_path):
    site = FakeSite({"/pkg/san2023.zip": ok(ERROR_HTML, "application/zip"),
                     "/ar/sap2023.pdf": ok(ERROR_HTML, "application/pdf")})
    runner, layout, _ = make_runner(tmp_path, site)
    a, b = run_both(runner)
    for r in (a, b):
        assert r.outcomes[0].state == JobState.QUARANTINED.value
        assert r.outcomes[0].error_class == "DISGUISED_HTML"
    assert not any(layout.raw.rglob("*.*"))


# ---------------------------------------------------------------- UT-08..10 timeout / 429 / 5xx
def test_ut08_timeout_retries_then_classified(tmp_path):
    site = FakeSite({"/pkg/san2023.zip": httpx.ReadTimeout("slow"), "/ar/sap2023.pdf": ok(make_pdf())})
    runner, _, _ = make_runner(tmp_path, site)
    a = runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    assert a.outcomes[0].state == JobState.FAILED.value and a.outcomes[0].error_class == "TIMEOUT"
    assert len([c for c in site.calls if c[0] == "/pkg/san2023.zip"]) == 4  # 1 + 3 reintentos


def test_ut09_429_respects_retry_after(tmp_path):
    sleeps = []
    site = FakeSite({"/pkg/san2023.zip": [httpx.Response(429, headers={"retry-after": "7"}), ok(make_zip())],
                     "/ar/sap2023.pdf": ok(make_pdf())})
    layout = DataLayout(tmp_path / "dr")
    svc = DownloadService(client=client_for(site), sleep=sleeps.append, initial_backoff_s=0.0, max_retries=3,
                          rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    r = UnifiedIngestRunner(layout, {"CNMV": make_runner(tmp_path / "z", site)[0].adapters["CNMV"]}, download=svc)
    out = r.run_discovery(DiscoveryRequest(authority="CNMV"))
    assert out.outcomes[0].state == JobState.COMPLETED.value
    assert max(sleeps) >= 7


def test_ut10_5xx_preserves_real_status(tmp_path):
    site = FakeSite({"/pkg/san2023.zip": httpx.Response(503), "/ar/sap2023.pdf": ok(make_pdf())})
    runner, _, svc = make_runner(tmp_path, site)
    res = svc.download(DownloadRequest(url="https://cnmv.test/pkg/san2023.zip", staging_dir=str(tmp_path / "s"),
                                       file_name="a.zip"))
    assert not res.ok and res.http_status == 503 and res.error_class == "HTTP_TRANSIENT"   # DEFECT-02


def test_ut10b_4xx_single_attempt(tmp_path):
    site = FakeSite({"/pkg/san2023.zip": httpx.Response(403)})
    runner, _, svc = make_runner(tmp_path, site)
    res = svc.download(DownloadRequest(url="https://cnmv.test/pkg/san2023.zip", staging_dir=str(tmp_path / "s"),
                                       file_name="a.zip"))
    assert res.error_class == "HTTP_PERMANENT" and res.http_status == 403 and len(site.calls) == 1


# ---------------------------------------------------------------- UT-11 locks
def test_ut11_concurrent_lock_blocks_second_worker(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site(), lock_timeout_s=0.2)
    cand = runner.adapters["CNMV"].discover(DiscoveryRequest(authority="CNMV"))[0]
    with runner.locks.acquire(f"doc-{cand.document_id}"):
        out = runner.process_candidate(runner.adapters["CNMV"], cand)
    assert out.state == JobState.FAILED.value and out.error_class == "LOCKED"
    assert not any(layout.raw.rglob("*.*"))
    out2 = runner.process_candidate(runner.adapters["CNMV"], cand)  # tras liberar, procede
    assert out2.state == JobState.COMPLETED.value


def test_ut11b_stale_lock_recovered(tmp_path):
    t = [1000.0]
    lm = LockManager(tmp_path / "l", stale_after_s=10, clock=lambda: t[0], sleep=lambda s: None)
    p = lm._path("k"); p.write_text("{}")
    os.utime(p, (500, 500))
    with lm.acquire("k", timeout_s=1):
        pass


# ---------------------------------------------------------------- UT-12 promoción atómica / .part / resume
def test_ut12_interrupted_download_leaves_only_part_then_resumes(tmp_path):
    """Un proceso previo murió a mitad: solo existe ``.part``; el siguiente intento reanuda con Range."""
    payload = make_pdf(40)
    cut = len(payload) // 2
    st = tmp_path / "st"; st.mkdir()
    (st / "a.pdf.part").write_bytes(payload[:cut])
    assert not (st / "a.pdf").exists()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") == f"bytes={cut}-"
        return httpx.Response(206, content=payload[cut:], headers={"content-type": "application/pdf"})

    svc = DownloadService(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None,
                          initial_backoff_s=0.0, rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    res = svc.download(DownloadRequest(url="https://h.test/a.pdf", staging_dir=str(st), file_name="a.pdf"))
    import hashlib
    assert res.ok and res.resumed
    assert res.sha256 == hashlib.sha256(payload).hexdigest()
    assert not (st / "a.pdf.part").exists()          # .part renombrado atómicamente


def test_ut12b_no_final_file_while_failing(tmp_path):
    site = FakeSite({"/x.pdf": httpx.ConnectError("down")})
    svc = DownloadService(client=client_for(site), sleep=lambda s: None, initial_backoff_s=0.0, max_retries=1,
                          rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    res = svc.download(DownloadRequest(url="https://h.test/x.pdf", staging_dir=str(tmp_path / "st"), file_name="x.pdf"))
    assert not res.ok and res.error_class == "NETWORK"
    assert not (tmp_path / "st" / "x.pdf").exists()                # DEFECT-05: nada final sin verificación


# ---------------------------------------------------------------- UT-13/14 fallo de manifiesto/catálogo (2PC)
class FailingManifests(ManifestRepository):
    def stage(self, rec):
        raise OSError("disk full (simulado)")


class FailingCatalog(CatalogRepository):
    def upsert(self, rec):
        raise RuntimeError("duckdb locked (simulado)")


def _no_orphans(layout):
    return not any(p.is_file() for p in layout.raw.rglob("*")) and \
        not any(p.is_file() for p in layout.cas.rglob("*")) and not any(layout.manifests.rglob("*.pending"))


def test_ut13_manifest_failure_rolls_back_raw(tmp_path):
    layout = DataLayout(tmp_path / "data_root")
    runner, _, _ = make_runner(tmp_path, base_site(), manifests=FailingManifests(layout))
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == JobState.FAILED.value and out.error_class == "MANIFEST_FAILED"
    assert _no_orphans(layout)


def test_ut14_catalog_failure_rolls_back_raw_and_manifest(tmp_path):
    layout = DataLayout(tmp_path / "data_root")
    cat = FailingCatalog(layout.catalog_db)
    runner, _, _ = make_runner(tmp_path, base_site(), catalog=cat)
    out = runner.run_discovery(DiscoveryRequest(authority="CNMV")).outcomes[0]
    assert out.state == JobState.FAILED.value and out.error_class == "CATALOG_FAILED"
    assert _no_orphans(layout) and not list(layout.manifests.rglob("*.json"))


# ---------------------------------------------------------------- UT-15 cero escritura fuera del root
def test_ut15_zero_writes_outside_data_root(tmp_path):
    sentinel = tmp_path / "outside"; sentinel.mkdir(); (sentinel / "keep.txt").write_text("x")
    before = sorted(str(p) for p in sentinel.rglob("*"))
    runner, layout, _ = make_runner(tmp_path / "nest", base_site())
    run_both(runner)
    assert sorted(str(p) for p in sentinel.rglob("*")) == before
    with pytest.raises(PathPolicyError):
        layout.assert_inside(tmp_path / "outside" / "x")


def test_ut16_no_default_root_hardcoded(monkeypatch):
    monkeypatch.delenv("ARGOS_DATA_ROOT", raising=False)
    with pytest.raises(PathPolicyError):
        resolve_layout(None)
    with pytest.raises(PathPolicyError):
        resolve_layout("relative/path")
    monkeypatch.setenv("ARGOS_DATA_ROOT", str(Path.cwd().anchor + "tmp_root_x"))
    assert resolve_layout().root.name == "tmp_root_x"


# ---------------------------------------------------------------- UT-17 CAS / dedup / inmutabilidad raw
def test_ut17_cas_dedup_identical_content_two_documents(tmp_path):
    same = make_pdf(12, "SAME")
    site = FakeSite({"/pkg/san2023.zip": ok(same, "application/pdf"), "/ar/sap2023.pdf": ok(same, "application/pdf")})
    runner, layout, _ = make_runner(tmp_path, site)
    runner.adapters["CNMV"]._provider = provider_for([
        {"lei": "L1", "ticker": "SAN", "fiscal_year": 2023, "doc_type": "IAGC", "url": "https://cnmv.test/pkg/san2023.zip"}])
    # el nombre .zip con contenido PDF debe rechazarse por firma; usar extensión coherente:
    site.routes["/pkg/san2023.pdf"] = [ok(same, "application/pdf")]
    runner.adapters["CNMV"]._provider = provider_for([
        {"lei": "L1", "ticker": "SAN", "fiscal_year": 2023, "doc_type": "IAGC", "url": "https://cnmv.test/pkg/san2023.pdf"}])
    run_both(runner)
    blobs = [p for p in layout.cas.rglob("*") if p.is_file()]
    assert len(blobs) == 1
    raws = [p for p in layout.raw.rglob("*") if p.is_file()]
    assert len(raws) == 2
    m = [json.loads(p.read_text(encoding="utf-8")) for p in layout.manifests.rglob("*.json")]
    assert sum(1 for x in m if x["deduplicated"]) == 1


def test_ut17b_raw_never_overwritten_with_different_content(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site())
    runner.run_discovery(DiscoveryRequest(authority="CNMV"))
    raw = next(layout.raw.rglob("*.zip"))
    original = raw.read_bytes()
    # nuevo contenido para el mismo nombre/ruta lógica (otro run, otro manifiesto)
    site2 = base_site(zip_bytes=make_zip("OTRO"))
    runner2, _, _ = make_runner(tmp_path, site2)
    runner2.manifests.path_for("CNMV", 2023, "CNMV_LEI_ES_1_2023_ESEF_PACKAGE").unlink()
    runner2.run_discovery(DiscoveryRequest(authority="CNMV"))
    assert raw.read_bytes() == original
    assert len(list(raw.parent.glob("*.zip"))) == 2


# ---------------------------------------------------------------- UT-18 rate limiter
def test_ut18_domain_concurrency_limit():
    rl = DomainRateLimiter(max_concurrent_per_domain=2, min_interval_s=0, sleep=lambda s: None)
    gate = threading.Barrier(1)
    import time

    def worker():
        with rl.slot("https://one.test/a"):
            time.sleep(0.05)
    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert rl.peak_concurrency["one.test"] <= 2


def test_ut18b_min_interval_enforced():
    now = [0.0]; waits = []
    rl = DomainRateLimiter(max_concurrent_per_domain=1, min_interval_s=1.0, clock=lambda: now[0], sleep=waits.append)
    with rl.slot("https://a.test/x"): pass
    with rl.slot("https://a.test/y"): pass
    assert waits and abs(waits[0] - 1.0) < 1e-6


# ---------------------------------------------------------------- UT-19 contrato de adapters
def test_ut19_adapters_satisfy_protocol_and_registry():
    assert isinstance(CNMVAdapter(lambda r: []), SourceAdapter)
    assert isinstance(BaFinAdapter([]), SourceAdapter)
    assert {"CNMV", "BAFIN"} <= set(registered_authorities())
    assert get_adapter("cnmv").authority == "CNMV"


def test_ut20_bafin_adapter_reads_real_config_without_network():
    cfg = Path(__file__).resolve().parents[2] / "config" / "eqs_verified_links.json"
    if not cfg.exists():
        pytest.skip("config/eqs_verified_links.json no disponible")
    from mod_01_ingestion.src.unified.adapters.bafin import EqsVerifiedLinksProvider
    ad = BaFinAdapter([EqsVerifiedLinksProvider(cfg)])
    cands = ad.discover(DiscoveryRequest(authority="BAFIN", fiscal_years=[2020], limit=5))
    assert cands and all(c.fiscal_year == 2020 and c.source_url.startswith("http") for c in cands)
    md = ad.fetch_metadata(cands[0])
    assert md.file_name.startswith("DE_BAFIN_") and md.expected_kind in ("PDF", "ZIP", "HTML", None)


def test_ut21_legacy_bafin_client_delegates_to_unified(tmp_path):
    """LEGACY_BRIDGE: BaFinClient.download_filing ya no descarga con lógica propia."""
    import warnings
    from mod_01_ingestion.src.de_bafin_client import BaFinClient
    site = FakeSite({"/f/x.zip": ok(make_zip("L"), "application/zip")})
    root = tmp_path / "root"
    client = BaFinClient(download_dir=root / "raw" / "DE_BAFIN")
    import mod_01_ingestion.src.unified.legacy_bridge as lb
    orig = lb.UnifiedIngestRunner

    def factory(layout, adapters):
        svc = DownloadService(client=client_for(site), sleep=lambda s: None,
                              rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
        return orig(layout, adapters, download=svc)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        res = lb.bafin_download_filing_via_unified(client.download_dir, "https://h.test/f/x.zip", "LEI1", 2022,
                                                    ticker="T", runner_factory=factory)
    assert any(issubclass(x.category, DeprecationWarning) for x in w)
    assert res["status"] == "RAW" and Path(res["file_path"]).exists() and len(res["sha256_hash"]) == 64
    assert (root / "manifests" / "BAFIN" / "2022").exists()


def test_ut22_legacy_robust_downloader_preserves_status_defect02(tmp_path, monkeypatch):
    """Parche mínimo sobre el downloader Track B legacy (bridge): el 503 agotado conserva su status."""
    from mod_01_ingestion.src.robust_downloader import DownloadError, RobustDownloader
    site = FakeSite({"/x": httpx.Response(503)})
    rd = RobustDownloader(max_retries=1, initial_backoff_s=0.0, max_backoff_s=0.0)
    import mod_01_ingestion.src.robust_downloader as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    with pytest.raises(DownloadError) as ei:
        rd.download_to_file("https://h.test/x", tmp_path / "x.bin", client=client_for(site))
    assert ei.value.status_code == 503 and ei.value.error_type == "HTTP_503"


# ---------------------------------------------------------------- Fase 5: controles de piloto
def test_ut23_redirect_to_unapproved_domain_blocked(tmp_path):
    def handler(request):
        if request.url.host == "a.test":
            return httpx.Response(302, headers={"location": "https://evil.test/x.pdf"})
        return ok(make_pdf(), "application/pdf")
    svc = DownloadService(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
                          sleep=lambda s: None, rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    res = svc.download(DownloadRequest(url="https://a.test/x.pdf", staging_dir=str(tmp_path), file_name="x.pdf",
                                       allowed_domains=["a.test"]))
    assert not res.ok and res.error_class == "REDIRECT_NOT_ALLOWED"
    assert not list(tmp_path.glob("x.pdf*"))


def test_ut24_max_bytes_enforced_streaming_and_header(tmp_path):
    big = make_pdf(2000)
    site = FakeSite({"/big.pdf": ok(big, "application/pdf")})
    svc = DownloadService(client=client_for(site), sleep=lambda s: None,
                          rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    res = svc.download(DownloadRequest(url="https://a.test/big.pdf", staging_dir=str(tmp_path), file_name="b.pdf",
                                       max_bytes=1000))
    assert not res.ok and res.error_class == "SIZE_EXCEEDED"
    assert not list(tmp_path.glob("b.pdf*"))


def test_ut25_http_response_telemetry_logged(tmp_path):
    runner, layout, _ = make_runner(tmp_path, base_site())
    run_both(runner)
    ev = [e for e in runner.telemetry.read_all() if e["event"] == "http_response"]
    assert len(ev) == 2 and all(e["job_id"] and e["status"] == 200 for e in ev)
