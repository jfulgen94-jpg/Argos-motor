"""
U5D — Sincronización a Azure Blob del árbol UNIFICADO (cas/, cas_pins/, versions/, manifests/, catálogo y reports/).

Módulo SIN dependencia del SDK de Azure: recibe un ``container_client`` (el real de ``azure.storage.blob`` o uno simulado). El
sincronizador legacy (``cloud/azure_data_lake_sync.py``) lo invoca con ``--unified-root``; el tráfico real solo ocurre cuando
alguien lo ejecuta con una cadena de conexión: aquí no se lee ninguna credencial.

* Estructura preservada: ``<raíz>/<rel>`` → blob ``unified/<rel>`` (mismo árbol, mismos nombres).
* Metadatos: ``sha256``, ``unified_kind``, ``stater_managed`` y ``local_mtime_ns``. Un pin (enlace duro al blob) se sube como blob
  VACÍO con ``pin_of``/``pin_key``/``blob_size`` para no duplicar bytes.
* Seguridad: se omiten secretos (por nombre y por contenido), temporales (``.part``, locks), enlaces simbólicos y todo lo que no
  esté en ``SYNC_DIRS``. El catálogo DuckDB solo se sube si no hay un ``.wal`` pendiente (no está en reposo → ``CATALOG_NOT_QUIESCENT``).
* Los blobs del CAS son inmutables: si ya existen con otro tamaño/hash se informa ``conflict`` y NO se sobrescriben.
* Orden: cas → cas_pins → versions → manifests → reports → catalog (el índice se sube el último).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from mod_01_ingestion.src.unified.legacy_exclusions import MARKER, find_unified_root

UNIFIED_PREFIX = "unified/"
SYNC_DIRS = ("cas", "cas_pins", "versions", "manifests", "catalog", "reports")
_ORDER = {d: i for i, d in enumerate(SYNC_DIRS)}
_ORDER["catalog"] = len(SYNC_DIRS)                      # el catálogo, el último
_SKIP_SUFFIXES = (".part", ".part.meta", ".lock", ".tmp", ".wal", ".pyc", ".pem", ".key", ".pfx", ".p12")
_SKIP_NAMES = {".env", "azure_secrets.json", "credentials", "credentials.json", "cookies", "cookies.sqlite", MARKER.lower()}
_SECRET_RE = re.compile(r"(AccountKey=|DefaultEndpointsProtocol=|SharedAccessSignature|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
                        r"(?i:\bbearer\s+[A-Za-z0-9._~+/=-]{16,})|(?i:(api[_-]?key|secret|password)\"?\s*[:=]\s*\"?[^\s\"']{8,}))")
_MAX_SCAN = 1 << 20
_CT = {".json": "application/json", ".pdf": "application/pdf", ".zip": "application/zip", ".duckdb": "application/octet-stream"}


class UnifiedSyncError(Exception):
    pass


@dataclass(frozen=True)
class SyncItem:
    local: Path
    blob: str
    kind: str                       # cas | cas_pin | versions | manifests | reports | catalog
    size: int
    sha256: str
    metadata: Dict[str, str]
    marker: bool = False            # True → se sube un blob vacío (pin)


@dataclass
class SyncPlan:
    root: Path
    items: List[SyncItem] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)

    def by_kind(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for i in self.items:
            out[i.kind] = out.get(i.kind, 0) + 1
        return dict(sorted(out.items()))


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sensitive(path: Path) -> bool:
    n = path.name.lower()
    if n in _SKIP_NAMES or n.endswith(_SKIP_SUFFIXES):
        return True
    if path.suffix.lower() in (".json", ".txt", ".yaml", ".yml", ".csv", ".md", ".log") and path.stat().st_size <= _MAX_SCAN:
        try:
            return bool(_SECRET_RE.search(path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            return True
    return False


def _meta(kind: str, path: Path, sha: str, **extra: str) -> Dict[str, str]:
    m = {"stater_managed": "true", "unified_kind": kind, "sha256": sha, "local_mtime_ns": str(path.stat().st_mtime_ns)}
    m.update({k: quote(str(v), safe="") for k, v in extra.items()})
    return m


def build_plan(root, *, verify_hashes: bool = False) -> SyncPlan:
    """Calcula qué subir. Solo LEE el árbol local; exige un raíz unificado inicializado (marcador)."""
    root = Path(root)
    ur = find_unified_root(root)
    if ur is None or os.path.normcase(os.path.abspath(ur)) != os.path.normcase(os.path.abspath(root)):
        raise UnifiedSyncError(f"no es un raíz unificado inicializado (falta {MARKER}): {root}")
    plan = SyncPlan(root=root)
    for top in SYNC_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for cur, dirs, files in os.walk(base, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                f = Path(cur) / name
                rel = f.relative_to(root).as_posix()
                if f.is_symlink():
                    plan.skipped.append({"path": rel, "reason": "SYMLINK"})
                    continue
                if _sensitive(f):
                    plan.skipped.append({"path": rel, "reason": "SENSITIVE_OR_TEMPORARY"})
                    continue
                if top == "catalog" and f.suffix.lower() == ".duckdb" and (f.with_name(f.name + ".wal")).exists():
                    plan.skipped.append({"path": rel, "reason": "CATALOG_NOT_QUIESCENT"})
                    continue
                size = f.stat().st_size
                if top == "cas":
                    sha = name if (re.fullmatch(r"[0-9a-f]{64}", name) and not verify_hashes) else _sha(f)
                    if verify_hashes and sha != name:
                        plan.skipped.append({"path": rel, "reason": "CAS_HASH_MISMATCH"})
                        continue
                    plan.items.append(SyncItem(f, UNIFIED_PREFIX + rel, "cas", size, sha, _meta("cas", f, sha)))
                elif top == "cas_pins":
                    sha = Path(cur).relative_to(base).parts[0] if Path(cur) != base else ""
                    plan.items.append(SyncItem(f, UNIFIED_PREFIX + rel, "cas_pin", 0, sha,
                                               _meta("cas_pin", f, sha, pin_of=sha, pin_key=name, blob_size=size), marker=True))
                else:
                    sha = _sha(f)
                    plan.items.append(SyncItem(f, UNIFIED_PREFIX + rel, top, size, sha, _meta(top, f, sha)))
    plan.items.sort(key=lambda i: (_ORDER.get(i.kind if i.kind != "cas_pin" else "cas_pins", 99), i.blob))
    return plan


def _content_settings(path: Path):
    try:
        from azure.storage.blob import ContentSettings          # solo para el cliente real
        return ContentSettings(content_type=_CT.get(path.suffix.lower(), "application/octet-stream"))
    except ImportError:
        return None


class UnifiedSynchronizer:
    def __init__(self, container_client, *, sleep: Callable[[float], None] = time.sleep, attempts: int = 3):
        self.container, self._sleep, self._attempts = container_client, sleep, attempts

    def remote_map(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for b in self.container.list_blobs(name_starts_with=UNIFIED_PREFIX, include=["metadata"]):
            out[b.name] = {"size": b.size, "metadata": dict(getattr(b, "metadata", None) or {})}
        return out

    def _upload(self, item: SyncItem) -> Optional[str]:
        client = self.container.get_blob_client(item.blob)
        for attempt in range(self._attempts):
            try:
                if item.marker:
                    client.upload_blob(b"", overwrite=True, metadata=item.metadata)
                else:
                    with open(item.local, "rb") as data:
                        client.upload_blob(data, overwrite=item.kind != "cas", content_settings=_content_settings(item.local),
                                           metadata=item.metadata)
                return None
            except Exception as ex:                                 # noqa: BLE001 — se informa sin datos sensibles
                if attempt == self._attempts - 1:
                    return type(ex).__name__
                self._sleep(1.5 * (attempt + 1))
        return "unknown"

    def sync(self, root, *, dry_run: bool = False, verify_hashes: bool = False) -> Dict[str, Any]:
        plan = build_plan(root, verify_hashes=verify_hashes)
        remote = self.remote_map() if plan.items else {}
        res: Dict[str, Any] = {"planned": len(plan.items), "uploaded": 0, "skipped_exists": 0, "conflicts": [], "errors": [],
                               "dry_run": dry_run, "skipped": plan.skipped, "by_kind": plan.by_kind(), "uploaded_blobs": []}
        for item in plan.items:
            r = remote.get(item.blob)
            if r is not None:
                same_hash = r["metadata"].get("sha256") == item.sha256
                same_size = item.marker or r["size"] == item.size
                if same_hash and same_size:
                    res["skipped_exists"] += 1
                    continue
                if item.kind == "cas":
                    res["conflicts"].append({"blob": item.blob, "reason": "CAS_IMMUTABLE_MISMATCH"})
                    continue
            if dry_run:
                res["uploaded"] += 1
                res["uploaded_blobs"].append(item.blob)
                continue
            err = self._upload(item)
            if err:
                res["errors"].append({"blob": item.blob, "error": err})
            else:
                res["uploaded"] += 1
                res["uploaded_blobs"].append(item.blob)
        return res
