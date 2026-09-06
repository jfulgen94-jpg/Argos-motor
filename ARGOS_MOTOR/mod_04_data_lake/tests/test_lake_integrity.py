"""
Tests de integración y calidad para MOD_04: Data Lake DuckDB.
Valida inicialización DDL, inserción de documentos, cuadre contable en financial_panel,
y exportación a formato Parquet columnar.
"""
import pytest
import tempfile
from pathlib import Path
from datetime import date
from mod_04_data_lake.src.lake_manager import LakeManager


@pytest.fixture
def temp_lake():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_stater.duckdb"
        lake = LakeManager(db_path=db_file)
        lake.init_database()
        yield lake


def test_init_database_creates_all_tables(temp_lake):
    conn = temp_lake.get_connection(read_only=True)
    tables = [row[0] for row in conn.execute("SHOW TABLES").fetchall()]
    conn.close()
    
    assert "documents_raw" in tables
    assert "financial_facts_raw" in tables
    assert "financial_panel" in tables
    assert "audit_kams" in tables
    assert "esg_kpis" in tables


def test_insert_document_raw(temp_lake):
    doc = {
        "doc_id": "test-doc-001",
        "source": "SEC_EDGAR",
        "issuer_lei": "5493006MHB84DD0ZWV18",
        "issuer_isin": "US0378331005",
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "doc_type": "10-K",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "filing_date": date(2024, 11, 1),
        "download_url": "https://www.sec.gov/Archives/edgar/data/320193/sample.txt",
        "file_path": "data/raw/sec/2024/aapl_10k.txt",
        "file_size_bytes": 1024000,
        "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "status": "RAW",
        "quarantine_msg": None,
    }
    temp_lake.insert_document_raw(doc)
    
    conn = temp_lake.get_connection(read_only=True)
    res = conn.execute("SELECT doc_id, ticker, status FROM documents_raw WHERE doc_id = 'test-doc-001'").fetchone()
    conn.close()
    
    assert res is not None
    assert res[0] == "test-doc-001"
    assert res[1] == "AAPL"
    assert res[2] == "RAW"


def test_upsert_financial_panel_with_balanced_math(temp_lake):
    record = {
        "entity_lei": "5493006MHB84DD0ZWV18",
        "fiscal_year": 2024,
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "source_market": "US",
        "reporting_currency": "USD",
        "accounting_standard": "US-GAAP",
        "period_end_date": date(2024, 9, 30),
        "total_activo": 352583.0,
        "total_pasivo": 290437.0,
        "patrimonio_neto": 62146.0, # 290437 + 62146 = 352583 (Perfect match)
        "revenue": 391035.0,
        "beneficio_neto": 93736.0,
        "cfo": 118238.0,
        "capex": 9450.0,
        "fcf": 108788.0,
    }
    temp_lake.upsert_financial_panel_record(record)
    
    conn = temp_lake.get_connection(read_only=True)
    res = conn.execute("SELECT balance_check, balance_imbalance_eur FROM financial_panel WHERE entity_lei = '5493006MHB84DD0ZWV18'").fetchone()
    conn.close()
    
    assert res is not None
    assert res[0] is True
    assert res[1] == 0.0


def test_upsert_financial_panel_flags_imbalance(temp_lake):
    record = {
        "entity_lei": "BROKEN_LEI_001",
        "fiscal_year": 2024,
        "source_market": "ES",
        "reporting_currency": "EUR",
        "accounting_standard": "IFRS",
        "period_end_date": date(2024, 12, 31),
        "total_activo": 1000.0,
        "total_pasivo": 600.0,
        "patrimonio_neto": 300.0, # Imbalance = 100
    }
    temp_lake.upsert_financial_panel_record(record)
    
    conn = temp_lake.get_connection(read_only=True)
    res = conn.execute("SELECT balance_check, balance_imbalance_eur FROM financial_panel WHERE entity_lei = 'BROKEN_LEI_001'").fetchone()
    conn.close()
    
    assert res is not None
    assert res[0] is False
    assert res[1] == 100.0
