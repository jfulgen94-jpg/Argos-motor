"""
U5D — Exclusión explícita del árbol UNIFICADO para las herramientas legacy (reorganizador, auditores forenses, extractores).

Módulo SOLO con biblioteca estándar: las herramientas legacy lo importan sin arrastrar el núcleo unificado. No cambia su
comportamiento por defecto (sus raíces siguen siendo ``data/raw/...``); solo les permite NO tocar un raíz unificado si un barrido
lo alcanza (porque se les apuntó a un ancestro, o a la propia raíz unificada).

Un raíz unificado se reconoce por el archivo marcador ``.argos_unified_root`` (lo escribe ``UnifiedDataRoot.initialize``) o por
``ARGOS_UNIFIED_ROOT``. Reglas:

* Un barrido de LECTURA que está dentro de un raíz unificado omite ``RESERVED_DIRS`` (cas/, cas_pins/, versions/, catalog/,
  manifests/, ...). ``raw/`` queda visible porque son vistas (enlaces duros) de solo lectura para esos barridos.
* Un barrido de un ancestro que encuentra un raíz unificado lo poda ENTERO.
* Una herramienta que MUEVE o BORRA (el reorganizador con ``--apply``) se niega a operar sobre cualquier ruta dentro de un raíz
  unificado (``assert_not_unified``): un movimiento/borrado o una escritura in situ sobre un enlace duro altera el blob del CAS.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional, Tuple

MARKER = ".argos_unified_root"
ENV_VAR = "ARGOS_UNIFIED_ROOT"
RESERVED_DIRS: Tuple[str, ...] = ("cas", "cas_pins", "versions", "catalog", "manifests", "reports", "staging",
                                  "quarantine_unified", "locks", "telemetry")


class UnifiedTreeViolation(Exception):
    """Una herramienta legacy intentó modificar el árbol unificado."""


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


@lru_cache(maxsize=4096)
def _has_marker(directory: str) -> bool:
    return os.path.isfile(os.path.join(directory, MARKER))


def clear_cache() -> None:
    _has_marker.cache_clear()


def _env_root() -> Optional[str]:
    v = os.environ.get(ENV_VAR)
    return _norm(v) if v else None


def find_unified_root(path) -> Optional[Path]:
    """Raíz unificado que contiene ``path`` (o es ``path``), o ``None``."""
    p = _norm(path)
    env = _env_root()
    if env and (p == env or p.startswith(env.rstrip("\\/") + os.sep)):
        return Path(env)
    cur = p
    while True:
        if _has_marker(cur):
            return Path(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def is_unified_path(path) -> bool:
    return find_unified_root(path) is not None


def is_unified_reserved(path) -> bool:
    """True si ``path`` está dentro de un directorio reservado de un raíz unificado (o es ese raíz)."""
    root = find_unified_root(path)
    if root is None:
        return False
    rel = Path(_norm(path)).relative_to(Path(_norm(root))).parts
    return not rel or rel[0].lower() in RESERVED_DIRS or rel == (MARKER,)


def assert_not_unified(path, *, tool: str = "herramienta legacy") -> None:
    """Para herramientas que mueven/borran/escriben: negarse si ``path`` cae dentro de un raíz unificado."""
    root = find_unified_root(path)
    if root is not None:
        raise UnifiedTreeViolation(f"{tool} no puede operar sobre el árbol unificado: {path} (raíz {root})")


def iter_files(base, *, pattern_suffixes: Optional[Tuple[str, ...]] = None) -> Iterator[Path]:
    """Recorrido legacy seguro: poda raíces unificados descendientes y los directorios reservados del propio raíz."""
    base = Path(base)
    inside = find_unified_root(base)
    inside_n = Path(_norm(inside)) if inside is not None else None
    for cur, dirs, files in os.walk(base):
        keep = []
        for d in sorted(dirs):
            full = os.path.join(cur, d)
            if _has_marker(_norm(full)):                       # raíz unificado descendiente: se poda entero
                continue
            if inside_n is not None:
                rel = Path(_norm(full)).relative_to(inside_n).parts
                if rel and rel[0].lower() in RESERVED_DIRS:
                    continue
            keep.append(d)
        dirs[:] = keep
        if inside_n is not None and Path(_norm(cur)) == inside_n:
            files = []                                         # los archivos de la raíz (marcador, ...) no son datos raw
        for f in sorted(files):
            if pattern_suffixes is None or f.lower().endswith(pattern_suffixes):
                yield Path(cur) / f
