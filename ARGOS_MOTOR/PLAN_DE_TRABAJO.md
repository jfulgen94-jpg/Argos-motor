# STATER — MOTOR ARGOS: PLAN MAESTRO DE DESARROLLO

> **Clasificación:** Documento de Arquitectura Técnica Interna — `v1.0`  
> **Estado:** `APPROVED — Listo para ejecución`  
> **Fecha de cierre:** 2026-08-24  
> **Entidad:** STATER, S.L. — Yecla (Murcia, España)  
> **Stack:** Python 3.12 · DuckDB · Apache Parquet · FastAPI · Ollama (`qwen2.5:14b`) · Azure OpenAI  

---

## 1. Visión General y Cadena de Valor del Motor

```
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │           STATER MOTOR ARGOS — CADENA DE DATOS TRANSATLÁNTICA                 │
 ├───────────────────────────────────────────────────────────────────────────────┤
 │                                                                               │
 │  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
 │  │ MOD_01       │──▶│ MOD_02       │──▶│ MOD_04       │──▶│ MOD_06       │   │
 │  │ INGESTION    │   │ PARSER XBRL  │   │ DATA LAKE    │   │ API GATEWAY  │   │
 │  │ SEC + 5 OAMs │   │ IFRS/US-GAAP │   │ DuckDB+Parq. │   │ FastAPI REST │   │
 │  └──────────────┘   └──────────────┘   └──────┬───────┘   └──────────────┘   │
 │                                               │                               │
 │  ┌──────────────┐   ┌──────────────┐   ┌──────▼───────┐                      │
 │  │ MOD_07       │──▶│ MOD_03       │──▶│ MOD_05       │                      │
 │  │ AI AGENTS    │   │ NLP AUDIT    │   │ QUANT SFI    │                      │
 │  │ Ollama/Azure │   │ KAM+CSRD+ESG │   │ Factors/DCF  │                      │
 │  └──────────────┘   └──────────────┘   └──────────────┘                      │
 └───────────────────────────────────────────────────────────────────────────────┘
```

**Flujo de datos resumido:**
1. **MOD_01** descarga filings crudos (10-K, ESEF) → los sella con SHA-256 y los deposita en `data/raw/`.
2. **MOD_02** parsea el XBRL/iXBRL → genera tablas `financial_facts_raw` y `financial_panel` en el Data Lake.
3. **MOD_03** extrae KAMs, CAMs, CSRD y datos de gobernanza con NLP → escribe en `audit_kams` y `esg_kpis`.
4. **MOD_04** es el sistema nervioso: gestiona las capas raw → staging → core → analytics en DuckDB + Parquet.
5. **MOD_05** calcula ratios, scores cuantitativos, factores SFI y modelos DCF → escribe en `analytics`.
6. **MOD_06** expone la capa `analytics` al mundo a través de una API REST (FastAPI) y datasets bulk.
7. **MOD_07** es la capa de inteligencia autónoma: agentes Ollama (`qwen2.5:14b`) para razonamiento complejo sobre textos de auditoría y CSRD, con fallback transparente a Azure OpenAI en producción.

---

## 2. Cobertura de Mercados y Datos (MVP Fase 0)

| Mercado | Fuente de Datos | Formato | Tipo de Documento | Prioridad |
|---|---|---|---|---|
| EE.UU. | SEC EDGAR | XBRL + HTML | 10-K, 10-Q, 8-K (CAMs PCAOB AS 3101) | **CRÍTICA** |
| España | CNMV | iXBRL (ESEF) | Informes anuales ESEF + IAGC (KAMs ISA 701) | **CRÍTICA** |
| Francia | AMF / data.gouv.fr | iXBRL (ESEF) | Rapports annuels + informes de sostenibilidad | Alta |
| Alemania | BaFin / Unternehmensregister | iXBRL (ESEF) | Geschäftsberichte + Lagebericht | Alta |
| Italia | CONSOB / 1INFO | iXBRL (ESEF) | Relazioni annuali + CSRD | Alta |
| Países Bajos | AFM | iXBRL (ESEF) | Annual Reports (inglés nativo) | Alta |

**Secciones a extraer en Fase 0** (en orden de prioridad):
1. **Estados Financieros primarios** — Balance, PyG, EFE, Estado de PN.
2. **Informe de auditoría** — KAMs (ISA 701), CAMs (PCAOB AS 3101), párrafos de énfasis, Going Concern.
3. **Gobierno Corporativo** — IAGC, composición del Consejo, remuneraciones.
4. **Sostenibilidad CSRD/ESRS** — Métricas E1-G1, Capital Humano, Greenwashing.
5. **Notas a los estados financieros** — Criterios contables, desglose de partidas.

---

## 3. Arquitectura de Despliegue: Híbrido Local + Azure

```
  LOCAL WORKSTATION (Windows 11, VS Code)          AZURE CLOUD (Microsoft Founders Hub)
  ─────────────────────────────────────            ────────────────────────────────────
  ┌─────────────────────────────────┐              ┌──────────────────────────────────┐
  │  Python 3.12 (venv)             │              │  Azure Blob Storage              │
  │  DuckDB (embedded, local)       │─── sync ───▶│  (raw filings archivados)        │
  │  Parquet files (data/lake/)     │              │                                  │
  │  Ollama qwen2.5:14b (local)     │              │  Azure OpenAI Service            │
  │  FastAPI (dev server)           │─── API  ───▶│  (producción Fase 1+)            │
  │  pytest + GitHub Actions CI     │              │                                  │
  └─────────────────────────────────┘              │  Azure Container Apps (Fase 2)   │
                                                   └──────────────────────────────────┘
```

**Regla de entorno:**
- `STATER_ENV=local` → Ollama local + DuckDB local + archivos Parquet en disco.
- `STATER_ENV=azure` → Azure OpenAI + Azure Blob Storage + DuckDB sobre Parquet remoto.
- Variable de entorno gestionada en `.env` (nunca commiteado a git).

---

## 4. Estructura de Módulos y Carpetas del Monorepo

```
ARGOS_MOTOR/
│
├── PLAN_DE_TRABAJO.md                  ← Este documento
├── README.md                           ← Presentación pública para GitHub
├── requirements.txt                    ← Dependencias globales
├── pyproject.toml                      ← Config de pytest, black, mypy
├── .env.example                        ← Plantilla de variables de entorno
├── .gitignore
├── LICENSE                             ← MIT License
│
├── mod_01_ingestion/
│   ├── README.md
│   ├── src/
│   │   ├── edgar_client.py             ← Descarga de 10-K, 10-Q, 8-K SEC
│   │   ├── esef_client.py              ← Descarga de filings iXBRL europeos
│   │   ├── oam_router.py              ← Enrutador por país (CNMV/AMF/BaFin/CONSOB/AFM)
│   │   ├── sha256_sealer.py           ← Sellado criptográfico inmutable
│   │   └── storage_uploader.py        ← Sync a Azure Blob Storage
│   ├── tests/
│   │   ├── test_edgar_client.py
│   │   └── test_sha256_sealer.py
│   └── config/
│       └── sources.yaml               ← URLs, robots.txt, rate limits por fuente
│
├── mod_02_parser/
│   ├── README.md
│   ├── src/
│   │   ├── xbrl_parser.py             ← Parser IFRS ESEF (inline XBRL)
│   │   ├── usgaap_parser.py           ← Parser US-GAAP XBRL (SEC)
│   │   ├── taxonomy_mapper.py         ← Mapeo de conceptos IFRS <-> US-GAAP
│   │   └── balance_validator.py       ← Regla de cuadre: Activo = Pasivo + PN
│   ├── tests/
│   │   ├── test_xbrl_parser.py
│   │   └── test_balance_validator.py  ← Tests A = P + PN (100% cobertura exigida)
│   ├── schemas/
│   │   ├── financial_facts_raw.json
│   │   └── financial_panel.json
│   └── config/
│       └── taxonomy_dict.yaml         ← Diccionario IFRS <-> US-GAAP <-> PGC
│
├── mod_03_nlp_audit/
│   ├── README.md
│   ├── src/
│   │   ├── kam_extractor.py           ← KAMs (ISA 701) y CAMs (PCAOB AS 3101)
│   │   ├── csrd_mapper.py             ← Métricas ESRS E1-G1
│   │   ├── iagc_extractor.py          ← Consejo y remuneraciones
│   │   ├── greenwashing_detector.py   ← Detector cuantitativo de inconsistencias ESG
│   │   └── agent_client.py            ← Cliente que consume MOD_07 (AI Agents)
│   ├── tests/
│   ├── prompts/
│   │   ├── kam_extraction_prompt.txt
│   │   └── csrd_scoring_prompt.txt
│   └── config/
│       └── nlp_config.yaml
│
├── mod_04_data_lake/
│   ├── README.md
│   ├── src/
│   │   ├── lake_manager.py            ← Capas raw/staging/core/analytics
│   │   ├── parquet_writer.py          ← Escritura de Parquet particionados
│   │   └── snapshot_manager.py        ← Versiones diarias vYYYYMMDD
│   ├── tests/
│   ├── schemas/
│   │   ├── financial_panel.sql        ← DDL DuckDB
│   │   ├── audit_kams.sql
│   │   └── esg_kpis.sql
│   ├── migrations/
│   │   └── v001_initial_schema.sql
│   └── config/
│       └── lake_config.yaml
│
├── mod_05_quant_sfi/
│   ├── README.md
│   ├── src/
│   │   ├── ratio_engine.py            ← 40+ ratios financieros
│   │   ├── factor_builder.py          ← Factores Value, Quality, Momentum, LowVol
│   │   ├── dcf_engine.py              ← DCF con matrices WACC x g
│   │   ├── scoring_engine.py          ← S-Score v2.0 y scores ESG
│   │   └── backtest_runner.py         ← Simulador de carteras sistemáticas
│   ├── tests/
│   ├── notebooks/
│   │   └── factor_exploration.ipynb
│   └── config/
│       └── formulas.yaml              ← Definición matemática de cada ratio
│
├── mod_06_api_gateway/
│   ├── README.md
│   ├── src/
│   │   ├── main.py                    ← Punto de entrada FastAPI
│   │   ├── routers/
│   │   │   ├── companies.py           ← /companies/{lei}/financials, /esg, /kams
│   │   │   ├── sectors.py             ← /sectors/{code}/scores
│   │   │   └── datasets.py            ← /datasets/bulk
│   │   ├── auth/
│   │   │   └── api_key_auth.py
│   │   └── models/
│   │       └── schemas.py             ← Pydantic schemas
│   ├── tests/
│   ├── openapi/
│   │   └── openapi.yaml
│   └── config/
│       └── api_config.yaml
│
├── mod_07_ai_agents/
│   ├── README.md
│   ├── src/
│   │   ├── agent_router.py            ← Router: Ollama local o Azure OpenAI
│   │   ├── ollama_agent.py            ← Cliente Ollama (qwen2.5:14b)
│   │   ├── azure_openai_agent.py      ← Cliente Azure OpenAI (GPT-4o, Fase 1+)
│   │   └── task_dispatcher.py         ← Gestión de colas asíncronas
│   ├── tests/
│   ├── agents/
│   │   ├── kam_analyst_agent.py
│   │   └── csrd_analyst_agent.py
│   ├── modelfiles/
│   │   └── Modelfile.stater-audit     ← Modelfile Ollama con system prompt financiero
│   └── config/
│       └── agents_config.yaml
│
├── mod_08_monitor/                     ← Observabilidad, alertas y calidad de datos
│   ├── README.md
│   ├── src/
│   │   ├── logger.py                  ← Logger centralizado JSON (loguru) para todos los módulos
│   │   ├── metrics.py                 ← Contadores y histogramas Prometheus
│   │   └── data_quality_checker.py   ← Assertions de integridad del Data Lake
│   ├── tests/
│   │   └── test_monitor.py
│   ├── dashboards/
│   │   └── grafana_dashboard.json     ← Dashboard Grafana (importable, Fase 1+)
│   └── config/
│       └── monitor_config.env         ← Log level, DuckDB path, Prometheus port
│
├── infra/
│   ├── azure/
│   │   ├── blob_storage_config.yaml
│   │   └── openai_deployment.yaml
│   ├── github_actions/
│   │   └── ci_pipeline.yml
│   └── local_dev/
│       ├── setup_ollama.md            ← Guía paso a paso de instalación Ollama
│       └── dev_setup.sh
│
├── docs/
│   ├── architecture/
│   │   └── ADR_001_duckdb_vs_postgres.md
│   └── decisions/
│       └── ADR_002_ollama_vs_azure.md
│
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 5. Hoja de Ruta Semanal (Fase 0 — Semanas 1 a 12)

| Semana | Módulo | Hito Principal | Estado |
|---|---|---|---|
| S-01 | Infraestructura | Entorno local: venv, DuckDB, pytest | ⬜ PENDIENTE |
| S-02 | MOD_07 | Ollama instalado + qwen2.5:14b descargado | ⬜ PENDIENTE |
| S-02 | MOD_07 | Modelfile `stater-audit` con system prompt financiero | ⬜ PENDIENTE |
| S-03 | MOD_04 | Schema DuckDB con 4 tablas clave inicializado | ⬜ PENDIENTE |
| S-04 | MOD_01 | Cliente SEC EDGAR: descarga 10-K piloto + SHA-256 | ⬜ PENDIENTE |
| S-05 | MOD_01 | Clientes CNMV + AMF: primeros ESEF | ⬜ PENDIENTE |
| S-06 | MOD_01 | Los 5 OAMs europeos completos + sync Azure | ⬜ PENDIENTE |
| S-07 | MOD_02 | Parser iXBRL ESEF (Balance + PyG + EFE) | ⬜ PENDIENTE |
| S-08 | MOD_02 | Parser US-GAAP XBRL + Tests A = P + PN (tolerancia 0) | ⬜ PENDIENTE |
| S-09 | MOD_03 | KAM Extractor ISA 701 operativo + integración MOD_07 | ⬜ PENDIENTE |
| S-10 | MOD_03 | CSRD Mapper (20 métricas ESRS piloto) + IAGC | ⬜ PENDIENTE |
| S-11 | MOD_05 | 20 ratios financieros + DCF engine con 3 escenarios | ⬜ PENDIENTE |
| S-12 | MOD_06 | FastAPI con 3 endpoints operativos + GitHub Actions verde | ⬜ PENDIENTE |

---

## 6. Debate Técnico: Ollama Local vs Azure OpenAI vs Arquitectura Híbrida

> **Decisión Adoptada: Arquitectura Híbrida con Router Inteligente (MOD_07)**

### 6.1. ¿Qué es Ollama y por qué lo integramos?

[Ollama](https://ollama.ai) es un runtime de LLMs locales para Windows/Mac/Linux. Permite ejecutar `qwen2.5:14b` directamente en tu hardware sin enviar datos a ningún servidor externo. Para STATER es estratégico por:
- **Confidencialidad:** Los filings de clientes B2B nunca salen del perímetro.
- **Coste cero en Fase 0:** Sin factura por llamada en el procesamiento batch nocturno.
- **Independencia técnica:** Si Azure cambia su política, el motor sigue funcionando.

### 6.2. Comparativa de Opciones

| Criterio | Ollama Local (qwen2.5:14b) | Azure OpenAI (GPT-4o) | Híbrido (Router MOD_07) |
|---|---|---|---|
| **Coste por extracción** | 0,00 € | ~0,005-0,02 $/1K tokens | Mínimo (Ollama primero) |
| **Calidad KAM/CAM** | ★★★★☆ (excelente) | ★★★★★ (óptima) | ★★★★★ |
| **Confidencialidad** | Total (local) | Datos a Azure | Control por tipo de tarea |
| **Disponibilidad 24/7** | Requiere workstation | Cloud always-on | Fallover a Azure |
| **Créditos Founders Hub** | No aplica | Cubre con 2.500$ OpenAI | Aplica para producción |

### 6.3. Instalación Paso a Paso de Ollama (Semana 2)

**Paso 1: Instalación en Windows**
```powershell
winget install Ollama.Ollama
ollama --version
```

**Paso 2: Descarga del modelo**
```powershell
# Requiere ~9 GB de disco y 16-32 GB RAM
ollama pull qwen2.5:14b
ollama list
```

**Paso 3: Crear Modelfile personalizado para auditoría financiera**
```dockerfile
# mod_07_ai_agents/modelfiles/Modelfile.stater-audit
FROM qwen2.5:14b

SYSTEM """
You are STATER Audit Intelligence, a forensic financial analyst specialized in:
- Extracting Key Audit Matters (KAMs) under ISA 701 and Critical Audit Matters
  (CAMs) under PCAOB AS 3101.
- Mapping CSRD/ESRS sustainability disclosures (E1-G1) and detecting greenwashing.
- Analyzing corporate governance disclosures (IAGC, board composition).

Rules:
1. Always output structured JSON. Never free text.
2. Classify each KAM/CAM with severity: LOW | MEDIUM | HIGH | CRITICAL.
3. Flag any Going Concern paragraph with severity: CRITICAL.
4. Only use information present in the provided text. Never hallucinate data.
"""

PARAMETER temperature 0.1
PARAMETER top_p 0.9
```

```powershell
ollama create stater-audit -f ./mod_07_ai_agents/modelfiles/Modelfile.stater-audit
ollama run stater-audit "Extract KAMs from: [texto de prueba]"
```

**Paso 4: El código es idéntico en Ollama (local) y Azure OpenAI (producción)**

```python
# mod_07_ai_agents/src/agent_router.py
class AgentRouter:
    def route(self, task_type: str, env: str):
        if env == "local" or task_type == "batch_confidential":
            return OllamaAgent(model="stater-audit")
        elif env == "azure" or task_type == "high_precision":
            return AzureOpenAIAgent(deployment="gpt-4o")
        else:
            return HybridFallbackAgent()  # Intenta Ollama, fallback a Azure
```

> **Implicación clave:** El cambio de Ollama a Azure OpenAI solo requiere cambiar
> la variable `STATER_ENV`. No se reescribe ningún módulo al escalar a producción.

### 6.4. Capacidad de los Créditos Azure OpenAI (Founders Hub)

Con los **2.500 $ de créditos Azure OpenAI** del nivel Ideate:
- GPT-4o cuesta ~0,005 $/1K tokens de entrada.
- Un informe 10-K tiene ~15.000 tokens.
- **Los 2.500 $ cubren la extracción de KAMs de ~33.000 informes completos.**

---

## 7. Stack Técnico y Dependencias

```toml
# pyproject.toml
[tool.pytest.ini_options]
minversion = "8.0"
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=80"

[tool.black]
line-length = 100
target-version = ["py312"]
```

| Categoría | Librería | Versión | Justificación |
|---|---|---|---|
| Data Lake | `duckdb` | >=1.0 | Motor SQL analítico embebido |
| Columnar Storage | `pyarrow` | >=15.0 | Lectura/escritura Parquet |
| DataFrames | `pandas` | >=2.1 | Transformaciones tabulares |
| HTTP Client | `httpx` | >=0.27 | Async para descargas y Ollama API |
| HTML Parser | `beautifulsoup4` + `lxml` | latest | Extracción HTML de 10-K y ESEF |
| AI (local) | Ollama REST API via `httpx` | — | Sin SDK; API REST estándar compatible con OpenAI |
| AI (Azure) | `openai` | >=1.14 | SDK oficial Azure OpenAI |
| Azure Storage | `azure-storage-blob` | >=12.19 | Sync a Azure Blob |
| API Framework | `fastapi` + `uvicorn` | >=0.110 | REST de alta performance |
| Validación | `pydantic` | >=2.6 | Schemas con tipado estricto |
| Testing | `pytest` + `pytest-cov` | >=8.0 | Coverage >= 80% exigida |
| Logging | `loguru` | >=0.7 | Logs JSON estructurados para todos los módulos (MOD_08) |
| Métricas | `prometheus_client` | >=0.20 | Exposición de métricas para Grafana / Azure Monitor |

---

## 8. Modelo de Datos del Data Lake (DuckDB)

### Tabla: `documents_raw` (capa RAW, inmutable)
```sql
CREATE TABLE documents_raw (
    doc_id          VARCHAR PRIMARY KEY,
    source          VARCHAR NOT NULL,    -- 'SEC_EDGAR' | 'CNMV' | 'AMF' | 'BAFIN' | 'CONSOB' | 'AFM'
    issuer_lei      VARCHAR,
    issuer_isin     VARCHAR,
    ticker          VARCHAR,
    doc_type        VARCHAR NOT NULL,    -- '10-K' | 'ESEF' | 'CSRD'
    fiscal_year     INTEGER,
    download_url    VARCHAR NOT NULL,
    file_path       VARCHAR,
    sha256_hash     VARCHAR(64) NOT NULL,
    download_ts     TIMESTAMP DEFAULT NOW(),
    status          VARCHAR DEFAULT 'RAW' -- 'RAW' | 'PARSED' | 'FAILED' | 'QUARANTINE'
);
```

### Tabla: `financial_panel` (capa CORE, panel anual normalizado)
```sql
CREATE TABLE financial_panel (
    entity_lei          VARCHAR,
    fiscal_year         INTEGER,
    source_market       VARCHAR,         -- 'US' | 'ES' | 'FR' | 'DE' | 'IT' | 'NL'
    -- Estado de Situación Financiera
    total_activo        DOUBLE,
    activo_corriente    DOUBLE,
    total_pasivo        DOUBLE,
    patrimonio_neto     DOUBLE,
    -- Cuenta de Resultados
    revenue             DOUBLE,
    ebitda              DOUBLE,
    beneficio_neto      DOUBLE,
    -- Flujos de Efectivo
    cfo                 DOUBLE,
    capex               DOUBLE,
    fcf                 DOUBLE,
    -- Control de Calidad
    balance_check       BOOLEAN,         -- TRUE si Activo = Pasivo + PN
    version_id          VARCHAR,         -- vYYYYMMDD (snapshots diarios)
    PRIMARY KEY (entity_lei, fiscal_year)
);
```

### Tabla: `audit_kams` (capa ANALYTICS)
```sql
CREATE TABLE audit_kams (
    kam_id            VARCHAR PRIMARY KEY,
    entity_lei        VARCHAR,
    fiscal_year       INTEGER,
    topic             VARCHAR,  -- 'revenue_recognition' | 'impairment' | 'going_concern'
    severity          VARCHAR,  -- 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
    text_span         TEXT,
    extraction_method VARCHAR,  -- 'regex' | 'ollama' | 'azure_openai'
    status            VARCHAR DEFAULT 'RAW'  -- 'RAW' | 'VALIDATED' | 'FLAGGED'
);
```

---

## 9. Pruebas y Calidad — Regla de Cero Tolerancia

```python
# mod_02_parser/tests/test_balance_validator.py

def test_balance_passes_for_valid_filing(sample_esef_filing):
    result = balance_validator.validate(sample_esef_filing)
    assert result.is_balanced is True

def test_balance_quarantines_imbalanced_filing(broken_filing):
    """Cualquier descuadre, por mínimo que sea, envía el filing a cuarentena."""
    result = balance_validator.validate(broken_filing)
    assert result.is_balanced is False
    assert result.status == "QUARANTINE"
```

### GitHub Actions CI
```yaml
# .github/workflows/ci.yml
name: STATER Motor Argos CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: pytest --cov=src --cov-report=xml --cov-fail-under=80
      - run: python -m black --check src/
      - run: python -m mypy src/
```

---

## 10. Variables de Entorno

```bash
# .env.example — Copiar a .env y rellenar. NUNCA committear .env.

STATER_ENV=local                           # 'local' | 'azure'

# Azure Storage (Microsoft Founders Hub)
AZURE_STORAGE_CONNECTION_STRING=...
AZURE_BLOB_CONTAINER_RAW=stater-raw-filings

# Azure OpenAI (Fase 1+)
AZURE_OPENAI_KEY=...
AZURE_OPENAI_ENDPOINT=https://stater-openai.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Ollama (local, Fase 0)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=stater-audit

# API
STATER_API_HOST=0.0.0.0
STATER_API_PORT=8000
```

---

## 11. Checklist de Hitos de Desarrollo (Fase 0)

- [ ] Entorno local configurado (Python 3.12, DuckDB, pytest)
- [ ] Ollama instalado y `qwen2.5:14b` descargado (Semana 2)
- [ ] Modelfile `stater-audit` creado y testeado (Semana 2)
- [ ] MOD_04: Schema DuckDB con 4 tablas core creado (Semana 3)
- [ ] MOD_01: Cliente SEC EDGAR con SHA-256 operativo (Semana 4)
- [ ] MOD_01: Los 5 clientes OAMs europeos completados (Semana 6)
- [ ] MOD_01: Sync a Azure Blob Storage con créditos Founders Hub (Semana 6)
- [ ] MOD_02: Parser iXBRL ESEF extrayendo Balance + PyG + EFE (Semana 7)
- [ ] MOD_02: Tests de cuadre `A = P + PN` con 0 tolerancia (Semana 8)
- [ ] MOD_03: KAM Extractor + integración MOD_07 (Semana 9)
- [ ] MOD_03: CSRD Mapper 20 métricas + IAGC (Semana 10)
- [ ] MOD_05: 20 ratios + DCF engine 3 escenarios (Semana 11)
- [ ] MOD_06: FastAPI 3 endpoints + GitHub Actions verde (Semana 12)

---

## 12. Inventario de Módulos y Propuesta MOD_08

| # | Módulo | Descripción | Estado |
|---|---|---|---|
| MOD_01 | Ingestion | SEC EDGAR + 5 OAMs + SHA-256 | A desarrollar |
| MOD_02 | Parser XBRL | IFRS ESEF + US-GAAP + validador cuadre | A desarrollar |
| MOD_03 | NLP Audit | KAM/CAM, CSRD, IAGC, Notas | A desarrollar |
| MOD_04 | Data Lake | DuckDB + Parquet + 4 capas + snapshots | A desarrollar |
| MOD_05 | Quant SFI | 40+ ratios, DCF, factores, backtesting | A desarrollar |
| MOD_06 | API Gateway | FastAPI REST + auth + OpenAPI spec | A desarrollar |
| MOD_07 | AI Agents | Ollama + Azure OpenAI router | A desarrollar |
| MOD_08 | Monitor & Alertas | Logger JSON (loguru) + métricas Prometheus + Data Quality Checker | **APROBADO — A desarrollar** |

---

*Documento generado por STATER — Actualizar columna ESTADO en la Sección 11 conforme avanza el desarrollo.*  
*Última revisión: 2026-08-24 · Próxima revisión: Semana 4 de desarrollo.*
