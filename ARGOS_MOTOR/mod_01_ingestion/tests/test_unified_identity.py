"""
U3 — Identidad de emisores e instrumentos: validadores, resolvedor offline y perfil del catálogo v4.0.0.
Offline, sin red; el catálogo real se lee en SOLO LECTURA y se comprueba su hash antes/después.
"""
import copy
import hashlib
import json
import random
from pathlib import Path

import pytest

from mod_01_ingestion.src.unified.application.identity_resolver import resolve_identities
from mod_01_ingestion.src.unified.domain.enums import (
    DuplicateRelation, IdentifierStatus, IdentityConfidence, IdentityReviewStatus)
from mod_01_ingestion.src.unified.domain.errors import DomainValidationError
from mod_01_ingestion.src.unified.domain.identity import (
    check_isin, check_lei, check_tax_id, instrument_id_for, normalize_legal_name, normalize_lei, normalize_ticker,
    provisional_entity_id)

CATALOG = Path(__file__).resolve().parents[2] / "config" / "master_universe_es.json"


def make_lei(base18: str) -> str:
    """LEI sintético VÁLIDO (calcula los dígitos de control ISO 17442) para fixtures."""
    expanded = int("".join(str(int(c, 36)) for c in base18 + "00"))
    return f"{base18}{98 - expanded % 97:02d}"


LEI_A, LEI_B = make_lei("ABCDEFGH12345678AB"), make_lei("ZYXWVUTS98765432ZY")


def rec(ticker, name, lei=None, cif="A39000013", socimi=False, segment="MERCADO_CONTINUO", **kw):
    return {"ticker": ticker, "name_legal": name, "lei": lei, "cif_nif": cif, "is_socimi": socimi, "segment": segment, **kw}


# ============================================================== validadores (1-6)
def test_lei_valid_accepted():
    for v in ("HWUPKR0MPOU8FGXBT394", "5493006QMFDDMYWIAM13", LEI_A, " hwupkr0mpou8fgxbt394 "):
        c = check_lei(v)
        assert c.status is IdentifierStatus.VALID and c.checksum_ok is True and c.usable_for_identity


@pytest.mark.parametrize("bad,err", [("959800201400051783", "LENGTH_18"), ("959800KVCD3WK0L9A989X", "LENGTH_21"),
                                    ("HWUPKR0MPOU8FGXBT39-", "INVALID_CHARACTERS"), ("HWUPKR0MPOU8FGXBT3AB", "BAD_CHECK_DIGITS_FORMAT")])
def test_lei_bad_format_rejected(bad, err):
    c = check_lei(bad)
    assert c.status is IdentifierStatus.INVALID_FORMAT and c.error == err and not c.usable_for_identity


def test_lei_bad_checksum_rejected_and_raw_preserved():
    raw = "HWUPKR0MPOU8FGXBT395"                   # un dígito cambiado
    c = check_lei(raw)
    assert c.status is IdentifierStatus.INVALID_CHECKSUM and c.checksum_ok is False and not c.usable_for_identity
    assert c.raw == raw and c.normalized == raw and c.length == 20      # el valor no se corrige por similitud
    assert check_lei(None).status is IdentifierStatus.MISSING and check_lei("  ").status is IdentifierStatus.MISSING


def test_invalid_lei_is_kept_raw_in_entity_and_never_identity():
    bad = "HWUPKR0MPOU8FGXBT395"
    res = resolve_identities([rec("AAA", "Alfa S.A.", lei=bad)])
    e = res.entities[0]
    assert e.lei_raw == bad and e.lei_status is IdentifierStatus.INVALID_CHECKSUM
    assert not e.entity_id.startswith("entity:lei:")
    assert e.identity_confidence is IdentityConfidence.LOW and e.review_status is IdentityReviewStatus.INVALID_IDENTIFIER


def test_isin_validation_and_normalization():
    assert check_isin("es0113900j37").status is IdentifierStatus.VALID
    assert check_isin("US0378331005").status is IdentifierStatus.VALID
    assert check_isin("ES0113900J38").status is IdentifierStatus.INVALID_CHECKSUM
    assert check_isin("XX").status is IdentifierStatus.INVALID_FORMAT
    assert check_isin(None).status is IdentifierStatus.MISSING


def test_tax_id_is_never_valid_without_reliable_logic_and_ticker_is_not_entity_id():
    assert check_tax_id("A-39000013").status is IdentifierStatus.UNVERIFIED          # forma plausible, sin checksum
    assert check_tax_id("1000372900652").status is IdentifierStatus.INVALID_FORMAT
    assert check_tax_id("").status is IdentifierStatus.MISSING
    assert normalize_ticker(" sa n ") == "SAN"
    res = resolve_identities([rec("SAN", "Banco Santander, S.A.", lei="5493006QMFDDMYWIAM13")])
    assert "SAN" not in res.entities[0].entity_id and res.entities[0].entity_id == "entity:lei:5493006QMFDDMYWIAM13"
    assert res.instruments[0].ticker == "SAN" and res.instruments[0].entity_id == res.entities[0].entity_id


# ============================================================== identidad (7-16)
def test_two_instruments_can_point_to_one_entity_via_valid_lei():
    res = resolve_identities([rec("AAA", "Alfa S.A.", lei=LEI_A), rec("AAA2", "Alfa S.A.", lei=LEI_A)])
    assert len(res.entities) == 1 and len(res.instruments) == 2
    assert {i.entity_id for i in res.instruments} == {res.entities[0].entity_id}
    assert res.relations[0].relation is DuplicateRelation.MULTIPLE_INSTRUMENTS_SAME_ENTITY
    assert res.entities[0].identity_confidence is IdentityConfidence.HIGH            # nunca CONFIRMED offline
    assert all(e.identity_confidence is not IdentityConfidence.CONFIRMED for e in res.entities)


def test_same_name_alone_never_merges():
    res = resolve_identities([rec("AAA", "Alfa S.A.", lei=LEI_A, cif="A39000013"),
                              rec("BBB", "ALFA, S.A.", lei=LEI_B, cif="A28000727")])
    assert len(res.entities) == 2
    assert normalize_legal_name("Alfa S.A.") == normalize_legal_name("ALFA, S.A.")
    assert res.relations[0].relation in (DuplicateRelation.SAME_NAME_DIFFERENT_ENTITY, DuplicateRelation.UNRESOLVED)
    assert res.relations[0].review_status is IdentityReviewStatus.MANUAL_REVIEW_REQUIRED


def test_same_ticker_in_different_markets_is_not_merged():
    res = resolve_identities([rec("ABC", "Uno S.A.", lei=LEI_A, segment="IBEX35", mic="XMAD"),
                              rec("ABC", "Otro S.A.", lei=LEI_B, segment="OTRO", mic="XPAR")])
    assert len(res.entities) == 2
    assert {i.instrument_id for i in res.instruments} == {"instrument:source:master_universe_es:ABC",
                                                          "instrument:source:master_universe_es:ABC#2"}
    assert any(i.code == "DUPLICATE_TICKER" for i in res.issues)                    # se señala, no se oculta


def test_shared_valid_lei_is_explained_and_conflicting_tax_blocks_grouping():
    ok = resolve_identities([rec("AAA", "Alfa S.A.", lei=LEI_A), rec("AAB", "Alfa Holding S.A.", lei=LEI_A)])
    assert len(ok.entities) == 1
    assert ok.relations[0].relation is DuplicateRelation.SAME_ENTITY_POSSIBLE
    assert ok.relations[0].rule == "R1c:valid_lei_shared_names_differ"
    assert ok.entities[0].review_status is IdentityReviewStatus.POSSIBLE_SAME_ENTITY
    assert any(i.code == "ENTITY_NAMES_DIFFER" for i in ok.issues)
    bad = resolve_identities([rec("AAA", "Alfa S.A.", lei=LEI_A, cif="A39000013"),
                              rec("AAB", "Alfa S.A.", lei=LEI_A, cif="B28000727")])
    assert len(bad.entities) == 2                                                   # conflicto fiscal: no se agrupan
    assert bad.relations[0].relation is DuplicateRelation.IDENTIFIER_CONFLICT
    assert {e.review_status for e in bad.entities} == {IdentityReviewStatus.SHARED_IDENTIFIER_CONFLICT}
    assert not any(e.entity_id.startswith("entity:lei:") for e in bad.entities)


def test_shared_invalid_lei_never_merges():
    inv = "959800201400051783"                                                      # 18 caracteres
    res = resolve_identities([rec("ACS", "ACS Actividades S.A.", lei=inv, cif="A28000727"),
                              rec("FCC", "Fomento Construcciones S.A.", lei=inv, cif="A28037224")])
    assert len(res.entities) == 2 and res.relations[0].relation is DuplicateRelation.IDENTIFIER_CONFLICT
    assert res.relations[0].rule == "R2:invalid_lei_shared"


def test_conflicting_cif_generates_review():
    res = resolve_identities([rec("AAA", "Alfa S.A.", lei="BAD1", cif="A39000013"),
                              rec("AAB", "Alfa S.A.", lei="BAD2", cif="B28000727")])
    assert res.relations[0].relation is DuplicateRelation.IDENTIFIER_CONFLICT
    assert res.relations[0].review_status is IdentityReviewStatus.MANUAL_REVIEW_REQUIRED
    shared_cif = resolve_identities([rec("AAA", "Alfa S.A."), rec("BBB", "Beta S.A.")])
    assert shared_cif.relations[0].relation is DuplicateRelation.IDENTIFIER_CONFLICT and len(shared_cif.entities) == 2


def test_resolver_is_deterministic_idempotent_and_does_not_mutate_input():
    data = [rec("AAA", "Alfa S.A.", lei=LEI_A), rec("AAB", "Alfa S.A.", lei=LEI_A),
            rec("CCC", "Gamma S.A.", lei="XX"), rec("DDD", "Gamma S.A.", lei="YY", cif="B28000727"),
            rec("EEE", "Eps S.A.", lei=None, cif=None)]
    snapshot = copy.deepcopy(data)
    first = resolve_identities(data)
    assert data == snapshot                                                          # entrada intacta
    assert resolve_identities(data) == first                                         # determinista
    shuffled = data[:]
    random.Random(7).shuffle(shuffled)
    assert resolve_identities(shuffled) == first                                     # independiente del orden
    assert resolve_identities(copy.deepcopy(snapshot)).metrics == first.metrics      # idempotente


def test_fallback_never_uses_only_name_or_ticker():
    eid1, c1 = provisional_entity_id(country="ES", normalized_name="ALFA", lei_normalized="", tax_normalized="",
                                     source_record_key="s:AAA")
    eid2, _ = provisional_entity_id(country="ES", normalized_name="ALFA", lei_normalized="", tax_normalized="",
                                    source_record_key="s:BBB")
    assert eid1 != eid2 and c1 is IdentityConfidence.UNRESOLVED                      # sin ids: nunca CONFIRMED/HIGH
    _, c2 = provisional_entity_id(country="ES", normalized_name="ALFA", lei_normalized="BAD", tax_normalized="",
                                  source_record_key="s:AAA")
    assert c2 is IdentityConfidence.LOW
    assert instrument_id_for(isin_check=check_isin("ES0113900J37"), mic="XMAD", ticker="SAN", valid_from=None,
                             source="x", source_key="SAN") == "instrument:isin:ES0113900J37"
    assert instrument_id_for(isin_check=check_isin(None), mic="xmad", ticker="san", valid_from="2020-01-01",
                             source="x", source_key="SAN") == "instrument:listing:XMAD:SAN:2020-01-01"
    with pytest.raises(DomainValidationError):
        resolve_identities([{"name_legal": "Sin ticker"}])


def test_ticker_variant_rule_is_only_a_possibility():
    a = rec("URO", "Uro Properties S.A.", lei="BAD1", cif="1000280743966", socimi=True)
    b = rec("YURO", "Uro Properties S.A.", lei="BAD2", cif="A87006524", socimi=True)
    r = resolve_identities([a, b]).relations[0]
    assert r.relation is DuplicateRelation.TICKER_CHANGE_POSSIBLE and r.confidence is IdentityConfidence.LOW
    assert r.review_status is IdentityReviewStatus.MANUAL_REVIEW_REQUIRED
    assert DuplicateRelation.SAME_ENTITY_CONFIRMED not in {x.relation for x in resolve_identities([a, b]).relations}


# ============================================================== catálogo v4.0.0 real, solo lectura (17-20)
@pytest.fixture(scope="module")
def catalog():
    before = hashlib.sha256(CATALOG.read_bytes()).hexdigest()
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    res = resolve_identities(data["companies"].values(), source_version=data["version"])
    yield data, res
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest() == before               # el catálogo no se toca


def test_socimi_records_and_listings_are_preserved_not_claimed_as_entities(catalog):
    data, res = catalog
    expected = sum(1 for c in data["companies"].values() if c["is_socimi"])
    m = res.metrics
    assert m["socimi_record_count"] == m["socimi_listing_count"] == m["socimi_unique_ticker_count"] == expected
    assert m["catalog_record_count"] == m["listing_count"] == len(data["companies"])
    assert m["confirmed_entity_count"] == 0                                          # nada se confirma sin contraste externo
    assert m["socimi_entity_count_if_possible_pairs_merged_lower_bound"] <= m["socimi_entity_count_current_resolution"] <= expected
    assert all(i.entity_id for i in res.instruments) and len(res.instruments) == len(data["companies"])


def test_is_socimi_flag_is_preserved(catalog):
    data, res = catalog
    soc_tickers = {t for t, c in data["companies"].items() if c["is_socimi"]}
    ent = {e.entity_id: e for e in res.entities}
    assert {i.ticker for i in res.instruments if ent[i.entity_id].is_socimi} == soc_tickers


FIVE = [("CAST", "YCPS"), ("MAQ", "MAQ2"), ("SILI", "YSIL"), ("TORB", "TORB2"), ("URO", "YURO")]


def test_five_socimi_pairs_stay_in_review_and_are_not_merged(catalog):
    data, res = catalog
    by_ticker = {i.ticker: i for i in res.instruments}
    allowed = {DuplicateRelation.MULTIPLE_INSTRUMENTS_SAME_ENTITY, DuplicateRelation.TICKER_CHANGE_POSSIBLE,
               DuplicateRelation.SAME_ENTITY_POSSIBLE, DuplicateRelation.SAME_NAME_DIFFERENT_ENTITY,
               DuplicateRelation.UNRESOLVED, DuplicateRelation.IDENTIFIER_CONFLICT}
    rels = {(r.source_reference_a.split(":")[-1], r.source_reference_b.split(":")[-1]): r for r in res.relations}
    for a, b in FIVE:
        assert a in by_ticker and b in by_ticker                                      # ningún registro eliminado
        assert by_ticker[a].entity_id != by_ticker[b].entity_id                       # ni fusionado
        r = rels[tuple(sorted((a, b)))]
        assert r.relation in allowed and r.relation is not DuplicateRelation.SAME_ENTITY_CONFIRMED
        assert r.review_status is IdentityReviewStatus.MANUAL_REVIEW_REQUIRED


def test_invalid_leis_are_excluded_from_strong_identity(catalog):
    data, res = catalog
    invalid_raw = {c["lei"] for c in data["companies"].values() if check_lei(c["lei"]).status in
                   (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM)}
    assert invalid_raw and res.metrics["lei_invalid_count"] == sum(
        1 for c in data["companies"].values() if c["lei"] in invalid_raw)
    for e in res.entities:
        if e.lei_status in (IdentifierStatus.INVALID_FORMAT, IdentifierStatus.INVALID_CHECKSUM):
            assert not e.entity_id.startswith("entity:lei:") and e.lei_raw in invalid_raw
    assert normalize_lei(" x ") == "X"
