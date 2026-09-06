# MOD_01 — Motor de Ingesta Transatlántica Regulada
## STATER MOTOR ARGOS

## Propósito
Descarga, procesa y archiva filings corporativos oficiales de la **SEC EDGAR (EE.UU.)** y los **5 Mecanismos Oficialmente Designados (OAMs) de Europa** (CNMV, AMF, BaFin, CONSOB, AFM). Sella cada fichero con SHA-256 inmutable y sincroniza con el Data Lake en DuckDB.

---

## 🇪🇸 Ingesta de España (CNMV / ESEF) — Resumen Operativo

> [!IMPORTANT]
> Para una explicación exhaustiva sobre la anatomía de los paquetes ESEF, endpoints oficiales, modelos de parseo y validación de balances, consulta la [Guía Técnica Maestra de Ingesta y Parseo CNMV/ESEF](../CNMV_INGESTION_ARCHITECTURE_AND_PARSING_GUIDE.md).

### 1. Fuente Oficial y Método de Descarga
* **Repositorio Primario ESEF**: API REST de ESMA / XBRL International (`https://filings.xbrl.org/api/filings?filter[country]=ES`) con **542 paquetes anuales oficiales** de España (2020–2024).
* **Resolución de LEIs**: API GLEIF (`https://api.gleif.org/api/v1/lei-records`).
* **Scraper Complementario CNMV**: Para filings históricos pre-ESEF (2019) y documentos satélite individuales (IAGC e IARC).

### 2. Scripts Principales de Ingesta

| Script | Ubicación | Descripción |
|---|---|---|
| `mod_01_esef_batch_downloader.py` | `ARGOS_MOTOR/` | Motor de descarga batch con soporte para límites de tiempo, filtros por empresa y descarga masiva de los 542 filings españoles. |
| `organize_and_hash_all_zips.py` | `ARGOS_MOTOR/` | Localizador, descompresor automático y organizador en rutas canónicas con cálculo de hash SHA-256 para cada archivo extraído. |
| `mod_01_zip_content_validator.py` | `ARGOS_MOTOR/` | Validador forense de contenido iXBRL (balance, PyG, cifras, detección de placeholders). |
| `cnmv_real_downloader.py` | `mod_01_ingestion/src/` | Módulo integrado en el pipeline con soporte para orquestación directa. |

### 3. Comandos de Uso Rápido

```bash
# 1. Descarga por lotes con límite de tiempo (ej. 30 minutos)
python mod_01_esef_batch_downloader.py --tickers SAN BBVA IBE ITX TEF REP CABK AMS CLNX FER GRF MEL --years 2020 2021 2022 2023 2024 --minutes 30

# 2. Descargar todos los filings disponibles de España (542 paquetes)
python mod_01_esef_batch_downloader.py --all-es --years 2024 2023 2022 2021 2020

# 3. Descomprimir, organizar y sellar con SHA-256
python organize_and_hash_all_zips.py

# 4. Validar un paquete ESEF descargado
python mod_01_zip_content_validator.py "data/raw/ES_CNMV/2024/IBE_Iberdrola_SA/bundles/ibe_2024_esef_bundle.zip"
```

---

## Estructura Modular del Módulo 01

```
mod_01_ingestion/src/
├── oam_router.py              ← Router transatlántico unificado
├── edgar_client.py            ← 🇺🇸 EE.UU.: SEC EDGAR (10-K, 10-Q, 8-K)
├── cnmv_real_downloader.py    ← 🇪🇸 España: CNMV / ESEF Downloader & Scraper
├── fr_amf_client.py           ← 🇫🇷 Francia: AMF / Data.gouv (URD, ESEF)
├── de_bafin_client.py         ← 🇩🇪 Alemania: BaFin / Unternehmensregister (ESEF)
├── it_consob_client.py        ← 🇮🇹 Italia: CONSOB / 1INFO (ESEF, DNF)
├── nl_afm_client.py           ← 🇳🇱 Países Bajos: AFM (ESEF Annual Reports)
├── sha256_sealer.py           ← Sellado criptográfico inmutable SHA-256
└── storage_uploader.py        ← Sincronización a Data Lake / Blob Storage
```

---

## Trazabilidad y Rutas de Almacenamiento

1. **Zona de Aterrizaje en Bruto (Stage 1)**: `data/raw/landing_raw/{AÑO}/{TICKER}/`
2. **Estructura Canónica Organizada (Stage 2)**:
   * **Bundles ZIP originales**: `data/raw/ES_CNMV/{AÑO}/{TICKER}_{EMPRESA}/bundles/`
   * **Archivos XHTML y Taxonomías extraídas**: `data/raw/ES_CNMV/{AÑO}/{TICKER}_{EMPRESA}/extracted/`
   * **Manifiestos criptográficos**: `data/raw/ES_CNMV/{AÑO}/{TICKER}_{EMPRESA}/{ticker}_{year}_extracted_manifest.json`
3. **Inventario Global Consolidado**: `data/raw/ES_CNMV/ORGANIZED_INVENTORY_SHA256.json`
