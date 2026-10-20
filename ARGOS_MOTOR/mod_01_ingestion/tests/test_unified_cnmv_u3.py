"""
CNMV-U3 — Descubrimiento seguro de enlaces tokenizados: saneado, clasificación, presupuesto y ausencia de persistencia de tokens.
Todo sintético (httpx.MockTransport), raíz en tmp_path, sockets bloqueados. Los "tokens" de los fixtures son cadenas falsas fáciles de buscar.
"""
import ast
import json
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import cnmv_u3 as u3
from mod_01_ingestion.src.unified.cnmv_discovery import DiscoveryError
from mod_01_ingestion.src.unified.cnmv_evidence import (
    BudgetedFetcher, classify_href, contains_token, link_kind_summary, parse_full, sanitize_html, sanitize_text)
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode

UNIFIED = Path(__file__).resolve().parents[1] / "src" / "unified"
FAKE = "FAKETOKENZZZ"
HEAD = ("<tr><th>N\u00ba Registro Oficial</th><th>Fecha Estados Financieros</th><th>Fecha de publicaci\u00f3n (1)</th>"
        "<th>Nombre del auditor</th><th>Tipo</th><th>Fichero ZIP/Xbri (2)</th><th>Informe especial (3)</th>"
        "<th>Ampliaci\u00f3n informaci\u00f3n (4)</th><th>Opini\u00f3n del auditor (5)</th><th>P\u00e1rrafo de \u00e9nfasis (5)</th>"
        "<th>Observaciones</th></tr>")


def tok(n, kind):
    return f"https://www.cnmv.es/webservices/verdocumento/ver?e={FAKE}{n}{kind}%2bAAAA"


def tokenized(nreg, fy, pub, remarks="", detail=True):
    det = f'<a href="infadicionifa.aspx?id=0&amp;nreg={fy + 1}0{nreg}&amp;nregaud={nreg}">S\u00ed</a>' if detail else ""
    return (f'<tr><td>{nreg}</td><td>31/12/{fy}</td><td>{pub}</td><td>PWC</td>'
            f'<td><a href="{tok(nreg, "I")}">Individual</a> /<br/> <a href="{tok(nreg, "C")}">Consolidada</a></td>'
            f'<td><a href="{tok(nreg, "Z")}"><img/></a></td><td></td><td>{det}</td><td>Favorable</td><td>-</td><td>{remarks}</td></tr>')


def direct(nreg, fy, pub):
    return (f'<tr><td><a href="/AUDITA/{fy}/{nreg}.pdf">{nreg}</a></td><td>31/12/{fy}</td><td>{pub}</td><td>PWC</td><td></td><td></td><td></td>'
            f'<td></td><td>Limpia</td><td>-</td><td></td></tr>')


def listing(entity, rows):
    return (f'<html><head><title>CNMV - IFA - {entity}</title><script>var k="{FAKE}script";</script></head><body>'
            f'<form><input type="hidden" name="__VIEWSTATE" value="{FAKE}viewstate"/></form>'
            f'<p>Para visualizar el informe financiero anual remitido en formato FEUE, seleccione en la columna Tipo; '
            f'n&uacute;mero de registro oficial para PDF; xHTML.</p>'
            f'<table id="ctl00_ContentPrincipal_gridInformes"><caption> {entity} </caption><thead>{HEAD}</thead><tbody>{"".join(rows)}'
            f'</tbody></table></body></html>')


def detail_page(motive="Certificado del secretario", n=9):
    return (f'<html><head><title>Info adicional</title></head><body><table id="ctl00_ContentPrincipal_gridInformacionAdicional">'
            f'<caption>Informaci\u00f3n adicional</caption><thead><tr><th>Fecha de publicaci\u00f3n</th><th>Motivo</th><th>Documento</th></tr></thead>'
            f'<tbody><tr><td>25/02/2021</td><td>{motive}</td><td><a href="{tok(n, "D")}">doc</a></td></tr></tbody></table></body></html>')


ENT = {"A28015865": "TELEFONICA, S.A.", "A39000013": "BANCO SANTANDER, S.A.", "A-48010615": "IBERDROLA, S.A.",
       "A48265169": "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.", "A78374725": "REPSOL, S.A."}


def rows_for(base):
    return [tokenized(base + i, 2025 - i, f"2{i}/02/{2026 - i}") for i in range(6)] + [direct(base + 90, 2019, "20/02/2020")]


class Site:
    def __init__(self, handler=None):
        self.requests, self.handler = [], handler or self.default

    def default(self, request):
        p, nif = request.url.path, request.url.params.get("nif")
        if p == "/portal/Consultas/ifa/listadoifa":
            base = 1000 * (list(ENT).index(nif) + 1)
            return httpx.Response(200, text=listing(ENT[nif], rows_for(base)), headers={"content-type": "text/html"})
        if p == "/portal/Consultas/ifa/infadicionifa":
            return httpx.Response(200, text=detail_page(n=int(request.url.params.get("nregaud"))), headers={"content-type": "text/html"})
        return httpx.Response(404)

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)


def fetcher(site, **kw):
    clock = {"t": 0.0}

    def sleep(s):
        clock["t"] += s
    return BudgetedFetcher(site.client(), sleep=sleep, monotonic=lambda: clock["t"], **kw)


def root_of(tmp_path):
    return UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT).initialize().path


def all_bytes(root):
    return b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())


# ================================================================= clasificación y saneado
def test_links_are_classified_without_exposing_query_or_token():
    a = classify_href(tok(1, "I"), "salt1")
    assert (a.kind, a.host, a.path) == ("TOKENIZED", "www.cnmv.es", "/webservices/verdocumento/ver") and len(a.fp) == 12
    assert FAKE not in json.dumps(a.to_dict()) and "?" not in json.dumps(a.to_dict())
    assert classify_href(tok(1, "I"), "salt1").fp == a.fp and classify_href(tok(1, "I"), "salt2").fp != a.fp     # huella con sal por sesión
    assert classify_href(tok(1, "I"), "salt1").fp != classify_href(tok(2, "I"), "salt1").fp
    d = classify_href("/AUDITA/2019/18290.pdf", "s")
    assert (d.kind, d.registry, d.fp) == ("DIRECT_STABLE", "18290", None)
    det = classify_href("infadicionifa.aspx?id=0&nreg=2021024813&nregaud=18760&e=" + FAKE + "9999", "s")
    assert det.kind == "DETAIL_PAGE" and det.params == {"id": "0", "nreg": "2021024813", "nregaud": "18760"} and FAKE not in json.dumps(det.to_dict())
    assert classify_href("https://filings.xbrl.org/x.zip", "s").kind == "EXTERNAL"
    assert classify_href("/portal/otra.aspx?a=1", "s").kind == "OTHER"


def test_sanitized_evidence_has_no_token_query_fragment_script_or_viewstate():
    page = listing("TELEFONICA, S.A.", rows_for(100))
    clean = sanitize_html(page, "salt")
    for forbidden in (FAKE, "?", "#", "<script", "<input", "<form", "__VIEWSTATE", "<img", "?e="):
        assert forbidden not in clean, forbidden
    assert "data-token-fp=" in clean and "gridInformes" in clean and "TELEFONICA, S.A." in clean
    assert 'data-nreg="' in clean and 'data-nregaud="' in clean                     # identificadores de registro (no token) como atributos
    rows = parse_full(clean, "otra-sal")                                              # el extracto saneado sigue siendo analizable
    assert [r.nreg for r in rows][:2] == ["100", "101"] and link_kind_summary(rows[0]) == "DISCOVERED_TOKENIZED"
    assert {i.fp for i in rows[0].all_links() if i.fp} == {i.fp for i in parse_full(clean, "x")[0].all_links() if i.fp}   # conserva la huella
    d = sanitize_html(detail_page(), "salt")
    assert FAKE not in d and "gridInformacionAdicional" in d and "Certificado del secretario" in d
    assert "No se han encontrado datos disponibles" in sanitize_html("<html><body>No se han encontrado datos disponibles</body></html>", "s")


def test_sanitize_text_and_token_detector():
    raw = json.dumps({"url": tok(3, "I"), "ok": "https://www.cnmv.es/AUDITA/2019/1.pdf"})
    assert contains_token(raw) and not contains_token(sanitize_text(raw))
    assert json.loads(sanitize_text(raw))["url"] == "https://www.cnmv.es/webservices/verdocumento/ver"
    assert json.loads(sanitize_text(raw))["ok"].endswith("/AUDITA/2019/1.pdf")
    assert not contains_token("https://www.cnmv.es/portal/Consultas/ifa/listadoifa?id=0&nif=A28015865")


# ================================================================= presupuesto y reglas de red
def test_tokenized_and_document_endpoints_are_never_requested():
    site = Site()
    f = fetcher(site)
    f.begin_issuer("T")
    for url in (tok(1, "I"), "https://www.cnmv.es/webservices/verdocumento/ver", "https://www.cnmv.es/AUDITA/2019/1.pdf",
                "https://www.cnmv.es/x/file.zip", "https://www.cnmv.es/x/file.xhtml", "https://www.cnmv.es/x/img.png"):
        r = f.fetch(url)
        assert r.outcome == "NEEDS_REVIEW" and r.reason in ("TOKENIZED_ENDPOINT_FORBIDDEN", "DOCUMENT_ENDPOINT_FORBIDDEN")
        assert FAKE not in json.dumps(r.to_dict())
    assert site.requests == [] and f.total_requests == 0
    f.fetch("https://www.cnmv.es/x/file.zip", method="HEAD")
    assert site.requests == []                                                         # tampoco con HEAD


def test_request_budgets_per_issuer_and_total():
    site = Site(lambda r: httpx.Response(200, text="ok", headers={"content-type": "text/html"}))
    f = fetcher(site, max_per_issuer=3, max_total=5)
    outs = []
    for t in ("A", "B"):
        f.begin_issuer(t)
        outs += [f.fetch(f"https://www.cnmv.es/p{i}").reason for i in range(4)]
    assert outs.count("REQUEST_BUDGET_EXHAUSTED") == 3 and len(site.requests) == 5 and f.per_issuer == {"A": 3, "B": 2}


def test_first_403_halts_everything_and_status_counts_are_recorded():
    site = Site(lambda r: httpx.Response(403 if r.url.path == "/b" else 200, text="x", headers={"content-type": "text/html"}))
    f = fetcher(site)
    f.begin_issuer("T")
    assert f.fetch("https://www.cnmv.es/a").outcome == "OK"
    assert f.fetch("https://www.cnmv.es/b").reason == "HTTP_403" and f.halted == "HTTP_403"
    n = len(site.requests)
    r = f.fetch("https://www.cnmv.es/c")
    assert r.reason == "HALTED:HTTP_403" and len(site.requests) == n
    assert f.status_counts == {"200": 1, "403": 1}


def test_429_one_retry_ambiguous_redirects_and_cookies_are_not_forced():
    seq = [429, 200]
    site = Site(lambda r: httpx.Response(seq.pop(0), text="x", headers={"content-type": "text/html", "retry-after": "1",
                                                                       "set-cookie": "sid=1"}))
    f = fetcher(site)
    f.begin_issuer("T")
    assert f.fetch("https://www.cnmv.es/a").outcome == "OK" and len(site.requests) == 2 and f.status_counts["429"] == 1
    assert all("cookie" not in q.headers for q in site.requests)
    red = Site(lambda r: httpx.Response(302, headers={"location": "https://evil.example.org/x"}))
    g = fetcher(red)
    g.begin_issuer("T")
    assert g.fetch("https://www.cnmv.es/a").reason == "DOMAIN_NOT_ALLOWED" and len(red.requests) == 1
    wall = Site(lambda r: httpx.Response(200, text="Por favor, Iniciar sesión", headers={"content-type": "text/html"}))
    h = fetcher(wall)
    h.begin_issuer("T")
    assert h.fetch("https://www.cnmv.es/a").reason == "BLOCKED:LOGIN"


# ================================================================= ejecución completa
def run(tmp_path, site=None, inventory=None, **kw):
    site = site or Site()
    root = root_of(tmp_path)
    f = fetcher(site)
    out = u3.run_u3(root, fetcher=f, salt="testsalt", inventory=inventory, **kw)
    return root, site, out, f


def test_full_run_discovers_tokenized_cells_without_following_or_persisting_tokens(tmp_path):
    root, site, out, f = run(tmp_path)
    paths = [(q.method, q.url.path) for q in site.requests]
    assert set(p for _, p in paths) == {"/portal/Consultas/ifa/listadoifa", "/portal/Consultas/ifa/infadicionifa"}
    assert all(m == "GET" for m, _ in paths) and not any("verdocumento" in p or "AUDITA" in p for _, p in paths)
    assert out["requests_total"] == len(site.requests) == 5 * (1 + 6) and all(v <= 12 for v in out["requests_per_issuer"].values())
    assert out["requests_total"] <= 60 and out["documents_downloaded"] == 0 and out["document_bodies_read"] == 0
    assert out["http_status_counts"] == {"200": 35} and min(out["wait_seconds_between_requests"]) >= 5.0 - 1e-9
    assert all(q.headers["user-agent"] == "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com" and "cookie" not in q.headers for q in site.requests)
    cells = {(c["ticker"], c["fiscal_year"]): c for c in out["cells"]}
    assert len(cells) == 30
    c = cells[("TEF", 2020)]
    assert c["status"] == "DISCOVERED_TOKENIZED" and c["cross_class"] == "TOKENIZED_REQUIRES_APPROVAL" and c["ledger_status"] == "NEEDS_REVIEW"
    assert c["nreg"] == "1005" and c["pub_date"] and c["link_delivery"] == ["DETAIL_PAGE", "TOKENIZED"]
    assert c["formats"]["xhtml_feue_tipo_column"] == {"Consolidada": ["TOKENIZED"], "Individual": ["TOKENIZED"]}
    assert c["formats"]["zip_xbrl_column"] == ["TOKENIZED"] and len(c["token_fps"]) == 3 and c["additional_info"][0]["motive"]
    assert out["identity_evidence"]["repeated_fingerprints_in_session"] == 0 and out["identity_evidence"]["nreg_unique_across_cells"]
    # NINGÚN token (ni query) en ningún archivo bajo la raíz: resultados, evidencia saneada, telemetría, catálogo
    blob = all_bytes(root)
    assert FAKE.encode() not in blob and b"verdocumento/ver?" not in blob and b"__VIEWSTATE" not in blob
    assert not contains_token(blob.decode("utf-8", errors="ignore"))
    for sub in ("raw", "cas", "cas_pins", "manifests", "versions", "quarantine_unified"):
        assert not [p for p in (root / sub).rglob("*") if p.is_file()], sub
    led = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    assert {r.status.value for r in led.list()} == {"NEEDS_REVIEW"} and len(led.list()) == 30


def test_a_promoted_ledger_state_is_never_changed(tmp_path):
    root = root_of(tmp_path)
    led = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    key = CoverageKey("ES", "CNMV", "TEF", 2021, "CNMV_ANNUAL_REPORT")
    led.record(key, LedgerStatus.FOUND, run_id="r")
    led.record(key, LedgerStatus.PROMOTED, document_id="d", sha256="ab" * 32, run_id="r")
    u3.run_u3(root, fetcher=fetcher(Site()), salt="s")
    got = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT).get(key)
    assert got.status is LedgerStatus.PROMOTED                                      # el hallazgo tokenizado NO degrada un PROMOTED
    assert got.sha256 == "ab" * 32 and got.document_id == "d"


def test_403_stops_all_remaining_issuers_without_requests(tmp_path):
    def handler(request):
        if request.url.params.get("nif") == "A39000013":
            return httpx.Response(403, text="no")
        return Site().default(request)
    root, site, out, f = run(tmp_path, Site(handler))
    assert out["halted"] == "HTTP_403"
    seen = {q.url.params.get("nif") for q in site.requests if q.url.path.endswith("listadoifa")}
    assert seen == {"A28015865", "A39000013"}                                      # IBE, BBVA y REP nunca se piden
    cells = {(c["ticker"], c["fiscal_year"]): c for c in out["cells"]}
    assert cells[("SAN", 2022)]["reason"] == "HTTP_403" and cells[("IBE", 2022)]["reason"].startswith("HALTED")
    assert all(c["status"] in ("NEEDS_REVIEW", "SOURCE_UNAVAILABLE") for k, c in cells.items() if k[0] != "TEF")


def test_absent_year_wrong_entity_and_republication_signals(tmp_path):
    def handler(request):
        nif = request.url.params.get("nif")
        if request.url.path == "/portal/Consultas/ifa/infadicionifa":
            return httpx.Response(200, text=detail_page("Sustituye al informe anterior por error material"),
                                  headers={"content-type": "text/html"})
        if nif == "A39000013":
            return httpx.Response(200, text=listing("OTRA ENTIDAD, S.A.", rows_for(10)), headers={"content-type": "text/html"})
        if nif == "A48265169":
            return httpx.Response(200, text=listing(ENT[nif], [tokenized(1, 2020, "01/03/2021", remarks="Rectificación del informe"),
                                                              tokenized(2, 2020, "01/04/2021")]), headers={"content-type": "text/html"})
        return Site().default(request)
    _, _, out, _ = run(tmp_path, Site(handler))
    cells = {(c["ticker"], c["fiscal_year"]): c for c in out["cells"]}
    assert cells[("SAN", 2021)]["reason"] == "ENTITY_MISMATCH" and "nreg" not in cells[("SAN", 2021)]
    bb = cells[("BBVA", 2020)]
    assert bb["rows_for_year"] == 2 and bb["republication_signals"] and any("Rectificaci" in s for s in bb["republication_signals"])
    assert any("Sustituye" in s for s in bb["republication_signals"])
    assert cells[("BBVA", 2021)]["reason"] == "FY_ROW_ABSENT" and cells[("BBVA", 2021)]["status"] == "NEEDS_REVIEW"     # nunca NOT_PUBLISHED
    assert "BBVA:2020" in out["identity_evidence"]["cells_with_multiple_rows_per_year"]


def test_local_cross_check_uses_the_inventory_without_opening_files(tmp_path):
    inv = {"2021/A28015865_TEF/TEF_2021_ANUAL.pdf": {"ext": ".pdf", "size": 20260205, "sha256": u3.GENERIC_SHA_PREFIX + "0" * 52},
           "2022/A28015865_TEF/TEF_2022_ESEF.zip": {"ext": ".zip", "size": 999, "sha256": "ab" * 32}}
    _, _, out, _ = run(tmp_path, inventory=inv)
    cells = {(c["ticker"], c["fiscal_year"]): c for c in out["cells"]}
    assert cells[("TEF", 2021)]["local_class"] == "LOCAL_CONFLICT" and cells[("TEF", 2021)]["local_files"][0]["generic_placeholder"]
    assert cells[("TEF", 2022)]["local_class"] == "LOCAL_PRESENT_INSUFFICIENT_EVIDENCE"
    assert cells[("TEF", 2023)]["local_class"] == "MISSING_LOCAL"
    assert all(c["cross_class"] == "TOKENIZED_REQUIRES_APPROVAL" for c in cells.values() if c["status"] == "DISCOVERED_TOKENIZED")


def test_refuses_uninitialized_or_legacy_roots_and_never_writes_outside_the_root(tmp_path):
    with pytest.raises(DiscoveryError):
        u3.run_u3(tmp_path / "nope", fetcher=fetcher(Site()))
    with pytest.raises(Exception):
        u3.run_u3(Path("D:/ARGOS_DATA/raw/ES_CNMV/x"), fetcher=fetcher(Site()))
    before = {p for p in tmp_path.rglob("*")}
    root, *_ = run(tmp_path)
    assert {p for p in tmp_path.rglob("*") if root not in p.parents and p != root and p not in before} <= set()


def test_architecture_no_persistence_of_tokens_and_no_download_stack():
    for name in ("cnmv_evidence.py", "cnmv_u3.py"):
        text = (UNIFIED / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
               [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        for m in mods:
            assert not ({"requests", "socket", "subprocess", "download_service", "ingest_runner", "cas_store", "pilot_batch"} & set(m.split("."))), m
        assert ".unlink(" not in text and "rmtree" not in text
    for other in ("pilot_runner.py", "pilot_batch.py", "download_service.py", "ingest_runner.py", "cnmv_discovery.py"):
        t = (UNIFIED / other).read_text(encoding="utf-8")
        assert "cnmv_evidence" not in t and "cnmv_u3" not in t


def test_a_token_smuggled_into_a_text_field_blocks_persistence(tmp_path):
    def handler(request):
        if request.url.path == "/portal/Consultas/ifa/listadoifa" and request.url.params.get("nif") == "A28015865":
            return httpx.Response(200, text=listing(ENT["A28015865"], [tokenized(1, 2020, "01/03/2021", remarks=tok(77, "R"))]),
                                  headers={"content-type": "text/html"})
        return Site().default(request)
    root = root_of(tmp_path)
    with pytest.raises(DiscoveryError):
        u3.run_u3(root, fetcher=fetcher(Site(handler)), salt="s")
    assert not (root / "reports" / "pilot" / "discovery" / "cnmv_u3_results.json").exists()
    assert FAKE.encode() not in all_bytes(root)
