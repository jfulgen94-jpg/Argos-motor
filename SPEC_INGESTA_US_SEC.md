---
title: SPEC — Ingesta Estados Unidos (SEC EDGAR)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 7/14 (eje transatlantico SEC)
products_served:
  - Data Lake ARGOS (capa Gold)
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
---
# SPEC — Ingesta Estados Unidos (SEC EDGAR)

##  1. Objetivo y alcance

Reintroducir la descarga **continua e incremental** del eje transatlantico SEC EDGAR, partiendo del **backlog real de 4.853 10-K historicos** ya procesados por `edgar_client.py`. Objetivo: **flujo continuo** — todo 10-K/10-Q/8-K nuevo o modificado se ingesta, sella y parsea en **< 4 h** desde su publicacion. La tasa real de **10 requests/segundo** se respeta estrictamente (politica SEC).



##  ́2. Fuente reguladora y canal

| Canal | URL | Perfil |
|---|---|---|---|---|
| SEC EDGAR Full-Text | `https://data.sec.gov` | API oficial. User-Agent `STATER Financial Technologies dev@stater.es`; **max 10 req/s** (`_rate_limit()`: sleep 0.12 s entre llamadas). |
| SEC submissions | `https://data.sec.gov/submissions/CIK{cik}.json` | Indice por CIK; descubrimiento incremental via `get_company_submissions`. |
| XBRL company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | Hechos US-GAAP; `usgaap_parser.py` consumidor |

**Rate limiting real**: `edgar_client.py` — `_rate_limit()` garantiza 10 req/s max; caché de CIK en memoria(~31 tickers: AAPL, MSFT, AMZN,, GOOGL, META,, NVDA,, TSLA,, JPM,, BAC,, V,, MA,, WMT,, COST,, HD,, DIS,, KO,, PEP,, MCD,, IBM,, CSCO,, AVGO,, LIN,, LLY,, UNH,, JNJ,, MRK,, ABBV,, PG,, XOM,, CVX,, ACN). Header `Accept-Encoding: gzip, deflate`.



##  ́3. Catalogo y universo

- **Backlog**:4.853 10-K historicos(universo previamente procesado; punto de partida del manifiesto incremental).
- **Universo**: actualizable dinamico por `get_company_submissions(cik)`; cada emisor resuelve CIK (10 digitos.).

- **Catalogo**: `config/master_universe_us.json` compatible(ticker → {cik,, lei_opcional,, name_legal,, segment: SP500/NASDAQ100,, sector,, fiscal_year_end}); exclusiones: ETFs,, fondos,, SPVs,, ADR no operativo. Criterio: CIK verificado y caché mantenible..



##  ́4. Pipeline de descubrimiento y descarga

1. **Descubrimiento incremental**: `get_company_submissions(cik)` lista filings(10-K,, 10-Q,, 8-K); diff contra manifiesto local..
2. **Manifiesto reanudable**: `data/raw/SEC_EDGAR/_DOWNLOAD_CP.json`; `status ∈ {DONE,GAP}`, SHA-256; idempotente por accession_number..
3. **Descarga**: `download_filing(cik, accession_number, primary_doc_name, ...)` con rate limit 10 rps y backoff ante 429/403.
4. **Diffusion continua**: polling cada 15 min contra `submissions/`; SLO: filin nuevo → alerta < 15 min; ingesta completa < 4 h..

 Criterio: manifiesto SEC incremental con hashes;; cero 429 no gestionados.



##  ́5. Validacion y parseo

- **Branch Threshold US**: 10-K: umbrales equivalentes a CCAA audited;; 10-Q: trimestral menor;; 8-K: reglas especificas por evento..
- **Parseo**: `usgaap_parser.py` para US-GAAP;; `taxonomy_mapper.py` mapea `us-gaap:Assets`, `us-gaap:Revenues`; panel cuadre con `accounting_standard='US-GAAP'` (**A = P + PN**, tolerancia cero).
- **Restatements**: append-only;; un 10-K/A → fila nueva con `is_restated=TRUE`.



##  ́6. Carga, auditoria y liberacion Gold

- **Carga**: `documents_raw` con `source='SEC_EDGAR'`, `country_code='US'`;; `financial_facts_raw`; `financial_panel` con `accounting_standard='US-GAAP'` y `balance_check=TRUE`.



- **Auditoria forense**: recomputar SHA-256 contra `documents_raw.sha256_hash`;  ́100% antes de liberar al portfolio institucional..

- **Liberacion**: cobertura por emisor segun contrato SEC;; `issuer_gold_status` con `country_code='US'`.

**Criterio de aceptacion global**: pipeline incremental operativo y documentado;; manifiesto con hashes;; **88 + tests nuevos**(EDGAR incremental) en verde;; tasa 10 rps nunca superada(medible por log..
