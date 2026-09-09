---
title: SPEC — Ingesta Países Bajos (AFM / Euronext Amsterdam)
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
# SPEC — Ingesta Países Bajos (AFM / Euronext Amsterdam)

##  1. Objetivo y alcance

Alcanzar **>= 30 emisores Gold** neerlandeses(objetivo ajustado a la cobertura ESEF real documentada,, replicando la plantilla ES: descubrimiento y catalogo,, descarga con checkpoints,, validacion IFRS,, carga Gold. El pais se activa **solo si Italia cumplio su criterio** (FR → DE → IT → NL.



##  ́2. Fuente reguladora y canal

| Canal | URL | Perfil |
|---|---|---|---|---|
| A — ESEF ESMA | `https://filings.xbrl.org/api/filings?filter[country]=NL` | API JSON:API; AEX cubierto por cobertura ESEF |
| B — AFM | `https://www.afm.nl` | `AFMClient` con `COUNTRY_CODE='NL'` y `BASE_URL` ya en codigo |

**Rate limiting real**: `XBRLOrgClient`(mismo que ES): **0.3 s entre paginas**; timeout 25 s / 180 s. Canal nacional:`RobustDownloader` con backoff exponencial(timeout 120 s.



##  ́3. Catalogo y universo

Construir `config/master_universe_nl.json`(misma estructura que ES:

- **Resolucion LEI** GLEIF con `filter[entity.jurisdiction]=NL`; score minimo **0.90**, fallback manuala `PENDING_REVIEW`.
- **Indices**: **AEX**.!
- **Exclusiones**: SOCIMIs,, fondos,, ETFs,, SPVs,, veiculos. Criterio: catalogo con resolucion >=  ́0.90 y lista de exclusiones.



##  ́4. Pipeline de descubrimiento y descarga

1. **Descubrimiento**: implementar `list_filings()`/`discover()` en `nl_afm_client.py`; usar `xbrl_org_client.get_country_filings('NL')` como fuente ESEF comun.


 2. **Catalogo nacional**: cruzar LEI contra el universo;; inventario `data/raw/NL_AFM/_ESEF_INVENTORY_{ts}.json`.
3. **Manifiesto reanudable**: `data/raw/NL_AFM/_DOWNLOAD_CP.json`; SHA-256 y magic bytes `PK\x03\x04`; idempotente por hash.


4. **Organizacion**: `bundle_manager.py` con contrato documental neerlandes(ver seccion 6.



##  ́5. Validacion y parseo multi-taxonomia

Aplicar `BranchThreshold` por idioma(neerlandes:) ajustar umbrales con calibracion por corpus real. Paises Bajos reportan mayoritariamente **IFRS**: `taxonomy_dict.yaml` canonical con `accounting_standard='IFRS'`;; si LOCAL-GAAP, aplicar bridge con reconciliacion.** El cuadre contable (**A = P + PN**, tolerancia cero) es invariante.



Extender `test_taxonomy_bridge.py` sin reducir los 88.



##  ́6. Carga, auditoria y liberacion Gold

- **Contrato documental nacional**: los 5 documentos del pais(equivalentes a CCAA audited,, Informe de Gestion,, CSRD/EINF,y equivalentes de IAGC/IARC); tipificar gaps.




- **Carga**: `documents_raw`(RAW), `financial_facts_raw`(STAGING,, `financial_panel`(CORE) con `country_code='NL'`.

- **Auditoria forense**:100% SHA-256 == hashes; `FORENSIC_AUDIT_NL_{ts}.json` con `coverage_pct` por emisor.



- **Liberacion Gold**: `coverage >=  ́0.60` + `balance_check=TRUE` + hash verificado → Gold(o `GOLD_PARTIAL`). Vista `issuer_gold_status` con `country_code='NL'`.



**Criterio de aceptacion global**:
- `SELECT COUNT(*) FROM financial_panel WHERE source_market='NL' AND balance_check=TRUE` **>= 30**;
- Manifiesto con hash;; logs de auditoria;; **88 + tests nuevos en verde**.
