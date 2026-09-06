"""
MOD_08 — Métricas Prometheus para la API Gateway (MOD_06).

Expone el endpoint GET /metrics en formato Prometheus estándar.
Compatible con Grafana, Azure Monitor y cualquier scraper Prometheus.

Métricas expuestas:
- stater_documents_ingested_total      — Total de documentos descargados (por fuente)
- stater_parse_errors_total            — Errores de parser XBRL (por módulo)
- stater_balance_quarantines_total     — Filings enviados a cuarentena por descuadre
- stater_agent_calls_total             — Llamadas a agentes IA (por modelo: ollama/azure)
- stater_agent_latency_seconds         — Latencia de inferencia del agente (histograma)
- stater_api_requests_total            — Requests a la API (por endpoint y status)
- stater_api_latency_seconds           — Latencia de la API (histograma P50/P95/P99)
"""
from prometheus_client import Counter, Histogram, start_http_server
import os

# --- Contadores --------------------------------------------------------------
documents_ingested = Counter(
    "stater_documents_ingested_total",
    "Total documents downloaded by the ingestion module",
    ["source"],  # 'SEC_EDGAR' | 'CNMV' | 'AMF' | 'BAFIN' | 'CONSOB' | 'AFM'
)

parse_errors = Counter(
    "stater_parse_errors_total",
    "XBRL/iXBRL parse errors by module",
    ["module", "error_type"],
)

balance_quarantines = Counter(
    "stater_balance_quarantines_total",
    "Filings sent to QUARANTINE due to balance imbalance (A != P + PN)",
    ["source_market"],
)

agent_calls = Counter(
    "stater_agent_calls_total",
    "Total calls to AI agents by model backend",
    ["model"],  # 'ollama_stater_audit' | 'azure_gpt4o'
)

# --- Histogramas -------------------------------------------------------------
agent_latency = Histogram(
    "stater_agent_latency_seconds",
    "AI agent inference latency in seconds",
    ["model"],
    buckets=(1, 5, 10, 30, 60, 120, 300),
)

api_requests = Counter(
    "stater_api_requests_total",
    "API Gateway requests by endpoint and HTTP status",
    ["endpoint", "status_code"],
)

api_latency = Histogram(
    "stater_api_latency_seconds",
    "API Gateway request latency in seconds",
    ["endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# --- Aliases estándar ---
INGEST_DOCS_TOTAL = documents_ingested
INGEST_ERRORS_TOTAL = parse_errors
PIPELINE_DURATION_SECONDS = api_latency
AGENT_REQUESTS_TOTAL = agent_calls



def start_metrics_server(port: int = 9090) -> None:
    """
    Inicia el servidor HTTP de métricas Prometheus en el puerto especificado.
    Llamar desde el proceso principal de MOD_06 (FastAPI) al arrancar.
    """
    start_http_server(port)
    print(f"[MOD_08] Prometheus metrics server running on http://localhost:{port}/metrics")
