# MOD_06 — API Gateway (FastAPI)

## Propósito
Expone la capa ANALYTICS del Data Lake al mundo. Endpoints REST para consultas por empresa (LEI/ISIN), por sector y descarga bulk de datasets Parquet.

## Endpoints principales
```
GET  /companies/{lei}/financials     → Panel financiero anual
GET  /companies/{lei}/kams           → KAMs y CAMs con severidad
GET  /companies/{lei}/esg            → Métricas CSRD y S-Score v2.0
GET  /sectors/{sic_code}/scores      → Scores sectoriales
POST /datasets/bulk                  → Descarga Parquet institucional
```

## Autenticación
API Keys por tier (Free / Academic / Professional / Enterprise).

## Ejecución local
```bash
uvicorn src.main:app --reload --port 8000
# Docs: http://localhost:8000/docs
```
