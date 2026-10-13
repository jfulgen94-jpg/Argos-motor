"""
U4 — Modo SANDBOX / REPLAY offline OBLIGATORIO para migrar países al pipeline unificado.

* ``ReplayHttp``: servidor HTTP simulado (``httpx.MockTransport``). Solo responde lo que se le registró, para hosts
  permitidos; cualquier otra petición falla como error de red (``ReplayMiss``). Ningún socket real.
* ``make_sandbox_runner``: construye un ``UnifiedIngestRunner`` en modo SANDBOX/TEST con ese transporte. Se niega a
  trabajar sobre una ubicación operativa (``D:/ARGOS_DATA``, ``ARGOS_MOTOR/data``, ``ARGOS_DATA_ROOT``) o en LIVE/PILOT, y
  lo hace ANTES de crear ningún directorio.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlsplit

import httpx

from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.policy import is_host_allowed
from mod_01_ingestion.src.unified.download_service import DownloadService
from mod_01_ingestion.src.unified.ingest_runner import UnifiedIngestRunner
from mod_01_ingestion.src.unified.models import RunContext
from mod_01_ingestion.src.unified.persistence_guard import is_operational_location
from mod_01_ingestion.src.unified.rate_limiter import DomainRateLimiter
from mod_01_ingestion.src.unified.router import SourceRouter

SANDBOX_MODES = (ExecutionMode.SANDBOX, ExecutionMode.TEST)


class SandboxViolation(DomainValidationError):
    pass


class ReplayMiss(httpx.ConnectError):
    """Petición no registrada o a un host no permitido: se comporta como un fallo de red."""


class ReplayHttp:
    def __init__(self, allowed_hosts: Sequence[str]):
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self._routes: Dict[str, List[httpx.Response]] = {}
        self.calls: List[str] = []            # URL sin query, en orden de llegada
        self.misses: List[str] = []

    @staticmethod
    def _key(url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.hostname}{p.path}"

    def add(self, url: str, content: bytes = b"", *, status: int = 200, content_type: str = "application/octet-stream",
            headers: Optional[Mapping[str, str]] = None) -> "ReplayHttp":
        self._routes.setdefault(self._key(url), []).append(
            httpx.Response(status, content=content, headers={"content-type": content_type, **(headers or {})}))
        return self

    def _handle(self, request: httpx.Request) -> httpx.Response:
        key = self._key(str(request.url))
        self.calls.append(key)
        if not is_host_allowed(request.url.host or "", self.allowed_hosts) or key not in self._routes:
            self.misses.append(key)
            raise ReplayMiss(f"replay sin respuesta registrada para {key}", request=request)
        seq = self._routes[key]
        item = seq.pop(0) if len(seq) > 1 else seq[0]          # la última respuesta se repite
        return httpx.Response(item.status_code, content=item.content, headers=item.headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)


def make_sandbox_runner(root: Union[str, Path], router: SourceRouter, replay: ReplayHttp, *,
                        mode: ExecutionMode = ExecutionMode.SANDBOX, **runner_kw) -> UnifiedIngestRunner:
    """Runner unificado sobre ``router`` y HTTP de replay. Falla CERRADO ante cualquier configuración no segura."""
    mode = ExecutionMode(mode)
    if mode not in SANDBOX_MODES:
        raise SandboxViolation(f"el replay solo se ejecuta en {[m.value for m in SANDBOX_MODES]}, no en {mode.value}")
    if not isinstance(replay, ReplayHttp):
        raise SandboxViolation("se exige un ReplayHttp: el sandbox no usa nunca un cliente HTTP real")
    if is_operational_location(root):
        raise SandboxViolation("el sandbox no puede trabajar sobre una ubicación operativa")
    layout = DataLayout(Path(root))
    download = DownloadService(client=httpx.Client(transport=replay.transport(), follow_redirects=True),
                               sleep=lambda s: None, initial_backoff_s=0.0, max_retries=runner_kw.pop("max_retries", 1),
                               rate_limiter=DomainRateLimiter(min_interval_s=0, sleep=lambda s: None))
    run = runner_kw.pop("run", None) or RunContext(data_root=str(root), mode=mode)
    if ExecutionMode(run.mode) not in SANDBOX_MODES:
        raise SandboxViolation("el RunContext del sandbox debe ser SANDBOX o TEST")
    return UnifiedIngestRunner(layout, router.as_runner_adapters(), download=download, run=run, **runner_kw)
