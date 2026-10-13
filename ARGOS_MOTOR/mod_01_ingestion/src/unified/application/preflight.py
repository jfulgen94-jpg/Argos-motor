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
P3 hash esperado ya registrado (otro document_id compatible) -> SKIP · (P4 de U5A, por id de fuente + booleano, se
sustituyó en U5B por la evaluación versionada con contrato: ver ``_evaluate_versioned``) ·
P5 mismo document_id + hash esperado distinto -> POSSIBLE_REPUBLICATION · P6 mismo document_id sin hash verificable ->
PROCEED_DOWNLOAD · P7 identidad incompatible -> CONFLICT (o MANUAL_REVIEW si no se puede verificar) · P8 nada -> PROCEED_DOWNLOAD.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from mod_01_ingestion.src.unified.application.ports import KnownDocumentLookup
from mod_01_ingestion.src.unified.domain.enums import PreflightMatch, PreflightStatus
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError, sanitize_message
from mod_01_ingestion.src.unified.domain.models import DocumentCandidate, PreflightOutcome, RunContext
from mod_01_ingestion.src.unified.domain.versions import (
    IdScope, ResolvedIdentity, VersionStatus, resolve_identity, validate_republication_evidence)

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
             message: str = "", ident: Optional[ResolvedIdentity] = None, reuse: Optional[str] = None) -> PreflightOutcome:
        return PreflightOutcome(
            identity_key=ident.identity_key if ident else None, version_ref=ident.version_ref if ident else None,
            reuse_sha256=reuse,
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
        # U5B — identidad versionada (solo con contrato de la fuente + id declarado); sin ellos, SLOT_ONLY y matriz U5A.
        try:
            ident = resolve_identity(c.authority, doc_id, c.identity_contract, c.source_document_id)
        except DomainValidationError as ex:
            return self._out(c, ctx, S.MANUAL_REVIEW, "IDENTITY_UNRESOLVABLE", M.NONE, manual=True,
                             message=f"la identidad declarada no se puede resolver: {ex}")
        if ident.is_contracted:
            decided = self._evaluate_versioned(c, ctx, ident, expected)
            if decided is not None:
                return decided
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
            # P6 — sin hash verificable: nunca skip solo por document_id
            return self._out(c, ctx, S.PROCEED_DOWNLOAD, "NO_VERIFIABLE_HASH_DOCUMENT_ID_MATCH", M.DOCUMENT_ID,
                             manifest=m, catalog=cat, existing_sha=msha,
                             message="mismo document_id pero sin hash esperado: no hay evidencia para saltar la descarga")

        # Nada bajo este document_id ------------------------------------------------------------------
        # U5B: con identidad contratada, el mismo hash bajo OTRA identidad no es conflicto ni skip: las identidades no se
        # fusionan; la reutilización sin descarga solo ocurre en ``_evaluate_versioned`` (hash autoritativo exacto), y en
        # otro caso se descarga (el CAS deduplica).
        if expected and not ident.is_contracted:                            # P3
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
        return self._out(c, ctx, S.PROCEED_DOWNLOAD, "NO_MATCH", M.NONE)    # P8

    # ------------------------------------------------------------------ U5B: evaluación por identidad y versiones
    def _evaluate_versioned(self, c: DocumentCandidate, ctx: RunContext, ident: ResolvedIdentity,
                            expected: Optional[str]) -> Optional[PreflightOutcome]:
        """Decide con las versiones registradas de la identidad. Devuelve ``None`` si no hay nada registrado bajo ella y no
        procede reutilizar contenido (entonces rige la matriz U5A). Un id ``LOGICAL_DOCUMENT`` NUNCA da skip por sí solo;
        ambigüedad, conflicto o política incompatible NUNCA dan skip."""
        contract = ident.contract
        lk = self.lookup
        if not all(hasattr(lk, n) for n in ("find_versions", "find_versions_by_sha256", "blob_is_intact")):
            return self._out(c, ctx, S.MANUAL_REVIEW, "VERSION_LOOKUP_UNAVAILABLE", M.NONE, manual=True, ident=ident,
                             message="el lookup no soporta versiones: no se decide con una identidad contratada")
        versions = list(lk.find_versions(ident.identity_key))

        # estado parcial entre tabla y sidecar: explícito, sin reparar
        for v in versions:
            if not v.get("table_present", True):
                return self._out(c, ctx, S.RECOVERY_REQUIRED, "PARTIAL_VERSION_SIDECAR_ONLY", M.NONE, manual=True,
                                 ident=ident, existing_sha=v.get("sha256"),
                                 message="existe el sidecar de una versión pero no su fila: no se repara automáticamente")
            if not v.get("sidecar_present", True):
                return self._out(c, ctx, S.RECOVERY_REQUIRED, "PARTIAL_VERSION_TABLE_ONLY", M.NONE, manual=True,
                                 ident=ident, existing_sha=v.get("sha256"),
                                 message="existe la fila de una versión pero no su sidecar: no se repara automáticamente")
            if not v.get("facts_match", True):
                return self._out(c, ctx, S.CONFLICT, "VERSION_FACTS_MISMATCH_TABLE_SIDECAR", M.NONE, manual=True,
                                 ident=ident, existing_sha=v.get("sha256"),
                                 message="la fila y el sidecar de una versión contradicen sus hechos")
        # política (normalizador / contrato) incompatible con la registrada
        for v in versions:
            if (v.get("normalizer_version"), v.get("contract_id"), v.get("contract_version")) != (
                    contract.normalizer_version, contract.contract_id, contract.contract_version):
                return self._out(c, ctx, S.MANUAL_REVIEW, "IDENTITY_POLICY_VERSION_MISMATCH", M.NONE, manual=True,
                                 ident=ident, existing_sha=v.get("sha256"),
                                 message="la versión del normalizador/contrato difiere de la registrada: requiere revisión")
        # metadatos contradictorios: un id lógico no puede aparecer bajo otro slot
        if contract.id_scope is IdScope.LOGICAL_DOCUMENT:
            for v in versions:
                if v.get("document_id") and v["document_id"] != c.document_id:
                    return self._out(c, ctx, S.MANUAL_REVIEW, "LOGICAL_ID_REGISTERED_UNDER_OTHER_SLOT", M.NONE,
                                     manual=True, ident=ident, existing_sha=v.get("sha256"),
                                     message="el mismo id lógico figura bajo otro slot (emisor/periodo/tipo)")

        by_sha = {v["sha256"]: v for v in versions}
        cur = next((v for v in versions if v.get("status") == VersionStatus.CURRENT.value), None)

        def evidence_ok():
            if cur is None:
                return False, "NO_CURRENT_VERSION"
            return validate_republication_evidence(
                contract, c.republication_evidence, current_version_ref=cur.get("version_ref"),
                current_revision=cur.get("revision"), current_sha256=cur.get("sha256"),
                candidate_revision=c.source_revision, expected_sha256=expected)

        if versions:
            if expected and expected in by_sha:
                v = by_sha[expected]
                if (contract.id_scope is IdScope.VERSION and ident.version_ref and v.get("version_ref")
                        and v["version_ref"] != ident.version_ref):
                    return self._out(c, ctx, S.MANUAL_REVIEW, "VERSION_REF_CONTRADICTS_REGISTERED_HASH", M.NONE,
                                     manual=True, ident=ident, existing_sha=expected,
                                     message="el hash esperado figura registrado con otra referencia de versión")
                if c.republication_evidence is not None and evidence_ok()[0]:
                    return self._out(c, ctx, S.MANUAL_REVIEW, "EVIDENCE_CONTRADICTS_REGISTERED_HASH", M.NONE, manual=True,
                                     ident=ident, existing_sha=expected,
                                     message="la evidencia declara una versión nueva pero el hash ya está registrado")
                if lk.blob_is_intact(expected):
                    return self._out(c, ctx, S.SKIPPED_ALREADY_PRESENT, "ALREADY_PRESENT_VERSION_SHA256", M.SHA256,
                                     existing_sha=expected, ident=ident,
                                     message="versión ya registrada con el mismo hash y contenido íntegro")
                return self._out(c, ctx, S.PROCEED_DOWNLOAD, "REGISTERED_VERSION_CONTENT_UNVERIFIED", M.NONE,
                                 existing_sha=expected, ident=ident,
                                 message="versión registrada pero su contenido no se verifica: se vuelve a obtener")
            if contract.id_scope is IdScope.VERSION and ident.version_ref:
                same = [v for v in versions if v.get("version_ref") == ident.version_ref]
                if same and expected and all(v["sha256"] != expected for v in same):
                    return self._out(c, ctx, S.MANUAL_REVIEW, "VERSION_REF_REGISTERED_WITH_OTHER_HASH", M.NONE,
                                     manual=True, ident=ident, existing_sha=same[0]["sha256"],
                                     message="la misma referencia de versión figura con otro hash")
                if same and not expected:
                    if len({v["sha256"] for v in same}) > 1:
                        return self._out(c, ctx, S.MANUAL_REVIEW, "VERSION_REF_MAPS_TO_MULTIPLE_HASHES", M.NONE,
                                         manual=True, ident=ident, message="una referencia de versión con varios hashes")
                    if lk.blob_is_intact(same[0]["sha256"]):
                        return self._out(c, ctx, S.SKIPPED_ALREADY_PRESENT, "ALREADY_PRESENT_VERSION_REF",
                                         M.SOURCE_DOCUMENT_ID, existing_sha=same[0]["sha256"], ident=ident,
                                         message="referencia de versión ya registrada con contenido íntegro")
                    return self._out(c, ctx, S.PROCEED_DOWNLOAD, "REGISTERED_VERSION_CONTENT_UNVERIFIED", M.NONE,
                                     ident=ident, existing_sha=same[0]["sha256"])
            ok, why = evidence_ok()
            if ok:
                return self._out(c, ctx, S.REPUBLICATION_CONFIRMED,
                                 "REPUBLICATION_CONFIRMED:" + c.republication_evidence.kind.value, M.VERSION_EVIDENCE,
                                 existing_sha=cur.get("sha256"), ident=ident,
                                 message="republicación respaldada por evidencia válida según el contrato de la fuente")
            if expected:
                return self._out(c, ctx, S.POSSIBLE_REPUBLICATION, "NEW_HASH_WITHOUT_VALID_EVIDENCE:" + why, M.DOCUMENT_ID,
                                 existing_sha=(cur or versions[0]).get("sha256"), ident=ident,
                                 message="hash nuevo sin evidencia válida del contrato: posible republicación")
            return self._out(c, ctx, S.PROCEED_DOWNLOAD, "VERSIONS_EXIST_NO_VERIFIABLE_VALIDATOR", M.NONE,
                             existing_sha=(cur or versions[0]).get("sha256"), ident=ident,
                             message="sin hash ni evidencia: un id sin validador remoto no autoriza saltar la descarga")

        # Nada registrado bajo esta identidad: reutilización de CAS bajo OTRA identidad (solo hash autoritativo exacto).
        if (expected and contract.expected_sha256_authority and lk.get_manifest(c.authority, c.fiscal_year, c.document_id) is None
                and lk.get_catalog(c.document_id) is None):
            for o in lk.find_versions_by_sha256(expected):
                if (o.get("identity_key") != ident.identity_key and o.get("table_present", True)
                        and o.get("sidecar_present", True) and o.get("facts_match", True) and lk.blob_is_intact(expected)):
                    return self._out(c, ctx, S.REUSE_EXISTING_CONTENT, "REUSE_CAS_BLOB_AUTHORITATIVE_HASH", M.SHA256,
                                     existing_sha=expected, ident=ident, reuse=expected,
                                     message="mismo contenido ya en el CAS bajo otra identidad (hash autoritativo exacto)")
        return None
