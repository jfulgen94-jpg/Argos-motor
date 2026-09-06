"""
STATER MOTOR ARGOS — MOD_01: Test de Regresión Histórica de Identidad (Entity Resolver).

Verifica que el algoritmo de resolución de entidad previene de forma determinista
la colisión histórica que causó la asignación de Prosegur a ACS, Repsol o Inditex.
"""

import pytest
from mod_01_ingestion.src.entity_resolver import (
    EntityResolver,
    compute_comprehensive_similarity,
    normalize_cif,
    normalize_entity_name
)


def test_regression_acs_never_resolves_to_prosegur():
    """Prueba fundamental: Buscar 'ACS' o su CIF NUNCA debe resolver a Prosegur."""
    resolver = EntityResolver()
    
    # 1. Búsqueda por Ticker ACS
    res_acs, score_acs, _ = resolver.resolve_entity("ACS", expected_cif="A-28004885")
    assert res_acs is not None
    assert res_acs["ticker"] == "ACS"
    assert "ACS" in res_acs["name_legal"]
    assert res_acs["cif_nif"] == "A-28004885"

    # 2. Búsqueda con nombre de Prosegur esperando ACS debe RECHAZARSE
    prosegur_text = "PROSEGUR COMPAÑIA DE SEGURIDAD SA CIF A-28424083"
    res_mismatch, score_mismatch, reason = resolver.resolve_entity(
        query=prosegur_text,
        expected_cif="A-28004885"  # CIF de ACS
    )
    assert res_mismatch is None
    assert score_mismatch < 0.30  # Penalización por CIF discordante


def test_cif_exact_match_priority():
    """El CIF exacto garantiza match con score 1.0."""
    score = compute_comprehensive_similarity(
        query_name="Cualquier Texto Desconocido",
        target_name="Banco Santander, S.A.",
        query_cif="A-39000013",
        target_cif="A-39000013"
    )
    assert score == 1.0


def test_resolve_bluechips_identities():
    """Resuelve identidades de los principales emisores sin ambigüedad."""
    resolver = EntityResolver()
    
    # Santander
    san_entity = resolver.get_by_ticker("SAN")
    assert san_entity is not None
    assert san_entity["cif_nif"] == "A-39000013"

    # Iberdrola
    ibe_entity, score_ibe, _ = resolver.resolve_entity("IBERDROLA SA")
    assert ibe_entity is not None
    assert ibe_entity["ticker"] == "IBE"

    # Inditex (por nombre alternativo)
    itx_entity, score_itx, _ = resolver.resolve_entity("INDITEX")
    assert itx_entity is not None
    assert itx_entity["ticker"] == "ITX"
