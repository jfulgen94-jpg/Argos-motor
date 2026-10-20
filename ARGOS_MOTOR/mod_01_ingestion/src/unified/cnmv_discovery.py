"""
CNMV-U1 — Descubrimiento LIMITADO de referencias oficiales CNMV, SIN descargar documentos.

``DiscoveryFetcher`` es el ÚNICO camino de red de este módulo y solo pide PÁGINAS de consulta (HTML/JSON/texto):
* dominio único aprobado (``www.cnmv.es``), https, sin credenciales; cada redirección se valida ANTES de pedirla;
* una petición concurrente y al menos 5 s entre peticiones; 60 s por petición; plazo total por emisor;
* un único reintento y solo tras 429/503; 403, 404 y cualquier otro estado → ``NEEDS_REVIEW`` (sin reintento);
* una respuesta que sea un DOCUMENTO (PDF/ZIP/octet-stream/adjunto) NO se lee: se cierra la conexión y la URL queda como candidata;
* cookies, login, CAPTCHA, WAF o URL firmada → se detiene esa fuente (``NEEDS_REVIEW``); las cookies del servidor NO se reenvían.
No escribe nada: quien lo use decide dónde guardar los resultados.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message

ALLOWED_HOSTS = ("www.cnmv.es",)
USER_AGENT = "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com"
PAGE_TYPES = ("text/html", "application/xhtml+xml", "application/json", "text/plain", "text/xml", "application/xml")
DOCUMENT_TYPES = ("application/pdf", "application/zip", "application/octet-stream", "application/x-zip-compressed",
                  "application/xhtml", "application/msword", "application/vnd")
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
RETRY_ONCE = frozenset({429, 503})
_SIGNED = re.compile(r"(?i)([?&](sig|signature|token|access_token|x-amz-signature|expires|se|sv)=)")
_BLOCK_MARKERS = (("captcha", "CAPTCHA"), ("recaptcha", "CAPTCHA"), ("g-recaptcha", "CAPTCHA"), ("iniciar sesi", "LOGIN"),
                  ("acceso restringido", "LOGIN"), ("request rejected", "WAF"), ("access denied", "WAF"),
                  ("enable cookies", "COOKIE_REQUIRED"), ("cookies must be", "COOKIE_REQUIRED"),
                  ("habilite las cookies", "COOKIE_REQUIRED"))


class DiscoveryError(DomainValidationError):
    pass


class NoDataError(DiscoveryError):
    """La ficha oficial existe pero no devuelve datos para ese NIF (¿otra grafía del NIF?)."""


@dataclass
class FetchResult:
    url: str
    outcome: str                       # OK | DOCUMENT_NOT_DOWNLOADED | NEEDS_REVIEW
    reason: Optional[str] = None       # HTTP_403, HTTP_404, BLOCKED:CAPTCHA, SIGNED_URL, NETWORK, TIMEOUT, PAGE_TOO_LARGE ...
    status: Optional[int] = None
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    text: Optional[str] = None
    bytes_read: int = 0
    requests_made: int = 0
    set_cookie_seen: bool = False
    content_length: Optional[int] = None
    last_modified: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"url": self.url, "outcome": self.outcome, "reason": self.reason, "status": self.status,
                "final_url": self.final_url, "content_type": self.content_type, "bytes_read": self.bytes_read,
                "requests_made": self.requests_made, "set_cookie_seen": self.set_cookie_seen,
                "content_length": self.content_length, "last_modified": self.last_modified}


def check_url(url: str) -> Optional[str]:
    """None si la URL es admisible; si no, el motivo (nunca se hace la petición)."""
    u = urlsplit(url)
    if u.scheme != "https" or u.username or u.password or (u.hostname or "").lower() not in ALLOWED_HOSTS:
        return "DOMAIN_NOT_ALLOWED"
    if u.port not in (None, 443) or u.fragment:
        return "DOMAIN_NOT_ALLOWED"
    if _SIGNED.search("?" + u.query if u.query else ""):
        return "SIGNED_URL"
    return None


class DiscoveryFetcher:
    def __init__(self, client: Optional[httpx.Client] = None, *, min_interval_s: float = 5.0, timeout_s: float = 60.0,
                 per_issuer_s: float = 300.0, retry_wait_s: float = 15.0, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, telemetry=None):
        self._client = client or httpx.Client(follow_redirects=False, timeout=timeout_s)
        self.min_interval_s, self.timeout_s, self.per_issuer_s = min_interval_s, timeout_s, per_issuer_s
        self.retry_wait_s, self._sleep, self._mono, self.telemetry = retry_wait_s, sleep, monotonic, telemetry
        self._last_start: Optional[float] = None
        self._issuer: Optional[str] = None
        self._issuer_t0 = 0.0
        self.total_requests = 0
        self.log: List[Dict[str, Any]] = []

    def begin_issuer(self, issuer: str) -> None:
        self._issuer, self._issuer_t0 = issuer, self._mono()

    def _emit(self, event: str, **kw):
        if self.telemetry is not None:
            self.telemetry.emit(event, None, "cnmv_discovery", **kw)

    def _pace(self) -> None:
        if self._last_start is not None:
            wait = self.min_interval_s - (self._mono() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._mono()

    def _one(self, url: str, method: str = "GET") -> FetchResult:
        """UNA petición sin seguir redirecciones (se tratan en ``fetch``). ``HEAD`` solo obtiene cabeceras."""
        res = FetchResult(url=url, outcome="NEEDS_REVIEW", requests_made=1)
        self._pace()
        self.total_requests += 1
        try:
            with self._client.stream(method, url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.1",
                                                          "Accept-Language": "es-ES,es;q=0.9"}, timeout=self.timeout_s) as resp:
                self._client.cookies.clear()                       # nunca se reenvían cookies del servidor
                res.status, res.final_url = resp.status_code, str(resp.url)
                res.set_cookie_seen = bool(resp.headers.get("set-cookie"))
                clen = resp.headers.get("content-length")
                res.content_length = int(clen) if clen and clen.isdigit() else None
                res.last_modified = resp.headers.get("last-modified")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                res.content_type = ctype or None
                if resp.status_code in (301, 302, 303, 307, 308):
                    res.outcome, res.reason = "REDIRECT", resp.headers.get("location")
                    return res
                if resp.status_code in RETRY_ONCE:
                    res.reason = f"HTTP_{resp.status_code}"
                    res.outcome = "RETRYABLE"
                    ra = resp.headers.get("retry-after")
                    res.text = ra
                    return res
                if resp.status_code != 200:
                    res.reason = f"HTTP_{resp.status_code}"
                    return res
                disp = resp.headers.get("content-disposition", "").lower()
                if "attachment" in disp or any(ctype.startswith(t) for t in DOCUMENT_TYPES) or (ctype and ctype not in PAGE_TYPES):
                    res.outcome, res.reason = "DOCUMENT_NOT_DOWNLOADED", "DOCUMENT_RESPONSE_NOT_READ"
                    return res                                     # se sale del bloque: la conexión se cierra sin leer el cuerpo
                buf = bytearray()
                for chunk in resp.iter_bytes(8192):
                    buf += chunk
                    if len(buf) > MAX_PAGE_BYTES:
                        res.reason, res.bytes_read = "PAGE_TOO_LARGE", len(buf)
                        return res
                res.bytes_read = len(buf)
                text = bytes(buf).decode(resp.encoding or "utf-8", errors="replace")
                low = text.lower()
                for marker, kind in _BLOCK_MARKERS:
                    if marker in low:
                        res.reason = f"BLOCKED:{kind}"
                        return res
                res.outcome, res.text = "OK", text
                return res
        except httpx.TimeoutException:
            res.reason = "TIMEOUT"
        except httpx.RequestError as ex:
            res.reason = f"NETWORK:{type(ex).__name__}"
        return res

    def fetch(self, url: str, method: str = "GET") -> FetchResult:
        if method not in ("GET", "HEAD"):
            raise DiscoveryError("solo GET o HEAD")
        bad = check_url(url)
        if bad:
            return FetchResult(url=url, outcome="NEEDS_REVIEW", reason=bad)
        made, retried, cur = 0, False, url
        redirects = 0
        while True:
            if self._mono() - self._issuer_t0 > self.per_issuer_s:
                r = FetchResult(url=url, outcome="NEEDS_REVIEW", reason="ISSUER_TIME_BUDGET", requests_made=made)
                break
            r = self._one(cur, method)
            made += 1
            self.log.append({"issuer": self._issuer, "url": cur, "status": r.status, "outcome": r.outcome, "reason": r.reason})
            self._emit("discovery_request", issuer=self._issuer, url=cur, status=r.status, outcome=r.outcome, reason=r.reason)
            if r.outcome == "REDIRECT":
                nxt = urljoin(cur, r.reason or "")
                redirects += 1
                bad = check_url(nxt)
                if bad or redirects > MAX_REDIRECTS:
                    r = FetchResult(url=url, outcome="NEEDS_REVIEW", reason=bad or "TOO_MANY_REDIRECTS", status=r.status,
                                    requests_made=made)
                    break
                cur = nxt
                continue
            if r.outcome == "RETRYABLE":
                if retried:
                    r.outcome = "NEEDS_REVIEW"
                    break
                retried = True
                try:
                    wait = min(float(r.text), 30.0) if r.text else self.retry_wait_s
                except ValueError:
                    wait = self.retry_wait_s
                self._sleep(max(wait, self.min_interval_s))
                continue
            break
        r.url, r.requests_made = url, made
        if r.outcome == "RETRYABLE":
            r.outcome = "NEEDS_REVIEW"
        r.reason = sanitize_message(r.reason) if r.reason else r.reason
        return r


# ====================================================================== listado oficial de informes financieros anuales (IFA)
import hashlib  # noqa: E402
import html as _html  # noqa: E402
import unicodedata  # noqa: E402

LISTING_URL = "https://www.cnmv.es/portal/Consultas/ifa/listadoifa?id=0&nif={nif}"
AUDITA_RE = re.compile(r"^/AUDITA/(\d{4})/(\d+)\.pdf$")
_TAG = re.compile(r"<[^>]+>")


def nif_variants(nif: str) -> List[str]:
    """Grafías del NIF que usa el registro de la CNMV: sin guion y con guion tras la letra (misma regla que el motor legado)."""
    n = re.sub(r"[^A-Z0-9]", "", nif.upper())
    return [n, f"{n[0]}-{n[1:]}"] if len(n) > 1 else [n]


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", s))).strip()


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


@dataclass
class IfaRow:
    nreg: str
    fy_date: Optional[str]
    pub_date: Optional[str]
    auditor: Optional[str]
    fiscal_year: Optional[int]
    audita_urls: List[str] = field(default_factory=list)       # enlaces directos /AUDITA/<año>/<nreg>.pdf de la propia ficha
    extra_audita: List[str] = field(default_factory=list)      # REQ/INF u otros ficheros de la misma ficha
    tokenized_links: int = 0                                   # enlaces ``verdocumento/ver?e=…`` (token opaco: no se usan)
    tokenized_ref: List[str] = field(default_factory=list)     # huella (sha256[:12]) de cada token, nunca el token
    has_zip_link: bool = False
    has_detail_page: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class IfaListing:
    entity: Optional[str]
    rows: List[IfaRow]


def parse_ifa_listing(page: str) -> IfaListing:
    """Parsea la tabla ``gridInformes`` de la ficha IFA. Sin red. Una tabla ausente o sin cabecera esperada es un error explícito."""
    cap = re.search(r"<caption[^>]*>(.*?)</caption>", page, re.S)
    m = re.search(r"<table[^>]*gridInformes[^>]*>(.*?)</table>", page, re.S)
    if not m:
        if "No se han encontrado datos disponibles" in page:
            raise NoDataError("listado IFA: la CNMV responde que no hay datos para ese NIF")
        raise DiscoveryError("listado IFA: no se encontró la tabla de informes")
    body = m.group(1)
    head = re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)
    names = [_norm(_plain(h)) for h in head]

    def col(*needles) -> Optional[int]:
        for i, n in enumerate(names):
            if all(x in n for x in needles):
                return i
        return None

    i_reg, i_fy, i_pub, i_aud, i_zip = col("registro"), col("estados financieros"), col("publicaci"), col("auditor", "nombre"), col("zip")
    if i_reg is None or i_fy is None:
        raise DiscoveryError("listado IFA: cabecera inesperada (faltan registro/fecha)")
    rows: List[IfaRow] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds or len(tds) <= max(i_reg, i_fy):
            continue
        nreg = _plain(tds[i_reg])
        if not re.fullmatch(r"\d+", nreg):
            continue
        fy_date = _plain(tds[i_fy]) or None
        fy = None
        mm = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", fy_date or "")
        if mm:
            fy = int(mm.group(3))
        hrefs = [_html.unescape(h) for h in re.findall(r'<a\s[^>]*href="([^"]+)"', tr)]
        row = IfaRow(nreg=nreg, fy_date=fy_date, pub_date=(_plain(tds[i_pub]) or None) if i_pub is not None and i_pub < len(tds) else None,
                     auditor=(_plain(tds[i_aud]) or None) if i_aud is not None and i_aud < len(tds) else None, fiscal_year=fy)
        for h in hrefs:
            path = urlsplit(h).path if h.startswith("http") else h
            if "verdocumento" in h:
                row.tokenized_links += 1
                row.tokenized_ref.append(hashlib.sha256(h.encode("utf-8")).hexdigest()[:12])
            elif AUDITA_RE.match(path):
                (row.audita_urls if AUDITA_RE.match(path).group(2) == nreg else row.extra_audita).append(urljoin("https://www.cnmv.es", path))
            elif path.startswith("/AUDITA/"):
                row.extra_audita.append(urljoin("https://www.cnmv.es", path))
            elif "infadicion" in h.lower() or "opinionauditor" in h.lower():
                row.has_detail_page = True
        if i_zip is not None and i_zip < len(tds) and "verdocumento" in tds[i_zip]:
            row.has_zip_link = True
        rows.append(row)
    return IfaListing(entity=_plain(cap.group(1)) if cap else None, rows=rows)


# ====================================================================== orquestación del descubrimiento (sin descargas)
import csv as _csv  # noqa: E402
import json as _json  # noqa: E402
import os as _os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

ISSUERS = {"TEF": ("A28015865", "TELEFONICA, S.A."), "SAN": ("A39000013", "BANCO SANTANDER, S.A."),
           "IBE": ("A48010615", "IBERDROLA, S.A."), "BBVA": ("A48265169", "BANCO BILBAO VIZCAYA ARGENTARIA, S.A."),
           "REP": ("A78374725", "REPSOL, S.A.")}
YEARS = (2018, 2019, 2020)
DOC_TYPE = "CNMV_ANNUAL_REPORT"
GENERIC_SHA_PREFIX = "a80b7cc89747"               # PDF genérico repetido en D: (ver CNMV-U0): NO es un informe anual
LEGACY_ROOT = _os.path.normcase(r"D:\ARGOS_DATA\raw\ES_CNMV")
ARGOS_MOTOR = Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_comparison(ticker: str, fy: int, row: Optional[IfaRow], head: Optional[Dict[str, Any]],
                     inventory: Optional[Dict[str, str]] = None, downloaded_sha: Optional[str] = None) -> Dict[str, Any]:
    """SOLO LECTURA: contrasta lo oficial descubierto con el registro local (manifiesto del checkout) y el archivo de D: (``stat``)."""
    mpath = ARGOS_MOTOR / "audits" / "manifests" / f"MANIFEST_CNMV_{fy}.json"
    out: Dict[str, Any] = {"local_manifest": None, "category": "INSUFFICIENT_EVIDENCE", "notes": []}
    try:
        recs = [r for r in _json.loads(mpath.read_text(encoding="utf-8"))["manifest"] if r.get("ticker") == ticker]
    except (OSError, ValueError, KeyError):
        recs = []
    if not recs:
        out["notes"].append("sin registro local para este emisor/ejercicio")
        return out
    rec = recs[0]
    local_nreg = None
    m = re.search(r"/AUDITA/\d{4}/(\d+)\.pdf$", rec.get("url") or "")
    if m:
        local_nreg = m.group(1)
    p = str(rec.get("path") or "")
    on_disk = size = None
    if _os.path.normcase(p).startswith(LEGACY_ROOT):
        try:
            st = _os.stat(p)
            on_disk, size = True, st.st_size
        except OSError:
            on_disk = False
    rel = p.replace("\\", "/").split("/ES_CNMV/")[-1]
    inv_sha = (inventory or {}).get(rel)
    out["local_manifest"] = {"url": rec.get("url"), "nreg_in_url": local_nreg, "manifest_sha256": rec.get("sha256"),
                             "manifest_size": rec.get("size_bytes"), "file_on_disk": on_disk, "disk_size": size,
                             "inventory_sha256": inv_sha}
    sha = inv_sha or rec.get("sha256")
    if sha and str(sha).startswith(GENERIC_SHA_PREFIX):
        out["category"] = "LOCAL_PLACEHOLDER_CONTENT"
        out["notes"].append("el archivo local es el PDF genérico repetido (no es este informe)")
        return out
    if row is None:
        out["notes"].append("el listado oficial no tiene fila para este ejercicio")
        return out
    if local_nreg is None:
        out["notes"].append("la URL local no es una URL AUDITA: no se puede comparar el número de registro")
        return out
    if local_nreg != row.nreg:
        out["category"] = "DIFFERENT"
        out["notes"].append(f"registro local {local_nreg} != oficial {row.nreg}")
        return out
    if downloaded_sha and sha and downloaded_sha == sha:
        out["category"] = "HASH_MATCH"
        out["notes"].append("hash de la descarga del piloto == hash local (el mismo registro oficial)")
        return out
    rsize = (head or {}).get("content_length")
    if rsize is not None and size is not None:
        if rsize == size:
            out["category"] = "SIZE_MATCH_HASH_UNVERIFIED"
            out["notes"].append("mismo número de registro y mismo tamaño; el hash oficial no es comprobable sin descargar")
        else:
            out["category"] = "DIFFERENT"
            out["notes"].append(f"tamaño local {size} != Content-Length oficial {rsize}")
        return out
    out["notes"].append("mismo número de registro; sin tamaño remoto o archivo local para comparar")
    return out


def run_discovery(root: Path, *, issuers=ISSUERS, years=YEARS, fetcher: Optional[DiscoveryFetcher] = None,
                  cached_pages: Optional[Dict[str, Path]] = None, inventory: Optional[Dict[str, str]] = None,
                  downloaded: Optional[Dict[str, str]] = None, clock=_now, merge_previous: bool = False) -> Dict[str, Any]:
    """Descubre en el listado oficial IFA, sin descargar documentos. Escribe SOLO bajo ``root`` (resultados, ledger, telemetría)."""
    from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus
    from mod_01_ingestion.src.unified.data_root import UnifiedDataRoot, validate_unified_root
    from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
    from mod_01_ingestion.src.unified.models import RunContext
    from mod_01_ingestion.src.unified.telemetry import TelemetryLogger

    root = Path(root)
    validate_unified_root(root, ExecutionMode.PILOT)
    ur = UnifiedDataRoot(root, ExecutionMode.PILOT)
    if not ur.is_initialized():
        raise DiscoveryError("la raíz unificada debe estar inicializada")
    lay = ur.layout
    run = RunContext(data_root=str(root), mode=ExecutionMode.PILOT, operator="cnmv_u1_discovery")
    tel = TelemetryLogger(lay.telemetry, run)
    fetcher = fetcher or DiscoveryFetcher(telemetry=tel)
    if fetcher.telemetry is None:
        fetcher.telemetry = tel
    ledger = CoverageLedger(lay.catalog_db, ExecutionMode.PILOT, telemetry=tel)
    out_dir = lay.reports / "pilot" / "discovery"
    pages = out_dir / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    keys = {(t, y): CoverageKey("ES", "CNMV", t, y, DOC_TYPE) for t in issuers for y in years}
    ledger.expect(list(keys.values()), run_id=run.run_id)
    results: List[Dict[str, Any]] = []
    for ticker, (nif, entity_name) in issuers.items():
        fetcher.begin_issuer(ticker)
        listing, issue, src = None, None, None
        cached = (cached_pages or {}).get(ticker)
        if cached is not None:
            page, src = Path(cached).read_text(encoding="utf-8"), "CACHED_EVIDENCE_PAGE"
            fr = FetchResult(url=LISTING_URL.format(nif=nif), outcome="OK", status=200)
            variants = [nif]
        else:
            variants = nif_variants(nif)
        used_variant = nif
        for vi, variant in enumerate(variants if cached is None else [nif]):
            used_variant = variant
            if cached is None:
                fr = fetcher.fetch(LISTING_URL.format(nif=variant))
                page, src = fr.text, "LIVE_REQUEST"
                if fr.outcome == "OK" and fr.text:
                    (pages / (f"ifa_{ticker}.html" if vi == 0 else f"ifa_{ticker}_alt{vi}.html")).write_text(fr.text, encoding="utf-8")
            listing, issue = None, None
            if fr.outcome != "OK" or not page:
                issue = (fr.reason or fr.outcome)
                break
            try:
                listing = parse_ifa_listing(page)
            except NoDataError:
                issue = "NO_DATA_AVAILABLE"
                continue                                   # única reconsulta: la otra grafía del NIF
            except DiscoveryError as ex:
                issue = f"PARSE:{ex}"
            if listing is not None and _norm(listing.entity or "") != _norm(entity_name):
                issue, listing = f"ENTITY_MISMATCH:{listing.entity}", None
            break
        for y in years:
            key = keys[(ticker, y)]
            rec: Dict[str, Any] = {"ticker": ticker, "nif": nif, "nif_variant_used": used_variant, "fiscal_year": y,
                                   "doc_type": DOC_TYPE, "listing_source": src,
                                   "listing_status": "OK" if listing else "NEEDS_REVIEW", "limitations": []}
            row, head = None, None
            if listing is None:
                rec.update(status="NEEDS_REVIEW", reason=issue)
                blocked = str(issue or "").startswith("BLOCKED:")
                ledger.record(key, LedgerStatus.SOURCE_UNAVAILABLE if blocked else LedgerStatus.NEEDS_REVIEW,
                              reason=str(issue)[:80], evidence={"method": "cnmv_ifa_listing", "ref": f"listing:{ticker}"},
                              run_id=run.run_id)
            else:
                matches = [r for r in listing.rows if r.fiscal_year == y]
                if len(matches) > 1:
                    rec.update(status="NEEDS_REVIEW", reason="MULTIPLE_ROWS", nregs=[r.nreg for r in matches])
                    ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason="MULTIPLE_ROWS",
                                  evidence={"method": "cnmv_ifa_listing", "ref": "nregs:" + ",".join(r.nreg for r in matches)},
                                  run_id=run.run_id)
                elif not matches:
                    rec.update(status="NEEDS_REVIEW", reason="FY_ROW_ABSENT")
                    rec["limitations"].append("la ficha oficial no lista este ejercicio; no se infiere no publicado")
                    ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason="FY_ROW_ABSENT",
                                  evidence={"method": "cnmv_ifa_listing", "ref": f"listing:{ticker}"}, run_id=run.run_id)
                else:
                    row = matches[0]
                    rec.update(nreg=row.nreg, fy_date=row.fy_date, pub_date=row.pub_date, auditor=row.auditor,
                               extra_files=row.extra_audita, tokenized_links=row.tokenized_links,
                               tokenized_ref=row.tokenized_ref, has_zip_link=row.has_zip_link)
                    if row.audita_urls:
                        url = row.audita_urls[0]
                        hr = fetcher.fetch(url, method="HEAD")
                        head = {"outcome": hr.outcome, "reason": hr.reason, "status": hr.status, "content_type": hr.content_type,
                                "content_length": hr.content_length, "last_modified": hr.last_modified}
                        rec.update(status="DISCOVERED_DIRECT_URL", candidate_url=url, format_indicated="PDF (enlace directo AUDITA)",
                                   head=head)
                        if hr.outcome != "DOCUMENT_NOT_DOWNLOADED" or hr.content_type != "application/pdf":
                            rec["limitations"].append(f"la comprobación HEAD no confirmó un PDF ({hr.outcome}/{hr.reason})")
                        if row.tokenized_links:
                            rec["limitations"].append("la ficha además trae enlaces tokenizados que no se usan")
                        ledger.record(key, LedgerStatus.FOUND, reason="OFFICIAL_LISTING_DIRECT_URL",
                                      evidence={"method": "cnmv_ifa_listing", "ref": f"nreg:{row.nreg}"}, run_id=run.run_id)
                    elif row.tokenized_links:
                        rec.update(status="DISCOVERED_TOKENIZED_ONLY", candidate_url=None,
                                   format_indicated="xHTML (Individual/Consolidada) + ZIP/XBRL según la leyenda de la ficha; "
                                                    "enlaces con token opaco, no verificados")
                        rec["limitations"].append("los enlaces de la ficha llevan un token opaco (URL no estable/firmada): "
                                                  "no se usan como candidatas; solo se descubre el número de registro y las fechas")
                        ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason="TOKENIZED_URL_ONLY",
                                      evidence={"method": "cnmv_ifa_listing", "ref": f"nreg:{row.nreg}"}, run_id=run.run_id)
                    else:
                        rec.update(status="NEEDS_REVIEW", reason="ROW_WITHOUT_LINKS")
                        ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason="ROW_WITHOUT_LINKS",
                                      evidence={"method": "cnmv_ifa_listing", "ref": f"nreg:{row.nreg}"}, run_id=run.run_id)
            cur = ledger.get(key)
            rec["ledger_status"] = cur.status.value if cur is not None else None
            rec["local_comparison"] = local_comparison(ticker, y, row, head, inventory, (downloaded or {}).get(f"{ticker}:{y}"))
            rec["evidence"] = ("tabla gridInformes de la ficha IFA oficial; página guardada en reports/pilot/discovery/pages"
                               if listing else f"sin evidencia: {issue}")
            results.append(rec)
    prev_path = out_dir / "cnmv_u1_results.json"
    req_total, req_log, all_issuers = fetcher.total_requests, list(fetcher.log), list(issuers)
    if merge_previous and prev_path.exists():
        prev = _json.loads(prev_path.read_text(encoding="utf-8"))
        keep = [r for r in prev["results"] if r["ticker"] not in issuers]
        results = keep + results
        req_total += prev.get("requests_total", 0)
        req_log = list(prev.get("request_log", [])) + req_log
        all_issuers = list(dict.fromkeys(prev.get("issuers", []) + all_issuers))
    summary = {"generated_at": clock(), "issuers": all_issuers, "years": list(years), "requests_total": req_total,
               "request_log": req_log, "documents_downloaded": 0, "results": results}
    (out_dir / "cnmv_u1_results.json").write_text(_json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True, default=str),
                                                  encoding="utf-8")
    cands = [{"ticker": r["ticker"], "fiscal_year": r["fiscal_year"], "nreg": r["nreg"], "url": r["candidate_url"],
              "head_content_length": (r.get("head") or {}).get("content_length"),
              "head_last_modified": (r.get("head") or {}).get("last_modified"),
              "head_confirmed_pdf": (r.get("head") or {}).get("content_type") == "application/pdf"}
             for r in results if r.get("candidate_url")]
    (out_dir / "cnmv_u1_candidates.json").write_text(_json.dumps(cands, indent=2, sort_keys=True), encoding="utf-8")
    with open(out_dir / "cnmv_u1_coverage_matrix.csv", "w", encoding="utf-8", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["ticker", "fiscal_year", "status", "nreg", "fy_date", "pub_date", "candidate_url", "ledger_status", "local_category"])
        for r in results:
            w.writerow([r["ticker"], r["fiscal_year"], r["status"], r.get("nreg"), r.get("fy_date"), r.get("pub_date"),
                        r.get("candidate_url"), r.get("ledger_status"), r["local_comparison"]["category"]])
    return summary
