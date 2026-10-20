"""
CNMV-U1 — Descubrimiento limitado SIN descarga: transporte HTTP simulado (httpx.MockTransport), raíz en tmp_path, relojes
inyectados y sockets bloqueados. Ninguna prueba toca la red, D: ni documentos reales.
"""
import ast
import json
import os
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import cnmv_discovery as cd
from mod_01_ingestion.src.unified.cnmv_discovery import (
    DiscoveryError, DiscoveryFetcher, check_url, local_comparison, parse_ifa_listing, run_discovery)
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
UA = "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com"
TOKEN = "SECRETTOKEN%2bABC"
HEAD = ("<tr><th>N\u00ba Registro Oficial</th><th>Fecha Estados Financieros</th><th>Fecha de publicaci\u00f3n (1)</th>"
        "<th>Nombre del auditor</th><th>Tipo</th><th>Fichero ZIP/Xbri (2)</th></tr>")


def listing(entity="TELEFONICA, S.A.", rows=()):
    body = "".join(rows)
    return f'<html><body><table id="ctl00_gridInformes"><caption> {entity} </caption><thead>{HEAD}</thead><tbody>{body}</tbody></table></body></html>'


def direct(nreg, fy, pub, extra=""):
    return (f'<tr><td><a href="/AUDITA/{fy}/{nreg}.pdf">{nreg}</a></td><td>31/12/{fy}</td><td>{pub}</td><td>PWC</td><td></td><td></td>'
            f'{extra}</tr>')


def tokenized(nreg, fy, pub):
    h = f"https://www.cnmv.es/webservices/verdocumento/ver?e={TOKEN}{nreg}"
    return (f'<tr><td>{nreg}</td><td>31/12/{fy}</td><td>{pub}</td><td>PWC</td><td><a href="{h}">Individual</a> / '
            f'<a href="{h}2">Consolidada</a></td><td><a href="{h}3"><img/></a></td></tr>')


def page_for(entity):
    return listing(entity, [tokenized("20001", 2020, "25/02/2021"), direct("18290", 2019, "20/02/2020"),
                            direct("17817", 2018, "21/02/2019")])


NAMES = {"A28015865": "TELEFONICA, S.A.", "A39000013": "BANCO SANTANDER, S.A.", "A48010615": "IBERDROLA, S.A.",
         "A48265169": "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.", "A78374725": "REPSOL, S.A."}


class Site:
    def __init__(self, handler=None):
        self.requests = []
        self.handler = handler or self.default

    def default(self, request):
        u = request.url
        if u.path == "/portal/Consultas/ifa/listadoifa":
            nif = u.params.get("nif")
            return httpx.Response(200, text=page_for(NAMES[nif]), headers={"content-type": "text/html; charset=utf-8"})
        if request.method == "HEAD" and u.path.startswith("/AUDITA/"):
            return httpx.Response(200, headers={"content-type": "application/pdf", "content-length": "12345",
                                                "last-modified": "Thu, 20 Feb 2020 10:00:00 GMT"})
        return httpx.Response(404)

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)


def fetcher(site, sleeps=None, **kw):
    sl = sleeps if sleeps is not None else []
    clock = {"t": 0.0}

    def sleep(s):
        sl.append(s)
        clock["t"] += s
    return DiscoveryFetcher(site.client(), sleep=sleep, monotonic=lambda: clock["t"], **kw), sl


def pilot_root(tmp_path):
    return UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT).initialize().path


# ================================================================= URL y dominio
@pytest.mark.parametrize("url,bad", [
    ("https://www.cnmv.es/portal/x", None), ("http://www.cnmv.es/x", "DOMAIN_NOT_ALLOWED"),
    ("https://cnmv.es/x", "DOMAIN_NOT_ALLOWED"), ("https://evil.example.org/x", "DOMAIN_NOT_ALLOWED"),
    ("https://www.cnmv.es.evil.org/x", "DOMAIN_NOT_ALLOWED"), ("https://user:pw@www.cnmv.es/x", "DOMAIN_NOT_ALLOWED"),
    ("https://www.cnmv.es:8443/x", "DOMAIN_NOT_ALLOWED"), ("https://www.cnmv.es/x?sig=abc", "SIGNED_URL"),
    ("https://www.cnmv.es/x?a=1&token=abc", "SIGNED_URL"), ("https://www.cnmv.es/x?nif=A1&Signature=z", "SIGNED_URL")])
def test_only_the_approved_https_domain_and_no_signed_urls(url, bad):
    assert check_url(url) == bad


# ================================================================= fetcher: ritmo, reintentos, bloqueos
def test_requests_are_paced_with_user_agent_and_no_cookies_replayed():
    site = Site(lambda r: httpx.Response(200, text="ok", headers={"content-type": "text/html", "set-cookie": "sid=1; Path=/"}))
    f, sleeps = fetcher(site)
    f.begin_issuer("TEF")
    r1, r2 = f.fetch("https://www.cnmv.es/a"), f.fetch("https://www.cnmv.es/b")
    assert r1.outcome == r2.outcome == "OK" and r1.set_cookie_seen
    assert sleeps and all(s >= 5.0 - 1e-9 for s in sleeps)
    assert all(q.headers["user-agent"] == UA for q in site.requests)
    assert all("cookie" not in q.headers for q in site.requests)           # la cookie del servidor nunca se reenvía


def test_429_and_503_get_exactly_one_retry_everything_else_none():
    for st in (429, 503):
        site = Site(lambda r, st=st, n=[0]: (n.__setitem__(0, n[0] + 1), httpx.Response(st if n[0] == 1 else 200, text="x",
                    headers={"content-type": "text/html", "retry-after": "2"}))[1])
        f, sl = fetcher(site)
        f.begin_issuer("T")
        r = f.fetch("https://www.cnmv.es/a")
        assert r.outcome == "OK" and len(site.requests) == 2
    twice = Site(lambda r: httpx.Response(429, text="x"))
    f, _ = fetcher(twice)
    f.begin_issuer("T")
    assert f.fetch("https://www.cnmv.es/a").outcome == "NEEDS_REVIEW" and len(twice.requests) == 2
    for st in (403, 404, 500, 502, 504):
        one = Site(lambda r, st=st: httpx.Response(st, text="x"))
        f, _ = fetcher(one)
        f.begin_issuer("T")
        r = f.fetch("https://www.cnmv.es/a")
        assert r.outcome == "NEEDS_REVIEW" and r.reason == f"HTTP_{st}" and len(one.requests) == 1


def test_network_errors_and_timeouts_are_not_retried():
    for exc, why in ((httpx.ConnectError("down"), "NETWORK:ConnectError"), (httpx.ReadTimeout("slow"), "TIMEOUT")):
        def boom(request, exc=exc):
            raise exc
        site = Site(boom)
        f, _ = fetcher(site)
        f.begin_issuer("T")
        r = f.fetch("https://www.cnmv.es/a")
        assert r.outcome == "NEEDS_REVIEW" and r.reason == why and len(site.requests) == 1


def test_redirects_are_validated_before_being_requested():
    site = Site(lambda r: httpx.Response(302, headers={"location": "https://evil.example.org/x"}))
    f, _ = fetcher(site)
    f.begin_issuer("T")
    r = f.fetch("https://www.cnmv.es/a")
    assert r.outcome == "NEEDS_REVIEW" and r.reason == "DOMAIN_NOT_ALLOWED" and len(site.requests) == 1
    site2 = Site(lambda r: httpx.Response(302, headers={"location": "http://www.cnmv.es/wap/index.wml"}))
    f2, _ = fetcher(site2)
    f2.begin_issuer("T")
    assert f2.fetch("https://www.cnmv.es/").reason == "DOMAIN_NOT_ALLOWED"                  # http: no se sigue
    loop = Site(lambda r: httpx.Response(302, headers={"location": "https://www.cnmv.es/a"}))
    f3, _ = fetcher(loop)
    f3.begin_issuer("T")
    r3 = f3.fetch("https://www.cnmv.es/a")
    assert r3.reason == "TOO_MANY_REDIRECTS" and len(loop.requests) == cd.MAX_REDIRECTS + 1
    ok = Site(lambda r: httpx.Response(301, headers={"location": "/b"}) if r.url.path == "/a" else httpx.Response(200, text="x",
              headers={"content-type": "text/html"}))
    f4, _ = fetcher(ok)
    f4.begin_issuer("T")
    assert f4.fetch("https://www.cnmv.es/a").outcome == "OK" and len(ok.requests) == 2


class Boom(httpx.SyncByteStream):
    def __iter__(self):
        raise AssertionError("el cuerpo de un documento NO debe leerse")
        yield b""


def test_a_document_response_is_never_read():
    for ctype in ("application/pdf", "application/zip", "application/octet-stream"):
        site = Site(lambda r, c=ctype: httpx.Response(200, stream=Boom(), headers={"content-type": c, "content-length": "99"}))
        f, _ = fetcher(site)
        f.begin_issuer("T")
        r = f.fetch("https://www.cnmv.es/AUDITA/2019/1.pdf")
        assert r.outcome == "DOCUMENT_NOT_DOWNLOADED" and r.text is None and r.bytes_read == 0 and r.content_length == 99
    att = Site(lambda r: httpx.Response(200, stream=Boom(), headers={"content-type": "text/html",
                                                                      "content-disposition": "attachment; filename=x.html"}))
    f, _ = fetcher(att)
    f.begin_issuer("T")
    assert f.fetch("https://www.cnmv.es/x").outcome == "DOCUMENT_NOT_DOWNLOADED"


@pytest.mark.parametrize("body,kind", [("<div class='g-recaptcha'></div>", "CAPTCHA"), ("Por favor, Iniciar sesión", "LOGIN"),
                                       ("Request Rejected", "WAF"), ("You must enable cookies", "COOKIE_REQUIRED")])
def test_login_captcha_waf_and_cookie_walls_stop_the_source(body, kind):
    f, _ = fetcher(Site(lambda r: httpx.Response(200, text=body, headers={"content-type": "text/html"})))
    f.begin_issuer("T")
    r = f.fetch("https://www.cnmv.es/x")
    assert r.outcome == "NEEDS_REVIEW" and r.reason == f"BLOCKED:{kind}" and r.text is None


def test_oversize_pages_issuer_budget_and_methods():
    f, _ = fetcher(Site(lambda r: httpx.Response(200, content=b"x" * (cd.MAX_PAGE_BYTES + 10), headers={"content-type": "text/html"})))
    f.begin_issuer("T")
    assert f.fetch("https://www.cnmv.es/x").reason == "PAGE_TOO_LARGE"
    site = Site(lambda r: httpx.Response(200, text="x", headers={"content-type": "text/html"}))
    g, sl = fetcher(site, per_issuer_s=8.0)
    g.begin_issuer("T")
    outs = [g.fetch(f"https://www.cnmv.es/{i}").reason for i in range(4)]
    assert "ISSUER_TIME_BUDGET" in outs and len(site.requests) < 4
    with pytest.raises(DiscoveryError):
        g.fetch("https://www.cnmv.es/x", method="POST")


# ================================================================= parser del listado oficial
def test_parser_extracts_registry_dates_and_separates_direct_from_tokenized_links():
    page = listing(rows=[tokenized("20868", 2025, "24/02/2026"),
                         direct("18290", 2019, "20/02/2020", '<td><a href="/AUDITA/2019/REQ18290.pdf">r</a></td>')])
    out = parse_ifa_listing(page)
    assert out.entity == "TELEFONICA, S.A." and [r.nreg for r in out.rows] == ["20868", "18290"]
    t, d = out.rows
    assert (t.fiscal_year, t.pub_date, t.tokenized_links, t.audita_urls, t.has_zip_link) == (2025, "24/02/2026", 3, [], True)
    assert len(t.tokenized_ref) == 3 and all(len(x) == 12 for x in t.tokenized_ref) and TOKEN not in json.dumps(t.to_dict())
    assert d.audita_urls == ["https://www.cnmv.es/AUDITA/2019/18290.pdf"] and d.extra_audita == [
        "https://www.cnmv.es/AUDITA/2019/REQ18290.pdf"] and d.tokenized_links == 0 and d.pub_date == "20/02/2020"
    with pytest.raises(DiscoveryError):
        parse_ifa_listing("<html>sin tabla</html>")
    with pytest.raises(DiscoveryError):
        parse_ifa_listing('<table id="gridInformes"><tr><th>otra</th></tr></table>')


# ================================================================= descubrimiento completo (sin descargas)
def run(tmp_path, site=None, **kw):
    site = site or Site()
    root = pilot_root(tmp_path)
    f, sl = fetcher(site)
    f.telemetry = None
    out = run_discovery(root, fetcher=f, **kw)
    return root, site, out, sl


def test_discovery_finds_registry_numbers_and_candidates_without_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "no_such_checkout")
    root, site, out, sleeps = run(tmp_path)
    methods = [(q.method, q.url.path) for q in site.requests]
    assert out["documents_downloaded"] == 0
    assert all(m == "HEAD" for m, p in methods if p.startswith("/AUDITA/")) and not any(m == "GET" and p.startswith("/AUDITA/") for m, p in methods)
    assert sum(1 for m, p in methods if p == "/portal/Consultas/ifa/listadoifa") == 5          # una ficha por emisor
    assert sum(1 for m, p in methods if m == "HEAD") == 10                                      # 2 ejercicios con URL directa × 5
    assert len(site.requests) == out["requests_total"] == 15 and all(s >= 5.0 - 1e-9 for s in sleeps)
    res = {(r["ticker"], r["fiscal_year"]): r for r in out["results"]}
    assert len(res) == 15
    r19 = res[("TEF", 2019)]
    assert (r19["status"], r19["nreg"], r19["pub_date"], r19["fy_date"]) == ("DISCOVERED_DIRECT_URL", "18290", "20/02/2020", "31/12/2019")
    assert r19["candidate_url"] == "https://www.cnmv.es/AUDITA/2019/18290.pdf" and r19["head"]["content_length"] == 12345
    assert r19["format_indicated"].startswith("PDF") and r19["ledger_status"] == "FOUND"
    r20 = res[("TEF", 2020)]
    assert r20["status"] == "DISCOVERED_TOKENIZED_ONLY" and r20["candidate_url"] is None and r20["ledger_status"] == "NEEDS_REVIEW"
    assert r20["nreg"] == "20001" and r20["pub_date"] == "25/02/2021" and r20["limitations"]
    # los candidatos son exactamente las URL directas; los tokens no aparecen en ningún resultado
    d = root / "reports" / "pilot" / "discovery"
    cands = json.loads((d / "cnmv_u1_candidates.json").read_text(encoding="utf-8"))
    assert len(cands) == 10 and all(c["url"].startswith("https://www.cnmv.es/AUDITA/") and c["head_confirmed_pdf"] for c in cands)
    for p in d.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".csv"):
            assert TOKEN not in p.read_text(encoding="utf-8")
    assert (d / "cnmv_u1_coverage_matrix.csv").read_text(encoding="utf-8").count("\n") == 16
    # nada de raw / CAS / manifiestos / catálogo de documentos
    for sub in ("raw", "cas", "cas_pins", "manifests", "versions"):
        assert not [p for p in (root / sub).rglob("*") if p.is_file()], sub
    ledger = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    assert len(ledger.list()) == 15 and {r.status.value for r in ledger.list()} == {"FOUND", "NEEDS_REVIEW"}
    assert ledger.get(CoverageKey("ES", "CNMV", "SAN", 2018, "CNMV_ANNUAL_REPORT")).status.value == "FOUND"
    # los datos solo se escriben bajo reports/pilot/discovery y el ledger; ningún otro archivo nuevo
    new_files = {p.relative_to(root).parts[0] for p in root.rglob("*") if p.is_file()}
    assert new_files <= {".argos_unified_root", "catalog", "reports", "telemetry"}


def test_discovery_reuses_a_cached_evidence_page_without_a_request(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")
    cache = tmp_path / "tef.html"
    cache.write_text(page_for("TELEFONICA, S.A."), encoding="utf-8")
    root, site, out, _ = run(tmp_path, cached_pages={"TEF": cache})
    assert sum(1 for q in site.requests if q.url.path == "/portal/Consultas/ifa/listadoifa") == 4
    assert {r["listing_source"] for r in out["results"] if r["ticker"] == "TEF"} == {"CACHED_EVIDENCE_PAGE"}


def test_blocked_or_wrong_listing_is_never_turned_into_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")

    def handler(request):
        nif = request.url.params.get("nif")
        if nif == "A39000013":
            return httpx.Response(403, text="forbidden")
        if nif == "A48010615":
            return httpx.Response(200, text="<div class='g-recaptcha'></div>", headers={"content-type": "text/html"})
        if nif == "A48265169":
            return httpx.Response(200, text=page_for("OTRA ENTIDAD, S.A."), headers={"content-type": "text/html"})
        return Site().default(request)
    root, site, out, _ = run(tmp_path, Site(handler))
    res = {(r["ticker"], r["fiscal_year"]): r for r in out["results"]}
    assert all(res[("SAN", y)]["status"] == "NEEDS_REVIEW" and res[("SAN", y)]["reason"] == "HTTP_403" for y in (2018, 2019, 2020))
    assert all(res[("IBE", y)]["ledger_status"] == "SOURCE_UNAVAILABLE" for y in (2018, 2019, 2020))
    assert all(res[("BBVA", y)]["reason"].startswith("ENTITY_MISMATCH") for y in (2018, 2019, 2020))
    assert not [k for k, r in res.items() if r.get("candidate_url") and k[0] in ("SAN", "IBE", "BBVA")]
    assert len([q for q in site.requests if q.url.params.get("nif") == "A39000013"]) == 1                 # 403 sin reintento


def test_head_failure_keeps_the_official_link_but_flags_the_limitation(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")

    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(403)
        return Site().default(request)
    _, _, out, _ = run(tmp_path, Site(handler))
    r = next(x for x in out["results"] if x["ticker"] == "REP" and x["fiscal_year"] == 2019)
    assert r["candidate_url"] and r["head"]["outcome"] == "NEEDS_REVIEW" and any("HEAD" in l for l in r["limitations"])


def test_fy_absent_is_needs_review_not_not_published(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")

    def handler(request):
        if request.url.path == "/portal/Consultas/ifa/listadoifa":
            nif = request.url.params.get("nif")
            return httpx.Response(200, text=listing(NAMES[nif], [direct("17817", 2018, "21/02/2019")]),
                                  headers={"content-type": "text/html"})
        return Site().default(request)
    _, _, out, _ = run(tmp_path, Site(handler))
    r = next(x for x in out["results"] if x["ticker"] == "IBE" and x["fiscal_year"] == 2019)
    assert r["status"] == "NEEDS_REVIEW" and r["reason"] == "FY_ROW_ABSENT" and r["ledger_status"] == "NEEDS_REVIEW"


NO_DATA = "<html><body>No se han encontrado datos disponibles</body></html>"


def test_nif_spelling_variant_is_tried_once_when_the_official_page_has_no_data(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")
    assert cd.nif_variants("A48010615") == ["A48010615", "A-48010615"] and cd.nif_variants("a-48010615")[0] == "A48010615"

    def handler(request):
        nif = request.url.params.get("nif")
        if request.url.path == "/portal/Consultas/ifa/listadoifa" and nif == "A48010615":
            return httpx.Response(200, text=NO_DATA, headers={"content-type": "text/html"})
        if request.url.path == "/portal/Consultas/ifa/listadoifa" and nif == "A-48010615":
            return httpx.Response(200, text=page_for("IBERDROLA, S.A."), headers={"content-type": "text/html"})
        return Site().default(request)
    root, site, out, _ = run(tmp_path, Site(handler), issuers={"IBE": ("A48010615", "IBERDROLA, S.A.")})
    res = {r["fiscal_year"]: r for r in out["results"]}
    assert res[2019]["status"] == "DISCOVERED_DIRECT_URL" and res[2019]["nif_variant_used"] == "A-48010615"
    assert [q.url.params.get("nif") for q in site.requests if q.method == "GET"] == ["A48010615", "A-48010615"]
    pages = sorted(p.name for p in (root / "reports" / "pilot" / "discovery" / "pages").iterdir())
    assert pages == ["ifa_IBE.html", "ifa_IBE_alt1.html"]                           # ambas respuestas quedan como evidencia


def test_no_data_for_both_spellings_is_needs_review_with_exactly_two_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")
    site = Site(lambda r: httpx.Response(200, text=NO_DATA, headers={"content-type": "text/html"}))
    _, _, out, _ = run(tmp_path, site, issuers={"IBE": ("A48010615", "IBERDROLA, S.A.")})
    assert len(site.requests) == 2 and {r["reason"] for r in out["results"]} == {"NO_DATA_AVAILABLE"}
    assert {r["ledger_status"] for r in out["results"]} == {"NEEDS_REVIEW"} and not any(r.get("candidate_url") for r in out["results"])


def test_rerunning_one_issuer_merges_with_the_previous_results(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path / "x")
    root = pilot_root(tmp_path)
    f1, _ = fetcher(Site())
    run_discovery(root, fetcher=f1)
    site2 = Site()
    f2, _ = fetcher(site2)
    out = run_discovery(root, fetcher=f2, issuers={"REP": ("A78374725", "REPSOL, S.A.")}, merge_previous=True)
    assert len(out["results"]) == 15 and out["requests_total"] == 15 + len(site2.requests)
    assert len([r for r in out["results"] if r["ticker"] == "REP"]) == 3


# ================================================================= comparación local (solo lectura)
def _fake_checkout(tmp_path, fy, recs):
    d = tmp_path / "audits" / "manifests"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"MANIFEST_CNMV_{fy}.json").write_text(json.dumps({"manifest": recs}), encoding="utf-8")


def test_local_comparison_categories(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy" / "ES_CNMV"
    (legacy / "2019" / "A1_TEF").mkdir(parents=True)
    f = legacy / "2019" / "A1_TEF" / "TEF_2019_ANUAL.pdf"
    f.write_bytes(b"x" * 12345)
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    monkeypatch.setattr(cd, "ARGOS_MOTOR", tmp_path)
    monkeypatch.setattr(cd, "LEGACY_ROOT", os.path.normcase(str(legacy)))
    row = cd.IfaRow(nreg="18290", fy_date="31/12/2019", pub_date="20/02/2020", auditor="PWC", fiscal_year=2019)
    rec = {"ticker": "TEF", "url": "https://www.cnmv.es/AUDITA/2019/18290.pdf", "sha256": "ab" * 32, "size_bytes": 12345, "path": str(f)}
    _fake_checkout(tmp_path, 2019, [rec])
    head = {"content_length": 12345}
    assert local_comparison("TEF", 2019, row, head)["category"] == "SIZE_MATCH_HASH_UNVERIFIED"
    assert local_comparison("TEF", 2019, row, {"content_length": 999})["category"] == "DIFFERENT"
    assert local_comparison("TEF", 2019, row, None)["category"] == "INSUFFICIENT_EVIDENCE"
    assert local_comparison("TEF", 2019, row, head, downloaded_sha="ab" * 32)["category"] == "HASH_MATCH"
    assert local_comparison("TEF", 2019, row, head, downloaded_sha="cd" * 32)["category"] == "SIZE_MATCH_HASH_UNVERIFIED"
    other = cd.IfaRow(nreg="99999", fy_date="31/12/2019", pub_date=None, auditor=None, fiscal_year=2019)
    assert local_comparison("TEF", 2019, other, head)["category"] == "DIFFERENT"
    assert local_comparison("TEF", 2019, None, head)["category"] == "INSUFFICIENT_EVIDENCE"
    _fake_checkout(tmp_path, 2019, [dict(rec, sha256=cd.GENERIC_SHA_PREFIX + "0" * 52)])
    assert local_comparison("TEF", 2019, row, head)["category"] == "LOCAL_PLACEHOLDER_CONTENT"
    _fake_checkout(tmp_path, 2019, [dict(rec, url="https://www.cnmv.es/DocPortal/quees/Conducta.pdf")])
    assert local_comparison("TEF", 2019, row, head)["category"] == "INSUFFICIENT_EVIDENCE"
    assert local_comparison("XXX", 2019, row, head)["category"] == "INSUFFICIENT_EVIDENCE"
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before                    # el archivo local no se toca


# ================================================================= seguridad
def test_discovery_requires_an_initialized_pilot_root_and_refuses_legacy_paths(tmp_path):
    f, _ = fetcher(Site())
    with pytest.raises(DiscoveryError):
        run_discovery(tmp_path / "not_initialized", fetcher=f)
    with pytest.raises(Exception):
        run_discovery(Path("D:/ARGOS_DATA/raw/ES_CNMV/x"), fetcher=f)


def test_module_has_no_download_or_write_to_legacy_capability():
    text = (UNIFIED / "cnmv_discovery.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    for m in mods:
        assert not ({"requests", "socket", "subprocess", "download_service", "ingest_runner", "cas_store"} & set(m.split("."))), m
    assert "shutil" not in text and "os.remove" not in text and ".unlink(" not in text and "rmtree" not in text
    for other in ("pilot_runner.py", "ingest_runner.py", "download_service.py"):
        assert "cnmv_discovery" not in (UNIFIED / other).read_text(encoding="utf-8")
