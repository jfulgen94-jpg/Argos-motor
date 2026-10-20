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
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

from mod_01_ingestion.src.unified.domain.models import validate_sha256
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.lock_manager import LockManager
from mod_01_ingestion.src.unified.models import CasOwnershipReceipt, CasRollbackResult, PromotionResult


_PIN_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class CasPinError(OSError):
    """No se pudo crear la referencia durable (pin) de un blob sin vista raw: la promoción falla CERRADA."""


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

    def pin_path_for(self, sha256: str, pin_key: str) -> Path:
        """Ruta del pin: ``<root>/cas_pins/<sha256>/<pin_key>``, FUERA de ``cas/`` (no altera los recuentos de blobs)."""
        return self.layout.root / "cas_pins" / sha256 / pin_key

    def _create_pin(self, blob: Path, sha256: str, pin_key: str, receipt) -> Tuple[Optional[str], bool]:
        """Crea (o reutiliza) el pin. SOLO se llama con el lock ``cas-{sha256}`` tomado por ``promote``.

        El pin es un enlace duro del blob: la referencia nace en la MISMA sección crítica que la decisión de deduplicar,
        de modo que ``rollback_owned`` (que cuenta enlaces bajo el mismo lock) la ve siempre. Devuelve
        ``(pin_path, pin_created)``. Conservador:
          · blob nuevo creado en modo copia (sin enlaces duros): sin pin; ``rollback_owned`` nunca lo borra (sin prueba);
          · cualquier otro fallo de enlace: se falla CERRADO (``CasPinError``); si el blob lo creó este intento se retira
            antes de soltar el lock, para no dejar una promoción sin protección que luego alguien pueda borrar."""
        if receipt is not None and receipt.blob_link_mode != "hardlink":
            return None, False
        pin = self.pin_path_for(sha256, pin_key)
        try:
            self.layout.assert_inside(pin)
            pin.parent.mkdir(parents=True, exist_ok=True)
            if pin.exists():
                if os.path.samestat(pin.stat(), blob.stat()):
                    return str(pin), False                 # reutiliza el pin de esta identidad: no acumula enlaces
                pin.unlink()                               # pin caduco: apunta a un inodo anterior del blob
            os.link(blob, pin)
            return str(pin), True
        except (OSError, NotImplementedError, ValueError) as ex:
            try:
                pin.parent.rmdir()                         # no dejar un directorio de pines vacío (solo si está vacío)
            except OSError:
                pass
            if receipt is not None:
                blob.unlink(missing_ok=True)               # blob propio sin protección: se retira (seguimos bajo el lock)
            raise CasPinError(f"no se pudo crear el pin del blob {sha256[:12]}: {type(ex).__name__}") from ex

    def promote(self, staged_path: Path, sha256: str, raw_relpath: Optional[Path],
                create_view: bool = True, pin_key: Optional[str] = None) -> PromotionResult:
        """Inserta el blob (si no existe) y crea la vista raw. Mantiene ``staged_path`` intacto.

        U5B: con ``create_view=False`` solo se conserva el blob (p. ej. versiones UNCONFIRMED que no deben aparecer en
        ``raw/``). El resultado lo declara explícitamente: ``link_mode == "none"`` y ``raw_path is None``.
        U5B.1: sin vista, ``pin_key`` (hash estable de la identidad) es OBLIGATORIO: se crea un pin bajo el lock del hash."""
        validate_sha256(sha256, "sha256", required=True)      # U2: sin hash válido no se toca el filesystem
        staged_path = Path(staged_path)
        blob = self.blob_path(sha256)
        raw_path = None
        if not create_view and not (pin_key and _PIN_KEY_RE.match(pin_key)):
            raise ValueError("create_view=False exige un pin_key válido (referencia durable del blob)")
        if create_view:
            if raw_relpath is None:
                raise ValueError("create_view=True exige raw_relpath")
            raw_path = self.layout.assert_inside(self.layout.raw / raw_relpath)
        self.layout.assert_inside(blob)
        with self.locks.acquire(f"cas-{sha256}"):
            blob.parent.mkdir(parents=True, exist_ok=True)
            dedup = blob.exists()
            receipt = None
            if dedup:
                if blob.stat().st_size != staged_path.stat().st_size:
                    raise IOError(f"Blob CAS {sha256} con tamaño inconsistente")
            else:
                tmp = blob.with_name(blob.name + ".tmp")
                tmp.unlink(missing_ok=True)
                blob_mode = _link_or_copy(staged_path, tmp)
                os.replace(tmp, blob)
                st = blob.stat()      # U4: recibo de propiedad (este intento creó físicamente el blob, bajo el lock)
                receipt = CasOwnershipReceipt(created_blob=True, blob_dev=st.st_dev, blob_ino=st.st_ino,
                                              blob_size=st.st_size, blob_mtime_ns=st.st_mtime_ns,
                                              staged_path=str(staged_path), blob_link_mode=blob_mode)

            if not create_view:
                pin_path, pin_created = self._create_pin(blob, sha256, pin_key, receipt)
                return PromotionResult(None, str(blob), sha256, blob.stat().st_size, dedup, "none", receipt,
                                       pin_path=pin_path, pin_created=pin_created)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            final_raw = raw_path
            if raw_path.exists():
                if file_sha256(raw_path) == sha256:
                    return PromotionResult(str(raw_path), str(blob), sha256, blob.stat().st_size, dedup, "existing", receipt)
                final_raw = raw_path.with_name(f"{raw_path.stem}.{sha256[:8]}{raw_path.suffix}")
                if final_raw.exists():
                    return PromotionResult(str(final_raw), str(blob), sha256, blob.stat().st_size, dedup, "existing", receipt)
            mode = _link_or_copy(blob, final_raw)
            return PromotionResult(str(final_raw), str(blob), sha256, blob.stat().st_size, dedup, mode, receipt)

    def rollback(self, promo: PromotionResult) -> None:
        """Deshace una promoción (usado si falla manifiesto/catálogo: sin raw huérfano)."""
        raw = Path(promo.raw_path) if promo.raw_path else None
        if raw is not None and promo.link_mode != "existing":
            raw.unlink(missing_ok=True)
        if not promo.deduplicated:
            Path(promo.cas_path).unlink(missing_ok=True)

    def rollback_owned(self, promo: PromotionResult, keep_blob: bool = False) -> CasRollbackResult:
        """Reversión SEGURA (U4). Solo borra lo que este intento creó y puede demostrarlo:

        * vista raw: solo si ``link_mode`` es hardlink/copy (la creó este intento) y su contenido/inodo es el esperado;
        * blob: solo con recibo de propiedad (``created_blob``) cuya identidad (dev, ino, tamaño, mtime) sigue intacta,
          con enlace duro (``link_mode == "hardlink"``) y sin NINGUNA otra referencia (``st_nlink`` == 1 + el enlace del
          fichero staged, si sigue ligado). Todo bajo el lock del hash (``promote`` usa el mismo).
        En cualquier otro caso el blob NO se borra: ``PREEXISTING_LEFT`` / ``SHARED_LEFT`` (no es huérfano) o
        ``UNPROVEN_ORPHAN`` (creado por este intento pero sin prueba de exclusividad: requiere reconciliación manual).
        No lanza por el estado del filesystem: lo describe en el resultado."""
        sha = promo.sha256
        raw = Path(promo.raw_path) if promo.raw_path else None      # U5B: None = promoción sin vista (nunca Path(""))
        blob = Path(promo.cas_path)
        rel = None
        try:
            rel = blob.relative_to(self.layout.root).as_posix()
        except ValueError:
            rel = None
        with self.locks.acquire(f"cas-{sha}"):
            # ---- vista raw
            if raw is None or promo.link_mode == "none":
                raw_state = "NO_VIEW"                    # U5B: este intento no creó vista raw
            elif promo.link_mode == "existing" or not promo.link_mode:
                raw_state = "EXISTING_LEFT"
            elif not raw.exists():
                raw_state = "ABSENT"
            else:
                ours = False
                try:
                    if promo.link_mode == "hardlink":
                        ours = blob.exists() and os.path.samestat(raw.stat(), blob.stat())
                    else:
                        ours = file_sha256(raw) == sha
                except OSError:
                    ours = False
                if ours:
                    raw.unlink()
                    raw_state = "REMOVED"
                else:
                    raw_state = "UNPROVEN_LEFT"
            # ---- pin propio (U5B.1): se retira ANTES de reevaluar nlink, igual que la vista propia. Solo si lo creó este
            # intento y sigue siendo el mismo inodo del blob; un pin ajeno o dudoso no se toca y bloquea el borrado.
            pin_unproven = False
            if promo.pin_path and promo.pin_created:
                pin = Path(promo.pin_path)
                try:
                    if pin.exists():
                        if blob.exists() and os.path.samestat(pin.stat(), blob.stat()):
                            pin.unlink()
                            try:
                                pin.parent.rmdir()          # solo si queda vacío (no hay otros pines de este hash)
                            except OSError:
                                pass
                        else:
                            pin_unproven = True
                except OSError:
                    pin_unproven = True
            # ---- blob
            r = promo.receipt
            if not blob.exists():
                blob_state = "REMOVED" if (r is not None and r.created_blob) else "PREEXISTING_LEFT"
            elif promo.deduplicated and r is None:
                blob_state = "PREEXISTING_LEFT"          # ya existía antes de este intento: no es nuestro
            elif r is None or not r.created_blob:
                blob_state = "UNPROVEN_ORPHAN"
            else:
                st = blob.stat()
                same = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) == (r.blob_dev, r.blob_ino, r.blob_size,
                                                                              r.blob_mtime_ns)
                # con vista: el modo de la vista prueba el enlace duro (comportamiento U4). Sin vista: el modo con el que se
                # creó el blob (recibo). En modo copia no hay prueba de exclusividad => nunca se borra.
                link_ok = (promo.link_mode == "hardlink") if raw is not None else (r.blob_link_mode == "hardlink")
                if not same or not link_ok or pin_unproven:
                    blob_state = "UNPROVEN_ORPHAN"
                else:
                    staged = Path(r.staged_path)
                    staged_linked = staged.exists() and os.path.samestat(staged.stat(), st)
                    expected = 1 + (1 if staged_linked else 0)
                    if st.st_nlink == expected and keep_blob:
                        # U5B: otra identidad registra este hash SIN vista raw (no añade enlaces): el recuento no la ve.
                        blob_state = "SHARED_LEFT"
                    elif st.st_nlink == expected:
                        blob.unlink()
                        blob_state = "REMOVED"
                    elif st.st_nlink > expected:
                        blob_state = "SHARED_LEFT"
                    else:
                        blob_state = "UNPROVEN_ORPHAN"
            orphan = blob_state == "UNPROVEN_ORPHAN" or raw_state == "UNPROVEN_LEFT"
            return CasRollbackResult(blob_state=blob_state, raw_view_state=raw_state,
                                     orphaned_sha256=sha if orphan else None, orphaned_path=rel if orphan else None)

    def verify(self, sha256: str, raw_path: Path) -> bool:
        raw_path = Path(raw_path)
        return raw_path.exists() and file_sha256(raw_path) == sha256
