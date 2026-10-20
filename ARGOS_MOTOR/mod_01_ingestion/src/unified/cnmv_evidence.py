"""
CNMV-U3 — Saneado de evidencia, clasificación de enlaces (directo estable / tokenizado) y presupuesto de consultas.

Nada de este módulo descarga documentos ni sigue enlaces tokenizados. Los TOKENS (``verdocumento/ver?e=…``) solo viven en memoria durante
el análisis: lo que se persiste es el host y el path SIN query ni fragmento y, como mucho, una huella ``sha256(sal + enlace)[:12]`` con una
sal NO secreta distinta en cada ejecución, útil únicamente para detectar repeticiones dentro de esa misma sesión.

* ``classify_href``      → ``LinkInfo`` (tipo, host, path, huella); nunca devuelve query ni token.
* ``sanitize_html``      → extracto mínimo de la ficha IFA (título, leyenda, tabla ``gridInformes``) sin scripts, formularios, estado de
                           vista, imágenes ni query/fragmento en ningún enlace.
* ``sanitize_text``      → elimina query/fragmento de cualquier URL con ``?e=`` en un texto (JSON de resultados, logs).
* ``contains_token``     → detector de valores prohibidos (para tests y verificaciones previas a persistir).
* ``BudgetedFetcher``    → ``DiscoveryFetcher`` con tope de solicitudes por emisor y total, parada ante 403 y negativa a pedir endpoints
                           tokenizados o de documentos.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlsplit

from mod_01_ingestion.src.unified.cnmv_discovery import DiscoveryError, DiscoveryFetcher, FetchResult, _norm, _plain

BASE = "https://www.cnmv.es/portal/Consultas/ifa/"
DIRECT_RE = re.compile(r"^/AUDITA/(\d{4})/([A-Za-z]*)(\d+)\.pdf$")
TOKEN_PATH = "/webservices/verdocumento/ver"
DOC_SUFFIXES = (".pdf", ".zip", ".xhtml", ".xbrl", ".xsd", ".htm", ".jpg", ".jpeg", ".png", ".gif", ".xlsx", ".docx")
_QUERY_URL = re.compile(r"(https?://[^\s\"'<>\\]*?)\?e=[^\s\"'<>\\]*")
_TOKEN_QUERY = re.compile(r"[?&]e=[A-Za-z0-9%+/=_-]{12,}")


def new_salt() -> str:
    return secrets.token_hex(8)


@dataclass(frozen=True)
class LinkInfo:
    kind: str                       # DIRECT_STABLE | TOKENIZED | DETAIL_PAGE | EXTERNAL | OTHER
    host: Optional[str]
    path: Optional[str]
    fp: Optional[str] = None        # huella con sal por ejecución (solo TOKENIZED)
    registry: Optional[str] = None  # nº de registro que aparece en una ruta AUDITA
    params: Optional[Dict[str, str]] = None   # SOLO identificadores numéricos de registro de páginas de detalle (nunca token)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "host": self.host, "path": self.path, "fp": self.fp, "registry": self.registry,
                "params": self.params}


def classify_href(href: str, salt: str, base: str = BASE) -> LinkInfo:
    abs_url = urljoin(base, _html.unescape(href).strip())
    u = urlsplit(abs_url)
    host, path = (u.hostname or "").lower() or None, u.path
    if host != "www.cnmv.es":
        return LinkInfo("EXTERNAL", host, path)
    if path.lower() == TOKEN_PATH:
        return LinkInfo("TOKENIZED", host, TOKEN_PATH, fp=hashlib.sha256((salt + abs_url).encode("utf-8")).hexdigest()[:12])
    m = DIRECT_RE.match(path)
    if m:
        return LinkInfo("DIRECT_STABLE", host, path, registry=m.group(3))
    low = path.lower()
    if "infadicion" in low or "opinionauditor" in low:
        q = {k: v[0] for k, v in parse_qs(u.query).items() if k in ("nreg", "nregaud", "id") and v and v[0].isdigit()}
        return LinkInfo("DETAIL_PAGE", host, path, params=q or None)
    return LinkInfo("OTHER", host, path)


def _anchor_info(attrs: str, salt: str) -> LinkInfo:
    """Clasifica un ``<a …>``. Si el enlace ya fue saneado, conserva su huella ``data-token-fp`` (no hay token que recalcular)."""
    h = re.search(r'href="([^"]*)"', attrs)
    info = classify_href(h.group(1) if h else "", salt)
    fp = re.search(r'data-token-fp="([0-9a-f]{12})"', attrs)
    if info.kind == "TOKENIZED" and fp:
        info = LinkInfo(info.kind, info.host, info.path, fp=fp.group(1))
    if info.kind == "DETAIL_PAGE" and not info.params:
        d = {k: v for k, v in re.findall(r'data-(nreg|nregaud)="(\d+)"', attrs)}
        info = LinkInfo(info.kind, info.host, info.path, params=d or None)
    return info


def contains_token(text: str) -> bool:
    """True si el texto contiene una query ``e=<token>`` de CNMV (o un enlace tokenizado con query)."""
    return bool(_TOKEN_QUERY.search(text)) or bool(re.search(r"verdocumento/ver\?", text, re.I))


def sanitize_text(text: str) -> str:
    """Quita la query de toda URL con ``?e=`` (resultados JSON antiguos, logs). No toca nada más."""
    return _QUERY_URL.sub(lambda m: m.group(1), text)


def sanitize_html(page: str, salt: str) -> str:
    """Extracto mínimo y seguro de una ficha IFA o de una página de detalle: sin scripts/estilos/formularios/imágenes y sin query en enlaces."""
    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
    cap = re.search(r"<caption[^>]*>(.*?)</caption>", page, re.S)
    tables = re.findall(r"<table[^>]*id=\"[^\"]*grid[A-Za-z]*\"[^>]*>.*?</table>", page, re.S)
    out = ["<!-- evidencia saneada: sin tokens, sin query ni fragmento, sin scripts ni estado de vista -->",
           f"<title>{_plain(title.group(1)) if title else ''}</title>"]
    if "No se han encontrado datos disponibles" in page:
        out.append("<p>No se han encontrado datos disponibles</p>")
    legend = re.search(r"(?s)<p[^>]*>((?:(?!</p>).)*(?:xHTML|n&uacute;mero de registro|número de registro)(?:(?!</p>).)*)</p>", page)
    if legend:
        out.append(f"<p class=\"legend\">{_plain(legend.group(1))}</p>")
    for t in tables:
        def fix(m: "re.Match[str]") -> str:
            info = classify_href(m.group(2), salt)
            if info.kind == "TOKENIZED":
                return f'{m.group(1)}"https://www.cnmv.es{TOKEN_PATH}" data-token-fp="{info.fp}"'
            clean = urljoin(BASE, _html.unescape(m.group(2)).strip()).split("?")[0].split("#")[0]
            extra = "".join(f' data-{k}="{v}"' for k, v in (info.params or {}).items() if k in ("nreg", "nregaud"))
            return f'{m.group(1)}"{clean}"{extra}'
        t = re.sub(r"(<a\s[^>]*?href=)\"([^\"]*)\"", fix, t)
        t = re.sub(r"<img[^>]*>|<input[^>]*>|<script.*?</script>", "", t, flags=re.S)
        out.append(t)
    if not tables and (cap or not legend):
        body = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<form.*?</form>|<input[^>]*>|<img[^>]*>", "", page)
        text = _plain(re.sub(r"<[^>]+>", " ", body))
        main = text[text.find("Ir al contenido principal"):][:6000] if "Ir al contenido principal" in text else text[:6000]
        out.append(f"<pre>{_html.escape(main)}</pre>")
    result = "\n".join(out)
    if contains_token(result):
        raise DiscoveryError("el extracto saneado aún contiene un token: no se persiste")
    return result


# ====================================================================== parseo completo de la ficha IFA
@dataclass
class FullRow:
    nreg: str
    fiscal_year: Optional[int]
    fy_date: Optional[str]
    pub_date: Optional[str]
    auditor: Optional[str]
    registry_cell: List[LinkInfo] = field(default_factory=list)
    tipo: Dict[str, List[LinkInfo]] = field(default_factory=dict)      # etiqueta (Individual/Consolidada/…) -> enlaces
    zip_links: List[LinkInfo] = field(default_factory=list)
    special: List[LinkInfo] = field(default_factory=list)
    extension: List[LinkInfo] = field(default_factory=list)
    opinion: Optional[str] = None
    emphasis: Optional[str] = None
    remarks: Optional[str] = None

    def all_links(self) -> List[LinkInfo]:
        out = list(self.registry_cell) + list(self.zip_links) + list(self.special) + list(self.extension)
        for v in self.tipo.values():
            out += v
        return out

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["registry_cell"] = [x.to_dict() for x in self.registry_cell]
        d["tipo"] = {k: [x.to_dict() for x in v] for k, v in self.tipo.items()}
        for k in ("zip_links", "special", "extension"):
            d[k] = [x.to_dict() for x in getattr(self, k)]
        return d


def parse_full(page: str, salt: str) -> List[FullRow]:
    m = re.search(r"<table[^>]*gridInformes[^>]*>(.*?)</table>", page, re.S)
    if not m:
        raise DiscoveryError("sin tabla de informes")
    body = m.group(1)
    names = [_norm(_plain(h)) for h in re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)]

    def col(*needles) -> Optional[int]:
        for i, n in enumerate(names):
            if all(x in n for x in needles):
                return i
        return None
    ix = {"reg": col("registro"), "fy": col("estados financieros"), "pub": col("publicaci"), "aud": col("auditor", "nombre"),
          "tipo": col("tipo"), "zip": col("zip"), "esp": col("informe especial"), "amp": col("ampliaci"), "op": col("opini"),
          "enf": col("nfasis"), "obs": col("observaciones")}
    rows: List[FullRow] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if not tds or ix["reg"] is None or len(tds) <= ix["reg"]:
            continue
        nreg = _plain(tds[ix["reg"]])
        if not re.fullmatch(r"\d+", nreg):
            continue

        def cell(key) -> str:
            i = ix[key]
            return tds[i] if i is not None and i < len(tds) else ""

        def links(key) -> List[LinkInfo]:
            return [_anchor_info(a, salt) for a in re.findall(r'<a\s([^>]*)>', cell(key))]
        fy_date = _plain(cell("fy")) or None
        mm = re.fullmatch(r"\d{2}/\d{2}/(\d{4})", fy_date or "")
        row = FullRow(nreg=nreg, fiscal_year=int(mm.group(1)) if mm else None, fy_date=fy_date, pub_date=_plain(cell("pub")) or None,
                      auditor=_plain(cell("aud")) or None, registry_cell=links("reg"), zip_links=links("zip"), special=links("esp"),
                      extension=links("amp"), opinion=_plain(cell("op")) or None, emphasis=_plain(cell("enf")) or None,
                      remarks=_plain(cell("obs")) or None)
        for a in re.finditer(r'<a\s([^>]*)>(.*?)</a>', cell("tipo"), re.S):
            row.tipo.setdefault(_plain(a.group(2)) or "?", []).append(_anchor_info(a.group(1), salt))
        rows.append(row)
    return rows


def link_kind_summary(row: FullRow) -> str:
    kinds = {i.kind for i in row.all_links()}
    if "TOKENIZED" in kinds:
        return "DISCOVERED_TOKENIZED"
    if "DIRECT_STABLE" in kinds:
        return "DISCOVERED_DIRECT_STABLE"
    return "DISCOVERED_NO_DOCUMENT_LINK"


# ====================================================================== presupuesto de consultas
class BudgetedFetcher(DiscoveryFetcher):
    """Tope de solicitudes por emisor y total; se detiene ante un 403; nunca pide endpoints tokenizados ni de documentos."""

    def __init__(self, *a, max_per_issuer: int = 12, max_total: int = 60, **kw):
        super().__init__(*a, **kw)
        self.max_per_issuer, self.max_total = max_per_issuer, max_total
        self.halted: Optional[str] = None
        self._issuer_base = 0
        self.status_counts: Dict[str, int] = {}
        self.per_issuer: Dict[str, int] = {}
        self.retries = 0
        self.waits: List[float] = []
        self.durations: List[float] = []
        self.body_documents_read = 0

    def begin_issuer(self, issuer: str) -> None:
        super().begin_issuer(issuer)
        self._issuer_base = self.total_requests

    def fetch(self, url: str, method: str = "GET") -> FetchResult:
        u = urlsplit(url)
        if "verdocumento" in u.path.lower():
            return FetchResult(url=u.path, outcome="NEEDS_REVIEW", reason="TOKENIZED_ENDPOINT_FORBIDDEN")
        if u.path.lower().endswith(DOC_SUFFIXES) or u.path.upper().startswith("/AUDITA/"):
            return FetchResult(url=u.path, outcome="NEEDS_REVIEW", reason="DOCUMENT_ENDPOINT_FORBIDDEN")
        if self.halted:
            return FetchResult(url=url, outcome="NEEDS_REVIEW", reason=f"HALTED:{self.halted}")
        return super().fetch(url, method)

    def _one(self, url: str, method: str = "GET") -> FetchResult:
        if self.halted:
            return FetchResult(url=url, outcome="NEEDS_REVIEW", reason=f"HALTED:{self.halted}")
        if self.total_requests >= self.max_total or self.total_requests - self._issuer_base >= self.max_per_issuer:
            return FetchResult(url=url, outcome="NEEDS_REVIEW", reason="REQUEST_BUDGET_EXHAUSTED")
        t0 = self._mono()
        prev_last = self._last_start
        res = super()._one(url, method)
        self.durations.append(round(self._mono() - t0, 3))
        if prev_last is not None:
            self.waits.append(round(max(self._last_start - prev_last, 0.0), 3))
        key = str(res.status) if res.status is not None else (res.reason or "ERR")
        self.status_counts[key] = self.status_counts.get(key, 0) + 1
        self.per_issuer[self._issuer or "?"] = self.per_issuer.get(self._issuer or "?", 0) + 1
        if res.outcome == "DOCUMENT_NOT_DOWNLOADED":
            self.body_documents_read += 0           # el cuerpo nunca se lee; contador explícito para el informe
        if res.status == 403:
            self.halted = "HTTP_403"
        if self.telemetry is not None:
            p = urlsplit(url)
            self.telemetry.emit("cnmv_u3_request", None, "cnmv_evidence", host=p.hostname, path=p.path, method=method,
                                status=res.status, duration_s=self.durations[-1], outcome=res.outcome, reason=res.reason)
        return res
