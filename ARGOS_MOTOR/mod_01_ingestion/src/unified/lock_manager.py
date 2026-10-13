"""
FASE 4 / DEFECT-04 — Locks inter-proceso por clave (document_id / sha256).

Implementación sin dependencias: archivo de lock creado con ``O_CREAT|O_EXCL`` (atómico en
NTFS y POSIX). Un lock más antiguo que ``stale_after_s`` se considera abandonado y se
recupera (no se usa ``os.kill(pid, 0)``: en Windows termina procesos).
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional


class LockTimeout(Exception):
    error_class = "LOCKED"


class LockManager:
    def __init__(self, lock_dir: Path, stale_after_s: float = 3600.0, poll_s: float = 0.05,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.stale_after_s = stale_after_s
        self.poll_s = poll_s
        self._clock = clock
        self._sleep = sleep

    def _path(self, key: str) -> Path:
        return self.lock_dir / (re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:150] + ".lock")

    def _try_create(self, path: Path) -> bool:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            # Windows: crear con O_EXCL un archivo cuyo borrado está pendiente (otro hilo/proceso lo está soltando) da
            # PermissionError, no FileExistsError. Es "ocupado": se reintenta en el siguiente sondeo.
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "acquired_at": self._clock()}, f)
        return True

    def _is_stale(self, path: Path) -> bool:
        try:
            return (self._clock() - path.stat().st_mtime) > self.stale_after_s
        except OSError:
            return False

    @contextmanager
    def acquire(self, key: str, timeout_s: float = 30.0) -> Iterator[Path]:
        path = self._path(key)
        deadline = self._clock() + timeout_s
        while not self._try_create(path):
            if self._is_stale(path):
                try:
                    path.unlink()
                except (FileNotFoundError, PermissionError):
                    pass
                continue
            if self._clock() >= deadline:
                raise LockTimeout(f"Lock ocupado para '{key}' tras {timeout_s}s")
            self._sleep(self.poll_s)
        try:
            yield path
        finally:
            for _ in range(50):          # Windows: otro hilo puede tener el archivo abierto un instante
                try:
                    path.unlink()
                    break
                except FileNotFoundError:
                    break
                except PermissionError:
                    time.sleep(0.01)
