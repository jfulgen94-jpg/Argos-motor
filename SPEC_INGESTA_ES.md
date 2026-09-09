---
title: SPEC — Ingesta España (CNMV / BME / ESEF)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Baseline 2026-09-07 (Fase 0)
products_served:
  - Data Lake ARGOS (capa Gold)
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
---
# SPEC — Ingesta España (CNMV / BME / ESEF)

##  ́1. Objetivo y alcance

Alcanzar **>=  ́50 emisores espanoles con los 5 documentos reales** en capa Gold del Data Lake: sello SHA-256,, panel financiero cuadrado(tolerancia cero: A = P + PN)y cobertura documental media >=  ́60%. Alcance: ejercicios 2020-2024 (ventana ESEF ESMA; paquetes anuales consolidados).). Los **175 emisores** del `master_universe_es.json` v3.24.0 (IBEX 35:34, MERCADO_CONTINUO: 87, BME_GROWTH: 54; sicimis excluidos: 0) son la lista maestra contra la que se cruza el descubrimiento.



##  ́2. Fuente reguladora y canal

| Canal | URL / API | Perfil |
|---|---|---|---|---|---|
| A — ESEF ESMA | `https://filings.xbrl.org/api/filings?filter[country]=ES&filter[period_end]={year}-12-31&page[size]=200&include=entity` | API JSON:API publica. Paginacion exhaustiva; resolucion de LEI via relacion formal `entity`. ~542 paquetes ESEF (2020-2024) para Espana. Descarga streaming con magic bytes `PK\x03\x04` y SHA-256 en vuelo |
| B — CNMV | `https://www.cnmv.es` | IAGC,, IARC e informes adicionales. Descarga ZIP/XHTML/PDF con `User-Agent` STATER y `Accept-Language: es-ES` |
| C — BME Growth | `bme_growth_client.py` | Segmento BME Growth(54 emisores): paquetes complementarios |

**Rate limiting real** (documentado): `xbrl_org_client.py` duerme **0.3 s entre paginas** (≈3.3 req/s; paginas de 200 filings); timeout  ́25 s consulta /  180 s descarga. Canal CNMV: `RobustDownloader` con backoff exponencial(timeout 120 s). Maximo 2 descargas simultaneas por canal. Ventana preferente 02:00-06:00 CEST para paquetes grandes(XHTML 50-111 MB.



##  ́3. Catalogo y universo

Estructura por emisor(`master_universe_es.json`):

```json
{
  "ticker": "SAN",
  "cif_nif": "A-39000013",
  "lei": "5493006QMFDDMYWIAM13",
  "name_legal": "Banco Santander, S.A.",
  "segment": "IBEX35",
  "sector": "Banca",
  "is_socimi": false,
  "fiscal_year_end": "12-31",
  "resolution_score": 1.0
}
```

Campos operativos: `lei` GLEIF (20 chars); `segment` {IBEX35,, MERCADO_CONTINUO, BME_GROWTH}; `sector` (157 clases); `is_socimi` (exclusion tajante SOCIMIs/fondos/ETFs/SPVs: 0 en catalogo); `resolution_score`(GLEIF >= 0.90; fallback manuala `PENDING_REVIEW`).

**Cruza de descubrimiento**: `xbrl_org_client.get_country_filings("ES", year)` para 2020-2024; cada emisor deve resolver su LEI exacto al filing(`entity.lei` o ruta `/([A-Z0-9]{20})/` en `package_url`). Emisores sin filing en 3 anios → inventario `GAP` razonado. Criterio: inventario `data/raw/ES_CNMV/_ESEF_INVENTORY_{ts}.json` por LEI+anio+package_url+sha256}.



##  ́4. Pipeline de descubrimiento y descarga

Pasos reanudables:

1. **Descubrimiento**: paginar `get_country_filings("ES", year)` (cache por pais+anio; 3.3 req/s max).
2. **Catalogo**: cruzar LEI contra el universo;; emisores nuevos detectados → inventario;; `resolution_score< 0.90` → `PENDING_REVIEW`.
3. **Manifiesto idempotente** — `data/raw/ES_CNMV/_DOWNLOAD_CP.json`: cada ZIP se **sella SHA-256** y se verifica **magic bytes `PK\x03\x04`**; `status ∈ {DONE, BUNDLE_ONLY,GAP}`;**nunca se redescarga** un ZIP ya sellado con mismo hash;; un run a mitad retoma sin duplicar.


4. **Organizacion**: `cnmv_real_downloader.py` + `bundle_manager.py`; paquete 5 documentos por emisor-anio:`ESEF_PACKAGE`(ZIP), `INFORME_GESTION`, `EINF_CSRD`, `IAGC`, `IARC`.
5. **Sellado**: `sha256_sealer.py` registra `sha256_hash`, `file_size_bytes`, `download_url`, `download_ts`.

Criterio: para cada emisor:`status ∈ {DONE,, BUNDLE_ONLY,, GAP}` y reanudable tras interrupcion.



##  ́5. Validacion y parseo

**AI Guard + Branch Threshold** (`ai_pre_validation_guard.py`, `branch_threshold_validator.py`) — umbrales reales para espanol:



| Rama | min_chars | min_size_bytes | secciones min | Secciones requeridas |
|---|---|---|---|---|---|---|---|
| CCAA_AUDITED | |10.000 | |12.000 |4 | balance consolidado/de situacion; perdidas y ganancias; flujos de efectivo; memoria/notas; informe de auditoria |
| INFORME_GESTION | |4.000 | ||5.000 |3 | evolucion de los negocios; riesgos e incertidumbres; riesgo liquidez/credito/mercado; acciones propias; I+D |
| EINF_CSRD | ||3.500 | ||4.500 |3 | medioambiente; social; gobernanza; CSRD/ESRS |
| IAGC | ||3.000 | ||3 | gobierno corporativo; consejo; comisiones |
| IARC | ||2.500 | ||2 | remuneraciones; polica de remuneraciones |

**Anti-Lorem-ipsum**: `detect_lorem_ipsum=True` → **QUARANTINE** tajante. ZIP invalido → **QUARANTINE** con `quarantine_msg`.



**Parseo XBRL**: extender `xbrl_parser.py` para contextos reales(dimensiones,, `decimals`, scaling,, unidades,, `periods`) y ampliar `taxonomy_dict.yaml` con `ebitda`, `fcf`, `financial_result`, `beneficio_atribuible`, `dividendos_pagados` y otros IFRS. Ref: extender `test_xbrl_parser.py` y `test_taxonomy_mapper.py` sin romper los 88.



Carga: `documents_raw`(RAW), `financial_facts_raw`(STAGING,, `financial_panel`(CORE,, regla **A = P + PN, `balance_check` TRUE**, tolerancia cero.



##  ́6. Carga, auditoria y liberacion Gold

**Auditoria forense retroactiva** (`forensic_dataset_auditor.py`):
- 100% SHA-256 recomputados == `documents_raw.sha256_hash`;
- cada emisor Gold cumple el contrato de 5 documentos)(o `GOLD_PARTIAL` con gap documentado);
- informe `FORENSIC_AUDIT_ES_{ts}.json` con `total_checks`, `passed`, `quarantined`, `coverage_pct`.



**Liberacion Gold**: `coverage = n_docs / 5`; `coverage=1.0` + `balance_check=TRUE` + sha256 verificado → `fully_covered`; con gap → `GOLD_PARTIAL`. Vista `issuer_gold_status`: `country_code, entity_lei, fiscal_year, coverage_ratio, gold_status`.



**Criterio de aceptacion global**:
- `SELECT COUNT(*) FROM financial_panel WHERE source_market='ES' AND balance_check=TRUE` **>= 50**;
- Cobertura documental media >= **60%**;
- `_baseline_2026-09-07.json` vigente; **88 tests en verde** despues de CADA subfase.

