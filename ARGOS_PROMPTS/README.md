# STATER PROMPTS — AUDITORÍA TÉCNICA DE LOS 8 MÓDULOS DE ARGOS
**Área:** Arquitectura de Software e Ingeniería Cuantitativa  
**Ecosistema:** STATER MOTOR ARGOS / STATER_PROMPTS  
**Fecha de auditoría:** Agosto 2026

---

## ÍNDICE DE INFORMES POR MÓDULO

Este directorio contiene los **8 informes técnicos exhaustivos**, uno por cada módulo de la arquitectura de ARGOS.  
Cada informe describe con rigor **lo que existe en código actualmente**, sus clases, métodos, esquemas SQL, tests unitarios, capacidades reales y limitaciones técnicas.

```
STATER_PROMPTS/
├── README.md                      (Este índice maestro)
├── INFORME_MOD_01_INGESTION.md    (Módulo 01: Ingesta Transatlántica SEC + 5 OAMs Europeos)
├── INFORME_MOD_02_PARSER.md       (Módulo 02: Parser XBRL/iXBRL, Mapeo y Validador de Balance)
├── INFORME_MOD_03_NLP_AUDIT.md    (Módulo 03: Extractor de KAMs ISA 701, CSRD y Greenwashing)
├── INFORME_MOD_04_DATA_LAKE.md    (Módulo 04: Data Lake Columnar DuckDB + Parquet)
├── INFORME_MOD_05_QUANT_SFI.md    (Módulo 05: Motor Cuantitativo 40+ Ratios y Valoración DCF)
├── INFORME_MOD_06_API_GATEWAY.md  (Módulo 06: Gateway REST FastAPI y Distribución Institucional)
├── INFORME_MOD_07_AI_AGENTS.md    (Módulo 07: Enrutador de Agentes IA Ollama / Azure OpenAI)
└── INFORME_MOD_08_MONITOR.md      (Módulo 08: Observabilidad Prometheus, Logs JSON y Data Quality)
```

---

## RESUMEN EJECUTIVO DE ESTADO TÉCNICO

```
┌────────┬─────────────────────────────┬──────────────┬───────────────┬──────────────────────────────┐
│ MÓDULO │ DENOMINACIÓN TÉCNICA        │ ARCHIVOS SRC │ TESTS PASADOS │ ESTADO FUNCIONAL ACTUAL      │
├────────┼─────────────────────────────┼──────────────┼───────────────┼──────────────────────────────┤
│ MOD_01 │ Ingestor Multi-Regulador    │ 11 archivos  │ 8 tests (OK)  │ Arquitectura y SEC listos    │
│ MOD_02 │ Parser XBRL / iXBRL         │ 5 archivos   │ 5 tests (OK)  │ Decodificación y Balance OK  │
│ MOD_03 │ NLP Audit & KAMs            │ 6 archivos   │ 2 tests (OK)  │ Prompts e ISA 701 listos     │
│ MOD_04 │ Data Lake DuckDB / Parquet  │ 2 archivos   │ 4 tests (OK)  │ DDL SQL y ACID operativos    │
│ MOD_05 │ Quant SFI Lab               │ 3 archivos   │ 4 tests (OK)  │ Ratios y DCF deterministas   │
│ MOD_06 │ API Gateway FastAPI         │ 3 archivos   │ 4 tests (OK)  │ Endpoints REST y Swagger OK  │
│ MOD_07 │ AI Agents Router            │ 4 archivos   │ 4 tests (OK)  │ Enrutador Ollama/Azure OK    │
│ MOD_08 │ Monitor & Data Quality      │ 4 archivos   │ 5 tests (OK)  │ Logger JSON y 7 Reglas OK    │
├────────┴─────────────────────────────┴──────────────┴───────────────┴──────────────────────────────┤
│ TOTAL: 8 MÓDULOS INTEGRADOS          │ 38 archivos  │ 36 tests (OK) │ 100% SUITE VERDE             │
└────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
