"""
CNMV-U4 FINAL — Sin reanudación para transportes efímeros (URL con query/token): cada intento empieza desde cero en un parcial propio, nunca
se envía Range/If-Range, no hay ``.part.meta`` y un parcial ajeno jamás se incorpora ni se toca. Las URL directas sin query conservan su
reanudación. Offline: httpx.MockTransport, tmp_path y SOLO tokens sintéticos.
"""
import hashlib
import json
from pathlib import Path

import httpx

from mod_01_ingestion.src.unified.domain.models import DownloadRequest
from mod_01_ingestion.src.unified.download_service import DownloadService, _write_part_meta
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.tests.test_unified_token_safe import (
    FULL, LEAKS, PDF, STABLE, TOK, Site, assert_clean, make_runner, ok, run_all, tree_bytes)

BASE = "https://www.cnmv.es/webservices/verdocumento/ver"
DATA_A = b"%PDF-1.4\n" + b"AAAA-contenido-del-documento-A\n" * 120 + b"%%EOF\n"
DATA_B = b"%PDF-1.4\n" + b"BBBB-contenido-del-documento-B\n" * 130 + b"%%EOF\n"


def url(tok, extra=""):
    return f"{BASE}?e={tok}{extra}"


class Cut(httpx.SyncByteStream):
    """Entrega una parte del cuerpo y corta la conexión."""
    def __init__(self, data, cut):
        self.data, self.cut = data, cut

    def __iter__(self):
        yield self.data[:self.cut]
        raise httpx.ReadError("conexión cortada")


def tokens_site(plan):
    """plan: {token: [respuesta_o_callable, ...]}  (la última se repite). Cada petición se registra con sus cabeceras."""
    seen = {}

    def handler(request):
        t = request.url.params.get("e")
        n = seen.get(t, 0)
        seen[t] = n + 1
        seq = plan[t]
        item = seq[min(n, len(seq) - 1)]
        return item(request) if callable(item) else item
    return Site(handler)


def service(site, retries=1):
    return DownloadService(client=site.client(), sleep=lambda s: None, max_retries=retries, initial_backoff_s=0.0,
                           rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))


def dl(svc, staging, name, u):
    return svc.download(DownloadRequest(url=u, staging_dir=str(staging), file_name=name))


def full(data):
    return httpx.Response(200, content=data, headers={"content-type": "application/pdf"})


def cut(data, at):
    return httpx.Response(200, stream=Cut(data, at), headers={"content-type": "application/pdf"})


def headers_of(site):
    return [{k.lower(): v for k, v in r.headers.items()} for r in site.requests]


# ================================================================= bytes distintos nunca se mezclan
def test_two_transports_with_same_host_path_but_different_tokens_never_mix_bytes(tmp_path):
    site = tokens_site({"TOKA": [cut(DATA_A, 700), full(DATA_A)], "TOKB": [full(DATA_B)]})
    svc, stg = service(site), tmp_path / "stg"
    a = dl(svc, stg, "doc.pdf", url("TOKA"))
    assert a.ok and a.sha256 == hashlib.sha256(DATA_A).hexdigest() and (stg / "doc.pdf").read_bytes() == DATA_A
    b = dl(svc, stg, "doc.pdf", url("TOKB"))
    assert b.ok and b.sha256 == hashlib.sha256(DATA_B).hexdigest() and b.sha256 != a.sha256
    assert (stg / "doc.pdf").read_bytes() == DATA_B                              # solo B: nada de A en B
    assert b"AAAA" not in (stg / "doc.pdf").read_bytes() and not b.resumed
    assert sorted(p.name for p in stg.iterdir()) == ["doc.pdf"]                  # ni .part ni .part.meta sobrantes


def test_an_interrupted_tokenized_transport_leaves_no_partial_that_could_contaminate_the_next_one(tmp_path):
    site = tokens_site({"TOKA": [cut(DATA_A, 900)], "TOKB": [full(DATA_B)]})     # A siempre se corta (sin reintentos)
    svc, stg = service(site, retries=0), tmp_path / "stg"
    a = dl(svc, stg, "doc.pdf", url("TOKA"))
    assert not a.ok and a.error_class == "NETWORK"
    assert list(stg.iterdir()) == []                                              # el parcial propio se descartó
    b = dl(svc, stg, "doc.pdf", url("TOKB"))
    assert b.ok and (stg / "doc.pdf").read_bytes() == DATA_B and b"AAAA" not in (stg / "doc.pdf").read_bytes()


# ================================================================= el reintento empieza desde cero
def test_retry_after_interruption_restarts_from_zero_without_range_or_if_range(tmp_path):
    site = tokens_site({"TOKA": [cut(DATA_A, 1500), full(DATA_A)]})
    res = dl(service(site), tmp_path / "stg", "doc.pdf", url("TOKA"))
    assert res.ok and res.retries_taken == 1 and not res.resumed and res.size_bytes == len(DATA_A)
    assert (tmp_path / "stg" / "doc.pdf").read_bytes() == DATA_A                  # exactamente el cuerpo del 2.º intento
    hs = headers_of(site)
    assert len(hs) == 2 and all("range" not in h and "if-range" not in h for h in hs)


def test_no_tokenized_request_ever_carries_range_even_if_the_adapter_asks_for_it(tmp_path):
    site = tokens_site({"TOKA": [httpx.Response(429, content=b"x"), cut(DATA_A, 100), full(DATA_A)]})
    svc = service(site, retries=3)
    req = DownloadRequest(url=url("TOKA"), staging_dir=str(tmp_path / "s"), file_name="d.pdf",
                          headers={"Range": "bytes=10-", "If-Range": "etag"}, allow_resume=True)
    res = svc.download(req)
    assert res.ok and (tmp_path / "s" / "d.pdf").read_bytes() == DATA_A
    hs = headers_of(site)
    assert len(hs) == 3 and all("range" not in h and "if-range" not in h for h in hs)


def test_query_bearing_direct_urls_are_treated_as_sensitive_transport_too(tmp_path):
    site = tokens_site({"x": [cut(DATA_A, 300), full(DATA_A)]})
    u = f"{BASE}?e=x#frag"
    res = dl(service(site), tmp_path / "s", "d.pdf", u)
    assert res.ok and all("range" not in h and "if-range" not in h for h in headers_of(site))
    assert list(p.name for p in (tmp_path / "s").iterdir()) == ["d.pdf"]


# ================================================================= un parcial anterior no se incorpora ni se toca
def test_a_previous_partial_identified_only_by_host_and_path_is_not_reused_nor_touched(tmp_path):
    stg = tmp_path / "stg"
    stg.mkdir()
    part, meta = stg / "doc.pdf.part", stg / "doc.pdf.part.meta"
    part.write_bytes(b"%PDF-1.4\nPARCIAL-AJENO-DE-OTRO-TOKEN\n")
    _write_part_meta(meta, hashlib.sha256(STABLE.encode()).hexdigest()[:32], httpx.Headers({"etag": '"ajeno"'}))
    before = (part.read_bytes(), meta.read_bytes(), part.stat().st_mtime_ns, meta.stat().st_mtime_ns)
    site = tokens_site({"TOKB": [full(DATA_B)]})
    res = dl(service(site), stg, "doc.pdf", url("TOKB"))
    assert res.ok and (stg / "doc.pdf").read_bytes() == DATA_B and b"PARCIAL-AJENO" not in (stg / "doc.pdf").read_bytes()
    assert (part.read_bytes(), meta.read_bytes(), part.stat().st_mtime_ns, meta.stat().st_mtime_ns) == before   # archivos ajenos intactos
    assert all("range" not in h and "if-range" not in h for h in headers_of(site))


# ================================================================= las URL directas sin query conservan la reanudación
def test_direct_urls_without_query_keep_their_safe_resume(tmp_path):
    direct = "https://www.cnmv.es/AUDITA/2019/18290.pdf"
    stg = tmp_path / "stg"
    stg.mkdir()
    half = DATA_A[:1000]
    (stg / "doc.pdf.part").write_bytes(half)
    _write_part_meta(stg / "doc.pdf.part.meta", hashlib.sha256(direct.encode()).hexdigest()[:32], httpx.Headers({"etag": '"v1"'}))

    def handler(request):
        rng = request.headers.get("range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return httpx.Response(206, content=DATA_A[start:], headers={
                "content-type": "application/pdf", "content-range": f"bytes {start}-{len(DATA_A) - 1}/{len(DATA_A)}"})
        return full(DATA_A)
    site = Site(handler)
    res = service(site).download(DownloadRequest(url=direct, staging_dir=str(stg), file_name="doc.pdf"))
    assert res.ok and res.resumed and (stg / "doc.pdf").read_bytes() == DATA_A
    h = headers_of(site)[0]
    assert h["range"] == "bytes=1000-" and h["if-range"] == '"v1"'


# ================================================================= nada de tokens en ningún rastro + referencia estable íntegra
def test_no_token_in_partial_meta_errors_reports_catalog_manifest_or_telemetry_and_stable_reference_is_kept(tmp_path):
    seen = {"n": 0}

    def handler(request):
        seen["n"] += 1
        assert "range" not in request.headers and "if-range" not in request.headers
        return cut(PDF, 400) if seen["n"] == 1 else ok()
    site = Site(handler)
    rec = {"ticker": "TEF", "name": "Telefonica", "fiscal_year": 2020, "doc_type": "CNMV_ANNUAL_REPORT", "url": FULL,
           "registration_number": "18760", "declared_resource_kind": "XHTML+ZIP/XBRL (declarado, sin verificar)"}
    runner, layout = make_runner(tmp_path, site, [rec])
    (out,) = run_all(runner)
    assert out.state == "COMPLETED" and seen["n"] == 2
    blob = tree_bytes(layout.root)
    assert_clean(blob)
    assert not list(layout.staging.rglob("*.part*")) and not list(layout.root.rglob("*.part.meta"))
    man = json.loads(next(layout.manifests.rglob("*.json")).read_text(encoding="utf-8"))
    assert man["registration_number"] == "18760" and man["declared_resource_kind"].startswith("XHTML+ZIP")
    assert man["source_url"] == STABLE and man["final_url"] == STABLE
    cand = runner.adapters["CNMV"].discover(__import__("mod_01_ingestion.src.unified.models", fromlist=["DiscoveryRequest"]).DiscoveryRequest(authority="CNMV"))[0]
    ref = cand.stable_reference("2026-10-14T00:00:00+00:00")
    assert (ref.authority, ref.issuer_id, ref.fiscal_year, ref.registration_number) == ("CNMV", "TEF", 2020, "18760")
    assert ref.stable_url == STABLE and ref.declared_resource_kind.startswith("XHTML+ZIP")
    assert_clean(json.dumps(ref.to_dict()) + repr(cand) + json.dumps(out.to_dict(), default=str))
    for leak in LEAKS:
        assert leak.encode() not in blob, leak
    assert TOK.encode() not in b"".join(p.read_bytes() for p in Path(layout.root).rglob("*") if p.is_file())
