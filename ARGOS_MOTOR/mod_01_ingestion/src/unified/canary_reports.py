"""
Persistencia de informes de canario (SANDBOX) con consulta y retención configurable.

Tabla ADITIVA ``unified_canary_reports`` (creada de forma perezosa en la primera escritura; leer nunca crea nada).
* ``report_id`` determinista (run_id + fuente + inicio + disparador): guardar el mismo informe dos veces es idempotente; el
  mismo id con contenido distinto es un error explícito (nunca se sobrescribe).
* Consultas: último informe por fuente, historial, alertas ACTIVAS (las del último informe de cada fuente, con su ``first_seen``).
* Retención (``RetentionPolicy``): solo borra filas de ESTA tabla —nunca el ledger, el catálogo, los manifiestos ni archivos—
  y conserva siempre el informe más reciente de cada fuente.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from mod_01_ingestion.src.unified import _dbutil
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.models import utc_now

DDL = (
    """CREATE TABLE IF NOT EXISTS unified_canary_reports (
        report_id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL, authority VARCHAR NOT NULL, country_code VARCHAR,
        mode VARCHAR NOT NULL, trigger VARCHAR NOT NULL, status VARCHAR NOT NULL, ok BOOLEAN NOT NULL,
        started_at VARCHAR NOT NULL, finished_at VARCHAR NOT NULL, counts_json VARCHAR NOT NULL, alerts_json VARCHAR NOT NULL,
        coverage_json VARCHAR, discovery_error VARCHAR, recorded_at VARCHAR NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS ix_ucr_authority ON unified_canary_reports(authority, finished_at)",
)
TRIGGERS = ("MANUAL", "SCHEDULED")


class ReportStoreError(DomainValidationError):
    pass


@dataclass(frozen=True)
class RetentionPolicy:
    keep_last: int = 200                  # informes por fuente que se conservan como mínimo
    max_age_days: Optional[int] = None    # además, se descartan los más antiguos que esto (salvo el último de cada fuente)

    def __post_init__(self):
        if isinstance(self.keep_last, bool) or not isinstance(self.keep_last, int) or self.keep_last < 1:
            raise ReportStoreError("keep_last debe ser un entero >= 1")
        if self.max_age_days is not None and (isinstance(self.max_age_days, bool) or not isinstance(self.max_age_days, int)
                                              or self.max_age_days < 1):
            raise ReportStoreError("max_age_days debe ser None o un entero >= 1")


def report_status(report) -> str:
    sev = {a.severity for a in report.alerts}
    return "ERROR" if "ERROR" in sev else ("WARN" if sev else "OK")


def _parse(ts: str) -> datetime:
    d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class CanaryReportStore:
    def __init__(self, db_path, *, telemetry=None, clock=utc_now):
        self.db_path, self.telemetry, self._clock, self._ready = db_path, telemetry, clock, False

    def _ensure(self) -> None:
        if not self._ready:
            _dbutil.ensure_schema(self.db_path, DDL)
            self._ready = True

    @staticmethod
    def _row(r: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(r)
        out["counts"] = json.loads(out.pop("counts_json"))
        out["alerts"] = json.loads(out.pop("alerts_json"))
        cov = out.pop("coverage_json")
        out["coverage"] = json.loads(cov) if cov else None
        return out

    # ------------------------------------------------------------------ escritura
    def save(self, report, *, run_id: str, trigger: str = "MANUAL") -> Dict[str, Any]:
        if trigger not in TRIGGERS:
            raise ReportStoreError(f"trigger desconocido: {trigger!r}")
        if not report.finished_at or not report.started_at:
            raise ReportStoreError("el informe debe tener started_at y finished_at")
        rid = hashlib.sha256(f"{run_id}|{report.authority}|{report.started_at}|{trigger}".encode("utf-8")).hexdigest()[:32]
        payload = [rid, run_id, report.authority, report.country_code, report.mode, trigger, report_status(report), report.ok,
                   report.started_at, report.finished_at, json.dumps(report.counts, sort_keys=True),
                   json.dumps([a.to_dict() for a in report.alerts], sort_keys=True, ensure_ascii=False),
                   json.dumps(report.coverage, sort_keys=True) if report.coverage is not None else None,
                   report.discovery_error]
        self._ensure()
        with _dbutil.connect(self.db_path) as con:
            n = con.execute("INSERT INTO unified_canary_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT DO NOTHING", [*payload, self._clock()]).fetchall()[0][0]
            if n == 0:
                cur = con.execute("SELECT * FROM unified_canary_reports WHERE report_id = ?", [rid])
                cols = [d[0] for d in cur.description]
                prev = dict(zip(cols, cur.fetchone()))
                if [prev[c] for c in cols[:14]] != payload:
                    raise ReportStoreError(f"el informe {rid} ya existe con contenido distinto: no se sobrescribe")
        if self.telemetry is not None and n:
            self.telemetry.emit("canary_report_saved", None, "canary_reports", authority=report.authority, report_id=rid,
                                status=payload[6], trigger=trigger)
        return {"report_id": rid, "created": bool(n), "status": payload[6]}

    # ------------------------------------------------------------------ consulta (solo lectura)
    def latest(self, authority: str, limit: int = 1) -> List[Dict[str, Any]]:
        rows = _dbutil.read_rows(self.db_path, "SELECT * FROM unified_canary_reports WHERE authority = ? "
                                 "ORDER BY finished_at DESC, report_id DESC LIMIT ?", [authority.upper(), int(limit)])
        return [self._row(r) for r in rows]

    history = latest

    def latest_per_source(self) -> Dict[str, Dict[str, Any]]:
        rows = _dbutil.read_rows(
            self.db_path, "SELECT * EXCLUDE (rn) FROM (SELECT *, row_number() OVER (PARTITION BY authority ORDER BY "
            "finished_at DESC, report_id DESC) AS rn FROM unified_canary_reports) WHERE rn = 1 ORDER BY authority")
        return {r["authority"]: self._row(r) for r in rows}

    def count(self, authority: Optional[str] = None) -> int:
        rows = _dbutil.read_rows(self.db_path, "SELECT count(*) AS n FROM unified_canary_reports" +
                                 (" WHERE authority = ?" if authority else ""), [authority.upper()] if authority else [])
        return int(rows[0]["n"]) if rows else 0

    def active_alerts(self) -> List[Dict[str, Any]]:
        """Alertas del ÚLTIMO informe de cada fuente; ``first_seen`` = inicio de la racha de informes que ya la traían."""
        out: List[Dict[str, Any]] = []
        for authority, rep in self.latest_per_source().items():
            hist = self.history(authority, limit=100)
            for al in rep["alerts"]:
                first = rep["started_at"]
                for h in hist:
                    if any(x["code"] == al["code"] for x in h["alerts"]):
                        first = h["started_at"]
                    else:
                        break
                out.append({"authority": authority, "code": al["code"], "severity": al["severity"], "message": al["message"],
                            "details": al.get("details", {}), "first_seen": first, "report_id": rep["report_id"]})
        return sorted(out, key=lambda a: (a["authority"], a["severity"] != "ERROR", a["code"]))

    # ------------------------------------------------------------------ retención
    def apply_retention(self, policy: RetentionPolicy, now: Optional[str] = None) -> int:
        """Borra SOLO filas de ``unified_canary_reports`` fuera de la política. Conserva siempre el último de cada fuente."""
        rows = _dbutil.read_rows(self.db_path, "SELECT report_id, authority, finished_at FROM unified_canary_reports "
                                 "ORDER BY authority, finished_at DESC, report_id DESC")
        if not rows:
            return 0
        now_dt, doomed, rank = _parse(now or self._clock()), [], {}
        for r in rows:
            n = rank[r["authority"]] = rank.get(r["authority"], 0) + 1
            too_old = (policy.max_age_days is not None
                       and (now_dt - _parse(r["finished_at"])).total_seconds() > policy.max_age_days * 86400)
            if n > 1 and (n > policy.keep_last or too_old):
                doomed.append(r["report_id"])
        if doomed:
            with _dbutil.connect(self.db_path) as con:
                con.execute("BEGIN")
                try:
                    for rid in doomed:
                        con.execute("DELETE FROM unified_canary_reports WHERE report_id = ?", [rid])
                    con.execute("COMMIT")
                except BaseException:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    raise
            if self.telemetry is not None:
                self.telemetry.emit("canary_reports_pruned", None, "canary_reports", deleted=len(doomed))
        return len(doomed)
