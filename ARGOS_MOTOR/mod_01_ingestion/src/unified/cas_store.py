"""
FASE 4 / DEFECT-07 — Almacén raw direccionable por contenido (CAS) + vista lógica en ``raw/``.

* Blob único por SHA-256: ``cas/<sha[0:2]>/<sha256>``.
* La ruta lógica ``raw/<AUTORIDAD>/<año>/<emisor>/<archivo>`` es un hardlink al blob (copia si el
  FS no soporta enlaces). Documentos idénticos con distinto nombre comparten bloques en disco.
* Inmutabilidad: nunca se sobrescribe un raw existente con contenido distinto (se versiona el
  nombre con ``.<sha8>``). Un raw existente con el mismo hash es idempotente.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.lock_manager import LockManager
from mod_01_ingestion.src.unified.models import PromotionResult


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _link_or_copy(src: Path, dst: Path) -> str:
    try:
        os.link(src, dst)
        return "hardlink"
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)
        return "copy"


class ContentAddressedRawStore:
    def __init__(self, layout: DataLayout, locks: LockManager):
        self.layout = layout
        self.locks = locks

    def blob_path(self, sha256: str) -> Path:
        return self.layout.cas / sha256[:2] / sha256

    def promote(self, staged_path: Path, sha256: str, raw_relpath: Path) -> PromotionResult:
        """Inserta el blob (si no existe) y crea la vista raw. Mantiene ``staged_path`` intacto."""
        staged_path = Path(staged_path)
        blob = self.blob_path(sha256)
        raw_path = self.layout.assert_inside(self.layout.raw / raw_relpath)
        self.layout.assert_inside(blob)
        with self.locks.acquire(f"cas-{sha256}"):
            blob.parent.mkdir(parents=True, exist_ok=True)
            dedup = blob.exists()
            if dedup:
                if blob.stat().st_size != staged_path.stat().st_size:
                    raise IOError(f"Blob CAS {sha256} con tamaño inconsistente")
            else:
                tmp = blob.with_name(blob.name + ".tmp")
                tmp.unlink(missing_ok=True)
                _link_or_copy(staged_path, tmp)
                os.replace(tmp, blob)

            raw_path.parent.mkdir(parents=True, exist_ok=True)
            final_raw = raw_path
            if raw_path.exists():
                if file_sha256(raw_path) == sha256:
                    return PromotionResult(str(raw_path), str(blob), sha256, blob.stat().st_size, dedup, "existing")
                final_raw = raw_path.with_name(f"{raw_path.stem}.{sha256[:8]}{raw_path.suffix}")
                if final_raw.exists():
                    return PromotionResult(str(final_raw), str(blob), sha256, blob.stat().st_size, dedup, "existing")
            mode = _link_or_copy(blob, final_raw)
            return PromotionResult(str(final_raw), str(blob), sha256, blob.stat().st_size, dedup, mode)

    def rollback(self, promo: PromotionResult) -> None:
        """Deshace una promoción (usado si falla manifiesto/catálogo: sin raw huérfano)."""
        raw = Path(promo.raw_path)
        if promo.link_mode != "existing":
            raw.unlink(missing_ok=True)
        if not promo.deduplicated:
            Path(promo.cas_path).unlink(missing_ok=True)

    def verify(self, sha256: str, raw_path: Path) -> bool:
        raw_path = Path(raw_path)
        return raw_path.exists() and file_sha256(raw_path) == sha256
