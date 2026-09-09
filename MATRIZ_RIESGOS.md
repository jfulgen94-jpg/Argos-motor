---
title: MATRIZ DE RIESGOS — ARGOS / STATER
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Baseline 2026-09-07 (Fase 0)
products_served:
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - Data Lake ARGOS (capa Gold)
---
# MATRIZ DE RIESGOS — ARGOS / STATER

Escala impacto y probabilidad: 1 (minimo) a 5(maximo). Mitigacion: accion tecnica concreta;; Plan B: alternativa si la mitigacion falla. Se anaden **2 riesgos observados** en el repo(parser insuficiente para contextos reales;; `taxonomy_dict.yaml` incompleto) a los **6 obligatorios** del plan maestro.



## Resumen de riesgos

| ID | Riesgo | Impacto | Probabilidad | Exposicion (I×P) | Fase |
|---|---|---|---|---|---|---|---|
| R1 | Bloqueo 403/429 del canal CNMV | |4 | |4 | |16 | Fase 1 |
| R2 | Cambio de esquema ESEF ESMA | |4 | |3 | |12 | Fases 1/2/7 |
| R3 | Licencias de datos derivados OAM | |3 | |4 | |12 | Fases 1-14 |
| R4 | Colapso o indisponibilidad de filings.xbrl.org | |4 | |3 | |12 | Fases 1/2/7 |
| R5 | DuckDB multi-usuario >100 req/s | |3 | |3 | |9 | Fase 3 |
| R6 | Scrapers rotos por rediseno de portales | |4 | |3 | |12 | Fases 1/7 |
| R7 | Parser insuficiente para contextos XBRL reales(observado) | |5 | |4 | |20 | Fase 1 |
| R8 | `taxonomy_dict.yaml` incompleto(observado) | |3 | |4 | |12 | Fases 1/2 |



## R1 — Bloqueo 403/429 del canal CNMV (o filings.xbrl.org)

- **Descripcion**: el portal CNMV o la API de filings.xbrl.org responden 403 (WAF/bot) o 429 (rate limit) al lanzar descargas batch pesadas(paquetes ESEF de 50-111 MB).
- **Impacto**:4 — detiene la columna vertebral durante horas..
- **Probabilidad**:4 — descargas masivas sin cortesia lo provocan..

- **Mitigacion**:
  - Rate limiting por canal:`XBRLOrgClient` ya duerme **0.3 s entre paginas**; `RobustDownloader` backoff exponencial ante 429/403 (timeout 120 s;
  - Ventana preferente 02:00-06:00 CEST;; maximo 2 descargas simultaneas por canal;
  - User-Agent explicito y `Accept-Language` por pais;; Session reutilizada..


- **Plan B**: canal alternativo (`cnmv_portal_scraper.py` + `cnmv_real_downloader.py`) o `bme_growth_client.py` para BME Growth;; espera con jitter y reintentos;; si >24 h, descarga manual HITL.



##R2 — Cambio de esquema ESEF (ESMA)

- **Descripcion**: ESMA cambia la taxonomia o la estructura del paquete(namespaces,, dimensiones,, conceptos),, invalidando parser y bridges..
- **Impacto**:4 — rompe parseo de un ejercicio completo..
- **Probabilidad**:3 — cambios anuales versionados por ESMA..

- **Mitigacion**:
  - `taxonomy_dict.yaml`/`taxonomy_bridge_[country].yaml` versionados por ejercicio;; tests de contrato que fallan si un mapeo no resuelve;; monitor de diff del JSON:API al inicio de ventana..
- **Plan B**: `formula_transform`(SUM componentes) cuando la linea desaparece;; fallback `PENDING_REVIEW` y revision contable;; forensic recalcula SHA-256 y cuadre A = P + PN para detectar roturas temprano..



##R3 — Licencias de datos derivados OAM

- **Descripcion**: los datos ESEF y portales imponen condiciones de uso;; la reventa de datos derivados:(ratios,, scores,) sin licencia o atribucion puede generar requerimientos legales..
- **Impacto**:3 — riesgo legal/reputacional en el modelo B2B..
- **Probabilidad**:4 — el modelo PLG expone datos derivados publicamente...

- **Mitigacion**:
  - Auditoria legal de los 6 OAMs;; **attribution obligatoria** en web/API;; datos derivados como valor anadido propio(transformaciones); terminos en `/empresa/aviso-legal` y Developer Portal..
- **Plan B**: Enterprise con contrato de reventa por pais;; o tier Free restringido a indices libres(IBEX 35 + CAC  40 + DAX  30.



##R4 — Colapso o indisponibilidad de filings.xbrl.org

- **Descripcion**: el agregador ESEF cae o degrada,, bloqueando descubrimiento y descarga de FR/DE/IT/NL..
- **Impacto**:4 — paraliza la expansion geo y la deteccion de filings nuevos..
- **Probabilidad**:3 — servicio publico comunitario..

- **Mitigacion**:
  - Clientes nacionales con `list_filings()`/`discover()` propios;; cache local de `get_country_filings`(ya `_cache_filings`) persistida en disco;; polling 15 min con backoff y stale-while-revalidate..
- **Plan B**: descarga directa de registradores nacionales(Unternehmensregister,, BDIF,, 1INFO,, AFM) con resolucion LEI local;; cadencia diaria durante la caida..



##R5 — DuckDB multi-usuario >100 req/s

- **Descripcion**: DuckDB es embebido;; la API B2B (>100 req/s,, 500 usuarios) puede degradar conexiones concurrentes..
- **Impacto**:3 — degradacion de la API institucional;; SLO p95 en riesgo..
- **Probabilidad**:3 — volumenes alcanzables en produccion..

- **Mitigacion**:
  - Separacion escrituras/lecturas(replicas DuckDB de solo-lectura); cache Redis (hit_ratio >=  ́80%) absorbe picos;; exportacion Parquet para screener/bulk (sin tocar DuckDB.

- **Plan B**: migrar capa de servicio a DuckDB sobre S3 o PostgreSQL/Timescale,, preservando DuckDB como ingesta offline;; HPA hasta  500 usuarios.



##R6 — Scrapers rotos por rediseno de portales

- **Descripcion**: CNMV/BME (y FR/DE/IT/NL) redisenan HTML/URL,, rompiendo `cnmv_portal_scraper.py` y selectores..
- **Impacto**:4 — pierde cobertura IAGC/IARC y descarga directa..
- **Probabilidad**:3 — cambios sin aviso..

- **Mitigacion**:
  - **Canal A (filings.xbrl.org) primario**: paquete ESEF via API no depende del HTML;; tests de humo del scraper con fixture;; contrato 5 docs tolerable(`GOLD_PARTIAL` con gap.
- **Plan B**: scrapers alternativos(BME Growth;; descarga directa por URL canonica); o HITL (`remediation_runner.py` + `review_cli.py`.



##R7 — Parser insuficiente para contextos XBRL reales(observado en repo)

- **Descripcion**: `xbrl_parser.py` solo lee `nonFraction`/`fraction` **sin contextos,, dimensiones,, `decimals`, scaling ni periods**; los paquetes ESEF reales usan contextos complejos;; sin extension,, el panel no cuadra ni se llena..
- **Impacto**:5 — invalida `balance_check=TRUE` y toda la Fase  1..
- **Probabilidad**:4 — los fixtures reales ESEF lo demuestran..

- **Mitigacion**:
  - Extension en Fase 1.4: contextos,, `decimals`, scaling,, unidades,, periods;; tests ampliados sin romper los  88;; `balance_check=TRUE` tolerancia cero antes de Gold..
- **Plan B**: parseo iXBRL `ix:nonFraction` con `lxml` y resolucion de `contextRef`;; o referencia cruzada con companyfacts JSON de SEC para el cuadre..



##R8 — `taxonomy_dict.yaml` incompleto(observado en repo)

- **Descripcion**: carece de `ebitda`, `fcf`, `financial_result`, `beneficio_atribuible`, `dividendos_pagados` y otros IFRS;; panel incompleto y screener limitado..
- **Impacto**:3 — panel incompleto y catalogo de ratios(BlC) limitado..
- **Probabilidad**:4 — verificacion directa del YAML..

- **Mitigacion**:
  - Ampliar `taxonomy_dict.yaml` en Fase 1.4 con tests por concepto;; `formula_transform` para derivar `ebitda`/`fcf` cuando no se reportan explicitos(EBITDA = Resultado explotacion + amortizacion;; FCF = CFO − Capex..
- **Plan B**: calculo en capa ANALYTICS (`ratio_engine.py`) con formula documentada en `formulas.yaml`;; mapeo por pais via `taxonomy_bridge_[country].yaml`..



---

## Priorizacion

| Prioridad | IDs |
|---|---|---|
| Critica (I×P >=  ́16) | R7 (20), R1 (16) |
| Alta (12-15) | R2,, R3,, R4,, R6,, R8 |
| Media (<=  9) | R5 |
