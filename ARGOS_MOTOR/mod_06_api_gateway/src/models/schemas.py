"""
STATER MOTOR ARGOS — MOD_06: Pydantic Data Models & Response Schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import date, datetime


class HealthResponse(BaseModel):
    status: str = "HEALTHY"
    version: str = "0.1.0"
    environment: str
    duckdb_connected: bool
    ollama_online: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FinancialsResponse(BaseModel):
    entity_lei: str
    fiscal_year: int
    ticker: Optional[str] = None
    company_name: Optional[str] = None
    source_market: str
    reporting_currency: str
    total_activo: Optional[float] = None
    activo_corriente: Optional[float] = None
    total_pasivo: Optional[float] = None
    patrimonio_neto: Optional[float] = None
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    ebit: Optional[float] = None
    beneficio_neto: Optional[float] = None
    cfo: Optional[float] = None
    capex: Optional[float] = None
    fcf: Optional[float] = None
    balance_check: bool
    version_id: str


class KAMItem(BaseModel):
    kam_id: str
    kam_title: str
    kam_topic: str
    severity: str
    risk_description: Optional[str] = None
    audit_response: Optional[str] = None
    text_span: str


class KAMsResponse(BaseModel):
    entity_lei: str
    fiscal_year: int
    audit_firm: str
    audit_opinion: str
    has_going_concern: bool
    kams: List[KAMItem]


class ESGItem(BaseModel):
    kpi_id: str
    esrs_standard: str
    esrs_code: str
    kpi_name: str
    kpi_value_numeric: Optional[float] = None
    kpi_value_text: Optional[str] = None
    unit: Optional[str] = None
    s_score_value: Optional[float] = None
    greenwashing_flag: bool = False


class ESGResponse(BaseModel):
    entity_lei: str
    fiscal_year: int
    s_score_total: Optional[float] = None
    greenwashing_detected: bool = False
    kpis: List[ESGItem]


class ValuationResponse(BaseModel):
    entity_lei: str
    fair_value_per_share: float
    enterprise_value: float
    equity_value: float
    net_debt: float
    base_wacc: float
    base_terminal_g: float
    sensitivity_matrix: Dict[str, Dict[str, Optional[float]]]
