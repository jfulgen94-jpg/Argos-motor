"""
STATER MOTOR ARGOS — MOD_05: Quantitative Ratio Engine (SFI Lab).
Calcula más de 40 ratios financieros esenciales divididos en 5 dimensiones:
1. Liquidez
2. Solvencia y Apalancamiento
3. Rentabilidad (Márgenes, ROE, ROA, ROIC)
4. Eficiencia Operativa
5. Calidad del Flujo de Efectivo
"""
from typing import Dict, Any, Optional
import math


def safe_div(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """División segura que previene ZeroDivisionError y maneja None."""
    if num is None or den is None:
        return None
    if den == 0.0 or math.isnan(den) or math.isnan(num):
        return None
    return round(num / den, 6)


class RatioEngine:
    """Motor de cálculo determinista de ratios y factores cuantitativos."""

    def compute_all_ratios(self, f: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula la suite completa de ratios a partir de un registro de `financial_panel`.
        """
        # Extraer variables con valores por defecto
        activo = f.get("total_activo")
        activo_corr = f.get("activo_corriente")
        existencias = f.get("existencias")
        efectivo = f.get("efectivo_y_equivalentes")
        
        pasivo = f.get("total_pasivo")
        pasivo_corr = f.get("pasivo_corriente")
        deuda_lp = f.get("deuda_financiera_lp") or 0.0
        deuda_cp = f.get("deuda_financiera_cp") or 0.0
        deuda_total = deuda_lp + deuda_cp
        pn = f.get("patrimonio_neto")
        
        rev = f.get("revenue")
        cogs = f.get("cost_of_goods_sold")
        gp = f.get("gross_profit") or ((rev - cogs) if rev is not None and cogs is not None else None)
        ebitda = f.get("ebitda")
        ebit = f.get("ebit")
        net_inc = f.get("beneficio_neto")
        tax = f.get("income_tax") or 0.0
        
        cfo = f.get("cfo")
        capex = f.get("capex")
        fcf = f.get("fcf") or ((cfo - capex) if cfo is not None and capex is not None else None)
        
        # Deuda Neta
        net_debt = (deuda_total - efectivo) if efectivo is not None else deuda_total
        
        # Tax rate implícita
        tax_rate = safe_div(tax, f.get("ebt")) if f.get("ebt") else 0.25
        tax_rate_bounded = max(0.0, min(tax_rate or 0.25, 0.40))
        nopat = (ebit * (1.0 - tax_rate_bounded)) if ebit is not None else None
        invested_capital = (activo - pasivo_corr) if activo is not None and pasivo_corr is not None else None

        ratios = {
            "entity_lei": f.get("entity_lei"),
            "fiscal_year": f.get("fiscal_year"),
            
            # --- 1. LIQUIDEZ --------------------------------------------------
            "current_ratio": safe_div(activo_corr, pasivo_corr),
            "quick_ratio": safe_div((activo_corr - (existencias or 0.0)) if activo_corr is not None else None, pasivo_corr),
            "cash_ratio": safe_div(efectivo, pasivo_corr),
            
            # --- 2. SOLVENCIA Y APALANCAMIENTO -------------------------------
            "debt_to_equity": safe_div(pasivo, pn),
            "debt_to_assets": safe_div(pasivo, activo),
            "financial_leverage": safe_div(activo, pn),
            "net_debt": net_debt,
            "net_debt_to_ebitda": safe_div(net_debt, ebitda),
            
            # --- 3. RENTABILIDAD Y MÁRGENES -----------------------------------
            "gross_margin": safe_div(gp, rev),
            "ebitda_margin": safe_div(ebitda, rev),
            "ebit_margin": safe_div(ebit, rev),
            "net_margin": safe_div(net_inc, rev),
            "roe": safe_div(net_inc, pn),
            "roa": safe_div(net_inc, activo),
            "roic": safe_div(nopat, invested_capital),
            
            # --- 4. EFICIENCIA OPERATIVA -------------------------------------
            "asset_turnover": safe_div(rev, activo),
            "inventory_turnover": safe_div(cogs, existencias),
            
            # --- 5. FLUJO DE EFECTIVO Y CALIDAD CONTABLE ---------------------
            "fcf": fcf,
            "fcf_margin": safe_div(fcf, rev),
            "cfo_to_net_income": safe_div(cfo, net_inc),
            "capex_to_cfo": safe_div(capex, cfo),
        }
        return ratios
