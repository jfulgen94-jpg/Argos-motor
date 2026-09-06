"""
Tests unitarios para MOD_06: API Gateway FastAPI.
Prueba endpoints /health, /companies/{lei}/financials y /companies/{lei}/valuation.
"""
import pytest
from fastapi.testclient import TestClient
from datetime import date
import tempfile
from pathlib import Path

from mod_06_api_gateway.src.main import app, lake


@pytest.fixture
def client_with_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_api.duckdb"
        lake.db_path = test_db
        lake.init_database()
        
        # Insert test data
        sample_record = {
            "entity_lei": "TEST_LEI_12345",
            "fiscal_year": 2024,
            "ticker": "TEST",
            "company_name": "Test Global Corp",
            "source_market": "US",
            "reporting_currency": "USD",
            "accounting_standard": "US-GAAP",
            "period_end_date": date(2024, 12, 31),
            "total_activo": 10000.0,
            "total_pasivo": 6000.0,
            "patrimonio_neto": 4000.0,
            "revenue": 12000.0,
            "beneficio_neto": 1500.0,
            "cfo": 2000.0,
            "capex": 500.0,
            "fcf": 1500.0,
            "deuda_financiera_lp": 1000.0,
            "deuda_financiera_cp": 500.0,
            "efectivo_y_equivalentes": 300.0,
        }
        lake.upsert_financial_panel_record(sample_record)
        
        test_client = TestClient(app)
        yield test_client


def test_health_endpoint(client_with_db):
    response = client_with_db.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["duckdb_connected"] is True


def test_get_financials_success(client_with_db):
    response = client_with_db.get("/companies/TEST_LEI_12345/financials?year=2024")
    assert response.status_code == 200
    data = response.json()
    assert data["entity_lei"] == "TEST_LEI_12345"
    assert data["balance_check"] is True
    assert data["total_activo"] == 10000.0


def test_get_financials_not_found(client_with_db):
    response = client_with_db.get("/companies/NON_EXISTING/financials?year=2024")
    assert response.status_code == 404


def test_get_valuation_success(client_with_db):
    response = client_with_db.get("/companies/TEST_LEI_12345/valuation?year=2024&shares=100000")
    assert response.status_code == 200
    data = response.json()
    assert data["entity_lei"] == "TEST_LEI_12345"
    assert data["fair_value_per_share"] > 0
    assert "sensitivity_matrix" in data
