"""
U5A — KnownDocumentPreflight: decide, ANTES de cualquier descarga, si un candidato ya está registrado.

Puro y de solo lectura: depende únicamente del puerto ``KnownDocumentLookup`` y del dominio (sin DuckDB, filesystem, red,
locks, ``.part``, CAS ni escritura). Es una optimización segura y una puerta de consistencia temprana; NO sustituye
a los locks ni al ``ManifestCatalogUnitOfWork``, que sigue siendo la autoridad final antes del commit (una carrera entre
dos workers que pasan el preflight se resuelve allí).

No confundir (principio fundamental): identidad lógica (``document_id``), publicación en la fuente (``source_document_id``),
versión regulatoria, contenido binario (SHA-256) y ubicación física (CAS). Fuerza de la evidencia, de mayor a menor:
1 SHA-256 esperado y registrado · 2 SHA-256 local registrado en ambas capas · 3 id estable de versión de la fuente ·
4 identidad compuesta · 5 URL · 6 nombre de archivo. URL y nombre NUNCA bastan para saltar una descarga; el
``document_id`` por sí solo tampoco (lo deriva el propio candidato).

Decisiones (ver audits/UNIFIED_DOWNLOAD_U5A_2026-10-10/02_PREFLIGHT_DECISION_TABLE.md):
P1 parcial (solo manifiesto / solo catálogo) -> RECOVERY_REQUIRED · P2 ambos coinciden + hash esperado igual -> SKIP ·
P3 hash esperado ya registrado (otro document_id compatible) -> SKIP · P4 id de fuente estable registrado -> SKIP ·
P5 mismo document_id + hash esperado distinto -> POSSIBLE_REPUBLICATION · P6 mismo document_id sin hash verificable ->
PROCEED_DOWNLOAD · P7 identidad incompatible -> CONFLICT (o MANUAL_REVIEW si no se puede verificar) · P8 nada -> PROCEED_DOWNLOAD.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from mod_01_ingestion.src.unified.application.ports import KnownDocumentLookup
from mod_01_ingestion.src.unified.domain.enums import PreflightMatch, PreflightStatus
from mod_01_ingestion.src.unified.domain.errors import sanitize_message
from mod_01_ingestion.src.unified.domain.models import DocumentCandidate, PreflightOutcome, RunContext

S, M = PreflightStatus, PreflightMatch


def _norm_hash(v: Optional[str]) -> Optional[str]:
    return str(v).strip().lower() if v else None


def _norm(v: Any) -> str:
    return str(v).strip().upper() if v not in (None, "") else ""


def safe_url(url: Optional[str]) -> str:
    """URL sin query, fragmento ni credenciales (para mensajes y eventos)."""
    if not url:
        return ""
    p = urlsplit(url)
    host = p.hostname or ""
    return urlunsplit((p.scheme, host, p.path, "", "")) if host else sanitize_message(url)[:80]


def _summary(rec: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resumen mínimo y sin datos sensibles (sin rutas absolutas ni URLs)."""
    if rec is None:
        return None
    keys = ("document_id", "sha256", "status", "authority", "fiscal_year", "doc_type")
    return {k: rec.get(k) for k in keys if rec.get(k) is not None}


class KnownDocumentPreflight:
    def __init__(self, lookup: KnownDocumentLookup):
        self.lookup = lookup

    # ------------------------------------------------------------------ identidad
    @staticmethod
    def _identity_findings(c: DocumentCandidate, rec: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
        """(conflictos duros, puntos sin verificar). Duros: autoridad, periodo, tipo, entidad/instrumento distintos."""
        hard: List[str] = []
        soft: List[str] = []
        if _norm(rec.get("authority")) and _norm(rec.get("authority")) != _norm(c.authority):
            hard.append("authority")
        if rec.get("fiscal_year") not in (None, "") and int(rec["fiscal_year"]) != c.fiscal_year:
            hard.append("fiscal_year")
        if _norm(rec.get("doc_type")) and _norm(rec.get("doc_type")) != _norm(c.doc_type):
            hard.append("doc_type")
        # entidad: la evidencia más fuerte disponible en AMBOS lados
        if c.entity_id and rec.get("entity_id"):
            if c.entity_id != rec["entity_id"]:
                hard.append("entity_id")
        elif _norm(c.issuer_lei) and _norm(rec.get("issuer_lei")):
            if _norm(c.issuer_lei) != _norm(rec.get("issuer_lei")):
                hard.append("entity_id")
        elif _norm(rec.get("issuer_id")) and _norm(rec.get("issuer_id")) not in (_norm(c.issuer_id), _norm(c.issuer_lei)):
            soft.append("issuer_id")                 # representaciones distintas del emisor: no demostrable offline
        if c.instrument_id and rec.get("instrument_id") and c.instrument_id != rec["instrument_id"]:
            soft.append("instrument_id")             # el instrumento puede cambiar (ticker/listing): revisión, no conflicto
        return hard, soft

    # ------------------------------------------------------------------ construcción de resultados
    def _out(self, c: DocumentCandidate, ctx: RunContext, status: PreflightStatus, reason: str, matched: PreflightMatch,
             *, manifest=None, catalog=None, existing_sha: Optional[str] = None, manual: bool = False,
             message: str = "") -> PreflightOutcome:
        return PreflightOutcome(
            status=status, reason_code=reason, document_id=c.document_id, matched_by=matched,
            source_document_id=c.source_document_id, expected_sha256=_norm_hash(c.expected_sha256),
            existing_sha256=existing_sha, entity_id=c.entity_id, instrument_id=c.instrument_id,
            existing_manifest=_summary(manifest), existing_catalog=_summary(catalog), fiscal_year=c.fiscal_year,
            discovered_at=ctx.started_at, needs_manual_review=manual,
            safe_message=sanitize_message(message or f"{status.value}: {reason} ({safe_url(c.source_url)})"))

    # ------------------------------------------------------------------ evaluación
    def evaluate(self, candidate: DocumentCandidate, context: RunContext) -> PreflightOutcome:
        c, ctx = candidate, context
        doc_id = c.document_id
        expected = _norm_hash(c.expected_sha256)
        m = self.lookup.get_manifest(c.authority, c.fiscal_year, doc_id)
        cat = self.lookup.get_catalog(doc_id)

        # P1 — estado parcial: no descargar, no reparar, conservar
        if (m is None) != (cat is None):
            present = m if m is not None else cat
            sha = _norm_hash(present.get("sha256"))
            side = "MANIFEST_ONLY" if m is not None else "CATALOG_ONLY"
            differs = "_HASH_DIFFERS" if (expected and sha and expected != sha) else ""
            return self._out(c, ctx, S.RECOVERY_REQUIRED, f"PARTIAL_{side}{differs}", M.NONE, manifest=m, catalog=cat,
                             existing_sha=sha, manual=True,
                             message=f"estado parcial previo ({side.lower().replace('_', ' ')}); no se descarga ni se repara")

        if m is not None and cat is not None:
            msha, csha = _norm_hash(m.get("sha256")), _norm_hash(cat.get("sha256"))
            if not msha or msha != csha:
                return self._out(c, ctx, S.CONFLICT, "MANIFEST_CATALOG_HASH_MISMATCH", M.MANIFEST_AND_CATALOG,
                                 manifest=m, catalog=cat, existing_sha=msha, manual=True,
                                 message="manifiesto y catálogo discrepan en el hash registrado")
            hard, soft = self._identity_findings(c, {**cat, **m})
            if hard:
                return self._out(c, ctx, S.CONFLICT, "IDENTITY_INCOMPATIBLE:" + ",".join(sorted(hard)), M.COMPOSITE_IDENTITY,
                                 manifest=m, catalog=cat, existing_sha=msha, manual=True,
                                 message="la identidad registrada es incompatible con el candidato")
            if soft:
                return self._out(c, ctx, S.MANUAL_REVIEW, "IDENTITY_UNVERIFIABLE:" + ",".join(sorted(soft)),
                                 M.COMPOSITE_IDENTITY, manifest=m, catalog=cat, existing_sha=msha, manual=True,
                                 message="no se puede verificar la identidad del emisor/instrumento registrado")
            if expected:
                if expected == msha:                                       # P2
                    if self.lookup.content_is_intact(m):
                        return self._out(c, ctx, S.SKIPPED_ALREADY_PRESENT, "ALREADY_PRESENT_SHA256", M.SHA256,
                                         manifest=m, catalog=cat, existing_sha=msha)
                    return self._out(c, ctx, S.PROCEED_DOWNLOAD, "REGISTERED_CONTENT_UNVERIFIED", M.MANIFEST_AND_CATALOG,
                                     manifest=m, catalog=cat, existing_sha=msha,
                                     message="registrado pero el contenido local no se verifica: se vuelve a obtener")
                return self._out(c, ctx, S.POSSIBLE_REPUBLICATION, "SAME_DOCUMENT_ID_DIFFERENT_EXPECTED_HASH",  # P5
                                 M.DOCUMENT_ID, manifest=m, catalog=cat, existing_sha=msha,
                                 message="mismo document_id con otro hash esperado: posible republicación (no se sobrescribe)")
            if c.source_document_id and c.source_id_is_version_stable:     # P4
                same = [r for r in self.lookup.find_by_source_document_id(c.authority, c.source_document_id)
                        if r.get("document_id") == doc_id]
                if same and self.lookup.content_is_intact(m):
                    return self._out(c, ctx, S.SKIPPED_ALREADY_PRESENT, "ALREADY_PRESENT_SOURCE_DOCUMENT_ID",
                                     M.SOURCE_DOCUMENT_ID, manifest=m, catalog=cat, existing_sha=msha)
            # P6 — sin hash verificable: nunca skip solo por document_id
            return self._out(c, ctx, S.PROCEED_DOWNLOAD, "NO_VERIFIABLE_HASH_DOCUMENT_ID_MATCH", M.DOCUMENT_ID,
                             manifest=m, catalog=cat, existing_sha=msha,
                             message="mismo document_id pero sin hash esperado: no hay evidencia para saltar la descarga")

        # Nada bajo este document_id ------------------------------------------------------------------
        if expected:                                                        # P3
            rows = list(self.lookup.find_by_sha256(expected))
            for rec in rows:
                hard, soft = self._identity_findings(c, rec)
                if hard:
                    return self._out(c, ctx, S.CONFLICT, "CONTENT_REGISTERED_UNDER_INCOMPATIBLE_IDENTITY:" + ",".join(sorted(hard)),
                                     M.SHA256, catalog=rec, existing_sha=expected, manual=True,
                                     message="el mismo contenido figura registrado bajo una identidad incompatible")
            for rec in rows:
                hard, soft = self._identity_findings(c, rec)
                if soft:
                    return self._out(c, ctx, S.MANUAL_REVIEW, "CONTENT_REGISTERED_IDENTITY_UNVERIFIABLE:" + ",".join(sorted(soft)),
                                     M.SHA256, catalog=rec, existing_sha=expected, manual=True,
                                     message="contenido ya registrado; la identidad del emisor no es verificable")
            for rec in rows:
                if self.lookup.content_is_intact(rec):
                    return self._out(c, ctx, S.SKIPPED_ALREADY_PRESENT, "CONTENT_ALREADY_REGISTERED", M.SHA256,
                                     catalog=rec, existing_sha=expected,
                                     message="contenido ya registrado: no se crea otra copia ni otro registro")
        if c.source_document_id and c.source_id_is_version_stable:
            others = list(self.lookup.find_by_source_document_id(c.authority, c.source_document_id))
            if others:                                                      # mismo id de fuente bajo otro document_id
                return self._out(c, ctx, S.MANUAL_REVIEW, "SOURCE_DOCUMENT_ID_REGISTERED_UNDER_OTHER_DOCUMENT_ID",
                                 M.SOURCE_DOCUMENT_ID, catalog=others[0], manual=True,
                                 message="el id estable de la fuente ya figura bajo otro document_id")
        return self._out(c, ctx, S.PROCEED_DOWNLOAD, "NO_MATCH", M.NONE)    # P8
