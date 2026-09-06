"""
Tests unitarios para MOD_05: Ratio Engine.
Verifica cálculo de liquidez, solvencia, márgenes y calidad contable.
"""
import pytest
from mod_05_quant_sfi.src.ratio_engine import RatioEngine, safe_div


def test_safe_div():
    assert safe_div(10.0, 2.0) == 5.0
    assert safe_div(10.0, 0.0) is None
    assert safe_div(None, 5.0) is None
    assert safe_div(5.0, None) is None


def test_ratio_engine_computations():
    engine = RatioEngine()
    sample = {
        "entity_lei": "TEST_LEI_001",
        "fiscal_year": 2024,
        "total_activo": 1000.0,
        "activo_corriente": 400.0,
        "existencias": 100.0,
        "efectivo_y_equivalentes": 150.0,
        "total_pasivo": 600.0,
        "pasivo_corriente": 200.0,
        "deuda_financiera_lp": 300.0,
        "deuda_financiera_cp": 100.0,
        "patrimonio_neto": 400.0,
        "revenue": 1200.0,
        "cost_of_goods_sold": 720.0,
        "gross_profit": 480.0,
        "ebitda": 300.0,
        "ebit": 240.0,
        "ebt": 200.0,
        "income_tax": 50.0,
        "beneficio_neto": 150.0,
        "cfo": 220.0,
        "capex": 70.0,
        "fcf": 150.0,
    }
    
    ratios = engine.compute_all_ratios(sample)
    
    # Liquidez
    assert ratios["current_ratio"] == 2.0         # 400 / 200
    assert ratios["quick_ratio"] == 1.5           # (400 - 100) / 200
    assert ratios["cash_ratio"] == 0.75           # 150 / 200
    
    # Solvencia
    assert ratios["debt_to_equity"] == 1.5        # 600 / 400
    assert ratios["debt_to_assets"] == 0.6        # 600 / 1000
    assert ratios["net_debt"] == 250.0            # (300+100) - 150
    assert ratios["net_debt_to_ebitda"] == round(250.0 / 300.0, 6)
    
    # Márgenes y Rentabilidad
    assert ratios["gross_margin"] == 0.4          # 480 / 1200
    assert ratios["ebit_margin"] == 0.2           # 240 / 1200
    assert ratios["net_margin"] == 0.125          # 150 / 1200
    assert ratios["roe"] == 0.375                 # 150 / 400
    assert ratios["roa"] == 0.15                  # 150 / 1000
    
    # Cash Flow
    assert ratios["fcf_margin"] == 0.125          # 150 / 1200
    assert ratios["capex_to_cfo"] == round(70.0 / 220.0, 6)
