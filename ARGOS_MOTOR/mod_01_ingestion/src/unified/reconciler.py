"""
U3 — Reconciliador de SOLO LECTURA entre raw, CAS, manifiesto, catálogo y versiones.

Detecta (y clasifica) las desincronizaciones que un fallo intermedio puede dejar. NO repara, NO borra y NO escribe nada:
cada hallazgo trae la ``suggested_action`` para el operador. La recuperación automática se limita a lo que ya garantiza el
pipeline al re-ejecutarse (promoción CAS idempotente, ``.pending`` de manifiesto reescribible, UoW idempotente); los estados
parciales (solo manifiesto / solo catálogo) siguen exigiendo revisión explícita (``RECOVERY_REQUIRED`` en el preflight).

Códigos (severidad):
  ERROR  MANIFEST_ONLY · CATALOG_ONLY · HASH_MISMATCH_MANIFEST_CATALOG · RAW_MISSING · RAW_HASH_MISMATCH ·
         CAS_BLOB_MISSING · CAS_BLOB_HASH_MISMATCH · VERSION_TABLE_ONLY · VERSION_SIDECAR_ONLY · VERSION_FACTS_MISMATCH ·
         VERSION_BLOB_MISSING · MANIFEST_UNREADABLE
  WARN   FIELD_MISMATCH · PENDING_MANIFEST · RAW_ORPHAN · CAS_ORPHAN · CAS_TMP_LEFTOVER · PIN_STALE
  INFO   PIN_ORPHAN
Un hallazgo ERROR/WARN hace que ``ReconcileReport.clean`` sea False.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from mod_01_ingestion.src.unified.cas_store import ContentAddressedRawStore, file_sha256
from mod_01_ingestion.src.unified.config import DataLayout
from mod_01_ingestion.src.unified.repositories import CatalogRepository
from mod_01_ingestion.src.unified.version_store import VersionRepository

_SEVERITY = {
    "MANIFEST_ONLY": "ERROR", "CATALOG_ONLY": "ERROR", "HASH_MISMATCH_MANIFEST_CATALOG": "ERROR", "RAW_MISSING": "ERROR",
    "RAW_HASH_MISMATCH": "ERROR", "CAS_BLOB_MISSING": "ERROR", "CAS_BLOB_HASH_MISMATCH": "ERROR",
    "VERSION_TABLE_ONLY": "ERROR", "VERSION_SIDECAR_ONLY": "ERROR", "VERSION_FACTS_MISMATCH": "ERROR",
    "VERSION_BLOB_MISSING": "ERROR", "MANIFEST_UNREADABLE": "ERROR",
    "FIELD_MISMATCH": "WARN", "PENDING_MANIFEST": "WARN", "RAW_ORPHAN": "WARN", "CAS_ORPHAN": "WARN",
    "CAS_TMP_LEFTOVER": "WARN", "PIN_STALE": "WARN", "PIN_ORPHAN": "INFO"}
_ACTION = {
    "MANIFEST_ONLY": "estado parcial: revisar; el preflight devuelve RECOVERY_REQUIRED y no repara solo",
    "CATALOG_ONLY": "estado parcial: revisar; el preflight devuelve RECOVERY_REQUIRED y no repara solo",
    "HASH_MISMATCH_MANIFEST_CATALOG": "conflicto de contenido registrado: revisión manual, no se sobrescribe",
    "RAW_MISSING": "restaurar el raw desde el CAS (blob) o volver a obtener el documento tras revisión",
    "RAW_HASH_MISMATCH": "el raw difiere del hash registrado: cuarentena y revisión manual",
    "CAS_BLOB_MISSING": "el blob registrado no existe: volver a obtener el documento (el CAS lo recrea de forma idempotente)",
    "CAS_BLOB_HASH_MISMATCH": "el blob difiere de su nombre/hash: revisión manual",
    "VERSION_TABLE_ONLY": "versión sin sidecar: no se repara solo; revisar",
    "VERSION_SIDECAR_ONLY": "sidecar sin fila: no se repara solo; revisar",
    "VERSION_FACTS_MISMATCH": "fila y sidecar contradicen sus hechos: revisión manual",
    "VERSION_BLOB_MISSING": "el blob de la versión no existe: volver a obtener (idempotente) tras revisión",
    "MANIFEST_UNREADABLE": "manifiesto ilegible: revisión manual",
    "FIELD_MISMATCH": "campos de manifiesto y catálogo no coinciden: revisar",
    "PENDING_MANIFEST": "manifiesto pendiente (fallo/crash a mitad): volver a ejecutar el documento lo reescribe",
    "RAW_ORPHAN": "raw sin registro: volver a ejecutar el documento lo adopta de forma idempotente (promoción dedup)",
    "CAS_ORPHAN": "blob sin registro ni versión ni pin: volver a ejecutar el documento o revisar; no se borra solo",
    "CAS_TMP_LEFTOVER": "residuo .tmp de promoción interrumpida: revisión manual",
    "PIN_STALE": "el pin no apunta al inodo del blob: revisión manual",
    "PIN_ORPHAN": "pin sin versión registrada (crash entre promote y registro): se conserva; limpieza manual futura"}


@dataclass(frozen=True)
class ReconcileFinding:
    code: str
    document_id: Optional[str]
    detail: str
    severity: str = ""
    suggested_action: str = ""


@dataclass
class ReconcileReport:
    findings: List[ReconcileFinding] = field(default_factory=list)
    documents_checked: int = 0

    @property
    def clean(self) -> bool:
        return not any(f.severity in ("ERROR", "WARN") for f in self.findings)

    def by_code(self) -> Dict[str, List[ReconcileFinding]]:
        out: Dict[str, List[ReconcileFinding]] = {}
        for f in self.findings:
            out.setdefault(f.code, []).append(f)
        return out

    def codes(self) -> Set[str]:
        return {f.code for f in self.findings}


class UnifiedReconciler:
    """Solo lectura: no escribe, no borra, no crea directorios. Una sola pasada, determinista."""

    def __init__(self, layout: DataLayout, catalog: CatalogRepository, cas: ContentAddressedRawStore,
                 versions: Optional[VersionRepository] = None):
        self.layout, self.catalog, self.cas, self.versions = layout, catalog, cas, versions

    # ------------------------------------------------------------------
    def _add(self, rep: ReconcileReport, code: str, doc: Optional[str], detail: str) -> None:
        rep.findings.append(ReconcileFinding(code, doc, detail, _SEVERITY[code], _ACTION[code]))

    @staticmethod
    def _sha(path: Path) -> Optional[str]:
        try:
            return file_sha256(path)
        except OSError:
            return None

    def _check_file(self, rep, doc, label_missing, label_mismatch, path: Optional[str], sha: Optional[str]) -> None:
        if not path:
            return
        p = Path(path)
        if not p.exists():
            self._add(rep, label_missing, doc, f"{p.name} no existe")
        elif sha and self._sha(p) != sha:
            self._add(rep, label_mismatch, doc, f"{p.name} no coincide con el sha256 registrado")

    def reconcile(self) -> ReconcileReport:
        rep = ReconcileReport()
        manifests: Dict[str, Dict[str, Any]] = {}
        manifest_files: Dict[str, Path] = {}
        mdir = self.layout.manifests
        if mdir.is_dir():
            for p in sorted(mdir.rglob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    manifests[str(data["document_id"])] = data
                    manifest_files[str(data["document_id"])] = p
                except Exception:
                    self._add(rep, "MANIFEST_UNREADABLE", None, p.name)
            for p in sorted(mdir.rglob("*.json.pending")):
                self._add(rep, "PENDING_MANIFEST", p.name[:-len(".json.pending")], p.name)
        catalog = {r["document_id"]: r for r in self.catalog.list_records()}

        known_shas: Set[str] = set()
        known_raw: Set[str] = set()
        for doc in sorted(set(manifests) | set(catalog)):
            m, c = manifests.get(doc), catalog.get(doc)
            if m is not None:
                known_shas.add(str(m["sha256"]).lower())
                known_raw.add(os.path.normcase(os.path.abspath(str(m["raw_path"]))))
            if c is not None:
                known_shas.add(str(c["sha256"]).lower())
                known_raw.add(os.path.normcase(os.path.abspath(str(c["raw_path"]))))
            if m is not None and c is None:
                self._add(rep, "MANIFEST_ONLY", doc, "existe el manifiesto pero no la fila de catálogo")
            elif c is not None and m is None:
                self._add(rep, "CATALOG_ONLY", doc, "existe la fila de catálogo pero no el manifiesto")
            else:
                if str(m["sha256"]).lower() != str(c["sha256"]).lower():
                    self._add(rep, "HASH_MISMATCH_MANIFEST_CATALOG", doc, "sha256 distinto en manifiesto y catálogo")
                diffs = [k for k in ("raw_path", "status", "doc_type", "fiscal_year", "authority")
                         if str(m.get(k)) != str(c.get(k))]
                if str(c.get("manifest_path")) != str(manifest_files[doc]):
                    diffs.append("manifest_path")
                if diffs:
                    self._add(rep, "FIELD_MISMATCH", doc, "difieren: " + ", ".join(diffs))
            ref = m if m is not None else c
            sha = str(ref["sha256"]).lower()
            self._check_file(rep, doc, "RAW_MISSING", "RAW_HASH_MISMATCH", ref.get("raw_path"), sha)
            if m is not None:
                self._check_file(rep, doc, "CAS_BLOB_MISSING", "CAS_BLOB_HASH_MISMATCH", m.get("cas_path"), sha)
        rep.documents_checked = len(set(manifests) | set(catalog))

        # versiones (tabla + sidecar)
        if self.versions is not None:
            for v in self.versions.list_all_versions():
                sha = str(v["sha256"]).lower()
                known_shas.add(sha)
                tag = f'{v.get("identity_key")}/{sha[:12]}'
                if not v.get("table_present", True):
                    self._add(rep, "VERSION_SIDECAR_ONLY", v.get("document_id"), tag)
                elif not v.get("sidecar_present", True):
                    self._add(rep, "VERSION_TABLE_ONLY", v.get("document_id"), tag)
                elif not v.get("facts_match", True):
                    self._add(rep, "VERSION_FACTS_MISMATCH", v.get("document_id"), tag)
                if not self.cas.blob_path(sha).exists():
                    self._add(rep, "VERSION_BLOB_MISSING", v.get("document_id"), tag)

        # huérfanos: raw sin registro (contenido desconocido) y blobs sin ninguna referencia
        if self.layout.raw.is_dir():
            for p in sorted(q for q in self.layout.raw.rglob("*") if q.is_file()):
                if os.path.normcase(os.path.abspath(str(p))) in known_raw:
                    continue
                s = self._sha(p)
                if s is None or s.lower() not in known_shas:
                    self._add(rep, "RAW_ORPHAN", None, p.name)
        if self.layout.cas.is_dir():
            for p in sorted(q for q in self.layout.cas.rglob("*") if q.is_file()):
                if p.name.endswith(".tmp"):
                    self._add(rep, "CAS_TMP_LEFTOVER", None, p.name)
                elif p.name.lower() not in known_shas:
                    self._add(rep, "CAS_ORPHAN", None, p.name)
        pins = self.layout.root / "cas_pins"
        if pins.is_dir():
            version_shas = {str(v["sha256"]).lower() for v in (self.versions.list_all_versions() if self.versions else [])}
            for sd in sorted(q for q in pins.iterdir() if q.is_dir()):
                blob = self.cas.blob_path(sd.name)
                for p in sorted(q for q in sd.iterdir() if q.is_file()):
                    if blob.exists() and not os.path.samestat(p.stat(), blob.stat()):
                        self._add(rep, "PIN_STALE", None, f"{sd.name[:12]}/{p.name}")
                    elif sd.name.lower() not in version_shas:
                        self._add(rep, "PIN_ORPHAN", None, f"{sd.name[:12]}/{p.name}")
        return rep
