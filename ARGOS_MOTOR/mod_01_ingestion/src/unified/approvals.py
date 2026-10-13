"""
Procedimiento de APROBACIÓN de configuración de fuente y de contratos de identidad, con auditoría.

* Sujeto = (``subject_id``, ``kind``, ``version``) + ``content_hash`` (huella del contenido). Una versión es INMUTABLE: reenviar
  el mismo contenido es idempotente; contenido distinto bajo la misma versión es un error (hay que subir de versión).
* Estados: PENDING_APPROVAL → APPROVED | REJECTED; APPROVED → REVOKED. REJECTED y REVOKED son finales para esa versión.
* ``approve`` exige aprobador y REFERENCIA no vacíos y —por defecto— que el aprobador sea distinto de quien envió.
* Nada se activa sin aprobación: ``is_active`` solo es cierto si el estado es APPROVED **y** el contenido actual conserva la
  huella aprobada (un cambio posterior invalida la aprobación). ``resolve_active_configs`` aplica el registro a un
  ``SourceConfigSet``: la aprobación declarada dentro del archivo se IGNORA salvo ``accept_inline_approval=True``.
* Cada cambio queda en un registro append-only (quién, cuándo, referencia, motivo, estado anterior y nuevo).
Tablas ADITIVAS creadas de forma perezosa. Sin red, sin disco fuera de la base indicada.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mod_01_ingestion.src.unified import _dbutil
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.domain.models import utc_now
from mod_01_ingestion.src.unified.domain.versions import SourceIdentityContract
from mod_01_ingestion.src.unified.source_config import SourceConfig, SourceConfigSet

PENDING, APPROVED, REJECTED, REVOKED = "PENDING_APPROVAL", "APPROVED", "REJECTED", "REVOKED"
KINDS = ("SOURCE_CONFIG", "IDENTITY_CONTRACT")
DDL = (
    """CREATE TABLE IF NOT EXISTS unified_config_approvals (
        subject_id VARCHAR NOT NULL, kind VARCHAR NOT NULL, version VARCHAR NOT NULL, content_hash VARCHAR NOT NULL,
        status VARCHAR NOT NULL, submitted_by VARCHAR NOT NULL, submitted_at VARCHAR NOT NULL, decided_by VARCHAR,
        decided_at VARCHAR, ref VARCHAR, reason VARCHAR, updated_at VARCHAR NOT NULL, PRIMARY KEY (subject_id, kind, version))""",
    """CREATE TABLE IF NOT EXISTS unified_config_approval_events (
        subject_id VARCHAR NOT NULL, kind VARCHAR NOT NULL, version VARCHAR NOT NULL, event_seq INTEGER NOT NULL,
        action VARCHAR NOT NULL, from_status VARCHAR, to_status VARCHAR NOT NULL, actor VARCHAR NOT NULL, ref VARCHAR,
        reason VARCHAR, content_hash VARCHAR NOT NULL, occurred_at VARCHAR NOT NULL, PRIMARY KEY (subject_id, kind, version, event_seq))""",
)


class ApprovalError(DomainValidationError):
    pass


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def contract_content(c: SourceIdentityContract) -> Dict[str, Any]:
    return {"contract_id": c.contract_id, "contract_version": c.contract_version, "authority": c.authority,
            "namespace": c.namespace, "id_scope": c.id_scope.value, "normalizer_version": c.normalizer_version,
            "initial_version_policy": c.initial_version_policy.value,
            "allowed_evidence_kinds": sorted(k.value for k in c.allowed_evidence_kinds),
            "expected_sha256_authority": c.expected_sha256_authority}


def config_content(s: SourceConfig) -> Dict[str, Any]:
    """Contenido OPERATIVO de la fuente (sin el contrato, que se aprueba aparte)."""
    return {"source_id": s.source_id, "authority": s.authority, "country_code": s.country_code,
            "allowed_domains": list(s.allowed_domains), "user_agent": s.effective_user_agent, "min_interval_s": s.min_interval_s,
            "max_concurrent": s.max_concurrent, "timeout_s": s.timeout_s, "max_bytes": s.max_bytes, "max_total_s": s.max_total_s,
            "max_retries": s.max_retries, "retry_statuses": list(s.retry_statuses)}


class ApprovalRegistry:
    def __init__(self, db_path, *, require_distinct_approver: bool = True, telemetry=None, clock=utc_now):
        self.db_path, self.require_distinct, self.telemetry, self._clock = db_path, require_distinct_approver, telemetry, clock
        self._ready = False

    def _ensure(self) -> None:
        if not self._ready:
            _dbutil.ensure_schema(self.db_path, DDL)
            self._ready = True

    @staticmethod
    def _check(kind: str, **named: str) -> None:
        if kind not in KINDS:
            raise ApprovalError(f"tipo de sujeto desconocido: {kind!r}")
        for k, v in named.items():
            if not str(v or "").strip():
                raise ApprovalError(f"{k} obligatorio")

    def _emit(self, action: str, subject_id: str, kind: str, version: str, actor: str, to_status: str) -> None:
        if self.telemetry is not None:      # sin la referencia ni el motivo: solo el hecho del cambio
            self.telemetry.emit("config_approval_changed", None, "approvals", action=action, subject_id=subject_id, kind=kind,
                                version=version, actor=actor, to_status=to_status)

    def _transition(self, subject_id, kind, version, action, actor, allowed_from, to_status, *, ref=None, reason=None,
                    distinct=False):
        self._check(kind, subject_id=subject_id, version=version, actor=actor)
        self._ensure()
        now = self._clock()
        with _dbutil.connect(self.db_path) as con:
            con.execute("BEGIN")
            try:
                row = con.execute("SELECT status, submitted_by, content_hash FROM unified_config_approvals WHERE subject_id=? "
                                  "AND kind=? AND version=?", [subject_id, kind, version]).fetchone()
                if row is None:
                    raise ApprovalError("el sujeto no existe: primero hay que enviarlo (submit)")
                cur, submitter, chash = row
                if cur not in allowed_from:
                    raise ApprovalError(f"{action} no permitido desde {cur}")
                if distinct and self.require_distinct and actor == submitter:
                    raise ApprovalError("quien envía no puede aprobar su propio sujeto")
                con.execute("UPDATE unified_config_approvals SET status=?, decided_by=?, decided_at=?, ref=?, reason=?, "
                            "updated_at=? WHERE subject_id=? AND kind=? AND version=?",
                            [to_status, actor, now, ref, reason, now, subject_id, kind, version])
                self._append(con, subject_id, kind, version, action, cur, to_status, actor, ref, reason, chash, now)
                con.execute("COMMIT")
            except BaseException:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        self._emit(action, subject_id, kind, version, actor, to_status)
        return to_status

    @staticmethod
    def _append(con, subject_id, kind, version, action, from_status, to_status, actor, ref, reason, chash, at) -> None:
        seq = con.execute("SELECT coalesce(max(event_seq), 0) + 1 FROM unified_config_approval_events WHERE subject_id=? AND "
                          "kind=? AND version=?", [subject_id, kind, version]).fetchone()[0]
        con.execute("INSERT INTO unified_config_approval_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [subject_id, kind, version, seq, action, from_status, to_status, actor, ref,
                     sanitize_message(reason) if reason else None, chash, at])

    # ------------------------------------------------------------------ operaciones
    def submit(self, subject_id: str, kind: str, version: str, content: Any, submitted_by: str) -> str:
        self._check(kind, subject_id=subject_id, version=version, submitted_by=submitted_by)
        chash, now = fingerprint(content), self._clock()
        self._ensure()
        created = False
        with _dbutil.connect(self.db_path) as con:
            con.execute("BEGIN")
            try:
                row = con.execute("SELECT content_hash, status FROM unified_config_approvals WHERE subject_id=? AND kind=? "
                                  "AND version=?", [subject_id, kind, version]).fetchone()
                if row is None:
                    con.execute("INSERT INTO unified_config_approvals (subject_id, kind, version, content_hash, status, "
                                "submitted_by, submitted_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                [subject_id, kind, version, chash, PENDING, submitted_by, now, now])
                    self._append(con, subject_id, kind, version, "SUBMIT", None, PENDING, submitted_by, None, None, chash, now)
                    created, status = True, PENDING
                elif row[0] != chash:
                    raise ApprovalError("esa versión ya existe con otro contenido: las versiones son inmutables, "
                                        "hay que subir de versión")
                else:
                    status = row[1]
                con.execute("COMMIT")
            except BaseException:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        if created:
            self._emit("SUBMIT", subject_id, kind, version, submitted_by, PENDING)
        return status

    def approve(self, subject_id, kind, version, approved_by: str, ref: str) -> str:
        self._check(kind, ref=ref, approved_by=approved_by)
        return self._transition(subject_id, kind, version, "APPROVE", approved_by, (PENDING,), APPROVED, ref=ref, distinct=True)

    def reject(self, subject_id, kind, version, rejected_by: str, reason: str) -> str:
        self._check(kind, reason=reason)
        return self._transition(subject_id, kind, version, "REJECT", rejected_by, (PENDING,), REJECTED, reason=reason)

    def revoke(self, subject_id, kind, version, revoked_by: str, reason: str) -> str:
        self._check(kind, reason=reason)
        return self._transition(subject_id, kind, version, "REVOKE", revoked_by, (APPROVED,), REVOKED, reason=reason)

    # ------------------------------------------------------------------ consulta
    def status(self, subject_id: str, kind: str, version: str) -> Optional[str]:
        rows = _dbutil.read_rows(self.db_path, "SELECT status FROM unified_config_approvals WHERE subject_id=? AND kind=? AND "
                                 "version=?", [subject_id, kind, version])
        return rows[0]["status"] if rows else None

    def is_active(self, subject_id: str, kind: str, version: str, content: Any) -> bool:
        rows = _dbutil.read_rows(self.db_path, "SELECT status, content_hash FROM unified_config_approvals WHERE subject_id=? "
                                 "AND kind=? AND version=?", [subject_id, kind, version])
        return bool(rows) and rows[0]["status"] == APPROVED and rows[0]["content_hash"] == fingerprint(content)

    def history(self, subject_id: str, kind: Optional[str] = None, version: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, params = "SELECT * FROM unified_config_approval_events WHERE subject_id = ?", [subject_id]
        for col, val in (("kind", kind), ("version", version)):
            if val is not None:
                sql += f" AND {col} = ?"
                params.append(val)
        return _dbutil.read_rows(self.db_path, sql + " ORDER BY kind, version, event_seq", params)

    def pending(self) -> List[Dict[str, Any]]:
        return _dbutil.read_rows(self.db_path, "SELECT subject_id, kind, version, submitted_by, submitted_at FROM "
                                 "unified_config_approvals WHERE status = 'PENDING_APPROVAL' ORDER BY subject_id, kind, version")


# ======================================================================================= aplicación a la configuración
def submit_configs(configs: SourceConfigSet, registry: ApprovalRegistry, submitted_by: str) -> Dict[str, str]:
    """Envía a aprobación la configuración operativa de cada fuente y su contrato DECLARADO. No aprueba nada."""
    out: Dict[str, str] = {}
    for s in configs.sources:
        out[f"{s.source_id}:SOURCE_CONFIG"] = registry.submit(s.source_id, "SOURCE_CONFIG", configs.config_version,
                                                              config_content(s), submitted_by)
        if s.declared_contract is not None:
            c = s.declared_contract
            out[f"{s.source_id}:IDENTITY_CONTRACT"] = registry.submit(s.source_id, "IDENTITY_CONTRACT", c.contract_version,
                                                                      contract_content(c), submitted_by)
    return out


@dataclass(frozen=True)
class ActiveConfigs:
    active: SourceConfigSet
    pending: Dict[str, str]          # "<source_id>:<kind>" -> estado que impide activarlo


def resolve_active_configs(configs: SourceConfigSet, registry: ApprovalRegistry, *,
                           accept_inline_approval: bool = False) -> ActiveConfigs:
    """Devuelve SOLO lo aprobado en el registro: una fuente sin su configuración aprobada queda fuera; un contrato sin
    aprobación (o revocado, o cuyo contenido cambió) queda inactivo y la identidad vuelve a ``SLOT_ONLY``."""
    active: List[SourceConfig] = []
    blocked: Dict[str, str] = {}
    for s in configs.sources:
        st = registry.status(s.source_id, "SOURCE_CONFIG", configs.config_version)
        if not registry.is_active(s.source_id, "SOURCE_CONFIG", configs.config_version, config_content(s)):
            blocked[f"{s.source_id}:SOURCE_CONFIG"] = st or "NOT_SUBMITTED"
            continue
        contract, status = None, "NONE"
        if s.declared_contract is not None:
            c = s.declared_contract
            if registry.is_active(s.source_id, "IDENTITY_CONTRACT", c.contract_version, contract_content(c)):
                contract, status = c, "ACTIVE"
            elif accept_inline_approval and s.contract is not None:
                contract, status = s.contract, "ACTIVE"
            else:
                reg = registry.status(s.source_id, "IDENTITY_CONTRACT", c.contract_version)
                status = reg or "PENDING_APPROVAL"
                blocked[f"{s.source_id}:IDENTITY_CONTRACT"] = reg or "NOT_SUBMITTED"
        active.append(dataclasses.replace(s, contract=contract, contract_status=status))
    return ActiveConfigs(SourceConfigSet(config_version=configs.config_version, sources=tuple(active)), blocked)
