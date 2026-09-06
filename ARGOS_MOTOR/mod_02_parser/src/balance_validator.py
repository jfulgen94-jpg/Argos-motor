"""Balance Validator — Zero-tolerance check: Assets = Liabilities + Equity."""
from dataclasses import dataclass


@dataclass
class ValidationResult:
    is_balanced: bool
    status: str
    imbalance_amount: float = 0.0


def validate(filing: dict) -> ValidationResult:
    """
    Validate that: Total Assets = Total Liabilities + Total Equity.
    Any imbalance, however small, sends the filing to QUARANTINE.
    """
    assets = filing.get("total_activo", 0.0)
    liabilities = filing.get("total_pasivo", 0.0)
    equity = filing.get("patrimonio_neto", 0.0)
    imbalance = abs(assets - (liabilities + equity))
    if imbalance > 0.0:
        return ValidationResult(is_balanced=False, status="QUARANTINE", imbalance_amount=imbalance)
    return ValidationResult(is_balanced=True, status="PARSED")
