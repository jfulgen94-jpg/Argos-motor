"""
Vista de estado OPERATIVO (solo lectura): última ejecución por fuente, métricas, alertas activas, cobertura por país/autoridad
y los estados que piden atención (NEEDS_REVIEW, CONFLICT, SOURCE_UNAVAILABLE). Opcionalmente añade la integridad que informa el
reconciliador. No escribe nada.

Estado por fuente: NEVER_RUN · STALE (última ejecución más antigua que ``stale_after_s``) · ERROR · WARN · OK.
Estado global: el peor de todas las fuentes (ERROR > STALE > NEVER_RUN > WARN > OK) o ERROR si la integridad no está limpia.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from mod_01_ingestion.src.unified.canary_reports import CanaryReportStore, _parse
from mod_01_ingestion.src.unified.coverage_ledger import CoverageLedger, LedgerStatus

ATTENTION = (LedgerStatus.NEEDS_REVIEW, LedgerStatus.CONFLICT, LedgerStatus.SOURCE_UNAVAILABLE)
_ORDER = {"OK": 0, "WARN": 1, "NEVER_RUN": 2, "STALE": 3, "ERROR": 4}


@dataclass
class SourceStatus:
    authority: str
    country_code: Optional[str]
    status: str
    last_report: Optional[Dict[str, Any]] = None
    metrics: Dict[str, int] = field(default_factory=dict)
    active_alerts: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Optional[Dict[str, Any]] = None
    attention: Dict[str, int] = field(default_factory=dict)


@dataclass
class OperationalStatus:
    generated_at: str
    overall: str
    sources: Dict[str, SourceStatus]
    attention_keys: Dict[str, List[Dict[str, Any]]]
    integrity: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"generated_at": self.generated_at, "overall": self.overall, "integrity": self.integrity,
                "attention_keys": self.attention_keys,
                "sources": {a: {"authority": s.authority, "country_code": s.country_code, "status": s.status,
                                "last_report": s.last_report, "metrics": s.metrics, "active_alerts": s.active_alerts,
                                "coverage": s.coverage, "attention": s.attention} for a, s in sorted(self.sources.items())}}


def operational_status(store: CanaryReportStore, ledger: Optional[CoverageLedger], *, authorities: Iterable[str],
                       now_iso: str, stale_after_s: Optional[float] = None, reconciler=None,
                       max_attention_keys: int = 50) -> OperationalStatus:
    latest = store.latest_per_source()
    alerts = store.active_alerts()
    now = _parse(now_iso)
    sources: Dict[str, SourceStatus] = {}
    attention_keys: Dict[str, List[Dict[str, Any]]] = {s.value: [] for s in ATTENTION}
    for a in sorted({str(x).upper() for x in authorities}):
        rep = latest.get(a)
        st = SourceStatus(authority=a, country_code=rep["country_code"] if rep else None, status="NEVER_RUN")
        if rep is not None:
            st.status = rep["status"]
            st.last_report = {"report_id": rep["report_id"], "run_id": rep["run_id"], "trigger": rep["trigger"],
                              "started_at": rep["started_at"], "finished_at": rep["finished_at"], "ok": rep["ok"],
                              "status": rep["status"], "mode": rep["mode"]}
            st.metrics = dict(rep["counts"])
            st.active_alerts = [x for x in alerts if x["authority"] == a]
            if stale_after_s is not None and (now - _parse(rep["finished_at"])).total_seconds() > stale_after_s:
                st.status = "STALE"
        if ledger is not None:
            st.coverage = ledger.coverage(authority=a).to_dict()
            st.attention = {s.value: len(ledger.list(authority=a, status=s)) for s in ATTENTION}
            for s in ATTENTION:
                for r in ledger.list(authority=a, status=s):
                    if len(attention_keys[s.value]) < max_attention_keys:
                        attention_keys[s.value].append({"key": list(r.key.as_tuple()), "reason": r.reason,
                                                        "document_id": r.document_id, "updated_at": r.updated_at})
        sources[a] = st
    integrity = None
    if reconciler is not None:
        rep_r = reconciler.reconcile()
        by = {c: len(v) for c, v in sorted(rep_r.by_code().items())}
        integrity = {"clean": rep_r.clean, "documents_checked": rep_r.documents_checked, "findings_by_code": by}
    overall = max((s.status for s in sources.values()), key=lambda x: _ORDER.get(x, 0), default="OK")
    if integrity is not None and not integrity["clean"]:
        overall = "ERROR"
    return OperationalStatus(generated_at=now_iso, overall=overall, sources=sources, attention_keys=attention_keys,
                             integrity=integrity)


def render_text(status: OperationalStatus) -> str:
    """Vista de texto estable (para consola/informes); no incluye datos sensibles."""
    lines = [f"ESTADO OPERATIVO {status.generated_at}  global={status.overall}"]
    if status.integrity is not None:
        lines.append(f"  integridad: {'LIMPIA' if status.integrity['clean'] else 'CON HALLAZGOS'} "
                     f"({status.integrity['documents_checked']} docs) {json.dumps(status.integrity['findings_by_code'])}")
    for a, s in sorted(status.sources.items()):
        last = s.last_report["finished_at"] if s.last_report else "—"
        cov = f" cobertura={s.coverage['coverage_ratio']}" if s.coverage and s.coverage["coverage_ratio"] is not None else ""
        lines.append(f"  {a} ({s.country_code or '??'}) {s.status} última={last}{cov} "
                     f"atención={json.dumps(s.attention, sort_keys=True)}")
        for al in s.active_alerts:
            lines.append(f"      ! {al['severity']} {al['code']} desde {al['first_seen']}")
    return "\n".join(lines)
