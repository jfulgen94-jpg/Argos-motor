"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Tests Unitarios para Completación del Catálogo Maestro (--fill-gap)

Verifica:
1. Idempotencia y no duplicación de entidades en ejecuciones repetidas.
2. Manejo estricto de PENDING_REVIEW para entidades con score < 0.90.
3. Exclusión determinista de SOCIMIs del conteo total del universo operativo (socimis_count == 0).
4. Correcta preservación del esquema canónico institucional.
"""

import json
import pytest
from pathlib import Path
from mod_01_ingestion.src.master_universe_builder import (
    build_master_universe,
    fill_universe_gaps,
    MASTER_UNIVERSE_PATH,
    GAP_CANDIDATES
)


def test_fill_gap_idempotence():
    """Ejecutar fill_universe_gaps repetidas veces no genera duplicados ni corrompe el conteo."""
    res1 = fill_universe_gaps()
    total1 = res1["total_entities"]
    
    res2 = fill_universe_gaps()
    total2 = res2["total_entities"]
    
    assert total1 == total2
    assert len(res2["companies"]) == total2
    assert len(set(res2["companies"].keys())) == total2


def test_operational_universe_zero_socimis():
    """El universo operativo activo NUNCA debe contener SOCIMIs (socimis_count == 0)."""
    with open(MASTER_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["socimis_count"] == 0
    for ticker, comp in data["companies"].items():
        assert comp["is_socimi"] is False, f"La entidad {ticker} tiene is_socimi=True en el universo operativo"
        assert "SOCIMI" not in comp["segment"], f"Segmento inválido {comp['segment']} para {ticker}"


def test_pending_review_isolation(tmp_path, monkeypatch):
    """Entidades con score < 0.90 deben ir a PENDING_REVIEW y no al catálogo activo."""
    test_json = tmp_path / "master_universe_test.json"
    pending_json = tmp_path / "master_universe_es_PENDING_REVIEW.json"
    
    # Crear catálogo base
    base_payload = {
        "version": "3.0.0",
        "jurisdiction": "ES",
        "total_entities": 1,
        "segments_breakdown": {"IBEX35": 1, "MERCADO_CONTINUO": 0, "BME_GROWTH": 0},
        "socimis_count": 0,
        "companies": {
            "SAN": {
                "ticker": "SAN",
                "cif_nif": "A-39000013",
                "lei": "5493006QMFDDMYWIAM13",
                "name_legal": "Banco Santander, S.A.",
                "segment": "IBEX35",
                "is_socimi": False,
                "resolution_score": 1.0
            }
        }
    }
    with open(test_json, "w", encoding="utf-8") as f:
        json.dump(base_payload, f)

    # Mock de path
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.MASTER_UNIVERSE_PATH", test_json)
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.Path", 
                        lambda p: pending_json if "PENDING_REVIEW" in str(p) else Path(p))

    # Añadir un candidato de prueba con score < 0.90
    mock_candidates = [
        {
            "ticker": "DOUBTFUL_CO",
            "cif_nif": "",  # Sin CIF
            "lei": None,     # Sin LEI
            "name_legal": "Empresa No Verificada S.L.",
            "segment": "BME_GROWTH",
            "is_socimi": False,
            "fiscal_year_end": "12-31"
        }
    ]
    monkeypatch.setattr("mod_01_ingestion.src.master_universe_builder.GAP_CANDIDATES", mock_candidates)

    res = fill_universe_gaps()
    assert "DOUBTFUL_CO" not in res["companies"]
    assert res["total_entities"] == 1


def test_special_fiscal_year_ends_preserved():
    """Verifica que empresas con cierres fiscales atípicos (Logista, Inditex) están correctamente configuradas."""
    with open(MASTER_UNIVERSE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    comps = data["companies"]
    if "LOG" in comps:
        assert comps["LOG"]["fiscal_year_end"] == "09-30"
    if "ITX" in comps:
        assert comps["ITX"]["fiscal_year_end"] == "01-31"
    if "BKY" in comps:
        assert comps["BKY"]["fiscal_year_end"] == "06-30"
    if "ZOT" in comps:
        assert comps["ZOT"]["fiscal_year_end"] == "11-30"
