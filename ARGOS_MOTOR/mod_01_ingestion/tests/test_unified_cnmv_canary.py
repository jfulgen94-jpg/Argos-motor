"""
CNMV-C1 — Canario de UN recurso (TEF, 2020, registro 18760, ZIP/XBRL): selección exacta, presupuesto acumulado, no reanudación,
validación acotada del ZIP y ausencia de tokens. Todo sintético (httpx.MockTransport), raíz en tmp_path, SIN red real.
"""
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from mod_01_ingestion.src.unified import cnmv_canary as cc
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus
from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.transport import authorized_transport
from mod_01_ingestion.tests.test_unified_cnmv_u3 import FAKE, direct, listing, tok, tokenized

NREG = "18760"
ENT = "TELEFONICA, S.A."
KEY = CoverageKey("ES", "CNMV", "TEF", 2020, "CNMV_IFA_ZIP_XBRL")


def make_zip(members=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (members or {"informe.xhtml": b"<html>" + b"x" * 400 + b"</html>", "META-INF/taxonomyPackage.xml": b"<a/>" * 50}).items():
            z.writestr(name, data)
    return buf.getvalue()


ZIP = make_zip()


def page(rows=None):
    return listing(ENT, rows if rows is not None else [tokenized(NREG, 2020, "25/02/2021"), tokenized("17000", 2019, "25/02/2020"),
                                                       direct("16000", 2018, "20/02/2019")])


def zip_resp(data=ZIP):
    return httpx.Response(200, content=data, headers={"content-type": "application/zip"})


class Net:
    """Transporte simulado + reloj falso (sleep avanza el reloj; nadie duerme de verdad)."""
    def __init__(self, listing_resp=None, doc=None):
        self.t = 0.0
        self.requests = []
        self.times = []
        self.listing_resp = listing_resp or (lambda r: httpx.Response(200, text=page(), headers={"content-type": "text/html"}))
        self.doc = doc or (lambda r: zip_resp())
        self.transport = httpx.MockTransport(self)

    def __call__(self, request):
        self.requests.append(request)
        self.times.append(self.t)
        if request.url.path == "/portal/Consultas/ifa/listadoifa":
            out = self.listing_resp(request)
        elif request.url.path == "/webservices/verdocumento/ver":
            out = self.doc(request)
        else:
            out = httpx.Response(404)
        if isinstance(out, Exception):
            raise out
        return out

    def sleep(self, s):
        self.t += s

    def clock(self):
        return self.t


def setup(tmp_path):
    return UnifiedDataRoot(tmp_path / "unified_pilot", ExecutionMode.PILOT).initialize().path


def run(tmp_path, net, limits=None, phrase=cc.AUTH_PHRASE, root=None):
    return cc.run_canary(phrase, root_path=root or setup(tmp_path), inner_transport=net.transport, limits=limits,
                         sleep=net.sleep, clock=net.clock, retry_wait_s=15.0)


def tree_text(root):
    return b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file()).decode("utf-8", errors="ignore")


def no_leaks(blob):
    for leak in (FAKE, "?e=", "verdocumento/ver?", "%2bAAAA"):
        assert leak not in blob, leak


# ================================================================= selección exacta del recurso
def test_selects_exactly_the_zip_link_of_the_registry_row_never_individual_or_consolidated():
    sel = cc.select_zip_resource(page())
    assert (sel.registration_number, sel.fiscal_year) == (NREG, 2020) and sel.declared_resource_kind.startswith("Fichero ZIP/Xbri")
    with authorized_transport():
        url = sel.transport.reveal()
    assert url == tok(NREG, "Z") and url != tok(NREG, "I") and url != tok(NREG, "C")
    assert FAKE not in repr(sel) and FAKE not in str(sel.transport)             # el token no sale en ningún repr


@pytest.mark.parametrize("rows,why", [
    ([tokenized("17000", 2019, "25/02/2020")], "ROW_NOT_UNIQUE:0"),
    ([tokenized(NREG, 2020, "x"), tokenized(NREG, 2020, "y")], "ROW_NOT_UNIQUE:2"),
    ([tokenized(NREG, 2019, "x")], "FISCAL_YEAR_MISMATCH"),
    ([direct(NREG, 2020, "x")], "ZIP_LINK_NOT_UNIQUE:0"),
])
def test_ambiguous_or_missing_rows_are_rejected_not_guessed(rows, why):
    with pytest.raises(cc.ResourceSelectionError, match=why):
        cc.select_zip_resource(page(rows))


def test_two_zip_links_or_a_non_official_link_are_rejected():
    two = tokenized(NREG, 2020, "x").replace(f'<a href="{tok(NREG, "Z")}"><img/></a>',
                                              f'<a href="{tok(NREG, "Z")}">a</a><a href="{tok(NREG, "Y")}">b</a>')
    with pytest.raises(cc.ResourceSelectionError, match="ZIP_LINK_NOT_UNIQUE:2"):
        cc.select_zip_resource(page([two]))
    other = tokenized(NREG, 2020, "x").replace(tok(NREG, "Z"), "https://otro.example/doc?e=abc")
    with pytest.raises(cc.ResourceSelectionError, match="NOT_AN_OFFICIAL"):
        cc.select_zip_resource(page([other]))
    with pytest.raises(cc.ResourceSelectionError, match="ENTITY_MISMATCH"):
        cc.select_zip_resource(listing("OTRA, S.A.", [tokenized(NREG, 2020, "x")]))


# ================================================================= flujo completo y presupuesto
def test_full_canary_downloads_only_the_selected_zip_with_two_requests_and_leaves_no_token(tmp_path):
    net = Net()
    rep = run(tmp_path, net)
    assert rep["state"] == "COMPLETED" and rep["downloaded"] and rep["outcome"]["ledger_status"] == "PROMOTED"
    assert [r.url.path for r in net.requests] == ["/portal/Consultas/ifa/listadoifa", "/webservices/verdocumento/ver"]
    assert net.requests[1].url.params.get("e").startswith(FAKE + NREG + "Z")           # el recurso pedido es el ZIP de la fila exacta
    assert all("range" not in r.headers and "if-range" not in r.headers for r in net.requests)
    assert all(r.url.host == "www.cnmv.es" for r in net.requests)
    assert net.times[1] - net.times[0] >= 5                                            # pausa mínima entre peticiones
    assert rep["transport"]["requests"] == 2 and rep["transport"]["bytes_received"] > len(ZIP)
    assert rep["outcome"]["registration_number"] == NREG and "Fichero ZIP/Xbri" in rep["outcome"]["declared_resource_kind"]
    assert rep["outcome"]["sha256_is_official"] is False and rep["approved_by_second_person"] is None
    assert rep["zip"]["status"] == "OK_CLASSIFIED" and rep["zip"]["classification"] == "ZIP_WITH_XBRL_XHTML_MEMBERS"
    root = tmp_path / "unified_pilot"
    no_leaks(tree_text(root))
    assert not list(root.rglob("*.part*"))
    led = CoverageLedger(root / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    assert led.get(KEY).status is LedgerStatus.PROMOTED
    assert [r.key for r in led.list()] == [KEY]                                        # ninguna otra celda tocada
    man = json.loads(next((root / "manifests").rglob("*.json")).read_text(encoding="utf-8"))
    assert man["registration_number"] == NREG and man["source_url"] == "https://www.cnmv.es/webservices/verdocumento/ver"


def test_wrong_phrase_or_uninitialised_root_does_nothing(tmp_path):
    net = Net()
    with pytest.raises(cc.CanaryError):
        cc.run_canary("AUTORIZO PILOTO CNMV TEF 2019", root_path=setup(tmp_path), inner_transport=net.transport)
    with pytest.raises(cc.CanaryError):
        cc.run_canary(cc.AUTH_PHRASE, root_path=tmp_path / "vacio" / "unified_pilot", inner_transport=net.transport)
    assert net.requests == []


def test_limits_cannot_be_widened():
    for bad in ({"max_requests": 6}, {"max_documents": 2}, {"max_total_bytes": 257 * cc.MiB}, {"max_total_s": 601},
                {"min_interval_s": 1}, {"max_retries": 2}, {"retry_statuses": (403,)}, {"request_timeout_s": 61},
                {"allowed_host": "cnmv.es"}):
        with pytest.raises(cc.CanaryError):
            cc.CanaryLimits(**bad)


def test_a_single_retry_in_total_across_listing_and_download(tmp_path):
    seq = {"n": 0}

    def listing_resp(r):
        seq["n"] += 1
        return httpx.Response(503) if seq["n"] == 1 else httpx.Response(200, text=page(), headers={"content-type": "text/html"})
    net = Net(listing_resp=listing_resp, doc=lambda r: httpx.Response(503))
    rep = run(tmp_path, net)
    assert rep["state"] != "COMPLETED" and not rep["downloaded"]
    assert net.requests and len(net.requests) == 3 and rep["transport"]["retries"] == 1      # listado, reintento del listado, descarga
    assert [r.url.path for r in net.requests][-1] == "/webservices/verdocumento/ver"          # la descarga no obtuvo 2.º reintento
    assert rep["transport"]["budget_exceeded"] == "CANARY_RETRY_BUDGET_EXHAUSTED"
    assert len(net.requests) <= 5
    no_leaks(tree_text(tmp_path / "unified_pilot"))


def test_download_retries_once_on_503_then_succeeds_within_five_requests(tmp_path):
    seq = {"n": 0}

    def doc(r):
        seq["n"] += 1
        return httpx.Response(503) if seq["n"] == 1 else zip_resp()
    net = Net(doc=doc)
    rep = run(tmp_path, net)
    assert rep["state"] == "COMPLETED" and rep["transport"]["requests"] == 3 and rep["transport"]["retries"] == 1
    assert all("range" not in r.headers for r in net.requests)
    assert all(b - a >= 5 for a, b in zip(net.times, net.times[1:]))


def test_403_on_the_resource_stops_and_marks_needs_review(tmp_path):
    net = Net(doc=lambda r: httpx.Response(403))
    rep = run(tmp_path, net)
    assert not rep["downloaded"] and rep["transport"]["halted"] == "HTTP_403" and len(net.requests) == 2
    led = CoverageLedger(tmp_path / "unified_pilot" / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    assert led.get(KEY).status is LedgerStatus.NEEDS_REVIEW
    no_leaks(tree_text(tmp_path / "unified_pilot"))


def test_403_on_the_listing_never_requests_the_resource(tmp_path):
    net = Net(listing_resp=lambda r: httpx.Response(403))
    rep = run(tmp_path, net)
    assert rep["state"] == "NEEDS_REVIEW" and [r.url.path for r in net.requests] == ["/portal/Consultas/ifa/listadoifa"]


class Chunks(httpx.SyncByteStream):
    """Cuerpo sin Content-Length (el tope por documento no puede anticiparse): solo el contador acumulado lo detiene."""
    def __init__(self, n, size=1000):
        self.n, self.size = n, size

    def __iter__(self):
        for _ in range(self.n):
            yield b"0" * self.size


def test_cumulative_bytes_stop_a_body_without_content_length_and_leave_no_partial(tmp_path):
    net = Net(doc=lambda r: httpx.Response(200, stream=Chunks(20), headers={"content-type": "application/zip"}))
    lim = cc.CanaryLimits(max_total_bytes=len(page().encode("utf-8")) + 3000)
    rep = run(tmp_path, net, limits=lim)
    assert not rep["downloaded"] and rep["transport"]["budget_exceeded"] == "CANARY_TOTAL_BYTES_EXCEEDED"
    assert lim.max_total_bytes < rep["transport"]["bytes_received"] <= lim.max_total_bytes + 1000      # se corta en cuanto se supera
    assert not list((tmp_path / "unified_pilot").rglob("*.part*")) and not list((tmp_path / "unified_pilot" / "raw").rglob("*.zip"))


def test_declared_size_over_the_cumulative_limit_is_refused_before_reading_the_body(tmp_path):
    big = b"PK" + b"0" * 6000
    net = Net(doc=lambda r: httpx.Response(200, content=big, headers={"content-type": "application/zip"}))
    rep = run(tmp_path, net, limits=cc.CanaryLimits(max_total_bytes=len(page().encode("utf-8")) + 3000))
    assert not rep["downloaded"] and rep["outcome"]["error_class"] == "SIZE_EXCEEDED" and rep["transport"]["bytes_received"] < 3000


def test_budget_is_cumulative_across_requests_including_failed_ones():
    inner = httpx.MockTransport(lambda r: httpx.Response(500, content=b"x" * 100))
    bt = cc.BudgetedTransport(inner, cc.CanaryLimits(max_total_bytes=150), clock=lambda: 0.0, sleep=lambda s: None)
    c = httpx.Client(transport=bt)
    c.get("https://www.cnmv.es/a").read()                                              # 100 bytes (respuesta fallida)
    with pytest.raises(cc.CanaryBudgetExceeded) as ex:
        c.get("https://www.cnmv.es/b").read()                                         # 200 acumulados > 150
    assert ex.value.code == "CANARY_TOTAL_BYTES_EXCEEDED" and bt.bytes_received == 200 and bt.requests == 2


def test_transport_refuses_resume_headers_other_domains_and_plain_http():
    bt = cc.BudgetedTransport(httpx.MockTransport(lambda r: httpx.Response(200)), cc.CanaryLimits(), clock=lambda: 0.0,
                              sleep=lambda s: None)
    c = httpx.Client(transport=bt)
    for url, hdr, code in (("https://www.cnmv.es/x", {"Range": "bytes=1-"}, "CANARY_RESUME_FORBIDDEN"),
                           ("https://www.cnmv.es/x", {"If-Range": "e"}, "CANARY_RESUME_FORBIDDEN"),
                           ("https://cnmv.es/x", {}, "CANARY_DOMAIN_NOT_ALLOWED"),
                           ("http://www.cnmv.es/x", {}, "CANARY_DOMAIN_NOT_ALLOWED"),
                           ("https://user:pw@www.cnmv.es/x", {}, "CANARY_DOMAIN_NOT_ALLOWED")):
        with pytest.raises(cc.CanaryBudgetExceeded) as ex:
            c.get(url, headers=hdr)
        assert ex.value.code == code
    assert bt.requests == 0                                                              # ninguna llegó a enviarse


def test_request_budget_counts_redirects_and_never_leaves_the_domain(tmp_path):
    hops = {"n": 0}

    def doc(r):
        hops["n"] += 1
        return httpx.Response(302, headers={"location": f"https://www.cnmv.es/webservices/verdocumento/ver?e=REDIRTOK{hops['n']}"})
    net = Net(doc=doc)
    rep = run(tmp_path, net)
    assert not rep["downloaded"] and len(net.requests) == 5 and rep["transport"]["budget_exceeded"] == "CANARY_REQUEST_BUDGET_EXHAUSTED"
    off = Net(doc=lambda r: httpx.Response(302, headers={"location": "https://evil.example/x.zip"}))
    rep2 = run(tmp_path / "b", off)
    assert not rep2["downloaded"] and all(r.url.host == "www.cnmv.es" for r in off.requests)
    assert rep2["transport"]["budget_exceeded"] == "CANARY_DOMAIN_NOT_ALLOWED"
    blob = tree_text(tmp_path / "unified_pilot") + tree_text(tmp_path / "b" / "unified_pilot")
    no_leaks(blob)
    assert "REDIRTOK" not in blob


def test_total_time_limit_is_enforced_and_the_pace_is_kept():
    t = {"now": 0.0}
    slept = []

    def sleep(x):
        slept.append(x)
        t["now"] += x
    bt = cc.BudgetedTransport(httpx.MockTransport(lambda r: httpx.Response(200)), cc.CanaryLimits(max_total_s=100),
                              clock=lambda: t["now"], sleep=sleep)
    c = httpx.Client(transport=bt)
    c.get("https://www.cnmv.es/a").read()
    c.get("https://www.cnmv.es/b").read()
    assert slept == [5.0]                                                                # la 2.ª petición espera la pausa mínima
    t["now"] = 101.0
    with pytest.raises(cc.CanaryBudgetExceeded) as ex:
        c.get("https://www.cnmv.es/c")
    assert ex.value.code == "CANARY_TIME_EXCEEDED" and bt.requests == 2


def test_already_promoted_cell_is_not_requested_again(tmp_path):
    net = Net()
    run(tmp_path, net)
    n = len(net.requests)
    again = run(tmp_path, net, root=tmp_path / "unified_pilot")
    assert again["state"] == "SKIPPED_ALREADY_PROMOTED" and len(net.requests) == n


def test_html_error_page_instead_of_zip_is_not_promoted(tmp_path):
    net = Net(doc=lambda r: httpx.Response(200, text="<html><body>Error</body></html>", headers={"content-type": "text/html"}))
    rep = run(tmp_path, net)
    assert not rep["downloaded"] and rep["outcome"]["ledger_status"] != "PROMOTED"


# ================================================================= validación acotada del ZIP
def test_inspect_zip_resource_cases(tmp_path):
    def put(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return p
    ok = cc.inspect_zip_resource(put("ok.zip", ZIP))
    assert ok["status"] == "OK_CLASSIFIED" and ok["members"] == 2 and "informe.xhtml" in ok["first_members"]
    assert not (tmp_path / "informe.xhtml").exists()                                    # nada se extrae
    assert cc.inspect_zip_resource(put("pdf.zip", make_zip({"a.pdf": b"%PDF"})))["classification"] == "ZIP_WITH_PDF_ONLY"
    amb = cc.inspect_zip_resource(put("amb.zip", make_zip({"a.bin": b"1234"})))
    assert amb["status"] == "NEEDS_REVIEW" and amb["classification"] == "AMBIGUOUS_CONTENT"
    assert cc.inspect_zip_resource(put("html.zip", b"<html>no</html>"))["status"] == "NOT_A_ZIP"
    slip = cc.inspect_zip_resource(put("slip.zip", make_zip({"../../evil.xhtml": b"x"})))
    assert slip["status"] == "UNSAFE_ARCHIVE" and slip["reasons"] == ["ZIP_SLIP"]
    bad = bytearray(ZIP)
    bad[40] ^= 0xFF                                                                     # corrompe un byte de datos/CRC
    res = cc.inspect_zip_resource(put("bad.zip", bytes(bad)))
    assert res["status"] == "CORRUPT_ARCHIVE"
    bomb = make_zip({"big.xml": b"0" * (5 * 1024 * 1024)})
    assert cc.inspect_zip_resource(put("bomb.zip", bomb))["status"] == "UNSAFE_ARCHIVE"


def test_zip_without_a_primary_document_is_quarantined_and_left_in_needs_review(tmp_path):
    net = Net(doc=lambda r: zip_resp(make_zip({"datos.bin": b"1234" * 40})))
    rep = run(tmp_path, net)
    assert not rep["downloaded"] and rep["state"] == "QUARANTINED" and rep["outcome"]["ledger_status"] == "NEEDS_REVIEW"
    led = CoverageLedger(tmp_path / "unified_pilot" / "catalog" / "unified_catalog.duckdb", ExecutionMode.PILOT)
    assert led.get(KEY).status is LedgerStatus.NEEDS_REVIEW
    assert not list((tmp_path / "unified_pilot" / "raw").rglob("*.zip"))
    no_leaks(tree_text(tmp_path / "unified_pilot"))


# ================================================================= plan pendiente
def test_plan_artifact_matches_code_and_grants_nothing():
    f = Path(__file__).resolve().parents[1] / "config" / "pilot" / "cnmv_canary" / "canary_tef_2020.pending.json"
    on_disk = json.loads(f.read_text(encoding="utf-8"))
    assert on_disk == cc.canary_plan()
    assert on_disk["status"] == "PENDING_OWNER_AUTHORIZATION" and on_disk["authorization"]["granted_by"] is None
    assert on_disk["authorization"]["four_eyes"] is False and "Francisca" not in json.dumps(on_disk)
    lim = on_disk["limits"]
    assert (lim["max_requests"], lim["max_total_bytes"], lim["max_total_s"], lim["max_retries"]) == (5, 256 * 1024 * 1024, 600.0, 1)
    assert "A28015865" in json.dumps(on_disk) and on_disk["scope"]["republication_confirmed"] is False
    assert on_disk["destination_root"] == "D:/ARGOS_DATA/unified_pilot"
    no_leaks(json.dumps(on_disk))
