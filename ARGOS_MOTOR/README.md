# STATER MOTOR ARGOS

> **Motor Transatlántico de Inteligencia Financiera, Auditoría Forense y Modelos Cuantitativos**
> 
> *Entidad:* STATER Financial Technologies — Yecla (Murcia, España)  
> *Licencia:* MIT License  
> *Stack:* Python 3.12+ · DuckDB · Apache Parquet · FastAPI · Ollama (qwen2.5:14b) · Azure OpenAI  

---

## 📚 Documentación Técnica Destacada
* 📖 [**Guía Técnica Maestra: Ingesta, Anatomía de Archivos y Modelos de Parseo CNMV / ESEF**](CNMV_INGESTION_ARCHITECTURE_AND_PARSING_GUIDE.md) — Documento integral con diagnósticos forenses, anatomía de paquetes ESEF (XHTML 50–111 MB), esquemas de persistencia en DuckDB, validación de cuadre contable ($A = P + PN$) y manual operativo.

---

## 🌟 Módulos del Sistema

| Módulo | Nombre | Descripción |
|---|---|---|
| **MOD_01** | [`mod_01_ingestion`](mod_01_ingestion/README.md) | Ingesta transatlántica regulada (SEC EDGAR + 5 OAMs: CNMV, AMF, BaFin, CONSOB, AFM) con sellado SHA-256 y soporte para 542 paquetes ESEF oficiales. |
| **MOD_02** | [`mod_02_parser`](mod_02_parser/README.md) | Parser de taxonomías IFRS ESEF y US-GAAP con regla de cuadre contable (Tolerancia Cero A = P + PN). |
| **MOD_03** | [`mod_03_nlp_audit`](mod_03_nlp_audit/README.md) | Extracción de KAMs (ISA 701), CAMs (PCAOB AS 3101), métricas CSRD/ESRS y detección de Greenwashing. |
| **MOD_04** | [`mod_04_data_lake`](mod_04_data_lake/README.md) | Data Lake columnar en DuckDB + Parquet particionado (capas RAW, STAGING, CORE, ANALYTICS). |
| **MOD_05** | [`mod_05_quant_sfi`](mod_05_quant_sfi/README.md) | 40+ ratios financieros, factores cuantitativos, scoring de Capital Humano (S-Score v2.0) y DCF determinista. |
| **MOD_06** | [`mod_06_api_gateway`](mod_06_api_gateway/README.md) | API REST institucional de alto rendimiento con FastAPI y documentación OpenAPI. |
| **MOD_07** | [`mod_07_ai_agents`](mod_07_ai_agents/README.md) | Agente local en Ollama (`stater-audit`) con router a Azure OpenAI GPT-4o para producción. |
| **MOD_08** | [`mod_08_monitor`](mod_08_monitor/README.md) | Observabilidad centralizada con `loguru`, métricas Prometheus y chequeos automáticos de integridad. |

---

## 🚀 Inicio Rápido

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Descargar paquetes ESEF reales (ej. IBEX 35, 2024)
python mod_01_esef_batch_downloader.py --tickers SAN IBE MEL GRF BKT --years 2024

# 3. Descomprimir, organizar y sellar con SHA-256
python organize_and_hash_all_zips.py

# 4. Iniciar API Gateway
uvicorn mod_06_api_gateway.src.main:app --reload --port 8000
```
