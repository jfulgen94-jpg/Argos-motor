"""FastAPI Router for /sectors aggregation endpoints."""
from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter(prefix="/sectors", tags=["Sectors"])


@router.get("/{code}/scores")
async def get_sector_scores(code: str) -> Dict[str, Any]:
    return {
        "sector_code": code,
        "median_roic": 0.125,
        "median_debt_to_equity": 1.10,
        "average_s_score": 78.4,
    }
