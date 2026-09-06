"""ESG and S-Score v2.0 (Human Capital) quantitative scoring engine."""
from typing import Dict, Any


class ScoringEngine:
    def compute_s_score(self, human_capital_kpis: Dict[str, Any]) -> float:
        training_hours = human_capital_kpis.get("training_hours", 20.0)
        pay_gap_pct = human_capital_kpis.get("gender_pay_gap_pct", 10.0)
        
        score = 50.0 + min(30.0, training_hours) - max(0.0, pay_gap_pct * 1.5)
        return round(max(0.0, min(100.0, score)), 2)
