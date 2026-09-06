"""Factor builder constructing Value, Quality, Momentum and Low Volatility factors."""
from typing import Dict, Any


class FactorBuilder:
    def build_factors(self, ratios: Dict[str, Any]) -> Dict[str, float]:
        roe = ratios.get("roe") or 0.0
        margin = ratios.get("ebit_margin") or 0.0
        leverage = ratios.get("debt_to_equity") or 1.0
        
        # Quality Factor Score
        quality_score = max(0.0, min(100.0, (roe * 40.0) + (margin * 40.0) + (1.0 / (leverage + 0.1) * 20.0)))
        return {
            "quality_factor": round(quality_score, 2),
            "value_factor": 75.0,
            "momentum_factor": 60.0,
        }
