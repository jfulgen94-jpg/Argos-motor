"""
CNMV-U4 — Referencia documental PERSISTIBLE vs URL de transporte EFÍMERA (dominio puro: sin red, sin disco).

Dos conceptos estrictamente separados:

* **Referencia estable** (``StableReference`` / ``strip_url``): host y path SIN query, fragmento ni credenciales, más los metadatos de
  evidencia sin token (autoridad, emisor, ejercicio, nº de registro, familia, tipo de recurso declarado, momento de observación).
  Es lo único que puede entrar en manifiestos, catálogo, ledger, telemetría, informes, sidecars y mensajes de error.
* **URL de transporte** (``TransportUrl``): la URL completa con query/token/fragmento/credenciales. Solo vive en memoria, durante la
  operación de red. ``repr``/``str``/``format`` están redactados, no es serializable ni copiable por valor, no se compara por contenido y
  ``reveal()`` solo funciona dentro de ``authorized_transport()`` (lo abre el servicio de descarga). Fuera de una operación autorizada falla.

Las guardas (``assert_no_secret``) FALLAN CERRADO: nunca "sanean" guardando parte de una query; la query se elimina por completo.
Indicadores detectados: ``?e=``, ``token=``, ``sig=``, ``signature=``, ``X-Amz-*``, cabeceras ``Authorization:``/``Cookie:``, ``Bearer …``,
credenciales en la URL y cualquier URL con query o fragmento.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from mod_01_ingestion.src.unified.domain.errors import DomainValidationError


class SecretLeakError(DomainValidationError):
    """Un token, query, cookie o credencial intentó entrar en una salida persistente (se rechaza entero)."""


class TransportViolation(DomainValidationError):
    """Una URL de transporte se usó fuera de una operación autorizada o se intentó serializar/copiar."""


_AUTH_DEPTH: "contextvars.ContextVar[int]" = contextvars.ContextVar("unified_transport_authorized", default=0)


@contextlib.contextmanager
def authorized_transport() -> Iterator[None]:
    """Autoriza ``TransportUrl.reveal()`` SOLO dentro del bloque (lo usa ``DownloadService`` alrededor de la petición)."""
    tok = _AUTH_DEPTH.set(_AUTH_DEPTH.get() + 1)
    try:
        yield
    finally:
        _AUTH_DEPTH.reset(tok)


def strip_url(url: str) -> str:
    """``scheme://host[:port]/path`` sin credenciales, query ni fragmento. Una cadena que no es URL se devuelve intacta."""
    try:
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return url
        host = p.hostname + (f":{p.port}" if p.port else "")
        return urlunsplit((p.scheme, host, p.path, "", ""))
    except ValueError:
        return url.split("?")[0].split("#")[0]


def url_needs_transport(url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return True
    return bool(p.query or p.fragment or p.username or p.password)


class TransportUrl:
    """URL completa de transporte. Efímera: no persistible, no serializable, no comparable por contenido."""
    __slots__ = ("_TransportUrl__url", "_stable", "_host", "_path")

    def __init__(self, url: str):
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            raise TransportViolation("la URL de transporte no es una URL http(s) válida")
        object.__setattr__(self, "_TransportUrl__url", url)
        object.__setattr__(self, "_stable", strip_url(url))
        object.__setattr__(self, "_host", p.hostname.lower())
        object.__setattr__(self, "_path", p.path)

    def __setattr__(self, name, value):
        raise TransportViolation("TransportUrl es inmutable")

    # ---- lo único que se puede mostrar
    @property
    def host(self) -> str:
        return self._host

    @property
    def safe_path(self) -> str:
        return self._path

    @property
    def stable_url(self) -> str:
        return self._stable

    @property
    def safe_ref(self) -> str:
        return f"{self._host}{self._path}"

    def reveal(self) -> str:
        """La URL real, SOLO dentro de ``authorized_transport()`` (operación de red en memoria)."""
        if _AUTH_DEPTH.get() <= 0:
            raise TransportViolation("la URL de transporte solo puede usarse dentro de una operación de red autorizada")
        return self.__url

    # ---- redacción total
    def __repr__(self) -> str:
        return f"TransportUrl(host={self._host!r}, path={self._path!r}, query=<redacted>)"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    # ---- sin comparación por contenido, sin serialización, sin copia por valor
    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)

    def __reduce__(self):
        raise TransportViolation("TransportUrl no es serializable")

    def __reduce_ex__(self, protocol):
        raise TransportViolation("TransportUrl no es serializable")

    def __getstate__(self):
        raise TransportViolation("TransportUrl no es serializable")

    def __copy__(self) -> "TransportUrl":
        return self

    def __deepcopy__(self, memo) -> "TransportUrl":
        return self


def split_url(url: str) -> Tuple[str, Optional[TransportUrl]]:
    """``(url estable, transporte)``. Si la URL no lleva query/fragmento/credenciales no hace falta transporte."""
    if url_needs_transport(url):
        return strip_url(url), TransportUrl(url)
    return url, None


# ====================================================================== detección y redacción
_URL = re.compile(r"https?[:][/]{2}[^\s\"'<>)\]]+")
_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("URL_QUERY_OR_FRAGMENT", re.compile(r"https?[:][/]{2}[^\s\"'<>]*[?#](?!<redacted>)")),
    ("QUERY_E_PARAM", re.compile(r"(?i)[?&;]e=(?!<redacted>)[A-Za-z0-9%+/=_.~-]{6,}")),
    ("SECRET_PARAM", re.compile(r"(?i)\b(token|access_token|id_token|refresh_token|sig|signature|apikey|api_key|client_secret|"
                                r"password|passwd|x-amz-[a-z-]+|awsaccesskeyid)=(?!<redacted>)[^\s&\"']+")),
    ("AMZ_SIGNATURE", re.compile(r"(?i)x-amz-(signature|credential|security-token|algorithm|date)")),
    ("AUTH_HEADER", re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*(?!<redacted>)\S+")),
    ("BEARER", re.compile(r"(?i)\bbearer\s+(?!<redacted>)[A-Za-z0-9._~+/=-]{8,}")),
    ("URL_CREDENTIALS", re.compile(r"[:][/]{2}[^/\s:@]+:[^/\s@]+@")),
    ("TOKENIZED_ENDPOINT", re.compile(r"(?i)verdocumento/ver\?")),
)
_REDACT_HEADER = re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\n;]+|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_REDACT_PARAM = re.compile(r"(?i)\b(token|access_token|id_token|refresh_token|sig|signature|apikey|api_key|client_secret|password|passwd)=[^\s&\"']+")


def find_secret(text: str) -> Optional[str]:
    """Código del primer indicador de secreto en ``text`` (o ``None``)."""
    for code, pat in _PATTERNS:
        if pat.search(text):
            return code
    return None


def redact_text(text: object, secrets: Iterable[str] = ()) -> str:
    """Quita por completo query, fragmento y credenciales de toda URL del texto y valores de cabeceras/tokens. No deja restos de query."""
    s = str(text)
    for lit in secrets:
        if lit:
            s = s.replace(lit, "<redacted-url>")
    s = _URL.sub(lambda m: strip_url(m.group(0)), s)
    s = _REDACT_HEADER.sub("<redacted>", s)
    return _REDACT_PARAM.sub(lambda m: m.group(1) + "=<redacted>", s)


def assert_no_secret(obj: Any, where: str = "payload", _depth: int = 0) -> None:
    """Falla cerrado si ``obj`` (str, dict, lista, dataclass) contiene un secreto o una ``TransportUrl``."""
    if _depth > 12:
        raise SecretLeakError(f"{where}: estructura demasiado profunda para verificarse")
    if isinstance(obj, TransportUrl):
        raise SecretLeakError(f"{where}: una URL de transporte no puede persistirse")
    if isinstance(obj, str):
        code = find_secret(obj)
        if code:
            raise SecretLeakError(f"{where}: contiene un indicador de secreto ({code})")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_secret(str(k), f"{where}.<clave>", _depth + 1)
            assert_no_secret(v, f"{where}.{k}", _depth + 1)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for i, v in enumerate(obj):
            assert_no_secret(v, f"{where}[{i}]", _depth + 1)
    elif dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            assert_no_secret(getattr(obj, f.name), f"{where}.{f.name}", _depth + 1)


def sanitize_payload(obj: Any, _depth: int = 0) -> Any:
    """Copia saneada para telemetría: ``TransportUrl`` → host+path; cadenas → sin query/fragmento/credenciales."""
    if _depth > 12:
        return "<too-deep>"
    if isinstance(obj, TransportUrl):
        return obj.safe_ref
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {str(k): sanitize_payload(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [sanitize_payload(v, _depth + 1) for v in obj]
    return obj


# ====================================================================== referencia estable
@dataclass(frozen=True)
class StableReference:
    """Referencia documental persistible: nada de lo que hay aquí puede contener query, token, cookie ni credencial."""
    authority: str
    issuer_id: str
    fiscal_year: int
    registration_number: Optional[str]
    document_family: str
    declared_resource_kind: Optional[str]
    stable_host: str
    stable_path: str
    observed_at: str

    def __post_init__(self):
        for name in ("authority", "issuer_id", "document_family", "stable_host", "stable_path", "observed_at"):
            if not str(getattr(self, name) or "").strip():
                raise DomainValidationError(f"StableReference.{name} es obligatorio")
        if any(c in self.stable_path for c in "?#") or any(c in self.stable_host for c in "?#/@"):
            raise SecretLeakError("StableReference: el host/path estables no admiten query, fragmento ni credenciales")
        assert_no_secret(dataclasses.asdict(self), "StableReference")

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @property
    def stable_url(self) -> str:
        return urlunsplit(("https", self.stable_host, self.stable_path, "", ""))

    @classmethod
    def from_url(cls, url: str, **kw) -> "StableReference":
        p = urlsplit(strip_url(url))
        return cls(stable_host=(p.hostname or ""), stable_path=p.path or "/", **kw)
