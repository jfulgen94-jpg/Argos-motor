"""
U2 — Descarga segura e ingestión atómica: streaming a ``.part``, fsync + rename atómico, reanudación segura, HTTP 429/403/5xx,
Retry-After, timeouts, límites de tamaño, Zip Slip / bombas, cuarentena y no promoción ante validación fallida.

Offline y determinista: HTTP simulado con ``httpx.MockTransport`` (ningún socket), sleeps y relojes inyectados, todo en tmp_path.
"""
import hashlib
import io
import random
import stat
import zipfile
from email.utils import formatdate
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import download_service as ds
from mod_01_ingestion.src.unified.download_service import DownloadService, _parse_retry_after
from mod_01_ingestion.src.unified.models import DownloadRequest, SourceMetadata
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.reconciler import UnifiedReconciler
from mod_01_ingestion.src.unified.validation_pipeline import ValidationPipeline, inspect_zip_safety
from mod_01_ingestion.tests.test_unified_ingest import ERROR_HTML, make_corrupt_zip, make_pdf, make_zip
from mod_01_ingestion.tests.test_unified_versions import cand, go, mk

URL = "https://h.test/a.pdf"
PAYLOAD = make_pdf(60)
ZIP_OK = make_zip("U2")


class Chunks(httpx.SyncByteStream):
    """Cuerpo en trozos; puede observar cada trozo y/o romperse a mitad (conexión caída)."""

    def __init__(self, chunks, on_chunk=None, fail=None):
        self.chunks, self.on_chunk, self.fail = chunks, on_chunk, fail

    def __iter__(self):
        for i, c in enumerate(self.chunks):
            if self.on_chunk:
                self.on_chunk(i)
            yield c
        if self.fail:
            raise self.fail


def split(data: bytes, n: int):
    step = max(1, len(data) // n)
    return [data[i:i + step] for i in range(0, len(data), step)]


def service(handler, sleeps=None, **kw):
    sleeps = sleeps if sleeps is not None else []
    kw.setdefault("initial_backoff_s", 1.0)
    kw.setdefault("chunk_size", 512)
    return DownloadService(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append,
                           rng=random.Random(7), rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None),
                           **kw), sleeps


def req(st, name="a.pdf", **kw):
    return DownloadRequest(url=kw.pop("url", URL), staging_dir=str(st), file_name=name, **kw)


def ok_resp(data=PAYLOAD, **headers):
    return httpx.Response(200, content=data, headers={"content-type": "application/pdf", **headers})


# ================================================================= streaming, .part, fsync, rename atómico
def test_download_streams_into_part_and_never_writes_the_final_name_until_complete(tmp_path):
    st = tmp_path / "st"
    seen = []

    def on_chunk(i):
        seen.append(((st / "a.pdf").exists(), (st / "a.pdf.part").exists()))

    def handler(request):
        return httpx.Response(200, stream=Chunks(split(PAYLOAD, 8), on_chunk), headers={"content-type": "application/pdf"})
    svc, _ = service(handler, chunk_size=200)
    res = svc.download(req(st))
    assert res.ok and res.sha256 == hashlib.sha256(PAYLOAD).hexdigest() and res.size_bytes == len(PAYLOAD)
    assert seen and all(final is False for final, _ in seen)                      # el nombre final no existe durante la descarga
    assert all(part for _, part in seen[1:])                                        # el .part existe mientras se escribe
    assert (st / "a.pdf").read_bytes() == PAYLOAD and not (st / "a.pdf.part").exists() and not (st / "a.pdf.part.meta").exists()


def test_fsync_happens_before_the_atomic_rename_and_rename_is_the_only_way_to_the_final_name(tmp_path, monkeypatch):
    st = tmp_path / "st"
    events = []
    real_fsync, real_replace = ds.os.fsync, ds.os.replace

    def spy_fsync(fd):
        events.append(("fsync", (st / "a.pdf.part").stat().st_size, (st / "a.pdf").exists()))
        return real_fsync(fd)

    def spy_replace(src, dst, *a, **k):
        events.append(("replace", Path(src).name, Path(dst).name, Path(dst).exists()))
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(ds.os, "fsync", spy_fsync)
    monkeypatch.setattr(ds.os, "replace", spy_replace)
    svc, _ = service(lambda r: ok_resp())
    assert svc.download(req(st)).ok
    kinds = [e[0] for e in events]
    assert "fsync" in kinds and kinds.index("fsync") < kinds.index("replace")        # fsync antes del rename
    fs = [e for e in events if e[0] == "fsync"][0]
    assert fs[1] == len(PAYLOAD) and fs[2] is False                                   # todo el .part, y el final aún no existe
    assert [e for e in events if e[0] == "replace"] == [("replace", "a.pdf.part", "a.pdf", False)]


@pytest.mark.parametrize("name", ["../evil.pdf", "a/b.pdf", "a\\b.pdf", "C:\\x.pdf", "x:ads", "..", "name.", " name"])
def test_unsafe_file_names_are_rejected_before_touching_the_filesystem(tmp_path, name):
    st = tmp_path / "st"
    calls = []
    svc, _ = service(lambda r: calls.append(1) or ok_resp())
    res = svc.download(DownloadRequest(url=URL, staging_dir=str(st), file_name=name))
    assert res.ok is False and res.error_class == "PATH_VIOLATION" and calls == []
    assert not st.exists() and not (tmp_path / "evil.pdf").exists()


# ================================================================= HTTP 429 / 403 / 5xx y backoff
@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_statuses_back_off_and_preserve_the_real_code(tmp_path, code):
    calls = []
    svc, sleeps = service(lambda r: calls.append(1) or httpx.Response(code), max_retries=3)
    res = svc.download(req(tmp_path / "st"))
    assert not res.ok and res.http_status == code and res.error_class == "HTTP_TRANSIENT"
    assert len(calls) == 4 and len(sleeps) == 3                                       # 1 + 3 reintentos, un backoff por reintento
    assert all(s >= 1.0 * 2 ** i for i, s in enumerate(sleeps))                       # exponencial (con jitter hacia arriba)
    assert not (tmp_path / "st" / "a.pdf").exists()


def test_403_is_a_single_permanent_attempt_by_default_but_can_back_off_when_the_source_rate_limits_with_403(tmp_path):
    calls = []
    svc, sleeps = service(lambda r: calls.append(1) or httpx.Response(403), max_retries=2)
    res = svc.download(req(tmp_path / "a"))
    assert res.http_status == 403 and res.error_class == "HTTP_PERMANENT" and len(calls) == 1 and sleeps == []
    calls.clear()
    svc2, sleeps2 = service(lambda r: calls.append(1) or httpx.Response(403), max_retries=2,
                            extra_retryable_statuses=frozenset({403}))
    res2 = svc2.download(req(tmp_path / "b"))
    assert res2.http_status == 403 and res2.error_class == "HTTP_TRANSIENT" and len(calls) == 3 and len(sleeps2) == 2


# ================================================================= Retry-After
def test_retry_after_seconds_is_respected_over_a_smaller_backoff(tmp_path):
    seq = [httpx.Response(429, headers={"retry-after": "9"}), ok_resp()]
    svc, sleeps = service(lambda r: seq.pop(0), initial_backoff_s=0.0)
    assert svc.download(req(tmp_path / "st")).ok and max(sleeps) >= 9.0


def test_retry_after_http_date_is_respected_using_the_injected_clock(tmp_path):
    seq = [httpx.Response(503, headers={"retry-after": formatdate(1012.0, usegmt=True)}), ok_resp()]
    svc, sleeps = service(lambda r: seq.pop(0), initial_backoff_s=0.0, clock=lambda: 1000.0)
    assert svc.download(req(tmp_path / "st")).ok and 11.0 <= max(sleeps) <= 12.5
    assert _parse_retry_after("soon", lambda: 0.0) is None and _parse_retry_after("", lambda: 0.0) is None
    assert _parse_retry_after(formatdate(10.0, usegmt=True), lambda: 500.0) == 0.0     # fecha pasada => sin espera extra


def test_retry_after_is_capped_by_the_service_maximum(tmp_path):
    seq = [httpx.Response(429, headers={"retry-after": "99999"}), ok_resp()]
    svc, sleeps = service(lambda r: seq.pop(0), initial_backoff_s=0.0, max_retry_after_s=30.0)
    assert svc.download(req(tmp_path / "st")).ok and max(sleeps) == 30.0


# ================================================================= timeouts y límites de tamaño
def test_timeout_is_classified_after_retries_and_the_timeout_policy_reaches_every_request(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        raise httpx.ReadTimeout("lento", request=request)
    svc, sleeps = service(handler, max_retries=2, timeout_s=7.0)
    res = svc.download(req(tmp_path / "st"))
    assert not res.ok and res.error_class == "TIMEOUT" and len(seen) == 3 and len(sleeps) == 2
    assert all(t["read"] == 7.0 and t["connect"] == 7.0 for t in seen)               # también con un cliente inyectado


def test_total_deadline_stops_a_slow_drip_and_keeps_the_part_resumable(tmp_path):
    t = [0.0]

    def tick(i):
        t[0] += 100.0
    st = tmp_path / "st"
    svc, _ = service(lambda r: httpx.Response(200, stream=Chunks(split(PAYLOAD, 10), tick)), max_total_s=250.0,
                     chunk_size=200, monotonic=lambda: t[0])
    res = svc.download(req(st))
    assert not res.ok and res.error_class == "TIMEOUT"
    assert (st / "a.pdf.part").exists() and not (st / "a.pdf").exists()


def test_size_limits_header_stream_and_service_default(tmp_path):
    st = tmp_path / "st"
    svc, _ = service(lambda r: httpx.Response(200, content=b"x" * 5000, headers={"content-length": "5000"}))
    r = svc.download(req(st, max_bytes=1000))
    assert r.error_class == "SIZE_EXCEEDED" and not (st / "a.pdf.part").exists()      # por cabecera: ni se lee el cuerpo
    svc2, _ = service(lambda r: httpx.Response(200, stream=Chunks(split(b"y" * 5000, 5))))
    r2 = svc2.download(req(st, max_bytes=1000))
    assert r2.error_class == "SIZE_EXCEEDED" and not (st / "a.pdf.part").exists()     # en streaming: se corta y se descarta
    svc3, _ = service(lambda r: httpx.Response(200, content=b"z" * 5000), default_max_bytes=1000)
    r3 = svc3.download(req(st))                                                          # sin max_bytes: rige el tope del servicio
    assert r3.error_class == "SIZE_EXCEEDED" and not (st / "a.pdf").exists()


# ================================================================= interrupción, reanudación y no corrupción del destino
def test_interrupted_download_keeps_a_durable_part_and_the_next_attempt_resumes_it(tmp_path):
    st = tmp_path / "st"
    half = split(PAYLOAD, 4)[:2]
    got = b"".join(half)

    def broken(request):
        return httpx.Response(200, stream=Chunks(half, fail=httpx.ReadError("conexión caída")),
                              headers={"content-type": "application/pdf", "etag": '"v1"'})
    svc, _ = service(broken, max_retries=0)
    res = svc.download(req(st))
    assert not res.ok and res.error_class == "NETWORK"
    have = (st / "a.pdf.part").read_bytes()
    assert have and PAYLOAD.startswith(have) and len(have) <= len(got) and not (st / "a.pdf").exists()
    got = have                              # lo durable es un prefijo exacto del original; destino intacto
    seen = {}

    def resumed(request):
        seen.update(request.headers)
        return httpx.Response(206, content=PAYLOAD[len(got):], headers={
            "content-type": "application/pdf", "content-range": f"bytes {len(got)}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"})
    svc2, _ = service(resumed)
    res2 = svc2.download(req(st))
    assert res2.ok and res2.resumed and res2.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert seen["range"] == f"bytes={len(got)}-" and seen["if-range"] == '"v1"'          # reanuda solo si el recurso no cambió
    assert not (st / "a.pdf.part").exists() and not (st / "a.pdf.part.meta").exists()


def test_failed_attempt_never_touches_a_previously_staged_destination(tmp_path):
    st = tmp_path / "st"
    st.mkdir()
    (st / "a.pdf").write_bytes(b"VERSION ANTERIOR")
    svc, _ = service(lambda r: httpx.Response(200, stream=Chunks(split(PAYLOAD, 4)[:1], fail=httpx.ReadError("x"))),
                     max_retries=0)
    assert svc.download(req(st)).ok is False
    assert (st / "a.pdf").read_bytes() == b"VERSION ANTERIOR"


def test_resume_is_refused_when_the_resource_changed_or_the_range_does_not_line_up(tmp_path):
    st = tmp_path / "st"
    st.mkdir()
    new = make_pdf(61)
    cut = 500
    (st / "a.pdf.part").write_bytes(PAYLOAD[:cut])
    # (a) el recurso cambió: el servidor ignora el Range/If-Range y envía 200 con el contenido nuevo
    svc, _ = service(lambda r: ok_resp(new))
    res = svc.download(req(st))
    assert res.ok and not res.resumed and (st / "a.pdf").read_bytes() == new          # nada de mezclar bytes viejos y nuevos
    # (b) 206 con Content-Range que no empieza donde quedó el .part: se descarta y se reinicia limpio
    (st / "a.pdf").unlink()
    (st / "a.pdf.part").write_bytes(PAYLOAD[:cut])
    calls = []

    def lying(request):
        calls.append(request.headers.get("range"))
        if request.headers.get("range"):
            return httpx.Response(206, content=PAYLOAD[:50], headers={"content-range": "bytes 0-49/9999"})
        return ok_resp(PAYLOAD)
    svc2, _ = service(lying)
    res2 = svc2.download(req(st))
    assert res2.ok and not res2.resumed and (st / "a.pdf").read_bytes() == PAYLOAD and calls[0] and calls[1] is None
    # (c) el .part pertenece a otra URL: no se reanuda
    (st / "a.pdf").unlink()
    (st / "a.pdf.part").write_bytes(b"OTRO CONTENIDO")
    (st / "a.pdf.part.meta").write_text('{"url_sha": "otra-url", "etag": null, "last_modified": null}', encoding="utf-8")
    seen = []
    svc3, _ = service(lambda r: seen.append(r.headers.get("range")) or ok_resp())
    assert svc3.download(req(st)).ok and seen == [None] and (st / "a.pdf").read_bytes() == PAYLOAD


# ================================================================= Zip Slip / bombas / cuarentena
def zip_with(*members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data, *rest in members:
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            if rest:
                zi.external_attr = rest[0]
            zf.writestr(zi, data)
    return buf.getvalue()


def validate(tmp_path, data, **rules):
    p = tmp_path / "x.zip"
    p.write_bytes(data)
    meta = SourceMetadata(resolved_url="https://h.test/x.zip", file_name="x.zip", extension=".zip", expected_kind="ZIP",
                          authority_rules={"allowed_kinds": ["ZIP"], "min_size_bytes": 10, **rules})
    return ValidationPipeline().validate(p, meta, "ESEF_PACKAGE")


@pytest.mark.parametrize("member", [
    ("../evil.txt", b"x"), ("/abs/evil.txt", b"x"), ("C:/win/evil.txt", b"x"), ("a/../../evil.txt", b"x"),
    ("..\\evil.txt", b"x"), ("ok/..\\..\\evil.txt", b"x"), ("//server/share/x", b"x"), ("file.txt:stream", b"x"),
    ("link", b"/etc/passwd", (stat.S_IFLNK | 0o777) << 16)])
def test_zip_slip_members_are_rejected_before_any_content_validation(tmp_path, member):
    res = validate(tmp_path, zip_with(("report.xhtml", b"<html>" + b"x" * 200), member))
    assert not res.accepted and res.should_quarantine and res.completeness_status == "UNSAFE_ARCHIVE"
    assert any(r.startswith("ZIP_SLIP") for r in res.reasons)
    assert not (tmp_path.parent / "evil.txt").exists()                               # y, por supuesto, nada se extrajo


def test_safe_nested_names_are_not_flagged_and_zip_bombs_are_rejected(tmp_path):
    safe = zip_with(("META-INF/a.xml", b"<a/>"), ("reports/2023/ES.xhtml", b"<html>" + b"x" * 100))
    p = tmp_path / "s.zip"
    p.write_bytes(safe)
    assert inspect_zip_safety(p, {}) == []
    many = zip_with(*[(f"f{i}.txt", b"x") for i in range(5)])
    res = validate(tmp_path, many, max_members=3)
    assert not res.accepted and any(r.startswith("ZIP_BOMB") for r in res.reasons)
    bomb = zip_with(("zeros.bin", b"\0" * (3 << 20)))
    res2 = validate(tmp_path, bomb, max_compression_ratio=100)
    assert not res2.accepted and any("ratio" in r for r in res2.reasons)
    res3 = validate(tmp_path, bomb, max_uncompressed_bytes=1 << 20)
    assert not res3.accepted and any("descomprimidos" in r for r in res3.reasons)


def test_unreadable_zip_does_not_crash_the_safety_inspection(tmp_path):
    p = tmp_path / "bad.zip"
    p.write_bytes(make_corrupt_zip())
    assert inspect_zip_safety(p, {}) is not None                                      # sin excepción (zlib.error incluido)
    res = validate(tmp_path, make_corrupt_zip())
    assert not res.accepted and res.should_quarantine                                 # lo rechaza el validador de completitud


# ================================================================= integración con CAS / manifiesto / catálogo / UoW
def nothing_promoted(runner, layout):
    assert not [p for p in layout.raw.rglob("*") if p.is_file()] and not [p for p in layout.cas.rglob("*") if p.is_file()]
    assert not list(layout.manifests.rglob("*.json")) and runner.catalog.count() == 0
    assert not list(layout.staging.rglob("*.part")) and not list(layout.staging.rglob("*.part.meta"))


def test_corrupt_zip_goes_to_quarantine_without_crash_and_nothing_is_promoted(tmp_path):
    runner, layout, _ = mk(tmp_path, make_corrupt_zip(), [cand()])
    out = go(runner)
    assert out.state == "QUARANTINED" and out.error_class in ("CORRUPT_ARCHIVE", "VALIDATION_REJECTED")
    assert list(layout.quarantine.rglob("*.quarantine_reason.json")) and list(layout.quarantine.rglob("*.zip"))
    nothing_promoted(runner, layout)


def test_zip_slip_package_goes_to_quarantine_and_nothing_is_promoted(tmp_path):
    evil = zip_with(("report.xhtml", b"<html>" + b"x" * 300), ("../../evil.txt", b"pwn"))
    runner, layout, _ = mk(tmp_path, evil, [cand()])
    out = go(runner)
    assert out.state == "QUARANTINED" and "ZIP_SLIP" in (out.message or "")
    nothing_promoted(runner, layout)
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()
    reasons = (next(layout.quarantine.rglob("*.quarantine_reason.json"))).read_text(encoding="utf-8")
    assert "ZIP_SLIP" in reasons


def test_failed_validation_never_promotes_html_disguised_as_zip(tmp_path):
    runner, layout, _ = mk(tmp_path, ERROR_HTML, [cand()])
    out = go(runner)
    assert out.state == "QUARANTINED" and out.error_class in ("DISGUISED_HTML", "VALIDATION_REJECTED")
    nothing_promoted(runner, layout)


def test_runner_recovers_from_429_with_retry_after_and_ends_consistent(tmp_path):
    runner, layout, site = mk(tmp_path, ZIP_OK, [cand()])
    sleeps = []
    seq = [httpx.Response(429, headers={"retry-after": "4"}), httpx.Response(503), httpx.Response(200, content=ZIP_OK,
           headers={"content-type": "application/zip"})]

    def handler(request):
        site.calls.append((request.url.path, dict(request.headers)))
        return seq.pop(0)
    runner.download = DownloadService(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append,
                                      initial_backoff_s=0.0, rng=random.Random(1),
                                      rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None),
                                      telemetry=runner.telemetry)
    out = go(runner)
    assert out.state == "COMPLETED" and max(sleeps) >= 4.0 and len(site.calls) == 3
    assert UnifiedReconciler(layout, runner.catalog, runner.cas, runner.versions).reconcile().clean
    assert not list(layout.staging.rglob("*.part")) and not list(layout.staging.rglob("*.part.meta"))


def test_runner_size_limit_and_exhausted_retries_leave_no_promotion_and_keep_the_http_code(tmp_path):
    runner, layout, _ = mk(tmp_path, ZIP_OK, [cand()])
    runner.download.default_max_bytes = 100
    out = go(runner)
    assert out.state == "FAILED" and out.error_class == "SIZE_EXCEEDED"
    nothing_promoted(runner, layout)
    runner.download.default_max_bytes = 10 ** 9
    runner.download._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    runner.download.max_retries = 1
    runner.download._sleep = lambda s: None
    out2 = go(runner)
    assert out2.state == "FAILED" and out2.error_class == "HTTP_TRANSIENT"
    failed = [e for e in runner.telemetry.read_all() if e["event"] == "download_failed"][-1]
    assert failed["status"] == 429                                                    # el código real llega a la telemetría
    nothing_promoted(runner, layout)


def test_runner_interrupted_stream_leaves_part_not_raw_and_a_new_run_completes(tmp_path):
    runner, layout, site = mk(tmp_path, ZIP_OK, [cand()])
    half = split(ZIP_OK, 3)[:1]
    runner.download._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, stream=Chunks(half, fail=httpx.ReadError("caída")))))
    runner.download.max_retries = 0
    out = go(runner)
    assert out.state == "FAILED" and out.error_class == "NETWORK"
    parts = list(layout.staging.rglob("*.part"))
    assert len(parts) == 1 and ZIP_OK.startswith(parts[0].read_bytes())                # .part recuperable (prefijo exacto)
    nothing_promoted_but_part = [p for p in layout.raw.rglob("*") if p.is_file()] + list(layout.manifests.rglob("*.json"))
    assert nothing_promoted_but_part == [] and runner.catalog.count() == 0
    r2, _, _ = mk(tmp_path, ZIP_OK, [cand()])                                         # run nuevo, red sana
    assert go(r2).state == "COMPLETED"
    assert UnifiedReconciler(layout, r2.catalog, r2.cas, r2.versions).reconcile().clean
