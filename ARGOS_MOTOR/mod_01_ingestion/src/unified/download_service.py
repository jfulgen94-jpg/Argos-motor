"""
FASE 4 — DownloadService: ÚNICA implementación de descarga HTTP para todas las autoridades.

Responsabilidades (no varían por país): streaming, redirects, timeouts, retries con backoff
exponencial + jitter, Retry-After, clasificación de respuestas, ``.part`` + reanudación
Range, SHA-256 en streaming, ``flush`` + ``fsync`` y rename atómico dentro de staging.

Remedia DEFECT-02 (preserva el status HTTP real), DEFECT-03 (fsync), DEFECT-05 (jamás
escribe el nombre final sin pasar por ``.part``) y DEFECT-09 (rate limiter por dominio).
El servicio NO promueve a raw: devuelve un archivo en staging que valida/promueve el pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Optional

import httpx

from mod_01_ingestion.src.unified.models import (
    DownloadRequest, DownloadResult, ErrorClass, JobContext)
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.telemetry import TelemetryLogger

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DEFAULT_HEADERS = {"User-Agent": "STATER Regulatory Engine/2.0 (dev@stater.es)"}


class DownloadFailure(Exception):
    def __init__(self, message: str, error_class: ErrorClass, status_code: Optional[int] = None):
        super().__init__(message)
        self.error_class = error_class
        self.status_code = status_code


def classify_status(status: int, extra_retryable: FrozenSet[int] = frozenset()) -> Optional[ErrorClass]:
    """Clasificación común de respuestas HTTP (None = éxito). ``extra_retryable``: estados adicionales que la política del
    servicio trata como transitorios (p. ej. un 403 de WAF que en realidad es limitación de tasa)."""
    if status in RETRYABLE_STATUS or status in extra_retryable:
        return ErrorClass.HTTP_TRANSIENT
    if status >= 400 and status != 416:
        return ErrorClass.HTTP_PERMANENT
    return None


class DownloadService:
    def __init__(
        self,
        telemetry: Optional[TelemetryLogger] = None,
        rate_limiter: Optional[DomainRateLimiter] = None,
        max_retries: int = 4,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        max_retry_after_s: float = 300.0,
        chunk_size: int = 64 * 1024,
        timeout_s: float = 60.0,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Optional[random.Random] = None,
        extra_retryable_statuses: FrozenSet[int] = frozenset(),
        default_max_bytes: int = 2 * 1024 ** 3,
        max_total_s: float = 3600.0,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.telemetry = telemetry
        self.rate_limiter = rate_limiter or DomainRateLimiter()
        self.max_retries = max_retries
        self.initial_backoff_s = initial_backoff_s
        self.max_backoff_s = max_backoff_s
        self.max_retry_after_s = max_retry_after_s
        self.chunk_size = chunk_size
        self.timeout_s = timeout_s
        self._client = client
        self._sleep = sleep
        self._rng = rng or random.Random()
        # U2: 403 NO se reintenta por defecto (permanente: una sola petición, status preservado). Quien sepa que su fuente
        # responde 403 por limitación de tasa lo declara en ``extra_retryable_statuses={403}`` y obtiene backoff.
        self.extra_retryable_statuses = frozenset(extra_retryable_statuses)
        self.default_max_bytes = default_max_bytes     # tope si la petición no trae ``max_bytes``
        self.max_total_s = max_total_s                 # plazo TOTAL de una descarga (cubre goteo lento sin timeout de lectura)
        self._clock = clock
        self._monotonic = monotonic

    # -- utilidades -----------------------------------------------------------------
    def backoff(self, attempt: int) -> float:
        base = min(self.max_backoff_s, self.initial_backoff_s * (2 ** attempt))
        return base + self._rng.uniform(0.1, 0.5) * base

    def _emit(self, event: str, job: Optional[JobContext], **fields):
        if self.telemetry:
            self.telemetry.emit(event, job, "download_service", **fields)

    @staticmethod
    def _hash_file(path: Path, chunk: int) -> "hashlib._Hash":
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while block := f.read(chunk):
                h.update(block)
        return h

    # -- API pública ----------------------------------------------------------------
    def download(self, req: DownloadRequest, job: Optional[JobContext] = None) -> DownloadResult:
        started = self._monotonic()
        if not _is_plain_filename(req.file_name):      # nunca fuera del staging ni con rutas/ADS: ni siquiera se crea nada
            self._emit("download_failed", job, status=None, error_class=ErrorClass.PATH_VIOLATION.value,
                       message="nombre de archivo no permitido", retries=0)
            return DownloadResult(ok=False, final_url=req.url, error_class=ErrorClass.PATH_VIOLATION.value,
                                  error_message="nombre de archivo no permitido (solo un nombre simple dentro del staging)")
        staging = Path(req.staging_dir)
        staging.mkdir(parents=True, exist_ok=True)
        final_path = staging / req.file_name
        part_path = final_path.with_name(final_path.name + ".part")
        meta_path = final_path.with_name(final_path.name + ".part.meta")
        url_sha = hashlib.sha256(req.url.encode("utf-8")).hexdigest()[:32]    # sin guardar la URL (puede llevar tokens)
        limit = req.max_bytes or self.default_max_bytes
        total_s = req.max_total_s or self.max_total_s
        deadline = started + total_s
        timeout_s = req.timeout_s or self.timeout_s
        max_retries = self.max_retries if req.max_retries is None else req.max_retries
        extra_retry = self.extra_retryable_statuses | frozenset(req.retry_statuses or ())

        client = self._client or httpx.Client(headers=DEFAULT_HEADERS, timeout=self.timeout_s, follow_redirects=True)
        owns_client = self._client is None
        attempt = 0
        resumed = False
        status: Optional[int] = None
        mime = None
        final_url = req.url
        last_error: Optional[DownloadFailure] = None
        try:
            while True:
                try:
                    headers = {**DEFAULT_HEADERS, **req.headers}
                    existing = part_path.stat().st_size if (req.allow_resume and part_path.exists()) else 0
                    meta = _read_part_meta(meta_path)
                    if existing > 0 and meta is not None and meta.get("url_sha") != url_sha:
                        existing = 0                   # el .part es de otra URL: no se reanuda sobre otro contenido
                    if existing > 0:
                        headers["Range"] = f"bytes={existing}-"
                        validator = _if_range_validator(meta)
                        if validator:
                            headers["If-Range"] = validator    # si el recurso cambió, el servidor responde 200 y se reinicia
                    elif part_path.exists():
                        part_path.unlink()
                        meta_path.unlink(missing_ok=True)
                    self._emit("download_attempt", job, url=req.url, attempt=attempt, resume_from=existing)
                    with self.rate_limiter.slot(req.url):
                        with client.stream("GET", req.url, headers=headers, timeout=timeout_s) as resp:
                            status = resp.status_code
                            final_url = str(resp.url)
                            mime = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
                            self._emit("http_response", job, url=str(resp.url), status=status, mime=mime,
                                       content_length=resp.headers.get("content-length"),
                                       redirect_chain=[str(h.url) for h in resp.history])
                            if req.allowed_domains is not None:
                                hosts = {(h.url.host or "").lower() for h in resp.history} | {(resp.url.host or "").lower()}
                                bad = sorted(h for h in hosts if not _host_allowed(h, req.allowed_domains))
                                if bad:
                                    raise DownloadFailure(f"Redirección/host no aprobado: {bad}",
                                                          ErrorClass.REDIRECT_NOT_ALLOWED, status)
                            clen = resp.headers.get("content-length")
                            if limit and clen and clen.isdigit() and int(clen) > limit:
                                raise DownloadFailure(f"content-length {clen} > max_bytes {limit}",
                                                      ErrorClass.SIZE_EXCEEDED, status)
                            klass = classify_status(status, extra_retry)
                            if klass is not None:
                                retry_after = resp.headers.get("retry-after")
                                raise _Retryable(status, klass, retry_after)
                            if status == 416:  # rango no satisfacible: reiniciar limpio
                                part_path.unlink(missing_ok=True)
                                raise _Retryable(status, ErrorClass.NETWORK, None, immediate=True)
                            if status == 206 and existing > 0:
                                if not _content_range_starts_at(resp.headers.get("content-range"), existing):
                                    # el servidor no continúa donde quedó el .part: se descarta y se empieza limpio
                                    part_path.unlink(missing_ok=True)
                                    meta_path.unlink(missing_ok=True)
                                    raise _Retryable(status, ErrorClass.NETWORK, None, immediate=True)
                                mode, resumed = "ab", True
                            else:
                                mode, resumed = "wb", False
                            if mode == "wb":
                                _write_part_meta(meta_path, url_sha, resp.headers)
                            with open(part_path, mode) as f:
                                try:
                                    for block in resp.iter_bytes(chunk_size=self.chunk_size):
                                        if block:
                                            f.write(block)
                                            if limit and f.tell() > limit:
                                                raise DownloadFailure(f"descarga supera max_bytes {limit}",
                                                                      ErrorClass.SIZE_EXCEEDED, status)
                                            if self._monotonic() > deadline:
                                                raise DownloadFailure(
                                                    f"plazo total de descarga agotado ({total_s}s)",
                                                    ErrorClass.TIMEOUT, status)
                                except BaseException:
                                    try:                      # lo escrito hasta aquí queda DURABLE: el .part es reanudable
                                        f.flush()
                                        os.fsync(f.fileno())
                                    except OSError:
                                        pass
                                    raise
                                f.flush()
                                os.fsync(f.fileno())          # DEFECT-03
                    break
                except DownloadFailure:
                    raise
                except _Retryable as r:
                    last_error = DownloadFailure(
                        f"HTTP {r.status} en {req.url}", r.klass, r.status)
                    if r.klass is ErrorClass.HTTP_PERMANENT:
                        raise last_error  # 4xx no reintentable: 1 solo intento
                    if attempt >= max_retries:
                        raise last_error   # DEFECT-02: conserva status + clase reales
                    wait = 0.0 if r.immediate else self.backoff(attempt)
                    ra = _parse_retry_after(r.retry_after, self._clock)       # segundos o fecha HTTP
                    if ra is not None:
                        if ra > self.max_retry_after_s:
                            self._emit("retry_after_capped", job, requested_s=round(ra, 3), cap_s=self.max_retry_after_s)
                        wait = max(wait, min(ra, self.max_retry_after_s))
                    self._emit("download_retry", job, status=r.status, wait_s=round(wait, 3), attempt=attempt)
                    if wait:
                        self._sleep(wait)
                    attempt += 1
                except httpx.TimeoutException as ex:
                    last_error = DownloadFailure(f"Timeout en {req.url}: {ex}", ErrorClass.TIMEOUT, status)
                    if attempt >= max_retries:
                        raise last_error
                    self._emit("download_retry", job, status=None, error="timeout", attempt=attempt)
                    self._sleep(self.backoff(attempt))
                    attempt += 1
                except httpx.RequestError as ex:
                    last_error = DownloadFailure(f"Red caída en {req.url}: {ex}", ErrorClass.NETWORK, status)
                    if attempt >= max_retries:
                        raise last_error
                    self._emit("download_retry", job, status=None, error="network", attempt=attempt)
                    self._sleep(self.backoff(attempt))
                    attempt += 1

            if not part_path.exists() or part_path.stat().st_size == 0:
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadFailure(f"Descarga vacía: {req.url}", ErrorClass.EMPTY_FILE, status)

            digest = self._hash_file(part_path, self.chunk_size).hexdigest()
            if req.expected_sha256 and req.expected_sha256.lower() != digest:
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                raise DownloadFailure(
                    f"SHA-256 esperado {req.expected_sha256} != obtenido {digest}", ErrorClass.CHECKSUM_MISMATCH, status)

            os.replace(part_path, final_path)   # rename atómico .part -> staged (nunca se escribe el nombre final directamente)
            meta_path.unlink(missing_ok=True)
            _fsync_dir(final_path.parent)       # durabilidad del rename (POSIX; en Windows no aplica)
            size = final_path.stat().st_size
            res = DownloadResult(
                ok=True, staged_path=str(final_path), sha256=digest, size_bytes=size, http_status=status,
                mime_type=mime, final_url=final_url, resumed=resumed, retries_taken=attempt,
                duration_s=round(self._monotonic() - started, 4))
            self._emit("download_completed", job, sha256=digest, size_bytes=size, status=status,
                       retries=attempt, resumed=resumed)
            return res
        except DownloadFailure as ex:
            if ex.error_class in (ErrorClass.SIZE_EXCEEDED, ErrorClass.REDIRECT_NOT_ALLOWED):
                part_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
            res = DownloadResult(
                ok=False, http_status=ex.status_code, final_url=final_url, retries_taken=attempt,
                error_class=ex.error_class.value, error_message=str(ex),
                duration_s=round(self._monotonic() - started, 4))
            self._emit("download_failed", job, status=ex.status_code, error_class=ex.error_class.value,
                       message=str(ex), retries=attempt)
            return res
        finally:
            if owns_client:
                client.close()


_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$")


def _is_plain_filename(name: str) -> bool:
    """Un nombre simple: sin separadores, sin ``..``, sin unidad/ADS (``:``), sin NUL, ni terminado en punto o espacio."""
    if not name or name in (".", "..") or "\x00" in name:
        return False
    if any(c in name for c in ("/", "\\", ":")):
        return False
    if name != name.strip() or name.endswith("."):
        return False
    return Path(name).name == name and not Path(name).is_absolute()


def _parse_retry_after(value: Optional[str], clock: Callable[[], float]) -> Optional[float]:
    """RFC 9110: ``Retry-After`` = segundos enteros o fecha HTTP. Devuelve segundos de espera (>= 0) o None si no es válido."""
    if not value:
        return None
    v = value.strip()
    if v.isdigit():
        return float(v)
    try:
        dt = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, dt.timestamp() - clock())


def _content_range_starts_at(header: Optional[str], start: int) -> bool:
    """Un 206 sin ``Content-Range`` se acepta (servidores antiguos); si lo trae, debe empezar exactamente en ``start``."""
    if not header:
        return True
    m = _CONTENT_RANGE_RE.match(header.strip())
    return bool(m) and int(m.group(1)) == start


def _write_part_meta(path: Path, url_sha: str, headers) -> None:
    try:
        path.write_text(json.dumps({"url_sha": url_sha, "etag": headers.get("etag"),
                                    "last_modified": headers.get("last-modified")}), encoding="utf-8")
    except OSError:
        pass          # sin meta el .part sigue siendo reanudable (modo heredado), solo sin If-Range


def _read_part_meta(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _if_range_validator(meta: Optional[dict]) -> Optional[str]:
    """``If-Range`` solo admite un ETag FUERTE o una fecha ``Last-Modified``."""
    if not meta:
        return None
    etag = meta.get("etag")
    if etag and not str(etag).startswith("W/"):
        return str(etag)
    return meta.get("last_modified") or None


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _host_allowed(host: str, allowed) -> bool:
    host = host.lower()
    return any(host == a.lower() or host.endswith("." + a.lower()) for a in allowed)


class _Retryable(Exception):
    def __init__(self, status: int, klass: ErrorClass, retry_after: Optional[str], immediate: bool = False):
        super().__init__(f"status {status}")
        self.status = status
        self.klass = klass
        self.retry_after = retry_after
        self.immediate = immediate
