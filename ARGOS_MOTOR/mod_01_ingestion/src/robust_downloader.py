"""
STATER MOTOR ARGOS — MOD_01: Robust Streaming Downloader.
Implements streaming downloads with chunking, atomic .tmp renaming,
Range request resumption, exponential backoff with jitter for HTTP 429/5xx errors,
in-flight SHA-256 computation, and checksum verification.
"""
import os
import time
import random
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import httpx


class DownloadError(Exception):
    """Excepción base para errores de descarga documental."""
    def __init__(self, message: str, status_code: Optional[int] = None, error_type: str = "DOWNLOAD_FAILED"):
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class RobustDownloader:
    """Descargador de alta fiabilidad para recursos regulatorios oficiales."""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 4,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 30.0,
        chunk_size: int = 64 * 1024,
        timeout: float = 60.0
    ):
        self.headers = headers or {"User-Agent": "STATER Regulatory Engine/1.0 (dev@stater.es)"}
        self.max_retries = max_retries
        self.initial_backoff_s = initial_backoff_s
        self.max_backoff_s = max_backoff_s
        self.chunk_size = chunk_size
        self.timeout = timeout

    def _compute_backoff(self, attempt: int) -> float:
        """Calcula el tiempo de espera con backoff exponencial y jitter aleatorio."""
        backoff = min(self.max_backoff_s, self.initial_backoff_s * (2 ** attempt))
        jitter = random.uniform(0.1, 0.5) * backoff
        return backoff + jitter

    def download_to_file(
        self,
        url: str,
        destination_path: Path,
        expected_sha256: Optional[str] = None,
        allow_resume: bool = True,
        client: Optional[httpx.Client] = None
    ) -> Dict[str, Any]:
        """
        Descarga un recurso hacia un archivo local mediante streaming atómico.
        
        Retorna un diccionario con:
        - file_path: str
        - file_size_bytes: int
        - sha256: str
        - http_status: int
        - mime_type: str
        - resumed: bool
        - retries_taken: int
        - final_url: str
        """
        destination_path = Path(destination_path)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination_path.with_suffix(destination_path.suffix + ".part")

        attempt = 0
        sha256_hasher = hashlib.sha256()
        existing_bytes = 0
        resumed = False
        final_url = url
        final_status = 200
        detected_mime = "application/octet-stream"

        should_close_client = False
        if client is None:
            client = httpx.Client(headers=self.headers, timeout=self.timeout, follow_redirects=True)
            should_close_client = True

        try:
            while attempt <= self.max_retries:
                req_headers = dict(self.headers)
                
                # Comprobar si existe archivo parcial para reanudación
                if allow_resume and temp_path.exists():
                    existing_bytes = temp_path.stat().st_size
                    if existing_bytes > 0:
                        req_headers["Range"] = f"bytes={existing_bytes}-"
                else:
                    existing_bytes = 0

                try:
                    with client.stream("GET", url, headers=req_headers) as response:
                        final_url = str(response.url)
                        final_status = response.status_code
                        detected_mime = response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()

                        # Manejo de códigos reintentables (429 / 5xx)
                        if response.status_code in self.RETRYABLE_STATUS_CODES:
                            if attempt == self.max_retries:
                                raise DownloadError(
                                    f"Servidor respondió con código {response.status_code} tras {attempt} reintentos en {url}",
                                    status_code=response.status_code,
                                    error_type=f"HTTP_{response.status_code}"
                                )
                            wait_s = self._compute_backoff(attempt)
                            # Si el servidor envía cabecera Retry-After
                            retry_after = response.headers.get("retry-after")
                            if retry_after and retry_after.isdigit():
                                wait_s = max(wait_s, float(retry_after))
                            
                            time.sleep(wait_s)
                            attempt += 1
                            continue

                        # Manejo de error 4xx no reintentable
                        if response.status_code >= 400 and response.status_code != 416:
                            raise DownloadError(
                                f"Error HTTP {response.status_code} al descargar {url}",
                                status_code=response.status_code,
                                error_type=f"HTTP_{response.status_code}"
                            )

                        # Si el servidor respondió 206 Partial Content
                        if response.status_code == 206 and existing_bytes > 0:
                            mode = "ab"
                            resumed = True
                        else:
                            # Servidor no soporta Range o descarga desde cero
                            mode = "wb"
                            existing_bytes = 0
                            resumed = False

                        # Escritura por bloques
                        with open(temp_path, mode) as f:
                            for chunk in response.iter_bytes(chunk_size=self.chunk_size):
                                if chunk:
                                    f.write(chunk)

                        # Descarga completada exitosamente sin excepciones de streaming
                        break

                except (httpx.RequestError, httpx.TimeoutException, DownloadError) as ex:
                    if isinstance(ex, DownloadError) and ex.status_code and ex.status_code not in self.RETRYABLE_STATUS_CODES:
                        raise ex
                    
                    if attempt == self.max_retries:
                        raise DownloadError(
                            f"Fallo de conexión irrecuperable tras {attempt} reintentos: {str(ex)}",
                            error_type="CONNECTION_DROPPED"
                        )
                    
                    wait_s = self._compute_backoff(attempt)
                    time.sleep(wait_s)
                    attempt += 1

            # Calcular SHA-256 completo del archivo final
            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise DownloadError(f"Archivo descargado vacío o inexistente: {url}", error_type="EMPTY_FILE")

            total_size = temp_path.stat().st_size
            sha256_hasher = hashlib.sha256()
            with open(temp_path, "rb") as f:
                while chunk := f.read(self.chunk_size):
                    sha256_hasher.update(chunk)
            actual_sha256 = sha256_hasher.hexdigest()

            # Verificación de integridad si se proporcionó expected_sha256
            if expected_sha256 and expected_sha256.lower() != actual_sha256.lower():
                # Borrar archivo temporal corrupto
                if temp_path.exists():
                    temp_path.unlink()
                raise DownloadError(
                    f"Discordancia de SHA-256 en {url}. Esperado: {expected_sha256}, Obtenido: {actual_sha256}",
                    error_type="CHECKSUM_MISMATCH"
                )

            # Renombrado atómico del archivo temporal a destino definitivo
            if destination_path.exists():
                destination_path.unlink()
            temp_path.rename(destination_path)

            return {
                "file_path": str(destination_path.as_posix()),
                "file_size_bytes": total_size,
                "sha256": actual_sha256,
                "http_status": final_status,
                "mime_type": detected_mime,
                "resumed": resumed,
                "retries_taken": attempt,
                "final_url": final_url,
            }

        finally:
            if should_close_client:
                client.close()
