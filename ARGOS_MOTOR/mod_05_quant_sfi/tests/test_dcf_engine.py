"""
Tests unitarios para MOD_05: DCF Engine.
Verifica cálculo de Valor Empresa (EV), Valor Fondos Propios y matriz WACC × g.
"""
import pytest
from mod_05_quant_sfi.src.dcf_engine import DCFEngine


def test_dcf_engine_valuation():
    dcf = DCFEngine()
    val = dcf.calculate_valuation(
        base_fcf=100.0,
        shares_outstanding=10.0,
        net_debt=50.0,
        projection_years=5,
        base_wacc=0.10,
        base_terminal_g=0.02,
        fcf_growth_base=0.05
    )
    
    assert val["fair_value_per_share"] > 0.0
    assert val["enterprise_value"] > val["equity_value"] # Because net_debt is positive (50)
    assert val["equity_value"] == round(val["enterprise_value"] - 50.0, 2)
    assert "sensitivity_matrix" in val
    
    matrix = val["sensitivity_matrix"]
    assert "10.0%" in matrix
    assert "2.0%" in matrix["10.0%"]
    assert matrix["10.0%"]["2.0%"] == val["fair_value_per_share"]


def test_dcf_engine_invalid_inputs():
    dcf = DCFEngine()
    val = dcf.calculate_valuation(base_fcf=-50.0, shares_outstanding=10.0, net_debt=0.0)
    assert "error" in val
    assert val["fair_value_per_share"] == 0.0
