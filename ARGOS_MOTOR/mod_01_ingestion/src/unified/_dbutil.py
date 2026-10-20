"""
Acceso mínimo y común a DuckDB para los módulos operativos de U5C (informes, aprobaciones).

Una conexión por operación con exclusión mutua EN PROCESO por archivo (``db_mutex``) y reintento ante ``IOException``. Las
lecturas son de SOLO LECTURA: no crean el archivo ni las tablas (si faltan, devuelven vacío). Sin garantía multiproceso.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Sequence

from mod_01_ingestion.src.unified.repositories import db_mutex


@contextmanager
def connect(db_path, read_only: bool = False) -> Iterator[Any]:
    import duckdb
    with db_mutex(db_path):
        con, last = None, None
        for _ in range(200):
            try:
                con = duckdb.connect(str(db_path), read_only=read_only)
                break
            except duckdb.IOException as ex:
                last = ex
                time.sleep(0.02)
        if con is None:
            raise last
        try:
            yield con
        finally:
            con.close()


def ensure_schema(db_path, statements: Sequence[str]) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as con:
        for s in statements:
            con.execute(s)


def read_rows(db_path, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    import duckdb
    if not Path(db_path).exists():
        return []
    try:
        with connect(db_path, read_only=True) as con:
            cur = con.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    except duckdb.CatalogException:
        return []
