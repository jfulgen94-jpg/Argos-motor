"""
STATER MOTOR ARGOS — MOD_06: Main FastAPI Gateway Application.
Expone endpoints REST institucionales para datos financieros, KAMs, CSRD y DCF.
"""
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import os
import httpx
from datetime import datetime

from mod_04_data_lake.src.lake_manager import LakeManager
from mod_05_quant_sfi.src.ratio_engine import RatioEngine
from mod_05_quant_sfi.src.dcf_engine import DCFEngine
from mod_06_api_gateway.src.models.schemas import (
    HealthResponse, FinancialsResponse, KAMsResponse, KAMItem, ESGResponse, ESGItem, ValuationResponse
)
from mod_08_monitor.src.logger import get_logger

log = get_logger("MOD_06")

app = FastAPI(
    title="STATER Motor Argos — Financial Intelligence API",
    description="Transatlantic institutional API for normalized financial panels, ISA 701 KAMs, CSRD metrics and SFI valuation models.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

lake = LakeManager()
ratio_engine = RatioEngine()
dcf_engine = DCFEngine()


from datetime import datetime, timezone
import math


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Estado de salud del sistema, Data Lake y motor local Ollama."""
    env = os.getenv("STATER_ENV", "local")
    
    # Check DuckDB
    duckdb_ok = False
    try:
        conn = lake.get_connection(read_only=True)
        conn.execute("SELECT 1")
        conn.close()
        duckdb_ok = True
    except Exception:
        duckdb_ok = False

    # Check Ollama
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            ollama_ok = (r.status_code == 200)
    except Exception:
        ollama_ok = False

    return HealthResponse(
        status="HEALTHY" if (duckdb_ok and ollama_ok) else "DEGRADED",
        version="0.1.0",
        environment=env,
        duckdb_connected=duckdb_ok,
        ollama_online=ollama_ok,
        timestamp=datetime.now(timezone.utc)
    )


@app.get("/companies/{lei}/financials", response_model=FinancialsResponse, tags=["Financials"])
async def get_company_financials(lei: str, year: int = Query(default=2024, description="Año fiscal")):
    """Obtiene el panel financiero anual normalizado y validado con balance cuadrado (por LEI o Ticker)."""
    conn = lake.get_connection(read_only=True)
    try:
        cursor = conn.execute(
            "SELECT * FROM financial_panel WHERE (entity_lei = ? OR ticker = ?) AND fiscal_year = ?",
            [lei, lei, year]
        )
        cols = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"No se encontraron estados financieros para identificador {lei} y año {year}")
    
    raw_dict = dict(zip(cols, row))
    clean_record = {k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in raw_dict.items()}
    return FinancialsResponse(**clean_record)


@app.get("/companies/{lei}/kams", response_model=KAMsResponse, tags=["Audit & Forensic"])
async def get_company_kams(lei: str, year: int = Query(default=2024, description="Año fiscal")):
    """Obtiene las Cuestiones Clave de Auditoría (KAMs ISA 701 / CAMs PCAOB) extraídas por el agente (por LEI o Ticker)."""
    conn = lake.get_connection(read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT * FROM audit_kams 
            WHERE (entity_lei = ? OR entity_lei IN (SELECT entity_lei FROM financial_panel WHERE entity_lei = ? OR ticker = ?))
              AND fiscal_year = ?
            """,
            [lei, lei, lei, year]
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No se encontraron KAMs para identificador {lei} y año {year}")

    first = rows[0]
    items = [
        KAMItem(
            kam_id=r[0],
            kam_title=r[8],
            kam_topic=r[9],
            severity=r[10],
            risk_description=r[11],
            audit_response=r[12],
            text_span=r[13]
        ) for r in rows
    ]

    return KAMsResponse(
        entity_lei=lei,
        fiscal_year=year,
        audit_firm=first[4] or "UNKNOWN",
        audit_opinion=first[6] or "UNQUALIFIED",
        has_going_concern=bool(first[7]),
        kams=items
    )


@app.get("/companies/{lei}/valuation", response_model=ValuationResponse, tags=["Quantitative Valuation"])
async def get_company_valuation(
    lei: str,
    year: int = Query(default=2024),
    shares: float = Query(default=1000000.0, description="Número de acciones en circulación"),
    wacc: float = Query(default=0.09, description="Costo Promedio Ponderado de Capital (WACC)"),
    g: float = Query(default=0.02, description="Crecimiento a perpetuidad")
):
    """Calcula la valoración intrínseca por DCF determinista y matriz de sensibilidad."""
    conn = lake.get_connection(read_only=True)
    try:
        row = conn.execute(
            "SELECT fcf, (COALESCE(deuda_financiera_lp, 0) + COALESCE(deuda_financiera_cp, 0) - COALESCE(efectivo_y_equivalentes, 0)) AS net_debt FROM financial_panel WHERE entity_lei = ? AND fiscal_year = ?",
            [lei, year]
        ).fetchone()
    finally:
        conn.close()

    if not row or row[0] is None:
        raise HTTPException(status_code=404, detail=f"Datos insuficientes de FCF para calcular DCF de LEI {lei}")

    base_fcf, net_debt = row[0], row[1] or 0.0
    val = dcf_engine.calculate_valuation(
        base_fcf=base_fcf,
        shares_outstanding=shares,
        net_debt=net_debt,
        base_wacc=wacc,
        base_terminal_g=g
    )
    
    return ValuationResponse(
        entity_lei=lei,
        fair_value_per_share=val["fair_value_per_share"],
        enterprise_value=val["enterprise_value"],
        equity_value=val["equity_value"],
        net_debt=val["net_debt"],
        base_wacc=val["base_wacc"],
        base_terminal_g=val["base_terminal_g"],
        sensitivity_matrix=val["sensitivity_matrix"]
    )
