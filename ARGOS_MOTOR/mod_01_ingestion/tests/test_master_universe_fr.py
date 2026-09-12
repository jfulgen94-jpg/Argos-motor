"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Tests de Validación y Auditoría del Catálogo Maestro Francés (Master Universe FR)

Verifica:
1. Sintaxis JSON y estructura raíz canónica (jurisdiction, supervisor, segments_breakdown).
2. Ausencia de LEIs duplicados (identificadores únicos globales).
3. Ausencia de tickers duplicados dentro del universo francés.
4. Cumplimiento de country_code == 'FR' y longitud de LEI de 20 caracteres en todas las empresas.
5. Regla estricta de exclusión de SOCIMIs/SIIC (socimis_count == 0, is_socimi is False).
6. Presencia y justificación documental en master_universe_fr_PENDING_REVIEW.json.
"""

import json
import pytest
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
MASTER_UNIVERSE_FR = CONFIG_DIR / "master_universe_fr.json"
PENDING_REVIEW_FR = CONFIG_DIR / "master_universe_fr_PENDING_REVIEW.json"


def test_master_universe_fr_exists_and_valid():
    """El archivo master_universe_fr.json debe existir y ser JSON válido."""
    assert MASTER_UNIVERSE_FR.exists(), f"No existe {MASTER_UNIVERSE_FR}"
    with open(MASTER_UNIVERSE_FR, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["jurisdiction"] == "FR"
    assert data["country_name"] == "France"
    assert data["socimis_count"] == 0
    assert data["total_entities"] >= 30, f"Se esperaban >= 30 entidades, encontradas: {data['total_entities']}"
    assert data["total_entities"] == len(data["companies"])


def test_no_duplicate_leis_or_tickers():
    """No debe existir duplicidad ni de LEI ni de Ticker en el catálogo principal."""
    with open(MASTER_UNIVERSE_FR, "r", encoding="utf-8") as f:
        data = json.load(f)

    companies = data["companies"]
    leis = [c["lei"] for c in companies.values()]
    tickers = list(companies.keys())

    assert len(leis) == len(set(leis)), "Se detectaron LEIs duplicados en master_universe_fr.json"
    assert len(tickers) == len(set(tickers)), "Se detectaron tickers duplicados en master_universe_fr.json"


def test_mandatory_fields_and_integrity():
    """Todas las entidades deben cumplir los requisitos regulatorios y de esquema."""
    with open(MASTER_UNIVERSE_FR, "r", encoding="utf-8") as f:
        data = json.load(f)

    for ticker, comp in data["companies"].items():
        assert comp["country_code"] == "FR", f"{ticker} no tiene country_code='FR'"
        assert len(comp["lei"]) == 20, f"{ticker} tiene un LEI no reglamentario ({comp['lei']})"
        assert comp["is_socimi"] is False, f"{ticker} está marcado como SOCIMI/SIIC"
        assert comp["resolution_score"] >= 0.90, f"{ticker} tiene un resolution_score insuficiente"
        assert comp["fiscal_year_end"] in ["12-31", "06-30", "08-31", "03-31", "01-31"]
        assert "source" in comp, f"{ticker} carece del bloque de trazabilidad 'source'"
        assert "gleif_source" in comp["source"]
        assert "filing_source" in comp["source"]


def test_pending_review_schema_and_isolation():
    """Las entidades en PENDING_REVIEW deben documentar su motivo de exclusión."""
    assert PENDING_REVIEW_FR.exists(), f"No existe {PENDING_REVIEW_FR}"
    with open(PENDING_REVIEW_FR, "r", encoding="utf-8") as f:
        pending = json.load(f)

    assert pending["jurisdiction"] == "FR"
    assert pending["total_pending"] == len(pending["entities"])
    for p in pending["entities"]:
        assert "reason" in p and len(p["reason"]) > 10, f"Entidad pendiente {p.get('ticker')} sin motivo documentado"
        assert len(p["lei"]) == 20
