---
title: PLAN MAESTRO ARGOS / STATER — PRODUCTION ROADMAP v1
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - Baseline 2026-09-07 (Fase 0)
products_served:
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - SFI Lab Desktop
  - Campus LUMINIC C1/C2
  - Data Lake ARGOS (capa Gold)
---

# PLAN MAESTRO — ARGOS / STATER (Producción)

> Roadmap de produccion del repositorio ARGOS hacia plataforma FinTech de datos institucionales. Documento maestro: hoja de ruta semana-s semana, criterios binarios y gobernanza del contrato de tests.



## 1. Resumen ejecutivo

ARGOS evoluciona desde un motor con 8 modulos y **88 tests en verde**, catalogo maestro espanol de **175 emisores** (IBEX 35: 34, Mercado Continuo: 87, BME Growth: 54, sicimis: 0) y **cero datos reales en disco**, hasta una **plataforma FinTech de datos institucionales en produccion**: Data Lake multi-pais con datos ESEF reales, API B2B institucional, web corporativa PLG y observabilidad de operaciones. La ingesta de datos reales de los 5 paises europeos + SEC es la **columna vertebral**; todo lo demas es dependiente de ella.





**Reglas cardinales**:
- **Solo datos reales**: prohibido ejecutar `clean_and_rebuild_all_institutional.py` e `institutional_document_builder.py`; prohibido generar datos financieros sinteticos fuera de fixtures de test mockeados.
 
- **Contrato de tests inviolable**: `python -m pytest ARGOS_MOTOR/ -q` debe terminar con **>= 88 passed** despues de CADA fase. Los 2 tests de `archive/legacy_scripts_pre_v3/` estan fuera del testpaths y no cuentan.



- **Criterios binarios**: cada fase termina solo cuando su criterio es verificablemente TRUE (tests verdes,, archivo existe con hash,, endpoint  ́200 con schema validado,, parquet con row_count exacto). Cat



##  ́2. Estado actual verificado (baseline  ́2026-09-07)

| Componente | Estado real verificado | Implicacion |
|---|---|---|---|---|---|
| MOD_01 Ingesta | Clientes por pais(ES,, FR,, DE,, IT,, NL,, US] via `oam_router.py` con `SUPPORTED_MARKETS = [US, ES,, FR,, DE,, IT,, NL]`. ES tiene pipeline completo(paquete 5 docs,, validacion por ramas,, SHA-256). FR/DE/IT/NL tienen `download_filing` pero sin descubrimiento de filings(gap a cerrar en Fase 7) | Fase 1 completa ES; Fase 7 cierra descubrimiento por pais |
| MOD_02 Parser | `xbrl_parser.py` lee nonFraction/fraction sin contextos ni scaling; `taxonomy_dict.yaml` carece de ebitda,, fcf,, financial_result,, beneficio_atribuible,, dividendos_pagados | Extension obligatoria en Fases 1/2 |
| MOD_04 Data Lake |  ́5 tablas SQL (documents_raw,, financial_facts_raw con `is_restated`,, financial_panel con `source_market`/`accounting_standard`/`balance_check`,, audit_kams,, esg_kpis;;`export_table_to_parquet(...PARTITION_BY)` implementado | Sin `country_code` en documents_raw; se anade por migracion compat (Fase 2) |
| MOD_06 API | `/health`, `/companies/{lei}/financials`, `/companies/{lei}/kams`, `/companies/{lei}/valuation` existentes; auth primitivo (admin key + prefijo `stater_`). README promete `/companies/{lei}/esg`, `/sectors/{sic}/scores`, `POST /datasets/bulk` (no implementados) | Bloque C: catalogo completo + tiers + cache + OpenAPI 3.1 |
| MOD_08 Monitor | Metricas Prometheus: `stater_documents_ingested_total`, `stater_parse_errors_total`, `stater_balance_quarantines_total`, `stater_agent_calls_total`, `stater_api_requests_total`, `stater_api_latency_seconds` | Faltan dashboards Grafana,, scheduler,, deteccion restatements (Bloque E) |
| Infra | CI template `infra/github_actions/ci_pipeline.yml`; configs Azure; **NO existen Dockerfile, docker-compose, Helm ni k8s** | Bloque E crea la capa container desde cero |
| Config | `master_universe_es.json` v3.24.0: 175 entidades,, 157 sectores,, LEI GLEIF con `resolution_score` | Plantilla para catalogos FR/DE/IT/NL |
| Data | `data/` vacio: cero ESEF descargados, cero Parquet, cero DuckDB real | Fase 1 es 100% datos reales; sin atajo ni simulacion |
| Tests | Baseline ejecutado: **88 passed** con Python 3.13; clone **shallow** documentado | `_baseline_2026-09-07.json` es el andamiaje del contrato |







##  ́3. Hoja de ruta semana-s semana (Gantt simplificado)

| Semana | Bloque | Tarea | Equipo | Criterio binario | Dependencias |
|---|---|---|---|---|---|---|---|
| 1 | A-ES | Ingesta ES: descubrimiento, catalogo,, descarga batch | Datos/Io | Inventario ESEF + manifiesto con SHA-256 reanudable | Fase 0 |
| 1 | A-ES | Validacion AI Guard + Branch Threshold | Datos/Io | Cero Lorem Ipsum; ZIP invalidos a QUARANTINE | Descarga real |
| 1 | A-ES | Extraccion XBRL y carga RAW/STAGING/CORE | Datos/Ing | `balance_check=TRUE` tolerancia cero | Parser contextos |
| 2 | A-ES/B | Continuar parseo + ampliar `taxonomy_dict.yaml` | Ing | `ebitda`, `fcf`, `financial_result`, `beneficio_atribuible`, `dividendos_pagados` mapeados | Parser |
|  ́2 | B | Data Lake multi-pais: country_code, Parquet,, bridges,, versionado | Ing/Plat |  ́88 + tests nuevos bridge/versionado verdes; Parquet row_count == DuckDB | Esquemas v1 |
|  ́3 | A-ES/B | **Cierre ES Gold** + auditoria forense | Datos/Aud | ES: `balance_check=TRUE` >= 50; forensic 100% hashes | Parseo completo |
|  ́3 | E | Observabilidad incremental: metricas, dashboards, scheduler | Plat | Dashboard con datos reales; scheduler sin solapamientos | Data en disco |
|  ́4 | A-ES/B | Consolidacion ES + Data Lake | Datos/Aud | Cobertura media >=  ́60%; `issuer_gold_status`; 88 verdes | Fases 1-2 |
|  ́5 | C | **API Institucional B2B** (solo si ES >=  ́50 Gold) | Plat |  ́8 endpoints  ́200; spec OpenAPI validada; tests auth/bulk/cache | ES Gold |
|  ́6 | D | **Web Corporativa PLG**: screener, auth,, CWV | Web | `npm run build` + lighthouse >=  ́90; WCAG AA | API v1 |
|  ́6 | E | Infra Ops: Dockerfile,, compose,, Helm,, CI/CD | DevOps | `docker compose up` /health 200;; `helm lint` OK;; gitleaks limpio | Fases 1-3 |
|  ́7 | E | Observabilidad produccion: restatements,, alertas,, SLO | Plat | Test restatement >5% genera alerta | Scheduler |
|  ́7 | A-FR | **Activacion Francia** | Datos | FR: >=  ́30 Gold;; manifiesto FR | ES Gold; Bridge FR |
|  ́9 | A-DE | **Activacion Alemania** | Datos | DE: >=  ́30 Gold;; `taxonomy_bridge_de.yaml` | FR activa |
|  ́11 | A-IT | **Activacion Italia** | Datos | IT: >=  ́30 Gold | DE activa |
|  ́13 | A-NL | **Activacion Paises Bajos** | Datos | NL: >=  ́30 Gold | IT activa |
|  ́14 | A-US | **SEC EDGAR continua**: backlog 4.853 10-K | Datos | Manifiesto SEC incremental; rate limit 10 rps | — |
|  ́15-16 | F+G | Consolidacion: hoja de ruta,, matriz riesgos,, validacion e2e | Dir/Ing | Documentos completoscon frontmatter; e2e OK | Todas |



##  ́4. Estructura de entregables (docs/planificacion/)

| Documento | Contenido |
|---|---|
| `PLAN_MAESTRO_ARGOS_v1.md` | Resumen ejecutivo + hoja de ruta semana-s semana |
| `SPEC_INGESTA_ES.md` | Plan ingesta Espana(6 secciones fijas) |
| `SPEC_INGESTA_FR.md` | Plan ingesta Francia |
| `SPEC_INGESTA_DE.md` | Plan ingesta Alemania |
| `SPEC_INGESTA_IT.md` | Plan ingesta Italia |
| `SPEC_INGESTA_NL.md` | Plan ingesta Paises Bajos |
| `SPEC_INGESTA_US_SEC.md` | Plan ingesta SEC EDGAR |
| `SPEC_DATA_LAKE_MULTI_PAIS.md` | Data Lake: particionado,, bridges,, versionado,, capas,, Gold |
| `SPEC_API_INSTITUCIONAL.md` | Endpoints + auth/keys/webhooks + cache + OpenAPI 3.1 + SLA |
| `SPEC_WEB_CORPORATIVA.md` | Web Next.js + hub + screener PLG + auth + CWV/SEO/WCAG |
| `SPEC_INFRA_OBSERVABILIDAD.md` | Salud Data Lake + restatements + scheduler + DevOps/k8s |
| `MATRIZ_RIESGOS.md` | 6 riesgos obligatorios + 2 observados |



##  ́5. Validacion final end-to-end (pre-lanzamiento)

1. `python -m pytest ARGOS_MOTOR/ -q` → **88+ passed**
2. `curl http://localhost:8000/health` → 200 con `status=HEALTHY`
3. `curl http://localhost:8000/companies/{lei}/financials?year=2024` → 200 con schema `FinancialsResponse` y `balance_check=true`
4. `curl http://localhost:8000/screener/filter?country=ES&index=IBEX35` →  ́200 con filas reales y CSV exportable
5. Forensic audit: 100% SHA-256 recomputados == hashes en `documents_raw`
6. Panel Grafana: `fully_covered` por pais >  ́0 y alertas gap activas
7. Restatement: fixture modificado >5% genera alerta e2e `is_restated=TRUE`



##  ́6. Criterios de aceptacion por fase

| Fase | Validacion primaria | Secundaria |
|---|---|---|---|---|---|
| 0 | `pytest` >= 88 passed | Baseline con hash existe |
| 1 | ES Gold (`balance_check=TRUE`) >= 50 | Inventario + manifiesto + forensic 100% |
|  ́2 |  ́88 + tests nuevos pass | Parquet row_count == DuckDB; country_code poblado |
|  ́3 | tests auth/screener/bulk/cache pass |  ́8 endpoints  ́200; OpenAPI validada |
|  ́4 | `npm run build` + lighthouse >=  ́90 |  ́0 dead links; WCAG AA |
|  ́5 | `docker compose up` + /health  ́200 | helm lint/template OK; gitleaks limpio; backup restaurado |
|hab  ́6 | tests restatement /> ́5% y  ́<5% pasan | Dashboard con datos reales; SLO 15 min / 4 h |
|hab  ́7 | FR/DE/IT/NL >=  ́30 Gold cada uno | Manifiestos con hash; 6 SPEC_INGESTA existentes |
|hab  ́8 |  ́8+1 documentos con frontmatter YAML valido | Hoja de ruta y matriz de riesgos completas |