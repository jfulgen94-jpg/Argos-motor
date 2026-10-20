"""
CNMV-C1 — Canario de UN recurso: Telefónica (A28015865), ejercicio 2020, registro 18760, enlace «Fichero ZIP/XBRL» de la ficha oficial.

PREPARADO, NO EJECUTADO. Reutiliza el pipeline unificado (``UnifiedIngestRunner`` + ``PilotDownloadService``); solo añade:

* ``CanaryLimits`` y ``BudgetedTransport``: UN punto de paso para TODAS las peticiones (ficha y recurso) que impone el presupuesto
  acumulado (solicitudes, bytes recibidos incluidos intentos fallidos, plazo total, pausa mínima, dominio único, un único reintento
  para 429/503, parada en 403, nada de ``Range``/``If-Range``). Los límites no se amplían solos.
* ``select_zip_resource``: elige el enlace ZIP/XBRL EXACTO de la fila 18760/2020 de la ficha ya descargada (nunca adivina ni reconstruye
  tokens); la URL tokenizada solo vive en memoria como ``TransportUrl``.
* ``inspect_zip_resource``: validación acotada del ZIP descargado (firma, CRC, Zip Slip/bomba, miembros listados sin extraer).
* ``run_canary``: orquesta lo anterior. Exige la frase de autorización del propietario; sin ella no hace NADA.

SHA-256 y tamaño son calculados localmente (no oficiales). No se compara con ninguna copia histórica y no se atribuye aprobación
cuatro-ojos: la autorización es solo del propietario. Las identidades siguen en SLOT_ONLY; no hay REPUBLICATION_CONFIRMED.
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from mod_01_ingestion.src.unified.adapters.cnmv import CNMVAdapter
from mod_01_ingestion.src.unified.cnmv_discovery import (
    ISSUERS, LISTING_URL, DiscoveryFetcher, NoDataError, _norm, _plain, nif_variants, parse_ifa_listing)
from mod_01_ingestion.src.unified.cnmv_evidence import BASE, TOKEN_PATH, classify_href, new_salt, sanitize_html
from mod_01_ingestion.src.unified.configured_adapter import ConfiguredAdapter
from mod_01_ingestion.src.unified.coverage_ledger import CoverageKey, CoverageLedger, LedgerStatus, record_outcome
from mod_01_ingestion.src.unified.data_root import DEFAULT_PILOT_ROOT, UnifiedDataRoot, validate_unified_root
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.domain.transport import TransportUrl, assert_no_secret
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import DiscoveryRequest, RunContext
from mod_01_ingestion.src.unified.pilot import PilotBudget, PilotLimitExceeded, PilotLimits, PilotPlan
from mod_01_ingestion.src.unified.pilot_runner import PilotDownloadService
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.source_config import parse_source_configs
from mod_01_ingestion.src.unified.validation_pipeline import inspect_zip_safety

AUTH_PHRASE = "AUTORIZO CANARIO CNMV TEF 2020 ZIP"          # PROPUESTA: solo vale si el propietario la escribe en el chat
CANARY_REF = "CNMV-CANARY-TEF-2020-001"
ALLOWED_HOST = "www.cnmv.es"
USER_AGENT = "Stater-ARGOS-MOTOR/1.0 j.fulgen94@gmail.com"
TICKER, NIF, FISCAL_YEAR, NREG = "TEF", "A28015865", 2020, "18760"
DOC_TYPE = "CNMV_IFA_ZIP_XBRL"
RETRY_ONCE = frozenset({429, 503})
MiB = 1024 * 1024


class CanaryError(DomainValidationError):
    pass


class ResourceSelectionError(CanaryError):
    """La ficha no permite elegir de forma inequívoca el recurso ZIP/XBRL (se deja en NEEDS_REVIEW)."""


class CanaryBudgetExceeded(httpx.TransportError):
    """Se agotó un límite del canario o se intentó una petición no permitida. Nunca se reintenta."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CanaryLimits:
    allowed_host: str = ALLOWED_HOST
    max_requests: int = 5
    max_documents: int = 1
    max_total_bytes: int = 256 * MiB
    request_timeout_s: float = 60.0
    max_total_s: float = 600.0
    min_interval_s: float = 5.0
    max_retries: int = 1
    retry_statuses: tuple = (429, 503)

    def __post_init__(self):
        if self.allowed_host != ALLOWED_HOST:
            raise CanaryError("dominio único www.cnmv.es")
        if not (1 <= self.max_requests <= 5 and self.max_documents == 1 and 0 < self.max_total_bytes <= 256 * MiB
                and 0 < self.request_timeout_s <= 60 and 0 < self.max_total_s <= 600 and self.min_interval_s >= 5
                and 0 <= self.max_retries <= 1 and set(self.retry_statuses) <= RETRY_ONCE):
            raise CanaryError("los límites del canario no pueden ampliarse")

    def to_dict(self) -> Dict[str, Any]:
        return {"allowed_domains": [self.allowed_host], "max_requests": self.max_requests, "max_documents": self.max_documents,
                "max_total_bytes": self.max_total_bytes, "request_timeout_s": self.request_timeout_s,
                "max_total_s": self.max_total_s, "min_interval_s": self.min_interval_s, "max_concurrent": 1,
                "max_retries": self.max_retries, "retry_statuses": list(self.retry_statuses), "http_403": "STOP_NEEDS_REVIEW",
                "range_if_range_resume": "NEVER", "redirects_outside_domain": "NEVER"}


class _CountingStream(httpx.SyncByteStream):
    def __init__(self, inner, transport: "BudgetedTransport"):
        self._inner, self._t = inner, transport

    def __iter__(self):
        for chunk in self._inner:
            self._t._add_bytes(len(chunk))
            yield chunk

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close:
            close()


class BudgetedTransport(httpx.BaseTransport):
    """Punto único de paso: cuenta solicitudes (redirecciones y reintentos incluidos), bytes recibidos y plazo, y marca el ritmo."""

    def __init__(self, inner: httpx.BaseTransport, limits: CanaryLimits, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._inner, self.limits, self._clock, self._sleep = inner, limits, clock, sleep
        self.requests = 0
        self.bytes_received = 0
        self.retries = 0
        self.statuses: List[int] = []
        self.halted: Optional[str] = None
        self.exceeded: Optional[str] = None
        self._t0: Optional[float] = None
        self._last_start: Optional[float] = None
        self._pending_retry = False

    def _stop(self, code: str):
        self.exceeded = self.exceeded or code
        raise CanaryBudgetExceeded(code)

    def _add_bytes(self, n: int) -> None:
        self.bytes_received += n
        if self.bytes_received > self.limits.max_total_bytes:
            self._stop("CANARY_TOTAL_BYTES_EXCEEDED")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        u = request.url
        if u.scheme != "https" or (u.host or "").lower() != self.limits.allowed_host or u.port not in (None, 443) \
                or u.userinfo:
            self._stop("CANARY_DOMAIN_NOT_ALLOWED")
        if "range" in request.headers or "if-range" in request.headers:
            self._stop("CANARY_RESUME_FORBIDDEN")
        if self.halted:
            self._stop(f"CANARY_HALTED_{self.halted}")
        now = self._clock()
        if self._t0 is None:
            self._t0 = now
        if now - self._t0 > self.limits.max_total_s:
            self._stop("CANARY_TIME_EXCEEDED")
        if self.requests >= self.limits.max_requests:
            self._stop("CANARY_REQUEST_BUDGET_EXHAUSTED")
        if self._pending_retry:
            self._pending_retry = False
            if self.retries >= self.limits.max_retries:
                self._stop("CANARY_RETRY_BUDGET_EXHAUSTED")
            self.retries += 1
        if self._last_start is not None:
            wait = self.limits.min_interval_s - (self._clock() - self._last_start)
            if wait > 0:
                self._sleep(wait)
        self._last_start = self._clock()
        self.requests += 1
        resp = self._inner.handle_request(request)
        self.statuses.append(resp.status_code)
        if resp.status_code == 403:
            self.halted = "HTTP_403"
        elif resp.status_code in RETRY_ONCE:
            self._pending_retry = True
        return httpx.Response(resp.status_code, headers=resp.headers, stream=_CountingStream(resp.stream, self),
                              extensions=resp.extensions)

    def close(self) -> None:
        self._inner.close()

    def summary(self) -> Dict[str, Any]:
        return {"requests": self.requests, "bytes_received": self.bytes_received, "retries": self.retries,
                "statuses": list(self.statuses), "halted": self.halted, "budget_exceeded": self.exceeded}


# ====================================================================== selección exacta del recurso en la ficha
@dataclass
class ZipSelection:
    transport: TransportUrl = field(repr=False)
    registration_number: str = NREG
    fiscal_year: int = FISCAL_YEAR
    declared_resource_kind: str = ""
    entity: Optional[str] = None


def select_zip_resource(page: str, *, nreg: str = NREG, fiscal_year: int = FISCAL_YEAR, ticker: str = TICKER) -> ZipSelection:
    """Enlace de la columna ZIP de la fila ``nreg``/``fiscal_year`` de la tabla ``gridInformes``. Exactamente uno, o error."""
    listing = parse_ifa_listing(page)
    if _norm(listing.entity or "") != _norm(ISSUERS[ticker][1]):
        raise ResourceSelectionError(f"ENTITY_MISMATCH:{listing.entity}")
    m = re.search(r"<table[^>]*gridInformes[^>]*>(.*?)</table>", page, re.S)
    body = m.group(1) if m else ""
    heads = [_plain(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)]
    names = [_norm(h) for h in heads]

    def col(*needles) -> Optional[int]:
        return next((i for i, n in enumerate(names) if all(x in n for x in needles)), None)
    i_reg, i_fy, i_zip = col("registro"), col("estados financieros"), col("zip")
    if None in (i_reg, i_fy, i_zip):
        raise ResourceSelectionError("TABLE_COLUMNS_NOT_RECOGNISED")
    hits = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) <= max(i_reg, i_fy, i_zip) or _plain(tds[i_reg]) != nreg:
            continue
        hits.append(tds)
    if len(hits) != 1:
        raise ResourceSelectionError(f"ROW_NOT_UNIQUE:{len(hits)}")
    tds = hits[0]
    fy = re.fullmatch(r"\d{2}/\d{2}/(\d{4})", _plain(tds[i_fy]))
    if not fy or int(fy.group(1)) != fiscal_year:
        raise ResourceSelectionError("FISCAL_YEAR_MISMATCH")
    hrefs = re.findall(r'<a\s[^>]*?href="([^"]*)"', tds[i_zip])
    if len(hrefs) != 1:
        raise ResourceSelectionError(f"ZIP_LINK_NOT_UNIQUE:{len(hrefs)}")
    full = urljoin(BASE, _html.unescape(hrefs[0]).strip())
    info = classify_href(full, "x")
    if info.kind != "TOKENIZED" or info.host != ALLOWED_HOST or info.path != TOKEN_PATH or urlsplit(full).scheme != "https":
        raise ResourceSelectionError("ZIP_LINK_NOT_AN_OFFICIAL_RESOURCE")
    return ZipSelection(transport=TransportUrl(full), registration_number=nreg, fiscal_year=fiscal_year,
                        declared_resource_kind=f"{heads[i_zip]} (declarado por la ficha, sin verificar)", entity=listing.entity)


# ====================================================================== validación acotada del ZIP (sin extraer)
_RULES = {"max_members": 5000, "max_uncompressed_bytes": 1024 * MiB, "max_compression_ratio": 1000}
_XBRL_SUFFIXES = (".xbrl", ".xhtml", ".html", ".htm", ".xml", ".xsd")


def inspect_zip_resource(path: Path, *, list_limit: int = 50) -> Dict[str, Any]:
    """``status``: OK_CLASSIFIED | NEEDS_REVIEW | UNSAFE_ARCHIVE | CORRUPT_ARCHIVE | NOT_A_ZIP. Nunca extrae nada a disco."""
    path = Path(path)
    with open(path, "rb") as f:
        if f.read(4) != b"PK\x03\x04":
            return {"status": "NOT_A_ZIP", "reasons": ["SIGNATURE_MISMATCH"]}
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            unsafe = inspect_zip_safety(path, _RULES)
            if unsafe:
                return {"status": "UNSAFE_ARCHIVE", "reasons": [r.split(":")[0] for r in unsafe[:20]], "members": len(infos)}
            bad = zf.testzip()                                                  # CRC de todos los miembros, en memoria y por bloques
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, EOFError) as ex:
        return {"status": "CORRUPT_ARCHIVE", "reasons": [type(ex).__name__]}
    if bad is not None:
        return {"status": "CORRUPT_ARCHIVE", "reasons": ["CRC_MISMATCH"], "members": len(infos)}
    names = [i.filename for i in infos if not i.is_dir()]
    kinds: Dict[str, int] = {}
    for n in names:
        ext = ("." + n.rsplit(".", 1)[-1].lower()) if "." in n.rsplit("/", 1)[-1] else "(none)"
        kinds[ext] = kinds.get(ext, 0) + 1
    xbrl_like = sum(v for k, v in kinds.items() if k in _XBRL_SUFFIXES)
    pdf_only = bool(names) and set(kinds) == {".pdf"}
    if xbrl_like and not pdf_only:
        klass, status = "ZIP_WITH_XBRL_XHTML_MEMBERS", "OK_CLASSIFIED"
    elif pdf_only:
        klass, status = "ZIP_WITH_PDF_ONLY", "OK_CLASSIFIED"
    else:
        klass, status = "AMBIGUOUS_CONTENT", "NEEDS_REVIEW"
    return {"status": status, "classification": klass, "members": len(infos), "member_kinds": dict(sorted(kinds.items())),
            "first_members": sorted(names)[:list_limit], "uncompressed_bytes": sum(i.file_size for i in infos),
            "sha256_is_official": False}


# ====================================================================== plan (artefacto pendiente) y ejecución
def canary_plan(limits: Optional[CanaryLimits] = None) -> Dict[str, Any]:
    return {"artifact": "CNMV_CANARY_PLAN", "status": "PENDING_OWNER_AUTHORIZATION", "reference": CANARY_REF,
            "scope": {"authority": "CNMV", "issuer": TICKER, "nif": NIF, "fiscal_year": FISCAL_YEAR, "registration_number": NREG,
                      "resource": "enlace de la columna ZIP/XBRL de esa fila de la ficha oficial", "document_type": DOC_TYPE,
                      "identity": "SLOT_ONLY", "republication_confirmed": False},
            "limits": (limits or CanaryLimits()).to_dict(), "user_agent": USER_AGENT,
            "authorization": {"required_phrase": AUTH_PHRASE, "granted_by": None, "four_eyes": False,
                              "note": "no reutiliza la autorización 2019; no se atribuye aprobación a terceros"},
            "sequence": ["GET ficha IFA del NIF (1 solicitud, 2.ª solo si la grafía del NIF no devuelve datos)",
                         "selección exacta de la fila 18760/2020 y de su único enlace ZIP/XBRL",
                         "GET del recurso con URL de transporte solo en memoria (sin Range/If-Range)",
                         "validación acotada del ZIP sin extraer", "registro en CAS/manifiesto/catálogo/ledger sin tokens"],
            "destination_root": "D:/ARGOS_DATA/unified_pilot", "local_hash_is_official": False,
            "compare_with_historical_copy": False}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_canary(phrase: str, *, root_path: Path = DEFAULT_PILOT_ROOT, inner_transport: Optional[httpx.BaseTransport] = None,
               limits: Optional[CanaryLimits] = None, sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.monotonic, retry_wait_s: float = 15.0, now: Callable[[], str] = _now,
               ) -> Dict[str, Any]:
    if phrase != AUTH_PHRASE:
        raise CanaryError("autorización no válida: la frase debe ser exactamente la acordada")
    limits = limits or CanaryLimits()
    root = UnifiedDataRoot(Path(root_path), ExecutionMode.PILOT)
    validate_unified_root(root.path, ExecutionMode.PILOT)
    if not root.is_initialized():
        raise CanaryError("la raíz del piloto no está inicializada")
    lay = root.layout
    report: Dict[str, Any] = {"reference": CANARY_REF, "authorization_status": "OWNER_AUTHORIZED_NOT_INDEPENDENTLY_VERIFIED",
                              "approved_by_second_person": None, "steps": [], "downloaded": False, "state": None}
    step = lambda name, **kw: report["steps"].append({"step": name, "at": now(), **kw})      # noqa: E731
    run = RunContext(data_root=str(root.path), mode=ExecutionMode.PILOT, operator=f"canary:{CANARY_REF}")
    key = CoverageKey("ES", "CNMV", TICKER, FISCAL_YEAR, DOC_TYPE)
    from mod_01_ingestion.src.unified.telemetry import TelemetryLogger
    ledger = CoverageLedger(lay.catalog_db, ExecutionMode.PILOT, telemetry=TelemetryLogger(lay.telemetry, run))
    ledger.expect([key], run_id=run.run_id)
    known = ledger.get(key)
    if known is not None and known.status is LedgerStatus.PROMOTED:
        report.update(state="SKIPPED_ALREADY_PROMOTED", sha256=known.sha256)
        return _write(root, report)

    bt = BudgetedTransport(inner_transport or httpx.HTTPTransport(), limits, clock=clock, sleep=sleep)

    def finish(state: str, reason: str, status: LedgerStatus = LedgerStatus.NEEDS_REVIEW) -> Dict[str, Any]:
        report.update(state=state, reason=reason, transport=bt.summary())
        ledger.record(key, status, reason=reason[:80], evidence={"method": "cnmv_canary", "ref": f"canary:{CANARY_REF}"},
                      run_id=run.run_id)
        step("finished", state=state, reason=reason)
        return _write(root, report)

    listing_client = httpx.Client(transport=bt, follow_redirects=False, timeout=limits.request_timeout_s)
    http = httpx.Client(transport=bt, follow_redirects=True, timeout=limits.request_timeout_s)
    try:
        fetcher = DiscoveryFetcher(listing_client, min_interval_s=limits.min_interval_s, timeout_s=limits.request_timeout_s,
                                   per_issuer_s=limits.max_total_s, retry_wait_s=retry_wait_s, sleep=sleep, monotonic=clock)
        fetcher.begin_issuer(TICKER)
        selection, page = None, None
        for variant in nif_variants(NIF):
            fr = fetcher.fetch(LISTING_URL.format(nif=variant))
            step("listing", outcome=fr.outcome, reason=fr.reason, status=fr.status)
            if fr.outcome != "OK" or not fr.text:
                return finish("NEEDS_REVIEW", fr.reason or fr.outcome)
            try:
                selection = select_zip_resource(fr.text)
                page = fr.text
                break
            except NoDataError:
                continue
            except Exception as ex:                                       # selección ambigua o ficha no reconocida
                return finish("NEEDS_REVIEW", f"SELECTION:{sanitize_message(str(ex))}")
        if selection is None:
            return finish("NEEDS_REVIEW", "NO_DATA_AVAILABLE")
        ev = lay.reports / "pilot" / "canary"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / f"ficha_{CANARY_REF}.html").write_text(sanitize_html(page, new_salt()), encoding="utf-8")
        step("resource_selected", registration_number=selection.registration_number, declared=selection.declared_resource_kind)

        rec = {"ticker": TICKER, "name": ISSUERS[TICKER][1], "fiscal_year": FISCAL_YEAR, "doc_type": DOC_TYPE,
               "url": selection.transport.stable_url, "transport_url": selection.transport,      # la URL completa nunca se revela aquí
               "registration_number": selection.registration_number, "declared_resource_kind": selection.declared_resource_kind}
        cfg = parse_source_configs({"schema_version": "1", "config_version": "cnmv-canary-1", "sources": [{
            "source_id": "cnmv_canary", "authority": "CNMV", "country_code": "ES", "allowed_domains": [ALLOWED_HOST],
            "user_agent": USER_AGENT, "contact": "j.fulgen94@gmail.com",
            "rate": {"min_interval_s": limits.min_interval_s, "max_concurrent": 1}, "timeout_s": limits.request_timeout_s,
            "max_bytes": limits.max_total_bytes, "max_total_s": limits.max_total_s,
            "retries": {"max_retries": limits.max_retries, "retry_statuses": list(limits.retry_statuses)}}]}).get("CNMV")
        adapter = ConfiguredAdapter(CNMVAdapter(lambda req: [rec]), cfg)
        rate = DomainRateLimiter(max_concurrent_per_domain=1, min_interval_s=cfg.min_interval_s, overrides=cfg.rate_overrides(),
                                 sleep=sleep)
        service = PilotDownloadService(rate_limiter=rate, client=http, sleep=sleep, timeout_s=cfg.timeout_s,
                                       max_total_s=cfg.max_total_s, max_retry_after_s=30.0, retry_wait_s=retry_wait_s,
                                       overall_s=float(limits.max_total_s))
        runner = UnifiedIngestRunner(lay, {"CNMV": adapter}, download=service, run=run)
        budget = PilotBudget(PilotPlan(authority="CNMV", config_version="cnmv-canary-1",
                                       limits=PilotLimits(allowed_domains=(ALLOWED_HOST,), max_documents=1,
                                                          max_bytes_per_document=limits.max_total_bytes,
                                                          max_total_bytes=limits.max_total_bytes, max_total_s=limits.max_total_s),
                                       root=str(root.path), plan_version=CANARY_REF))
        budget.start()
        cand = adapter.discover(DiscoveryRequest(authority="CNMV", fiscal_years=[FISCAL_YEAR], issuer_ids=[TICKER],
                                                 doc_types=[DOC_TYPE], limit=1))[0]
        try:
            budget.begin_document("CNMV", cand.source_url)
            outcome = runner.process_candidate(adapter, cand)
            res = record_outcome(ledger, cand, outcome, run_id=run.run_id)
        except PilotLimitExceeded as ex:
            return finish("NEEDS_REVIEW", ex.code)
        report["outcome"] = {"state": outcome.state, "error_class": outcome.error_class,
                             "message": sanitize_message(outcome.message or "") or None, "sha256": outcome.sha256,
                             "sha256_is_official": False, "document_id": cand.document_id, "ledger_status": res.status.value,
                             "failure_stage": outcome.failure_stage, "attempt_id": outcome.attempt_id,
                             "registration_number": cand.registration_number, "declared_resource_kind": cand.declared_resource_kind}
        ok = outcome.state in ("COMPLETED", "SKIPPED_ALREADY_PRESENT") and bool(outcome.sha256 and outcome.raw_path)
        report["downloaded"] = ok
        report["state"] = outcome.state
        if ok:
            size = Path(outcome.raw_path).stat().st_size
            report["outcome"]["size_bytes"] = size
            insp = inspect_zip_resource(Path(outcome.raw_path))
            report["zip"] = insp
            if insp["status"] != "OK_CLASSIFIED":
                ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason=f"ZIP_{insp['status']}"[:80],
                              evidence={"method": "cnmv_canary_zip", "ref": f"canary:{CANARY_REF}"}, run_id=run.run_id)
                report["outcome"]["ledger_status"] = LedgerStatus.NEEDS_REVIEW.value
        elif bt.halted:
            ledger.record(key, LedgerStatus.NEEDS_REVIEW, reason=f"{bt.halted}"[:80],
                          evidence={"method": "cnmv_canary", "ref": f"canary:{CANARY_REF}"}, run_id=run.run_id)
            report["outcome"]["ledger_status"] = LedgerStatus.NEEDS_REVIEW.value
        report["transport"] = bt.summary()
        step("finished", state=outcome.state)
        return _write(root, report)
    finally:
        listing_client.close()
        http.close()


def _write(root: UnifiedDataRoot, report: Dict[str, Any]) -> Dict[str, Any]:
    assert_no_secret(report, "informe")
    d = root.layout.reports / "pilot"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"canary_{report['reference']}.json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str, ensure_ascii=False),
                                                         encoding="utf-8")
    return report
