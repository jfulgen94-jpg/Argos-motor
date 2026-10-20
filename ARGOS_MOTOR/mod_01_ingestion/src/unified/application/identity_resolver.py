"""Resolvedor de identidad OFFLINE (U3): registros de catálogo -> entidades jurídicas + instrumentos + incidencias.

Puro, determinista e idempotente: no muta la entrada, no usa red, filesystem ni DuckDB, no depende del orden de los
registros y no fusiona casos ambiguos. Solo importa ``unified.domain``. No está conectado al pipeline de descarga.

Reglas de fusión (la ÚNICA fusión automática):
    registros con el MISMO LEI válido (formato + checksum ISO 17442) y sin conflicto de identificador fiscal
    comparten ``entity_id = entity:lei:<LEI>``. Todo lo demás recibe un ``entity_id`` provisional por registro.
Un LEI válido sigue siendo ``HIGH`` y no ``CONFIRMED``: sin contraste externo (GLEIF) nada se confirma.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mod_01_ingestion.src.unified.domain.enums import (
    DuplicateRelation, IdentifierStatus, IdentityConfidence, IdentityReviewStatus)
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.identity import (
    IdentifierCheck, IdentityIssue, IdentityResolution, LegalEntity, ListedInstrument, RelationRecord, check_isin,
    check_lei, check_tax_id, entity_id_from_lei, instrument_id_for, normalize_legal_name, normalize_ticker,
    provisional_entity_id)

_REVIEW_PRIORITY = {
    IdentityReviewStatus.SHARED_IDENTIFIER_CONFLICT: 5, IdentityReviewStatus.MANUAL_REVIEW_REQUIRED: 4,
    IdentityReviewStatus.POSSIBLE_SAME_ENTITY: 3, IdentityReviewStatus.INVALID_IDENTIFIER: 2,
    IdentityReviewStatus.INSUFFICIENT_EVIDENCE: 1, IdentityReviewStatus.NO_REVIEW_REQUIRED: 0}


@dataclass(frozen=True)
class _Rec:
    ref: str
    ticker: str
    name: str
    name_n: str
    lei: IdentifierCheck
    tax: IdentifierCheck
    isin: IdentifierCheck
    is_socimi: bool
    market: Optional[str]
    mic: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    status: str


def _ticker_variant(a: str, b: str) -> bool:
    """Variantes típicas de un mismo código: sufijo numérico (MAQ/MAQ2) o prefijo Y (URO/YURO). Solo heurística."""
    def core(t: str) -> str:
        t = re.sub(r"\d+$", "", t)
        return t[1:] if t.startswith("Y") and len(t) > 3 else t
    return a != b and core(a) == core(b)


def _tax_conflict(a: _Rec, b: _Rec) -> bool:
    return (a.tax.status is IdentifierStatus.UNVERIFIED and b.tax.status is IdentifierStatus.UNVERIFIED
            and a.tax.normalized != b.tax.normalized)


def classify_pair(a: _Rec, b: _Rec) -> RelationRecord:
    shared_lei = bool(a.lei.normalized) and a.lei.normalized == b.lei.normalized
    shared_tax = bool(a.tax.normalized) and a.tax.normalized == b.tax.normalized
    same_name = bool(a.name_n) and a.name_n == b.name_n
    tconf = _tax_conflict(a, b)
    ev = [f"lei_a={a.lei.normalized or '-'}[{a.lei.status.value}]", f"lei_b={b.lei.normalized or '-'}[{b.lei.status.value}]",
          f"tax_a={a.tax.normalized or '-'}[{a.tax.status.value}]", f"tax_b={b.tax.normalized or '-'}[{b.tax.status.value}]",
          f"same_name={same_name}", f"shared_lei={shared_lei}", f"shared_tax={shared_tax}"]
    R, C, S = DuplicateRelation, IdentityConfidence, IdentityReviewStatus

    def rel(relation, conf, review, rule):
        return RelationRecord(a.ref, b.ref, relation, conf, review, rule, tuple(ev))

    if shared_lei and a.lei.status is IdentifierStatus.VALID:
        if tconf:
            return rel(R.IDENTIFIER_CONFLICT, C.LOW, S.SHARED_IDENTIFIER_CONFLICT, "R1a:valid_lei_shared_but_tax_conflict")
        if same_name:
            return rel(R.MULTIPLE_INSTRUMENTS_SAME_ENTITY, C.HIGH, S.NO_REVIEW_REQUIRED, "R1b:valid_lei_shared_same_name")
        return rel(R.SAME_ENTITY_POSSIBLE, C.MEDIUM, S.POSSIBLE_SAME_ENTITY, "R1c:valid_lei_shared_names_differ")
    if shared_lei:       # LEI compartido pero inválido: no es evidencia de identidad
        return rel(R.IDENTIFIER_CONFLICT, C.LOW, S.SHARED_IDENTIFIER_CONFLICT, "R2:invalid_lei_shared")
    if shared_tax:
        if same_name:
            return rel(R.SAME_ENTITY_POSSIBLE, C.LOW, S.MANUAL_REVIEW_REQUIRED, "R3a:tax_shared_same_name")
        return rel(R.IDENTIFIER_CONFLICT, C.LOW, S.SHARED_IDENTIFIER_CONFLICT, "R3b:tax_shared_names_differ")
    if same_name:
        both_valid = a.lei.status is IdentifierStatus.VALID and b.lei.status is IdentifierStatus.VALID
        if both_valid and tconf:
            return rel(R.SAME_NAME_DIFFERENT_ENTITY, C.MEDIUM, S.MANUAL_REVIEW_REQUIRED, "R4a:distinct_valid_leis_and_tax")
        if both_valid:
            return rel(R.UNRESOLVED, C.UNRESOLVED, S.MANUAL_REVIEW_REQUIRED, "R4b:distinct_valid_leis_same_name")
        if tconf:
            return rel(R.IDENTIFIER_CONFLICT, C.LOW, S.MANUAL_REVIEW_REQUIRED, "R5a:same_name_tax_conflict_lei_not_usable")
        if _ticker_variant(a.ticker, b.ticker):
            return rel(R.TICKER_CHANGE_POSSIBLE, C.LOW, S.MANUAL_REVIEW_REQUIRED, "R5b:same_name_ticker_variant_defective_ids")
        return rel(R.SAME_ENTITY_POSSIBLE, C.LOW, S.MANUAL_REVIEW_REQUIRED, "R5c:same_name_defective_ids")
    return rel(R.NOT_DUPLICATE, C.LOW, S.NO_REVIEW_REQUIRED, "R0:no_shared_signal")


def _read(records: Iterable[Mapping[str, Any]], country: str, source: str, version: Optional[str]) -> List[_Rec]:
    out: List[_Rec] = []
    seen: Dict[str, int] = {}
    for r in records:
        ticker = normalize_ticker(r.get("ticker"))
        if not ticker:
            raise DomainValidationError("registro de catálogo sin ticker: no se puede trazar al origen")
        seen[ticker] = seen.get(ticker, 0) + 1
        ref = f"{source}:{version + ':' if version else ''}{ticker}" + (f"#{seen[ticker]}" if seen[ticker] > 1 else "")
        name = str(r.get("name_legal") or r.get("legal_name") or "").strip()
        out.append(_Rec(
            ref=ref, ticker=ticker, name=name, name_n=normalize_legal_name(name),
            lei=check_lei(r.get("lei")), tax=check_tax_id(r.get("cif_nif") or r.get("cif"), country),
            isin=check_isin(r.get("isin")), is_socimi=bool(r.get("is_socimi")),
            market=r.get("market") or r.get("segment"), mic=r.get("mic"),
            valid_from=r.get("valid_from"), valid_to=r.get("valid_to"), status=str(r.get("listing_status") or "UNKNOWN")))
    return out


def resolve_identities(records: Iterable[Mapping[str, Any]], *, country: str = "ES",
                       source: str = "master_universe_es", source_version: Optional[str] = None) -> IdentityResolution:
    recs = sorted(_read(records, country, source, source_version),
                  key=lambda x: (x.ticker, x.name_n, x.lei.normalized, x.tax.normalized, x.ref))
    by_ref = {r.ref: r for r in recs}
    issues: List[IdentityIssue] = []

    # --- incidencias por registro ---
    for r in recs:
        if r.lei.status in (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM):
            issues.append(IdentityIssue(f"LEI_{r.lei.status.value}", "WARNING", r.ref,
                                        f"LEI {r.lei.raw!r} no utilizable para identidad ({r.lei.error})"))
        elif r.lei.status is IdentifierStatus.MISSING:
            issues.append(IdentityIssue("LEI_MISSING", "WARNING", r.ref, "sin LEI"))
        if r.tax.status is IdentifierStatus.INVALID_FORMAT:
            issues.append(IdentityIssue("TAX_ID_INVALID_FORMAT", "WARNING", r.ref, f"identificador fiscal {r.tax.raw!r} con forma desconocida"))
            if check_isin(r.tax.normalized).status is IdentifierStatus.VALID:
                issues.append(IdentityIssue("TAX_FIELD_CONTAINS_ISIN", "INFO", r.ref,
                                            f"el campo fiscal contiene un ISIN válido ({r.tax.normalized}); no se reasigna automáticamente"))
        elif r.tax.status is IdentifierStatus.MISSING:
            issues.append(IdentityIssue("TAX_ID_MISSING", "WARNING", r.ref, "sin identificador fiscal"))
        if r.isin.status in (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM):
            issues.append(IdentityIssue("ISIN_INVALID", "WARNING", r.ref, f"ISIN {r.isin.raw!r} inválido ({r.isin.error})"))
        if "#" in r.ref:
            issues.append(IdentityIssue("DUPLICATE_TICKER", "ERROR", r.ref, "ticker repetido en el catálogo de entrada"))

    # --- relaciones candidatas (por señal compartida; nunca por similitud difusa) ---
    signals: Dict[Tuple[str, str], List[str]] = {}
    for r in recs:
        for kind, val in (("lei", r.lei.normalized), ("tax", r.tax.normalized), ("name", r.name_n)):
            if val:
                signals.setdefault((kind, val), []).append(r.ref)
    pairs = sorted({tuple(sorted(p)) for refs in signals.values() if len(refs) > 1
                    for p in itertools.combinations(refs, 2)})
    relations = tuple(classify_pair(by_ref[a], by_ref[b]) for a, b in pairs)

    # --- agrupación: única fusión automática = mismo LEI válido sin conflicto fiscal ---
    group_of: Dict[str, List[str]] = {}
    for r in recs:
        if r.lei.status is IdentifierStatus.VALID:
            group_of.setdefault(r.lei.normalized, []).append(r.ref)
    entity_of: Dict[str, Tuple[str, IdentityConfidence]] = {}
    for lei, refs in sorted(group_of.items()):
        conflict = any(_tax_conflict(by_ref[a], by_ref[b]) for a, b in itertools.combinations(refs, 2))
        if conflict:
            for ref in refs:
                issues.append(IdentityIssue("SHARED_VALID_LEI_WITH_TAX_CONFLICT", "ERROR", ref,
                                            f"LEI válido {lei} compartido con identificadores fiscales distintos: no se agrupa"))
            continue
        for ref in refs:
            entity_of[ref] = (entity_id_from_lei(lei), IdentityConfidence.HIGH)
    for r in recs:
        if r.ref not in entity_of:
            entity_of[r.ref] = provisional_entity_id(country=country, normalized_name=r.name_n,
                                                     lei_normalized=r.lei.normalized, tax_normalized=r.tax.normalized,
                                                     source_record_key=r.ref)

    # --- revisión por entidad ---
    review_of: Dict[str, IdentityReviewStatus] = {}

    def bump(ref: str, status: IdentityReviewStatus):
        cur = review_of.get(ref, IdentityReviewStatus.NO_REVIEW_REQUIRED)
        if _REVIEW_PRIORITY[status] > _REVIEW_PRIORITY[cur]:
            review_of[ref] = status

    for r in recs:
        if r.lei.status in (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM) \
                or r.tax.status is IdentifierStatus.INVALID_FORMAT:
            bump(r.ref, IdentityReviewStatus.INVALID_IDENTIFIER)
        elif entity_of[r.ref][1] is not IdentityConfidence.HIGH:
            bump(r.ref, IdentityReviewStatus.INSUFFICIENT_EVIDENCE)
    for rel in relations:
        if rel.relation in (DuplicateRelation.NOT_DUPLICATE, DuplicateRelation.MULTIPLE_INSTRUMENTS_SAME_ENTITY):
            continue
        for ref in (rel.source_reference_a, rel.source_reference_b):
            bump(ref, rel.review_status)

    # --- entidades e instrumentos ---
    members: Dict[str, List[_Rec]] = {}
    for r in recs:
        members.setdefault(entity_of[r.ref][0], []).append(r)
    entities: List[LegalEntity] = []
    for eid, rs in sorted(members.items()):
        first = rs[0]
        tax_src = next((x for x in rs if x.tax.status is not IdentifierStatus.MISSING), first)
        names = {x.name_n for x in rs}
        review = max((review_of.get(x.ref, IdentityReviewStatus.NO_REVIEW_REQUIRED) for x in rs),
                     key=lambda s: _REVIEW_PRIORITY[s])
        if len(names) > 1:
            issues.append(IdentityIssue("ENTITY_NAMES_DIFFER", "INFO", first.ref,
                                        f"instrumentos de {eid} con razones sociales distintas (¿cambio de nombre?)"))
            if _REVIEW_PRIORITY[review] < _REVIEW_PRIORITY[IdentityReviewStatus.POSSIBLE_SAME_ENTITY]:
                review = IdentityReviewStatus.POSSIBLE_SAME_ENTITY
        entities.append(LegalEntity(
            entity_id=eid, legal_name=first.name, normalized_legal_name=first.name_n, country=country.upper(),
            lei_raw=first.lei.raw, lei_normalized=first.lei.normalized, lei_status=first.lei.status,
            local_tax_id_raw=tax_src.tax.raw, local_tax_id_normalized=tax_src.tax.normalized,
            local_tax_id_status=tax_src.tax.status, is_socimi=any(x.is_socimi for x in rs),
            identity_confidence=entity_of[first.ref][1], source_references=tuple(sorted(x.ref for x in rs)),
            review_status=review))
    instruments = tuple(sorted((ListedInstrument(
        instrument_id=instrument_id_for(isin_check=r.isin, mic=r.mic, ticker=r.ticker, valid_from=r.valid_from,
                                        source=source, source_key=r.ref.split(":", 1)[1]),
        entity_id=entity_of[r.ref][0], ticker=r.ticker, mic=r.mic, market=r.market,
        isin=r.isin.normalized or None, valid_from=r.valid_from, valid_to=r.valid_to, listing_status=r.status,
        source_reference=r.ref) for r in recs), key=lambda i: i.source_reference))

    res = IdentityResolution(entities=tuple(entities), instruments=instruments, relations=relations,
                             issues=tuple(sorted(issues, key=lambda i: (i.source_reference, i.code, i.detail))))
    res.metrics.update(compute_metrics(recs, res, entity_of))
    return res


def compute_metrics(recs: Sequence[_Rec], res: IdentityResolution,
                    entity_of: Mapping[str, Tuple[str, IdentityConfidence]]) -> Dict[str, Any]:
    def dist(values):
        d: Dict[str, int] = {}
        for v in values:
            d[str(v)] = d.get(str(v), 0) + 1
        return dict(sorted(d.items()))

    def repeated(values):
        c: Dict[str, int] = {}
        for v in values:
            if v:
                c[v] = c.get(v, 0) + 1
        return {k: n for k, n in c.items() if n > 1}

    leis = [r.lei.normalized for r in recs]
    taxes = [r.tax.normalized for r in recs]
    isins = [r.isin.normalized for r in recs]
    rep_lei, rep_tax, rep_isin = repeated(leis), repeated(taxes), repeated(isins)
    soc = [r for r in recs if r.is_socimi]
    ents = res.entities
    socimi_ents = [e for e in ents if e.is_socimi]
    # cota inferior informativa: si TODAS las parejas "posibles" de SOCIMIs fueran la misma entidad
    parent: Dict[str, str] = {e.entity_id: e.entity_id for e in socimi_ents}
    ref_entity = {r.ref: entity_of[r.ref][0] for r in recs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    poss = (DuplicateRelation.SAME_ENTITY_POSSIBLE, DuplicateRelation.TICKER_CHANGE_POSSIBLE)
    soc_pairs = [rel for rel in res.relations if rel.relation in poss and rel.source_reference_a in
                 {r.ref for r in soc} and rel.source_reference_b in {r.ref for r in soc}]
    for rel in soc_pairs:
        a, b = find(ref_entity[rel.source_reference_a]), find(ref_entity[rel.source_reference_b])
        if a != b:
            parent[a] = b
    return {
        "catalog_record_count": len(recs),
        "listing_count": len(res.instruments),
        "unique_ticker_count": len({r.ticker for r in recs}),
        "unique_normalized_legal_name_count": len({r.name_n for r in recs if r.name_n}),
        "lei_present_count": sum(1 for r in recs if r.lei.status is not IdentifierStatus.MISSING),
        "lei_valid_count": sum(1 for r in recs if r.lei.status is IdentifierStatus.VALID),
        "lei_invalid_count": sum(1 for r in recs if r.lei.status in (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM)),
        "lei_invalid_format_count": sum(1 for r in recs if r.lei.status is IdentifierStatus.INVALID_FORMAT),
        "lei_invalid_checksum_count": sum(1 for r in recs if r.lei.status is IdentifierStatus.INVALID_CHECKSUM),
        "lei_repeated_value_count": len(rep_lei), "lei_repeated_record_count": sum(rep_lei.values()),
        "tax_id_present_count": sum(1 for r in recs if r.tax.status is not IdentifierStatus.MISSING),
        "tax_id_invalid_format_count": sum(1 for r in recs if r.tax.status is IdentifierStatus.INVALID_FORMAT),
        "tax_id_repeated_value_count": len(rep_tax), "tax_id_repeated_record_count": sum(rep_tax.values()),
        "isin_present_count": sum(1 for r in recs if r.isin.status is not IdentifierStatus.MISSING),
        "isin_repeated_value_count": len(rep_isin),
        "socimi_record_count": len(soc),
        "socimi_listing_count": sum(1 for i in res.instruments if any(r.ref == i.source_reference and r.is_socimi for r in recs)),
        "socimi_unique_ticker_count": len({r.ticker for r in soc}),
        "socimi_entity_count_current_resolution": len(socimi_ents),
        "socimi_entity_count_if_possible_pairs_merged_lower_bound": len({find(e.entity_id) for e in socimi_ents}),
        "socimi_possible_duplicate_pair_count": len(soc_pairs),
        "records_without_reliable_identifier": sum(1 for r in recs if r.lei.status is not IdentifierStatus.VALID),
        "name_collision_pair_count": sum(1 for rel in res.relations if "same_name=True" in rel.evidence),
        "identifier_conflict_pair_count": sum(1 for rel in res.relations if rel.relation is DuplicateRelation.IDENTIFIER_CONFLICT),
        "entity_count": len(ents),
        "confirmed_entity_count": sum(1 for e in ents if e.identity_confidence is IdentityConfidence.CONFIRMED),
        "high_confidence_entity_count": sum(1 for e in ents if e.identity_confidence is IdentityConfidence.HIGH),
        "provisional_entity_count": sum(1 for e in ents if e.identity_confidence is IdentityConfidence.LOW),
        "unresolved_identity_count": sum(1 for e in ents if e.identity_confidence is IdentityConfidence.UNRESOLVED),
        "market_distribution": dist(r.market for r in recs),
        "listing_status_distribution": dist(r.status for r in recs),
        "review_status_distribution": dist(e.review_status.value for e in ents),
        "relation_distribution": dist(rel.relation.value for rel in res.relations),
    }
