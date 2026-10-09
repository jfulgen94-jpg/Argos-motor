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
import os
import random
import time
from pathlib import Path
from typing import Callable, Dict, Optional

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


def classify_status(status: int) -> Optional[ErrorClass]:
    """Clasificación común de respuestas HTTP (None = éxito)."""
    if status in RETRYABLE_STATUS:
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
        started = time.monotonic()
        staging = Path(req.staging_dir)
        staging.mkdir(parents=True, exist_ok=True)
        final_path = staging / req.file_name
        part_path = final_path.with_name(final_path.name + ".part")

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
                    if existing > 0:
                        headers["Range"] = f"bytes={existing}-"
                    elif part_path.exists():
                        part_path.unlink()
                    self._emit("download_attempt", job, url=req.url, attempt=attempt, resume_from=existing)
                    with self.rate_limiter.slot(req.url):
                        with client.stream("GET", req.url, headers=headers) as resp:
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
                            if req.max_bytes and clen and clen.isdigit() and int(clen) > req.max_bytes:
                                raise DownloadFailure(f"content-length {clen} > max_bytes {req.max_bytes}",
                                                      ErrorClass.SIZE_EXCEEDED, status)
                            klass = classify_status(status)
                            if klass is not None:
                                retry_after = resp.headers.get("retry-after")
                                raise _Retryable(status, klass, retry_after)
                            if status == 416:  # rango no satisfacible: reiniciar limpio
                                part_path.unlink(missing_ok=True)
                                raise _Retryable(status, ErrorClass.NETWORK, None, immediate=True)
                            if status == 206 and existing > 0:
                                mode, resumed = "ab", True
                            else:
                                mode, resumed = "wb", False
                            with open(part_path, mode) as f:
                                for block in resp.iter_bytes(chunk_size=self.chunk_size):
                                    if block:
                                        f.write(block)
                                        if req.max_bytes and f.tell() > req.max_bytes:
                                            raise DownloadFailure(f"descarga supera max_bytes {req.max_bytes}",
                                                                  ErrorClass.SIZE_EXCEEDED, status)
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
                    if attempt >= self.max_retries:
                        raise last_error   # DEFECT-02: conserva status + clase reales
                    wait = 0.0 if r.immediate else self.backoff(attempt)
                    if r.retry_after and r.retry_after.strip().isdigit():
                        wait = max(wait, min(float(r.retry_after), self.max_retry_after_s))
                    self._emit("download_retry", job, status=r.status, wait_s=round(wait, 3), attempt=attempt)
                    if wait:
                        self._sleep(wait)
                    attempt += 1
                except httpx.TimeoutException as ex:
                    last_error = DownloadFailure(f"Timeout en {req.url}: {ex}", ErrorClass.TIMEOUT, status)
                    if attempt >= self.max_retries:
                        raise last_error
                    self._emit("download_retry", job, status=None, error="timeout", attempt=attempt)
                    self._sleep(self.backoff(attempt))
                    attempt += 1
                except httpx.RequestError as ex:
                    last_error = DownloadFailure(f"Red caída en {req.url}: {ex}", ErrorClass.NETWORK, status)
                    if attempt >= self.max_retries:
                        raise last_error
                    self._emit("download_retry", job, status=None, error="network", attempt=attempt)
                    self._sleep(self.backoff(attempt))
                    attempt += 1

            if not part_path.exists() or part_path.stat().st_size == 0:
                part_path.unlink(missing_ok=True)
                raise DownloadFailure(f"Descarga vacía: {req.url}", ErrorClass.EMPTY_FILE, status)

            digest = self._hash_file(part_path, self.chunk_size).hexdigest()
            if req.expected_sha256 and req.expected_sha256.lower() != digest:
                part_path.unlink(missing_ok=True)
                raise DownloadFailure(
                    f"SHA-256 esperado {req.expected_sha256} != obtenido {digest}", ErrorClass.CHECKSUM_MISMATCH, status)

            os.replace(part_path, final_path)   # rename atómico .part -> staged
            size = final_path.stat().st_size
            res = DownloadResult(
                ok=True, staged_path=str(final_path), sha256=digest, size_bytes=size, http_status=status,
                mime_type=mime, final_url=final_url, resumed=resumed, retries_taken=attempt,
                duration_s=round(time.monotonic() - started, 4))
            self._emit("download_completed", job, sha256=digest, size_bytes=size, status=status,
                       retries=attempt, resumed=resumed)
            return res
        except DownloadFailure as ex:
            if ex.error_class in (ErrorClass.SIZE_EXCEEDED, ErrorClass.REDIRECT_NOT_ALLOWED):
                part_path.unlink(missing_ok=True)
            res = DownloadResult(
                ok=False, http_status=ex.status_code, final_url=final_url, retries_taken=attempt,
                error_class=ex.error_class.value, error_message=str(ex),
                duration_s=round(time.monotonic() - started, 4))
            self._emit("download_failed", job, status=ex.status_code, error_class=ex.error_class.value,
                       message=str(ex), retries=attempt)
            return res
        finally:
            if owns_client:
                client.close()


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
