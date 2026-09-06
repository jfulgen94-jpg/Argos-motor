"""Tests for MOD_08 — Data Quality Checker and Logger."""
import pytest
from mod_08_monitor.src.logger import get_logger


def test_logger_returns_bound_logger():
    log = get_logger("MOD_TEST")
    assert log is not None


def test_logger_module_context():
    """Logger must bind the module name correctly for structured output."""
    log = get_logger("MOD_08")
    # Just verify it can log without raising
    log.info("test_event: logger initialized correctly")


# --- Balance check integration (uses balance_validator from MOD_02) ----------
from mod_02_parser.src.balance_validator import validate


def test_quality_checker_catches_imbalanced_panel():
    """Simulate what data_quality_checker would flag in the DB."""
    broken = {"total_activo": 5000.0, "total_pasivo": 3000.0, "patrimonio_neto": 1500.0}
    result = validate(broken)
    assert result.status == "QUARANTINE"
    assert result.imbalance_amount == 500.0


def test_quality_checker_passes_balanced_panel():
    good = {"total_activo": 5000.0, "total_pasivo": 3000.0, "patrimonio_neto": 2000.0}
    result = validate(good)
    assert result.status == "PARSED"
    assert result.is_balanced is True
