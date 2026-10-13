"""
Coverage Ledger — universo ESPERADO frente a lo ENCONTRADO, por (país, autoridad, emisor, ejercicio, tipo documental).

* Tablas ADITIVAS en la base del catálogo, creadas de forma perezosa en la primera escritura (leer nunca crea nada):
  ``unified_coverage_ledger`` (estado vigente, PK = clave de cobertura) y ``unified_coverage_events`` (auditoría append-only).
* Estados: FOUND · VALIDATED · PROMOTED · NOT_PUBLISHED · SOURCE_UNAVAILABLE · NEEDS_REVIEW · CONFLICT · UNKNOWN
  (el vocabulario ``CoverageStatus`` de U1 era solo texto y no se usa).
* Reglas de transición (``resolve_transition``): una caída temporal de la fuente NUNCA borra un PROMOTED; FOUND/VALIDATED no
  retroceden un estado más avanzado; un CONFLICT solo se resuelve de forma explícita; NOT_PUBLISHED exige EVIDENCIA y fecha de
  comprobación, y si contradice un PROMOTED produce CONFLICT. Registrar lo mismo dos veces no duplica filas ni eventos.
* El ledger NO decide por sí mismo qué es válido: refleja los resultados del pipeline (``status_from_outcome``) y se
  contrasta con catálogo y reconciliador (``cross_check_ledger``). Sin red, sin disco fuera de la base indicada.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from mod_01_ingestion.src.unified.adapters.common import sanitize_source_url
from mod_01_ingestion.src.unified.domain.enums import ExecutionMode
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.domain.models import utc_now
from mod_01_ingestion.src.unified.repositories import db_mutex


class LedgerStatus(str, Enum):
    FOUND = "FOUND"
    VALIDATED = "VALIDATED"
    PROMOTED = "PROMOTED"
    NOT_PUBLISHED = "NOT_PUBLISHED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    CONFLICT = "CONFLICT"
    UNKNOWN = "UNKNOWN"


class LedgerError(DomainValidationError):
    pass


@dataclass(frozen=True)
class CoverageKey:
    country_code: str
    authority: str
    issuer_id: str
    fiscal_year: int
    doc_type: str

    def __post_init__(self):
        for name in ("country_code", "authority", "issuer_id", "doc_type"):
            if not str(getattr(self, name) or "").strip():
                raise LedgerError(f"clave de cobertura: {name} obligatorio")
        if isinstance(self.fiscal_year, bool) or not isinstance(self.fiscal_year, int) or not 1990 <= self.fiscal_year <= 2100:
            raise LedgerError("clave de cobertura: fiscal_year debe ser un entero 1990-2100")
        object.__setattr__(self, "country_code", str(self.country_code).strip().upper())
        object.__setattr__(self, "authority", str(self.authority).strip().upper())
        object.__setattr__(self, "issuer_id", str(self.issuer_id).strip())
        object.__setattr__(self, "doc_type", str(self.doc_type).strip().upper())

    def as_tuple(self) -> Tuple[str, str, str, int, str]:
        return (self.country_code, self.authority, self.issuer_id, self.fiscal_year, self.doc_type)

    @classmethod
    def from_candidate(cls, c) -> "CoverageKey":
        return cls(c.country_code, c.authority, c.issuer_id, c.fiscal_year, c.doc_type)


_RANK = {LedgerStatus.UNKNOWN: 0, LedgerStatus.FOUND: 1, LedgerStatus.VALIDATED: 2, LedgerStatus.PROMOTED: 3}


def resolve_transition(current: Optional[LedgerStatus], new: LedgerStatus, *, resolve_conflict: bool = False
                       ) -> Tuple[LedgerStatus, bool, str]:
    """``(estado resultante, aplicado, motivo)``. Pura y determinista."""
    L = LedgerStatus
    if current is None or current is L.UNKNOWN:
        return new, True, ""
    if current is L.PROMOTED:
        if new in (L.PROMOTED, L.CONFLICT, L.NEEDS_REVIEW):
            return new, True, ""
        if new is L.NOT_PUBLISHED:
            return L.CONFLICT, True, "NOT_PUBLISHED_CONTRADICTS_PROMOTED"
        return current, False, f"{new.value}_DOES_NOT_ERASE_PROMOTED"
    if current is L.CONFLICT:
        if new is L.CONFLICT or (new in (L.PROMOTED, L.NOT_PUBLISHED, L.NEEDS_REVIEW) and resolve_conflict):
            return new, True, "CONFLICT_RESOLVED" if new is not L.CONFLICT else ""
        return current, False, "CONFLICT_IS_STICKY_UNTIL_EXPLICITLY_RESOLVED"
    if current is L.NEEDS_REVIEW:
        if new in (L.PROMOTED, L.CONFLICT, L.NOT_PUBLISHED, L.NEEDS_REVIEW):
            return new, True, ""
        return current, False, f"{new.value}_DOES_NOT_CLEAR_REVIEW"
    if current is L.NOT_PUBLISHED:
        if new in (L.FOUND, L.VALIDATED, L.PROMOTED, L.CONFLICT, L.NEEDS_REVIEW, L.NOT_PUBLISHED):
            return new, True, "APPEARED_AFTER_NOT_PUBLISHED" if new in (L.FOUND, L.VALIDATED, L.PROMOTED) else ""
        return current, False, f"{new.value}_DOES_NOT_ERASE_NOT_PUBLISHED"
    if current is L.SOURCE_UNAVAILABLE:
        return new, True, ""
    # FOUND / VALIDATED: no retroceden
    if new in _RANK and _RANK[new] < _RANK[current]:
        return current, False, f"{new.value}_DOES_NOT_REGRESS_{current.value}"
    return new, True, ""


@dataclass(frozen=True)
class LedgerRecord:
    key: CoverageKey
    expected: bool
    status: LedgerStatus
    document_id: Optional[str] = None
    sha256: Optional[str] = None
    identity_key: Optional[str] = None
    version_status: Optional[str] = None
    reason: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    last_checked_at: Optional[str] = None
    updated_at: Optional[str] = None
    run_id: Optional[str] = None
    job_id: Optional[str] = None


@dataclass(frozen=True)
class RecordResult:
    key: CoverageKey
    status: LedgerStatus            # estado vigente tras la llamada
    applied: bool
    reason: str = ""
    changed: bool = False           # False => idempotente (nada nuevo que registrar)


@dataclass(frozen=True)
class CoverageSummary:
    expected: int
    by_status: Dict[str, int]
    promoted: int
    not_published: int
    unexpected_found: int
    coverage_ratio: Optional[float]      # PROMOTED / (esperados - NOT_PUBLISHED con evidencia)
    accounted_ratio: Optional[float]     # (PROMOTED + NOT_PUBLISHED) / esperados
    open_keys: int                       # esperados sin PROMOTED ni NOT_PUBLISHED

    def to_dict(self) -> Dict[str, Any]:
        return {"expected": self.expected, "by_status": dict(self.by_status), "promoted": self.promoted,
                "not_published": self.not_published, "unexpected_found": self.unexpected_found,
                "coverage_ratio": self.coverage_ratio, "accounted_ratio": self.accounted_ratio, "open_keys": self.open_keys}


_KEYCOLS = ("country_code", "authority", "issuer_id", "fiscal_year", "doc_type")
DDL = (
    """CREATE TABLE IF NOT EXISTS unified_coverage_ledger (
        country_code VARCHAR NOT NULL, authority VARCHAR NOT NULL, issuer_id VARCHAR NOT NULL, fiscal_year INTEGER NOT NULL,
        doc_type VARCHAR NOT NULL, expected BOOLEAN NOT NULL, status VARCHAR NOT NULL, document_id VARCHAR, sha256 VARCHAR,
        identity_key VARCHAR, version_status VARCHAR, reason VARCHAR, evidence_json VARCHAR, last_checked_at VARCHAR,
        updated_at VARCHAR NOT NULL, run_id VARCHAR, job_id VARCHAR,
        PRIMARY KEY (country_code, authority, issuer_id, fiscal_year, doc_type))""",
    """CREATE TABLE IF NOT EXISTS unified_coverage_events (
        country_code VARCHAR NOT NULL, authority VARCHAR NOT NULL, issuer_id VARCHAR NOT NULL, fiscal_year INTEGER NOT NULL,
        doc_type VARCHAR NOT NULL, event_seq INTEGER NOT NULL, status VARCHAR NOT NULL, applied BOOLEAN NOT NULL,
        reason VARCHAR, evidence_json VARCHAR, document_id VARCHAR, sha256 VARCHAR, recorded_at VARCHAR NOT NULL,
        run_id VARCHAR, job_id VARCHAR,
        PRIMARY KEY (country_code, authority, issuer_id, fiscal_year, doc_type, event_seq))""",
)


def _clean_evidence(ev: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if ev is None:
        return None
    out: Dict[str, Any] = {}
    for k, v in ev.items():
        if isinstance(v, str):
            v = sanitize_source_url(v) if v.startswith(("http://", "https://")) else sanitize_message(v)
        out[str(k)] = v
    return out


def _aware(ts: str) -> str:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError as ex:
        raise LedgerError(f"fecha inválida: {ts!r}") from ex
    if d.tzinfo is None:
        raise LedgerError("la fecha de comprobación debe llevar zona horaria")
    return d.astimezone(timezone.utc).isoformat()


class CoverageLedger:
    def __init__(self, db_path, mode: ExecutionMode = ExecutionMode.TEST, *, telemetry=None,
                 clock: Callable[[], str] = utc_now):
        from pathlib import Path
        self.db_path = Path(db_path)
        self.mode = ExecutionMode(mode)
        self.telemetry = telemetry
        self._clock = clock
        self._ready = False

    # ------------------------------------------------------------------ conexión
    @contextmanager
    def _connect(self, read_only: bool = False) -> Iterator[Any]:
        import duckdb
        with db_mutex(self.db_path):
            con, last = None, None
            for _ in range(200):
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

    def _ensure(self) -> None:
        if self._ready:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            for stmt in DDL:
                con.execute(stmt)
        self._ready = True

    def _read(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
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

    # ------------------------------------------------------------------ escritura
    def expect(self, keys: Iterable[CoverageKey], *, run_id: Optional[str] = None) -> int:
        """Declara el universo esperado. Idempotente: una clave ya conocida solo pasa a ``expected=True`` (su estado no cambia).
        Devuelve cuántas claves nuevas se crearon (con estado UNKNOWN)."""
        self._ensure()
        created = 0
        now = self._clock()
        with self._connect() as con:
            con.execute("BEGIN")
            try:
                for k in keys:
                    row = con.execute("SELECT expected FROM unified_coverage_ledger WHERE country_code=? AND authority=? "
                                      "AND issuer_id=? AND fiscal_year=? AND doc_type=?", list(k.as_tuple())).fetchone()
                    if row is None:
                        con.execute("INSERT INTO unified_coverage_ledger (country_code, authority, issuer_id, fiscal_year, "
                                    "doc_type, expected, status, updated_at, run_id) VALUES (?, ?, ?, ?, ?, TRUE, 'UNKNOWN', ?, ?)",
                                    [*k.as_tuple(), now, run_id])
                        self._event(con, k, LedgerStatus.UNKNOWN, True, "EXPECTED", None, None, None, now, run_id, None)
                        created += 1
                    elif not row[0]:
                        con.execute("UPDATE unified_coverage_ledger SET expected = TRUE, updated_at = ? WHERE country_code=? "
                                    "AND authority=? AND issuer_id=? AND fiscal_year=? AND doc_type=?", [now, *k.as_tuple()])
                con.execute("COMMIT")
            except BaseException:
                self._rollback(con)
                raise
        return created

    @staticmethod
    def _rollback(con) -> None:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass

    @staticmethod
    def _event(con, k: CoverageKey, status: LedgerStatus, applied: bool, reason: Optional[str], evidence_json: Optional[str],
               document_id, sha256, now: str, run_id, job_id) -> None:
        seq = con.execute("SELECT coalesce(max(event_seq), 0) + 1 FROM unified_coverage_events WHERE country_code=? AND "
                          "authority=? AND issuer_id=? AND fiscal_year=? AND doc_type=?", list(k.as_tuple())).fetchone()[0]
        con.execute("INSERT INTO unified_coverage_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [*k.as_tuple(), seq, status.value, applied, reason, evidence_json, document_id, sha256, now, run_id, job_id])

    def record(self, key: CoverageKey, status: LedgerStatus, *, document_id: Optional[str] = None, sha256: Optional[str] = None,
               identity_key: Optional[str] = None, version_status: Optional[str] = None, reason: Optional[str] = None,
               evidence: Optional[Mapping[str, Any]] = None, checked_at: Optional[str] = None, run_id: Optional[str] = None,
               job_id: Optional[str] = None, resolve_conflict: bool = False) -> RecordResult:
        """Registra un estado para ``key``. Las claves no esperadas se registran con ``expected=False`` (hallazgo inesperado)."""
        status = LedgerStatus(status)
        ev = _clean_evidence(evidence)
        if status is LedgerStatus.NOT_PUBLISHED:
            if not ev or not str(ev.get("method") or "").strip() or not str(ev.get("ref") or "").strip():
                raise LedgerError("NOT_PUBLISHED exige evidencia con 'method' y 'ref'")
            if checked_at is None:
                raise LedgerError("NOT_PUBLISHED exige la fecha de comprobación (checked_at)")
        checked = _aware(checked_at) if checked_at else None
        self._ensure()
        now = self._clock()
        ev_json = json.dumps(ev, sort_keys=True, ensure_ascii=False) if ev else None
        with self._connect() as con:
            con.execute("BEGIN")
            try:
                row = con.execute("SELECT status, document_id, sha256, reason, evidence_json, last_checked_at, version_status "
                                  "FROM unified_coverage_ledger WHERE country_code=? AND authority=? AND issuer_id=? AND "
                                  "fiscal_year=? AND doc_type=?", list(key.as_tuple())).fetchone()
                current = LedgerStatus(row[0]) if row else None
                result, applied, why = resolve_transition(current, status, resolve_conflict=resolve_conflict)
                final_reason = reason or why or None
                unchanged = bool(row) and applied and result is current and (document_id or row[1]) == row[1] and \
                    (sha256 or row[2]) == row[2] and (ev_json or row[4]) == row[4] and (final_reason or row[3]) == row[3] and \
                    (version_status or row[6]) == row[6]
                if row is None:
                    con.execute("INSERT INTO unified_coverage_ledger (country_code, authority, issuer_id, fiscal_year, doc_type, "
                                "expected, status, document_id, sha256, identity_key, version_status, reason, evidence_json, "
                                "last_checked_at, updated_at, run_id, job_id) VALUES (?, ?, ?, ?, ?, FALSE, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                [*key.as_tuple(), result.value, document_id, sha256, identity_key, version_status, final_reason,
                                 ev_json, checked or now, now, run_id, job_id])
                    self._event(con, key, status, True, final_reason, ev_json, document_id, sha256, now, run_id, job_id)
                    changed = True
                elif unchanged:
                    if checked:           # solo se refresca la fecha de última comprobación: sin evento nuevo
                        con.execute("UPDATE unified_coverage_ledger SET last_checked_at = ? WHERE country_code=? AND "
                                    "authority=? AND issuer_id=? AND fiscal_year=? AND doc_type=?", [checked, *key.as_tuple()])
                    changed = False
                else:
                    changed = False
                    if applied:
                        changed = True
                        con.execute(
                            "UPDATE unified_coverage_ledger SET status=?, document_id=coalesce(?, document_id), "
                            "sha256=coalesce(?, sha256), identity_key=coalesce(?, identity_key), "
                            "version_status=coalesce(?, version_status), reason=?, evidence_json=coalesce(?, evidence_json), "
                            "last_checked_at=coalesce(?, last_checked_at), updated_at=?, run_id=?, job_id=? WHERE country_code=? "
                            "AND authority=? AND issuer_id=? AND fiscal_year=? AND doc_type=?",
                            [result.value, document_id, sha256, identity_key, version_status, final_reason, ev_json, checked,
                             now, run_id, job_id, *key.as_tuple()])
                    last = con.execute("SELECT status, applied, reason FROM unified_coverage_events WHERE country_code=? AND "
                                       "authority=? AND issuer_id=? AND fiscal_year=? AND doc_type=? ORDER BY event_seq DESC "
                                       "LIMIT 1", list(key.as_tuple())).fetchone()
                    if applied or last != (status.value, applied, final_reason):     # un rechazo repetido no duplica eventos
                        self._event(con, key, status, applied, final_reason, ev_json, document_id, sha256, now, run_id, job_id)
                        changed = True
                con.execute("COMMIT")
            except BaseException:
                self._rollback(con)
                raise
        if self.telemetry is not None and changed:
            self.telemetry.emit("coverage_status", None, "coverage_ledger", authority=key.authority, country=key.country_code,
                                issuer_id=key.issuer_id, fiscal_year=key.fiscal_year, doc_type=key.doc_type,
                                status=result.value, requested=status.value, applied=applied, reason=final_reason)
        return RecordResult(key, result, applied, final_reason or "", changed)

    def record_not_published(self, key: CoverageKey, evidence: Mapping[str, Any], checked_at: str, **kw) -> RecordResult:
        return self.record(key, LedgerStatus.NOT_PUBLISHED, evidence=evidence, checked_at=checked_at, **kw)

    # ------------------------------------------------------------------ consulta (solo lectura)
    @staticmethod
    def _to_record(r: Dict[str, Any]) -> LedgerRecord:
        return LedgerRecord(
            key=CoverageKey(r["country_code"], r["authority"], r["issuer_id"], int(r["fiscal_year"]), r["doc_type"]),
            expected=bool(r["expected"]), status=LedgerStatus(r["status"]), document_id=r["document_id"], sha256=r["sha256"],
            identity_key=r["identity_key"], version_status=r["version_status"], reason=r["reason"],
            evidence=json.loads(r["evidence_json"]) if r["evidence_json"] else None, last_checked_at=r["last_checked_at"],
            updated_at=r["updated_at"], run_id=r["run_id"], job_id=r["job_id"])

    def get(self, key: CoverageKey) -> Optional[LedgerRecord]:
        rows = self._read("SELECT * FROM unified_coverage_ledger WHERE country_code=? AND authority=? AND issuer_id=? AND "
                          "fiscal_year=? AND doc_type=?", list(key.as_tuple()))
        return self._to_record(rows[0]) if rows else None

    def list(self, *, authority: Optional[str] = None, country_code: Optional[str] = None,
             fiscal_year: Optional[int] = None, status: Optional[LedgerStatus] = None,
             expected_only: bool = False) -> List[LedgerRecord]:
        where, params = ["1=1"], []
        for col, val in (("authority", authority and authority.upper()), ("country_code", country_code and country_code.upper()),
                         ("fiscal_year", fiscal_year), ("status", status.value if status else None)):
            if val is not None:
                where.append(f"{col} = ?")
                params.append(val)
        if expected_only:
            where.append("expected = TRUE")
        rows = self._read("SELECT * FROM unified_coverage_ledger WHERE " + " AND ".join(where) +
                          " ORDER BY country_code, authority, issuer_id, fiscal_year, doc_type", params)
        return [self._to_record(r) for r in rows]

    def events(self, key: CoverageKey) -> List[Dict[str, Any]]:
        return self._read("SELECT * FROM unified_coverage_events WHERE country_code=? AND authority=? AND issuer_id=? AND "
                          "fiscal_year=? AND doc_type=? ORDER BY event_seq", list(key.as_tuple()))

    def coverage(self, **filters) -> CoverageSummary:
        recs = self.list(**filters)
        exp = [r for r in recs if r.expected]
        by: Dict[str, int] = {}
        for r in exp:
            by[r.status.value] = by.get(r.status.value, 0) + 1
        promoted, notpub = by.get("PROMOTED", 0), by.get("NOT_PUBLISHED", 0)
        total = len(exp)
        denom = total - notpub
        return CoverageSummary(
            expected=total, by_status=dict(sorted(by.items())), promoted=promoted, not_published=notpub,
            unexpected_found=len([r for r in recs if not r.expected and r.status is not LedgerStatus.UNKNOWN]),
            coverage_ratio=(promoted / denom) if denom > 0 else None,
            accounted_ratio=((promoted + notpub) / total) if total else None, open_keys=total - promoted - notpub)

    def last_non_publication_check(self, key: CoverageKey) -> Optional[str]:
        r = self.get(key)
        return r.last_checked_at if r and r.status is LedgerStatus.NOT_PUBLISHED else None


# ======================================================================================= integración con el pipeline
_TRANSIENT = {"NETWORK", "TIMEOUT", "HTTP_TRANSIENT"}


def status_from_outcome(outcome) -> Tuple[LedgerStatus, str]:
    """Traduce el ``PipelineResult`` del runner a estado de ledger (y motivo). Sin heurísticas sobre 'no publicado'."""
    state, klass, stage = outcome.state, outcome.error_class, getattr(outcome, "failure_stage", None)
    if state in ("COMPLETED", "SKIPPED_ALREADY_PRESENT", "SKIPPED_DUPLICATE"):
        return LedgerStatus.PROMOTED, state
    if state == "MANUAL_REVIEW" and getattr(outcome, "version_status", None) == "UNCONFIRMED":
        return LedgerStatus.VALIDATED, "UNCONFIRMED_VERSION_RETAINED"       # contenido válido y guardado, sin confirmar
    if state == "CONFLICT" or (state == "FAILED" and klass == "INVARIANT_VIOLATION"):
        return LedgerStatus.CONFLICT, klass or state
    if state in ("MANUAL_REVIEW", "RECOVERY_REQUIRED", "QUARANTINED"):
        return LedgerStatus.NEEDS_REVIEW, klass or state
    if state == "FAILED":
        if stage == "ADAPTER" or klass in _TRANSIENT:
            return LedgerStatus.SOURCE_UNAVAILABLE, klass or "ADAPTER"
        return LedgerStatus.NEEDS_REVIEW, klass or "FAILED"          # 403/404/tamaño/redirección: ambiguo, no es 'no publicado'
    return LedgerStatus.UNKNOWN, state


def record_outcome(ledger: CoverageLedger, candidate, outcome, *, run_id: Optional[str] = None) -> RecordResult:
    from mod_01_ingestion.src.unified.domain.versions import resolve_identity
    key = CoverageKey.from_candidate(candidate)
    ident = resolve_identity(candidate.authority, candidate.document_id, candidate.identity_contract,
                             candidate.source_document_id)
    identity_key = ident.identity_key if ident.is_contracted else None          # nunca se inventa una identidad
    cur = ledger.get(key)
    if cur is None or cur.status in (LedgerStatus.UNKNOWN, LedgerStatus.NOT_PUBLISHED, LedgerStatus.SOURCE_UNAVAILABLE):
        ledger.record(key, LedgerStatus.FOUND, document_id=candidate.document_id, run_id=run_id, job_id=outcome.job_id)
    status, why = status_from_outcome(outcome)
    return ledger.record(key, status, document_id=candidate.document_id, sha256=outcome.sha256, reason=why,
                         identity_key=identity_key, version_status=getattr(outcome, "version_status", None), run_id=run_id,
                         job_id=outcome.job_id)


@dataclass(frozen=True)
class LedgerFinding:
    code: str
    key: Optional[CoverageKey]
    detail: str


def cross_check_ledger(ledger: CoverageLedger, catalog, report=None) -> List[LedgerFinding]:
    """Contrasta el ledger con el catálogo (y con el informe del reconciliador). SOLO LECTURA: no cambia nada."""
    out: List[LedgerFinding] = []
    cat = {r["document_id"]: r for r in catalog.list_records()}
    flagged: Dict[str, List[str]] = {}
    for f in (report.findings if report is not None else []):
        if f.document_id and f.severity in ("ERROR", "WARN"):
            flagged.setdefault(f.document_id, []).append(f.code)
    tracked = set()
    for r in ledger.list():
        tracked.add(r.document_id)
        if r.status is not LedgerStatus.PROMOTED:
            continue
        row = cat.get(r.document_id)
        if row is None:
            out.append(LedgerFinding("LEDGER_PROMOTED_WITHOUT_CATALOG", r.key, str(r.document_id)))
            continue
        if r.sha256 and str(row["sha256"]).lower() != str(r.sha256).lower():
            out.append(LedgerFinding("LEDGER_SHA_MISMATCH", r.key, str(r.document_id)))
        if r.document_id in flagged:
            out.append(LedgerFinding("LEDGER_PROMOTED_BUT_RECONCILER_FLAGGED", r.key, ",".join(sorted(set(flagged[r.document_id])))))
    for doc, row in sorted(cat.items()):
        if doc not in tracked:
            key = CoverageKey(row["country_code"], row["authority"], row["issuer_id"], int(row["fiscal_year"]), row["doc_type"])
            out.append(LedgerFinding("CATALOG_UNTRACKED_BY_LEDGER", key, doc))
    return out


def apply_cross_check(ledger: CoverageLedger, findings: Iterable[LedgerFinding], *, run_id: Optional[str] = None) -> int:
    """Acción EXPLÍCITA: los PROMOTED contradichos por el catálogo/reconciliador pasan a NEEDS_REVIEW (nunca se borran)."""
    n = 0
    for f in findings:
        if f.code in ("LEDGER_PROMOTED_WITHOUT_CATALOG", "LEDGER_SHA_MISMATCH", "LEDGER_PROMOTED_BUT_RECONCILER_FLAGGED") and f.key:
            ledger.record(f.key, LedgerStatus.NEEDS_REVIEW, reason=f.code, evidence={"method": "cross_check", "ref": f.detail[:120]},
                          run_id=run_id)
            n += 1
    return n
