"""
U5B — Persistencia ADITIVA de versiones de contenido, eventos de estado y observaciones (DuckDB + sidecar JSON).

* Tablas nuevas (``CREATE TABLE IF NOT EXISTS``, creadas de forma PEREZOSA en la primera escritura; leer nunca crea nada):
  ``unified_document_versions`` PK (identity_key, sha256) · ``unified_document_version_events`` PK
  (identity_key, sha256, event_seq) · ``unified_document_observations`` PK (run_id, job_id).
  ``unified_catalog`` y los manifiestos legacy NO se tocan.
* Idempotencia: ``INSERT ... ON CONFLICT DO NOTHING`` NO es la comprobación: tras un conflicto se RELEE la fila y se comparan
  todos los hechos (``DocumentVersion.FACT_FIELDS``). Iguales => idempotente; distintos => ``CONFLICT`` (nada se sobrescribe).
  Un ``ConstraintException`` por carrera se trata igual: releer y comparar.
* Estado: ``CURRENT`` como máximo uno por ``identity_key`` (invariante comprobada dentro de la transacción). El estado vigente de
  una versión es su último evento (append-only); ``UNCONFIRMED`` nunca reemplaza a ``CURRENT``.
* Sidecar JSON por versión (``<versions>/<hash(identity_key)>/<sha256>.json``, ``.pending`` + ``os.replace``): evidencia
  recuperable y auditable que no depende de la DuckDB. Si tabla y sidecar discrepan => estado explícito, sin reparar solos.
* NO hay atomicidad distribuida entre CAS, sidecar, tabla, manifiesto y catálogo: se ordena (sidecar pendiente -> tabla ->
  confirmar sidecar), se compensa lo propio y, si la compensación falla, se devuelve ``RECOVERY_REQUIRED``.
* Toda escritura requiere que el LLAMADOR tenga el lock de identidad (ver ``IngestRunner._lock_names``). DuckDB admite un único
  escritor; el patrón probado es una conexión por operación con reintento ante ``IOException``. No se afirma garantía
  multiproceso más allá de ese patrón.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import sanitize_message
from mod_01_ingestion.src.unified.domain.models import utc_now
from mod_01_ingestion.src.unified.domain.versions import (
    DocumentVersion, Observation, VersionStatus, diff_facts)
from mod_01_ingestion.src.unified.persistence_guard import assert_persistable

DDL = (
    """CREATE TABLE IF NOT EXISTS unified_document_versions (
        identity_key VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, identity_kind VARCHAR NOT NULL,
        authority VARCHAR NOT NULL, document_id VARCHAR NOT NULL, size_bytes BIGINT, normalizer_version VARCHAR NOT NULL,
        version_ref VARCHAR, revision INTEGER, contract_id VARCHAR, contract_version VARCHAR,
        source_document_id_raw VARCHAR, evidence_json VARCHAR,
        first_observed_at VARCHAR, run_id VARCHAR, job_id VARCHAR,
        PRIMARY KEY (identity_key, sha256))""",
    """CREATE TABLE IF NOT EXISTS unified_document_version_events (
        identity_key VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, event_seq INTEGER NOT NULL, status VARCHAR NOT NULL,
        evidence_json VARCHAR, recorded_at VARCHAR, run_id VARCHAR, job_id VARCHAR,
        PRIMARY KEY (identity_key, sha256, event_seq))""",
    """CREATE TABLE IF NOT EXISTS unified_document_observations (
        run_id VARCHAR NOT NULL, job_id VARCHAR NOT NULL, identity_key VARCHAR NOT NULL, sha256 VARCHAR,
        expected_sha256 VARCHAR, preflight_status VARCHAR NOT NULL, observed_at VARCHAR,
        PRIMARY KEY (run_id, job_id))""",
    "CREATE INDEX IF NOT EXISTS ix_udv_sha256 ON unified_document_versions(sha256)",
    "CREATE INDEX IF NOT EXISTS ix_udv_identity ON unified_document_versions(identity_key)",
)
_VERSION_COLS = ("identity_key", "sha256", "identity_kind", "authority", "document_id", "size_bytes", "normalizer_version",
                 "version_ref", "revision", "contract_id", "contract_version", "source_document_id_raw", "evidence_json",
                 "first_observed_at", "run_id", "job_id")
_STATUS_SQL = ("(SELECT e.status FROM unified_document_version_events e WHERE e.identity_key = v.identity_key "
               "AND e.sha256 = v.sha256 ORDER BY e.event_seq DESC LIMIT 1)")


@dataclass
class RegisterResult:
    outcome: str                       # CREATED | IDEMPOTENT | CONFLICT | FAILED | RECOVERY_REQUIRED
    identity_key: str
    sha256: str
    status: Optional[str] = None       # estado resultante de la versión
    superseded_sha256: Optional[str] = None
    differences: Tuple[str, ...] = ()
    message: str = ""
    compensation_errors: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome in ("CREATED", "IDEMPOTENT")

    @property
    def needs_manual_review(self) -> bool:
        return self.outcome in ("RECOVERY_REQUIRED", "CONFLICT")


class _Dup(Exception):
    """Carrera de clave (ConstraintException): hay que releer y comparar."""


def sidecar_dir_name(identity_key: str) -> str:
    return hashlib.sha256(identity_key.encode("utf-8")).hexdigest()[:32]


class VersionRepository:
    def __init__(self, db_path: Path, sidecar_root: Path, mode: ExecutionMode, authorized_sandbox_roots=()):
        self.db_path = Path(db_path)
        self.sidecar_root = Path(sidecar_root)
        self.mode = ExecutionMode(mode)
        self.authorized_sandbox_roots = tuple(authorized_sandbox_roots)
        self._schema_ready = False

    # ------------------------------------------------------------------ conexión
    @contextmanager
    def _connect(self, read_only: bool = False) -> Iterator[Any]:
        import duckdb
        last = None
        con = None
        for _ in range(200):          # un único escritor DuckDB: reintento corto ante IOException (patrón de CatalogRepository)
            try:
                con = duckdb.connect(str(self.db_path), read_only=read_only)
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

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            for stmt in DDL:
                con.execute(stmt)
        self._schema_ready = True

    def _read(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        """Lectura de SOLO LECTURA: no crea el archivo ni las tablas; sin tablas => vacío."""
        import duckdb
        if not self.db_path.exists():
            return []
        try:
            with self._connect(read_only=True) as con:
                cur = con.execute(sql, list(params))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        except duckdb.CatalogException:
            return []

    # ------------------------------------------------------------------ sidecar
    def sidecar_path(self, identity_key: str, sha256: str) -> Path:
        return self.sidecar_root / sidecar_dir_name(identity_key) / f"{sha256}.json"

    def read_sidecar(self, identity_key: str, sha256: str) -> Optional[Dict[str, Any]]:
        p = self.sidecar_path(identity_key, sha256)
        if not p.exists():
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def _stage_sidecar(self, fact: DocumentVersion, status: str, cas_path: str) -> Path:
        final = self.sidecar_path(fact.identity_key, fact.sha256)
        final.parent.mkdir(parents=True, exist_ok=True)
        pending = final.with_name(final.name + ".pending")
        payload = {"sidecar_version": "1", "facts": fact.facts(), "initial_status": status, "cas_path": cas_path,
                   "recorded_at": fact.first_observed_at or utc_now(), "run_id": fact.run_id, "job_id": fact.job_id}
        with open(pending, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        return pending

    # ------------------------------------------------------------------ lecturas
    def list_versions(self, identity_key: str) -> List[Dict[str, Any]]:
        """Versiones de una identidad con estado derivado y banderas de consistencia tabla/sidecar. Solo lectura."""
        rows = self._read(f"SELECT v.*, {_STATUS_SQL} AS status FROM unified_document_versions v "
                          "WHERE v.identity_key = ? ORDER BY v.first_observed_at, v.sha256", [identity_key])
        seen = set()
        for r in rows:
            side = self.read_sidecar(identity_key, r["sha256"])
            r["table_present"], r["sidecar_present"] = True, side is not None
            r["facts_match"] = side is None or not diff_facts(r, side.get("facts", {}))
            seen.add(r["sha256"])
        d = self.sidecar_root / sidecar_dir_name(identity_key)
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                if p.stem in seen:
                    continue
                side = json.loads(p.read_text(encoding="utf-8"))
                row = dict(side.get("facts", {}))
                row.update(status=None, table_present=False, sidecar_present=True, facts_match=True,
                           sha256=p.stem, identity_key=identity_key)
                rows.append(row)
        return rows

    def list_versions_by_sha256(self, sha256: str) -> List[Dict[str, Any]]:
        rows = self._read(f"SELECT v.*, {_STATUS_SQL} AS status FROM unified_document_versions v "
                          "WHERE v.sha256 = ? ORDER BY v.identity_key", [str(sha256).lower()])
        for r in rows:
            side = self.read_sidecar(r["identity_key"], r["sha256"])
            r["table_present"], r["sidecar_present"] = True, side is not None
            r["facts_match"] = side is None or not diff_facts(r, side.get("facts", {}))
        return rows

    def current_version(self, identity_key: str) -> Optional[Dict[str, Any]]:
        cur = [r for r in self.list_versions(identity_key) if r.get("status") == VersionStatus.CURRENT.value]
        return cur[0] if cur else None

    def get_observation(self, run_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        rows = self._read("SELECT * FROM unified_document_observations WHERE run_id = ? AND job_id = ?", [run_id, job_id])
        return rows[0] if rows else None

    # ------------------------------------------------------------------ escritura
    def register_version(self, fact: DocumentVersion, status: VersionStatus, *, cas_path: str,
                         supersede_current: bool = False, evidence_json: Optional[str] = None) -> RegisterResult:
        """Registra una versión (hechos + evento inicial) con relectura y comparación. Requiere el lock de identidad."""
        status = VersionStatus(status)
        ik, sha = fact.identity_key, fact.sha256
        try:
            assert_persistable({"document_id": fact.document_id, "sha256": sha, "status": status.value},
                               self.mode, self.sidecar_root, authorized_sandbox_roots=self.authorized_sandbox_roots)
            self.ensure_schema()
            pending = self._stage_sidecar(fact, status.value, cas_path)
        except Exception as ex:
            return RegisterResult("FAILED", ik, sha, message=sanitize_message(f"{type(ex).__name__}: {ex}"))

        res: Optional[RegisterResult] = None
        added_events: List[Tuple[str, str, int]] = []
        inserted = False
        for _attempt in range(3):
            try:
                res, inserted, added_events = self._txn_register(fact, status, supersede_current, evidence_json)
                break
            except _Dup:
                continue                                   # carrera: releer y comparar en el siguiente intento
            except Exception as ex:
                pending.unlink(missing_ok=True)
                return RegisterResult("FAILED", ik, sha, message=sanitize_message(f"{type(ex).__name__}: {ex}"))
        if res is None:
            pending.unlink(missing_ok=True)
            return RegisterResult("FAILED", ik, sha, message="conflicto de clave persistente tras reintentos")

        final = self.sidecar_path(ik, sha)
        if res.outcome in ("CONFLICT", "FAILED"):          # nada se escribió en la tabla: no se confirma ningún sidecar
            pending.unlink(missing_ok=True)
            return res
        if res.outcome == "IDEMPOTENT":
            pending.unlink(missing_ok=True)
            side = self.read_sidecar(ik, sha)
            if side is None:
                return RegisterResult("RECOVERY_REQUIRED", ik, sha, status=res.status,
                                      message="la versión existe en la tabla pero falta su sidecar; no se repara solo")
            d = diff_facts(fact.facts(), side.get("facts", {}))
            if d:
                return RegisterResult("CONFLICT", ik, sha, status=res.status, differences=d,
                                      message="el sidecar existente contradice los hechos de la versión")
            return res
        # CREATED: confirmar el sidecar (último paso); si falla, compensar lo propio
        try:
            os.replace(pending, final)
        except Exception as ex:
            errs = self._compensate(ik, sha, inserted, added_events)
            pending.unlink(missing_ok=True)
            msg = sanitize_message(f"no se pudo confirmar el sidecar: {type(ex).__name__}: {ex}")
            if errs:
                return RegisterResult("RECOVERY_REQUIRED", ik, sha, message=msg, compensation_errors=tuple(errs))
            return RegisterResult("FAILED", ik, sha, message=msg)
        return res

    def _txn_register(self, fact: DocumentVersion, status: VersionStatus, supersede: bool,
                      evidence_json: Optional[str]) -> Tuple[RegisterResult, bool, List[Tuple[str, str, int]]]:
        import duckdb
        ik, sha = fact.identity_key, fact.sha256
        row = fact.to_row()
        row["first_observed_at"] = row["first_observed_at"] or utc_now()
        cols = ", ".join(_VERSION_COLS)
        marks = ", ".join("?" for _ in _VERSION_COLS)
        with self._connect() as con:
            con.execute("BEGIN")
            try:
                n = con.execute(f"INSERT INTO unified_document_versions ({cols}) VALUES ({marks}) ON CONFLICT DO NOTHING",
                                [row[c] for c in _VERSION_COLS]).fetchall()[0][0]
                if n == 0:                                  # existía: RELEER y comparar TODOS los hechos
                    cur = con.execute("SELECT * FROM unified_document_versions WHERE identity_key = ? AND sha256 = ?",
                                      [ik, sha])
                    names = [d[0] for d in cur.description]
                    existing = dict(zip(names, cur.fetchone()))
                    diffs = diff_facts(fact.facts(), existing)
                    st = con.execute("SELECT status FROM unified_document_version_events WHERE identity_key = ? AND "
                                     "sha256 = ? ORDER BY event_seq DESC LIMIT 1", [ik, sha]).fetchone()
                    con.execute("ROLLBACK")
                    if diffs:
                        return RegisterResult("CONFLICT", ik, sha, status=st[0] if st else None, differences=diffs,
                                              message="misma clave (identity_key, sha256) con hechos contradictorios"), False, []
                    return RegisterResult("IDEMPOTENT", ik, sha, status=st[0] if st else None), False, []
                added: List[Tuple[str, str, int]] = []
                others = con.execute(
                    f"SELECT v.sha256 FROM unified_document_versions v WHERE v.identity_key = ? AND v.sha256 <> ? "
                    f"AND {_STATUS_SQL} = 'CURRENT'", [ik, sha]).fetchall()
                superseded = None
                if status is VersionStatus.CURRENT and others and not supersede:
                    con.execute("ROLLBACK")
                    return RegisterResult("FAILED", ik, sha, message="invariante: ya existe una versión CURRENT"), False, []
                con.execute("INSERT INTO unified_document_version_events (identity_key, sha256, event_seq, status, "
                            "evidence_json, recorded_at, run_id, job_id) VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
                            [ik, sha, status.value, evidence_json, utc_now(), fact.run_id, fact.job_id])
                added.append((ik, sha, 1))
                if status is VersionStatus.CURRENT and supersede:
                    for (osha,) in others:
                        seq = con.execute("SELECT coalesce(max(event_seq), 0) + 1 FROM unified_document_version_events "
                                          "WHERE identity_key = ? AND sha256 = ?", [ik, osha]).fetchone()[0]
                        con.execute("INSERT INTO unified_document_version_events (identity_key, sha256, event_seq, status, "
                                    "evidence_json, recorded_at, run_id, job_id) VALUES (?, ?, ?, 'SUPERSEDED', ?, ?, ?, ?)",
                                    [ik, osha, seq, evidence_json, utc_now(), fact.run_id, fact.job_id])
                        added.append((ik, osha, seq))
                        superseded = osha
                con.execute("COMMIT")
                return RegisterResult("CREATED", ik, sha, status=status.value, superseded_sha256=superseded), True, added
            except duckdb.ConstraintException:
                self._safe_rollback(con)
                raise _Dup()
            except BaseException:
                self._safe_rollback(con)
                raise

    @staticmethod
    def _safe_rollback(con) -> None:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass

    def _compensate(self, ik: str, sha: str, inserted: bool, added: List[Tuple[str, str, int]]) -> List[str]:
        """Deshace en la tabla SOLO lo insertado por este intento. Devuelve los errores (vacío = completa)."""
        errs: List[str] = []
        try:
            with self._connect() as con:
                con.execute("BEGIN")
                try:
                    for (k, s, seq) in added:
                        con.execute("DELETE FROM unified_document_version_events WHERE identity_key = ? AND sha256 = ? "
                                    "AND event_seq = ?", [k, s, seq])
                    if inserted:
                        con.execute("DELETE FROM unified_document_versions WHERE identity_key = ? AND sha256 = ?", [ik, sha])
                    con.execute("COMMIT")
                except BaseException:
                    self._safe_rollback(con)
                    raise
        except Exception as ex:
            errs.append(sanitize_message(f"compensación de versiones: {type(ex).__name__}: {ex}"))
        return errs

    def compensate_registration(self, result: RegisterResult, fact: DocumentVersion) -> List[str]:
        """Revierte un registro ya CONFIRMADO (lo usa el runner si falla un paso posterior). Idempotente."""
        errs = self._compensate(fact.identity_key, fact.sha256, True,
                                self._events_of(fact.identity_key, fact.sha256, result))
        try:
            self.sidecar_path(fact.identity_key, fact.sha256).unlink(missing_ok=True)
        except Exception as ex:
            errs.append(sanitize_message(f"sidecar: {type(ex).__name__}: {ex}"))
        return errs

    def _events_of(self, ik: str, sha: str, result: RegisterResult) -> List[Tuple[str, str, int]]:
        ev = [(ik, sha, 1)]
        if result.superseded_sha256:
            rows = self._read("SELECT max(event_seq) AS m FROM unified_document_version_events "
                              "WHERE identity_key = ? AND sha256 = ?", [ik, result.superseded_sha256])
            if rows and rows[0]["m"] is not None:
                ev.append((ik, result.superseded_sha256, int(rows[0]["m"])))
        return ev

    def record_observation(self, obs: Observation) -> RegisterResult:
        """Observación append-only, idempotente por (run_id, job_id); relee y compara si ya existía."""
        import duckdb
        try:
            if obs.sha256:        # la barrera de persistencia exige un SHA-256 real cuando hay contenido
                assert_persistable({"document_id": obs.identity_key, "sha256": obs.sha256, "status": "OBSERVED"},
                                   self.mode, self.sidecar_root, authorized_sandbox_roots=self.authorized_sandbox_roots)
            self.ensure_schema()
            for _ in range(3):
                try:
                    with self._connect() as con:
                        n = con.execute(
                            "INSERT INTO unified_document_observations (run_id, job_id, identity_key, sha256, expected_sha256, "
                            "preflight_status, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                            [obs.run_id, obs.job_id, obs.identity_key, obs.sha256, obs.expected_sha256, obs.preflight_status,
                             obs.observed_at or utc_now()]).fetchall()[0][0]
                    if n == 1:
                        return RegisterResult("CREATED", obs.identity_key, obs.sha256 or "")
                    ex = self.get_observation(obs.run_id, obs.job_id) or {}
                    d = tuple(k for k in Observation.FACT_FIELDS if ex.get(k) != obs.facts().get(k))
                    if d:
                        return RegisterResult("CONFLICT", obs.identity_key, obs.sha256 or "", differences=d,
                                              message="observación (run_id, job_id) con hechos contradictorios")
                    return RegisterResult("IDEMPOTENT", obs.identity_key, obs.sha256 or "")
                except duckdb.ConstraintException:
                    continue
            return RegisterResult("FAILED", obs.identity_key, obs.sha256 or "", message="conflicto persistente")
        except Exception as ex:
            return RegisterResult("FAILED", obs.identity_key, obs.sha256 or "",
                                  message=sanitize_message(f"{type(ex).__name__}: {ex}"))
