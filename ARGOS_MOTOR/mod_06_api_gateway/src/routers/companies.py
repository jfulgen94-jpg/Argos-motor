"""FastAPI Router for /companies endpoints."""
from fastapi import APIRouter, HTTPException, Query
from mod_04_data_lake.src.lake_manager import LakeManager
from mod_06_api_gateway.src.models.schemas import FinancialsResponse
import math

router = APIRouter(prefix="/companies", tags=["Companies"])
lake = LakeManager()


@router.get("/{lei}/financials", response_model=FinancialsResponse)
async def get_financials(lei: str, year: int = Query(default=2024)):
    conn = lake.get_connection(read_only=True)
    try:
        cursor = conn.execute("SELECT * FROM financial_panel WHERE entity_lei = ? AND fiscal_year = ?", [lei, year])
        cols = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Company financials not found")
    raw = dict(zip(cols, row))
    clean = {k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in raw.items()}
    return FinancialsResponse(**clean)
