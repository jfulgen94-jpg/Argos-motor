---
title: SPEC — Data Lake Multi-Pais (DuckDB + Parquet particionado)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 2 (Bloque B)
  - SPEC_INGESTA_ES.md
products_served:
  - Data Lake ARGOS (capa Gold)
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - SFI Lab Desktop
---
# SPEC — Data Lake Multi-Pais (DuckDB + Parquet particionado)

##  1. Objetivo y alcance

Evolucionar el Data Lake actual (`mod_04_data_lake`: 5 tablas SQL(documents_raw,, financial_facts_raw con `is_restated BOOLEAN DEFAULT FALSE`,, financial_panel con `source_market`/`accounting_standard`/`balance_check`/`version_id`,, audit_kams,, esg_kpis)) a un **Data Lake multi-pais**: capas Bronze/RAW → STAGING → CORE → ANALYTICS, particionado fisico por pais+anio,, versionado **append-only** de hechos(y `country_code` operativo). Regla de oro: **sin ruptura de schemas** — ninguna columna existente se elimina ni renombra; solo se anade por migracion compat.



##  ́2. Migracion DDL compat (country_code)

Migration `mod_04_data_lake/migrations/v002_multicountry.sql`:

```sql
ALTER TABLE documents_raw ADD COLUMN IF NOT EXISTS country_code VARCHAR(2);
-- ISO-3166-1: ES,, FR, DE,, IT,, NL,, US
UPDATE documents_raw SET country_code = CASE
    WHEN source = 'CNMV' THEN 'ES'
    WHEN source = 'AMF' THEN 'FR'
    WHEN source = 'BAFIN' THEN 'DE'
    WHEN source = 'CONSOB' THEN 'IT'
    WHEN source = 'AFM' THEN 'NL'
    WHEN source = 'SEC_EDGAR' THEN 'US'
END WHERE country_code IS NULL;
```

`init_database()` (`lake_manager.py`) sigue idempotente;; las 5 tablas conservan sus columnas;; `financial_panel`/`financial_facts_raw` no se tocan. Criterio: `country_code` poblado en toda fila nueva de `documents_raw`.



##  ́3. Particionado fisico por pais+anio

`export_table_to_parquet(table_name, output_path, partition_cols)` ya existe en `lake_manager.py`. Parametrizacion:

- `documents_raw` y `financial_facts_raw` → `PARTITION_BY(fiscal_year, country_code)`;
- directorio: `data/lake/parquet/{pais}/{ejercicio}/`;
- `parquet_writer.py` con `ROW_GROUP_SIZE` controlado y schema verificable..

Criterio: `export_partitioned.py` produce Parquet con `row_count` **exacto e igual al DuckDB** (chequeo por particion.



##  ́4. Capa de normalizacion multi-taxonomia

`taxonomy_bridge_[country].yaml` (`taxonomy_bridge_de.yaml`, `taxonomy_bridge_fr.yaml` al activar cada pais); estructura:

```yaml
mappings:
  total_activo:
    canonical: total_activo
    local_namespace: de-gaap            # o: fr-gaap
    hgb_concept: [de-gaap:Anlagevermoegen]
    frgaap_concept: [fr-gaap:ActifTotal]
    formula_transform:
      - op: SUM
        components: [activo_no_corriente, activo_corriente]
    priority: IFRS > LOCAL-GAAP
```

`TaxonomyMapper` aprende a cargar bridges por `country_code` (`load_bridge(country)`) y resuelve `canonical` con `formula_transform` cuando la linea consolidada no se reporta(p.ej. HGB). El `taxonomy_dict.yaml` maestro sigue siendo la base canonical(IFRS-FULL/US-GAAP/PGC. Criterio: `test_taxonomy_bridge.py` (nuevo) con mapeo HGB y French GAAP verificados sin romper los 88.



##  ́5. Versionado de hechos (restatements)

Politica **append-only** inmutable:

- Un hecho restated → **fila nueva** con `is_restated=TRUE` y `source_period_original` al ejercicio original;; **nunca** `UPDATE` sobre la fila original..
- `fact_id` = `doc_id + concept + period_end + context`; la version restated lleva sufijo de version( o `version_id` en panel).

 Criterio: test: mismo `fact_id` con dos versiones(FALSE/TRUE) conviven;; `SELECT ... WHERE is_restated=FALSE` retorna **solo** los originales. Detector >5% en `SPEC_INFRA_OBSERVABILIDAD.md`.



##  ́6. Ciclo de vida de capas y latencias

| Capa | Tabla | Contenido | Latencia max |
|---|---|---|---|---|---|
| Bronze/RAW | `documents_raw` | Documentos sellados SHA-256 | Descarga → RAW < 4 h |
| STAGING | `financial_facts_raw` | Hechos granulares XBRL | RAW → STAGING < 2 h |
| CORE | `financial_panel` | Panel anual cuadrado (A = P + PN) | RAW → CORE < 6 h (batch diario) |
| ANALYTICS | MOD_05 | Ratios,, scores,, DCF | CORE → ANALYTICS < 30 min |



##  ́7. Completitud por emisor(contrato 5 documentos)

```sql
coverage_ratio = COUNT(DISTINCT doc_type) / 5
```

- ES: CCAA audited,, Informe de Gestion,, EINF/CSRD,, IAGC,, IARC;
- `balance_check=TRUE` + sha256 verificado + `coverage=1.0` → `fully_covered`(Gold);
- `coverage >= 0.60` con gap tipificado → `GOLD_PARTIAL`;

Vista `issuer_gold_status` por pais/emisor/anio(columnas: `country_code, entity_lei, fiscal_year, coverage_ratio, gold_status)`). Se materializa en migration v003 cuando existan datos reales.



**Criterio de aceptacion global**: los 88 tests en verde;; sin tocar schemas existentes,, `country_code` operativo,, Parquet particionado con row_count verificado,, tests nuevos de bridge y versionado anadidos.
