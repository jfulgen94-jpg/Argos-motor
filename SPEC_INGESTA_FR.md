---
title: SPEC — Ingesta Francia (AMF / Euronext Paris)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 7 (expansion geo)
  - SPEC_DATA_LAKE_MULTI_PAIS.md
products_served:
  - Data Lake ARGOS (capa Gold)
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
---
# SPEC — Ingesta Francia (AMF / Euronext Paris)

## 1. Objetivo y alcance

Alcanzar **>= 30 emisores Gold** franceses(objetivo ajustado a la cobertura ESEF real documentada), replicando la plantilla ES: descubrimiento y catalogo, descarga con checkpoints, validacion multi-taxonomia,, carga/auditoria Gold. El pais se activa **solo si el anterior cumplio su criterio Gold**.



## 2. Fuente reguladora y canal

| Canal | URL | Perfil |
|---|---|---|---|---|
| A — ESEF ESMA | `https://filings.xbrl.org/api/filings?filter[country]=FR` | API JSON:API; ~SBF 120 / CAC 40 cubiertos por cobertura ESEF |
| B — AMF | `https://bdif.amf-france.org` (BDIF) | `AMFClient` con `COUNTRY_CODE='FR'` y `BASE_URL` ya en codigo |

**Rate limiting real**: `XBRLOrgClient` (mismo que ES): **0.3 s entre paginas**; timeout 25 s / 180 s. Canal nacional: `RobustDownloader` con backoff exponencial(timeout 120 s)y User-Agent institucional..



##  ́3. Catalogo y universo

Construir `config/master_universe_fr.json` (misma estructura que ES:

```json
{
  "ticker": "…",
  "lei": "…",
  "name_legal": "…",
  "segment": "SBF120",
  "sector": "…",
  "is_socimi": false,
  "fiscal_year_end": "12-31",
  "resolution_score": 0.92
}
```

- **Resolucion LEI** GLEIF con `filter[entity.jurisdiction]=FR`; score minimo **0.90**, fallback manuala `master_universe_fr_PENDING_REVIEW.json`.
- **Indices**: SBF 120 / CAC 40.
- **Exclusiones**: SOCIMIs,, fondos,, ETFs,, SPVs,, veiculos. Criterio: catalogo con resolucion >= 0.90 y lista de exclusiones.



##  ́4. Pipeline de descubrimiento y descarga

1. **Descubrimiento**: implementar `list_filings()`/`discover()` en `fr_amf_client.py` (hoy solo `download_filing`); usar `xbrl_org_client.get_country_filings('FR')` como fuente ESEF comun.

2. **Catalogo nacional**: cruzar LEI contra el universo;; inventario `data/raw/FR_AMF/_ESEF_INVENTORY_{ts}.json`.
3. **Manifiesto reanudable**: `data/raw/FR_AMF/_DOWNLOAD_CP.json`; SHA-256 y magic bytes `PK\x03\x04`; idempotente por hash.


4. **Organizacion**: `bundle_manager.py` con contrato documental frances(ver seccion 6).

Criterio: manifiesto con hashes y reanudable al interrumpir.



##  ́5. Validacion y parseo multi-taxonomia

Aplicar `BranchThreshold` por idioma (frances:) ajustar `min_chars`/secciones de los umbrales espanoles con calibracion por corpus real. Aplicar `taxonomy_bridge_fr.yaml` (`fr-gaap` para French GAAP,) al `TaxonomyMapper` y marcar `accounting_standard='LOCAL-GAAP'` con **reconciliacion IFRS cuando disponible**. El cuadre contable (**A = P + PN**, tolerancia cero) es invariante.



Extender `test_taxonomy_bridge.py` sin reducir los  ́88;; tests nuevos por idioma y bridge al contrato ampliable.



##  ́6. Carga, auditoria y liberacion Gold

- **Contrato documental nacional**: los 5 documentos del pais (equivalentes a CCAA audited,, Informe de Gestion,, CSRD/EINF y los equivalentes regulatorios de IAGC/IARC); tipificar gaps.


- **Carga**: `documents_raw`(RAW), `financial_facts_raw`(STAGING,, `financial_panel`(CORE) con `country_code='FR'`.

- **Auditoria forense**:100% SHA-256 == hashes; `FORENSIC_AUDIT_FR_{ts}.json` con `coverage_pct` por emisor.



- **Liberacion Gold**: `coverage >=  ́0.60` + `balance_check=TRUE` + hash verificado → Gold(o `GOLD_PARTIAL`). Vista `issuer_gold_status` con `country_code='FR'`.



**Criterio de aceptacion global**:
- `SELECT COUNT(*) FROM financial_panel WHERE source_market='FR' AND balance_check=TRUE` **>= 30**;
- Manifiesto con hash;; logs de auditoria;; **88 + tests nuevos en verde**.
