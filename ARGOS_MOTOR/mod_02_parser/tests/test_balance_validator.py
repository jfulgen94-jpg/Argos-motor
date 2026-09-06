"""Tests for balance validator — zero-tolerance rule: A = P + PN."""
from mod_02_parser.src.balance_validator import validate


def test_balanced_filing_passes():
    filing = {"total_activo": 1000.0, "total_pasivo": 600.0, "patrimonio_neto": 400.0}
    result = validate(filing)
    assert result.is_balanced is True
    assert result.status == "PARSED"


def test_imbalanced_filing_goes_to_quarantine():
    filing = {"total_activo": 1000.0, "total_pasivo": 600.0, "patrimonio_neto": 300.0}  # 100 imbalance
    result = validate(filing)
    assert result.is_balanced is False
    assert result.status == "QUARANTINE"
    assert result.imbalance_amount == 100.0
