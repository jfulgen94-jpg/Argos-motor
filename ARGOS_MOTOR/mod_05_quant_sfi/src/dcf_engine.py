"""
STATER MOTOR ARGOS — MOD_05: Discounted Cash Flow (DCF) Engine.
Modelo determinista de valoración intrínseca con matriz de sensibilidad bidimensional WACC × g.
Genera tres escenarios (Bear, Base, Bull) para cada emisor.
"""
from typing import Dict, Any, List, Optional
import math


class DCFEngine:
    """Motor determinista de valoración por descuento de flujos de caja libre (FCFF)."""

    def calculate_valuation(
        self,
        base_fcf: float,
        shares_outstanding: float,
        net_debt: float,
        projection_years: int = 5,
        base_wacc: float = 0.09,      # 9.0% WACC base
        base_terminal_g: float = 0.02, # 2.0% crecimiento a perpetuidad
        fcf_growth_base: float = 0.06  # 6.0% crecimiento anual proyectado
    ) -> Dict[str, Any]:
        """
        Calcula el valor intrínseco por acción y la matriz de sensibilidad WACC × g.
        """
        if base_fcf <= 0 or shares_outstanding <= 0:
            return {
                "error": "FCF base o número de acciones no válidos para DCF estándar",
                "enterprise_value": 0.0,
                "equity_value": 0.0,
                "fair_value_per_share": 0.0
            }

        # Proyección de flujos para escenario base
        projected_fcfs = []
        current_fcf = base_fcf
        for _ in range(projection_years):
            current_fcf *= (1.0 + fcf_growth_base)
            projected_fcfs.append(current_fcf)

        # Descuento de flujos explícitos
        pv_explicit = 0.0
        for t, fcf_t in enumerate(projected_fcfs, start=1):
            pv_explicit += fcf_t / ((1.0 + base_wacc) ** t)

        # Valor Terminal (Fórmula de Gordon Shapiro)
        terminal_fcf = projected_fcfs[-1] * (1.0 + base_terminal_g)
        terminal_value = terminal_fcf / (base_wacc - base_terminal_g)
        pv_terminal = terminal_value / ((1.0 + base_wacc) ** projection_years)

        # Enterprise Value y Equity Value
        enterprise_value = pv_explicit + pv_terminal
        equity_value = enterprise_value - net_debt
        fair_value_per_share = max(0.0, equity_value / shares_outstanding)

        # Matriz de Sensibilidad WACC × g
        wacc_range = [base_wacc - 0.02, base_wacc - 0.01, base_wacc, base_wacc + 0.01, base_wacc + 0.02]
        g_range = [base_terminal_g - 0.01, base_terminal_g, base_terminal_g + 0.01]
        
        sensitivity_matrix = {}
        for w in wacc_range:
            w_key = f"{round(w*100, 1)}%"
            sensitivity_matrix[w_key] = {}
            for g in g_range:
                g_key = f"{round(g*100, 1)}%"
                if w <= g:
                    sensitivity_matrix[w_key][g_key] = None
                    continue
                # Recalcular PV
                pv_exp = sum(fcf / ((1.0 + w) ** t) for t, fcf in enumerate(projected_fcfs, start=1))
                tv = (projected_fcfs[-1] * (1.0 + g)) / (w - g)
                pv_tv = tv / ((1.0 + w) ** projection_years)
                ev = pv_exp + pv_tv
                eq_val = ev - net_debt
                fv = round(max(0.0, eq_val / shares_outstanding), 2)
                sensitivity_matrix[w_key][g_key] = fv

        return {
            "base_wacc": base_wacc,
            "base_terminal_g": base_terminal_g,
            "fcf_growth_rate": fcf_growth_base,
            "pv_explicit_cash_flows": round(pv_explicit, 2),
            "pv_terminal_value": round(pv_terminal, 2),
            "enterprise_value": round(enterprise_value, 2),
            "net_debt": round(net_debt, 2),
            "equity_value": round(equity_value, 2),
            "shares_outstanding": shares_outstanding,
            "fair_value_per_share": round(fair_value_per_share, 2),
            "sensitivity_matrix": sensitivity_matrix,
        }
