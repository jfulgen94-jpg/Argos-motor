# GUÍA TÉCNICA MAESTRA: INGESTA, ANATOMÍA DE ARCHIVOS Y MODELOS DE PARSEO CNMV / ESEF
## STATER MOTOR ARGOS — MOD_01_INGESTION & MOD_02_PARSER

---

## 1. RESUMEN EJECUTIVO Y DIAGNÓSTICO FORENSE

### 1.1. Contexto del Problema y Diagnóstico Inicial
Durante las fases iniciales de desarrollo del módulo de ingesta para el mercado español (CNMV), se identificaron problemas recurrentes:
1. **Archivos HTML residuales de 10 a 35 KB**: Descargas que únicamente contenían páginas ASP.NET intermedias de la CNMV, carátulas de resultados, avisos de cookies o skeletons sin los estados financieros consolidados reales.
2. **Ausencia de API REST Pública Directa en `cnmv.es`**: El portal web oficial de la CNMV opera mediante formularios ASP.NET WebForms protegidos con `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` y sesiones de cookies (`CookiesPolicyCNMV_`, `IdiomaCNMV_`). No expone un endpoint REST público de descarga directa de ZIPs por NIF.
3. **Paquetes ESEF Oficiales vs. Informes Aislados**: A partir del ejercicio 2020 (Directiva Europea de Transparencia), las empresas cotizadas en el Mercado Continuo e IBEX 35 ya no presentan documentos PDF aislados como fuente primaria, sino un **Paquete ESEF Oficial en formato ZIP** que contiene el informe anual íntegro en XHTML con etiquetas iXBRL (Inline XBRL) y su correspondiente taxonomía contable.

### 1.2. Descubrimiento de la Fuente Oficial Primaria: ESMA & XBRL.org
A través de la red del repositorio europeo de OAMs coordinado por ESMA (European Securities and Markets Authority) y la base de datos abierta de `filings.xbrl.org`:
* Se dispone de un **endpoint JSON:API REST público**: `https://filings.xbrl.org/api/filings?filter[country]=ES`.
* Indexa **542 paquetes ESEF oficiales de España** distribuidos entre 2020 y 2024:
  * **2020**: 52 filings
  * **2021**: 127 filings
  * **2022**: 124 filings
  * **2023**: 125 filings
  * **2024**: 113 filings
* Cada filing entrega el **paquete ZIP original de 20 a 115 MB**, el cual contiene el informe financiero anual auditado completo, las cuentas anuales consolidadas, el informe de gestión y el Estado de Información No Financiera (EINF/CSRD).

### 1.3. Análisis de las Taxonomías Históricas IPP de la CNMV
Se examinaron los archivos históricos de taxonomía en el repositorio (`ipp_2005-06-30_v1.22.zip`, `ipp_2008-01-01.zip`, `ipp_2016-06-01.zip`):
* Demuestran que la CNMV define la entidad emisora bajo el esquema `http://www.cnmv.es/xbrl/ipp/Q-NIFCIF`.
* El identificador legal en España es el **NIF / CIF** (ej. `A-39000013` para Banco Santander, `A-95066230` para Iberdrola), mapeado internacionalmente mediante el código **LEI** (Legal Entity Identifier, 20 caracteres alfanuméricos según ISO 17442).

---

## 2. ARQUITECTURA DE INGESTA Y RUTAS DE ALMACENAMIENTO

### 2.1. Arquitectura en Dos Etapas (Two-Stage Pipeline)

```mermaid
flowchart TD
    A[GLEIF API / LEI Lookup] -->|LEI Resuelto| B[XBRL.org API / CNMV Scraper]
    B -->|Streaming Download + Hash| C[Stage 1: Raw Landing]
    C -->|data/raw/landing_raw/| D[Stage 2: Canonical Organization & Unpacking]
    D -->|Extracción Segura| E[data/raw/ES_CNMV/{YEAR}/{TICKER}_{NAME}/]
    E --> F[bundles/: ZIPs Originales + SHA-256]
    E --> G[extracted/: XHTML iXBRL + Taxonomías XML/XSD]
    E --> H[manifest.json: Trazabilidad Criptográfica]
    G --> I[MOD_02 Parser: Extracción y Validación Contable]
```

### 2.2. Mapa Canónico de Rutas en el Disco

```
ARGOS_MOTOR/
├── data/
│   └── raw/
│       ├── landing_raw/                                  ← STAGE 1: Zona de descarga temporal en bruto
│       │   ├── 2024/
│       │   │   ├── SAN/san_2024_esef_bundle.zip          ← Archivo ZIP original descargado
│       │   │   ├── SAN/san_2024_esef_bundle.meta.json    ← Metadatos de descarga con SHA-256
│       │   │   ├── IBE/ibe_2024_esef_bundle.zip
│       │   │   └── ...
│       │   └── batch_summary_YYYYMMDD_HHMMSS.json        ← Resumen de ejecución del lote
│       │
│       └── ES_CNMV/                                      ← STAGE 2: Estructura canónica oficial
│           ├── ORGANIZED_INVENTORY_SHA256.json           ← Inventario global consolidado
│           │
│           ├── 2024/
│           │   ├── SAN_Banco_Santander_SA/
│           │   │   ├── bundles/
│           │   │   │   └── san_2024_esef_bundle.zip      ← ZIP sellado
│           │   │   ├── extracted/
│           │   │   │   ├── reports/
│           │   │   │   │   └── 5493006QMFDDMYWIAM13-20241231-en.xhtml  ← 111.8 MB (Informe oficial)
│           │   │   │   ├── www.santander.com/20241231/
│           │   │   │   │   ├── *.xsd                     ← Esquemas de conceptos contables
│           │   │   │   │   ├── *_pre.xml                 ← Presentation Linkbase (árboles de balance)
│           │   │   │   │   ├── *_def.xml                 ← Definition Linkbase (dimensiones y ejes)
│           │   │   │   │   ├── *_lab-en.xml              ← Labels (etiquetas legibles)
│           │   │   │   │   └── *_cal.xml                 ← Calculation Linkbase (reglas de sumas)
│           │   │   │   └── META-INF/
│           │   │   │       ├── catalog.xml
│           │   │   │       ├── taxonomyPackage.xml
│           │   │   │       └── reportPackage.json
│           │   │   └── san_2024_extracted_manifest.json  ← Manifiesto criptográfico de la empresa
│           │   │
│           │   ├── IBE_Iberdrola_SA/
│           │   │   ├── bundles/ibe_2024_esef_bundle.zip
│           │   │   ├── extracted/reports/5QK37QC7NWOJ8D7WVQ45-20241231-es.xhtml (68.4 MB)
│           │   │   └── ibe_2024_extracted_manifest.json
│           │   │
│           │   ├── MEL_Melia_Hotels_International_SA/
│           │   ├── GRF_Grifols_SA/
│           │   └── BKT_Bankinter_SA/
│           │
│           ├── 2023/ (Estructura idéntica por empresa)
│           └── 2022/ (Estructura idéntica por empresa)
```

---

## 3. ANATOMÍA DETALLADA DEL PAQUETE ESEF OFICIAL

### 3. Doble Canal de Ingesta (Anual Auditado vs Intermedio TTM)

| Dimensión | Canal 1: Cuentas Anuales ESEF (2020–2024) | Canal 2: Información Intermedia CNMV IPP (2025+) |
| :--- | :--- | :--- |
| **Frecuencia** | Anual (1 vez/año tras cierre a 31/12) | Semestral (H1) / Trimestral (Q1, Q3) |
| **Estado Auditoría** | Auditado formalmente por Big Four (Informe de Auditoría) | Revisión limitada o no auditado |
| **Formato** | iXBRL / XHTML empaquetado ZIP con taxonomías | XBRL (Taxonomía IPP CNMV) / WebForms / PDF |
| **Directorio** | `data/raw/ES_CNMV/{AÑO}/{TICKER}_{EMPRESA}/` | `data/raw/ES_CNMV_INTERIM/{AÑO}/{PERIODO}/{TICKER}/` |
| **Uso en STATER** | **Fuente de Verdad Contable Inmutable** (Análisis profundo) | **Monitor de Fundamentales Vivos (TTM en Tiempo Real)** |
| **Necesidad Histórica** | Esencial para la serie histórica (2020-2024) | Innecesario pre-2025 (el informe anual lo consolida todo) |

Un paquete regulatorio ESEF (European Single Electronic Format) es un archivo ZIP normalizado según la especificación ESMA ESEF Reporting Manual. Contiene tres componentes esenciales:

```
{LEI}-{PERIODO}-{IDIOMA}.zip (ej. 5QK37QC7NWOJ8D7WVQ45-20241231-es.zip: 26.86 MB)
│
├── reports/
│   └── {LEI}-{PERIODO}-{IDIOMA}.xhtml
│       └─ Documento principal iXBRL (de 50 a 115 MB descomprimido).
│          Integra en formato HTML5 visualizable y legible por humanos
│          todas las etiquetas contables estructuradas para máquinas.
│          Contiene:
│          1. Informe de Auditoría Independiente (ISA 701)
│          2. Cuentas Anuales Consolidadas (Balance, PyG, EFE, ECPN)
│          3. Memoria Consolidada y Notas Explicativas (1 a 40+)
│          4. Informe de Gestión Consolidado
│          5. Estado de Información No Financiera (EINF / CSRD)
│
├── www.{dominio_empresa}.com/{fecha}/
│   ├── *.xsd              ← XML Schema: Define los conceptos financieros propios de la entidad
│   ├── *_pre.xml          ← Presentation Linkbase: Orden y jerarquía visual de los estados
│   ├── *_def.xml          ← Definition Linkbase: Relaciones dimensionales y desgloses
│   ├── *_lab-{lang}.xml   ← Label Linkbase: Nombres de cuentas en español e inglés
│   └── *_cal.xml          ← Calculation Linkbase: Fórmulas aritméticas de sumas y totales
│
└── META-INF/
    ├── catalog.xml        ← Mapeo de URIs del paquete ESEF a archivos locales
    ├── taxonomyPackage.xml← Metadatos de la taxonomía del emisor
    └── reportPackage.json ← Especificación de paquete de reporte XBRL v1.0
```

### Documentos Satélite Adicionales (No ESEF)
* **IAGC (Informe Anual de Gobierno Corporativo)**: Publicado por separado en el registro oficial CNMV.
* **IARC (Informe Anual sobre Remuneraciones de los Consejeros)**: Publicado por separado en el registro oficial CNMV.
* *Nota de diseño*: Estos documentos se capturan mediante el módulo complementario de scraping de CNMV (`CNMVScraper`) y se incorporan al manifiesto anual de 5 documentos.

---

## 4. MODELOS DE PARSEO Y EXTRACCIÓN (MOD_02_PARSER)

El parser toma como entrada el archivo `.xhtml` extraído junto con los linkbases `.xml` y `.xsd`.

### 4.1. Extracción de Hechos Contables (iXBRL Facts)
En el código XHTML, cada cifra contable oficial está encapsulada en tags XML bajo el namespace `xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"`:

```html
<!-- Ejemplo real de hecho contable en el balance iXBRL -->
<ix:nonFraction 
    name="ifrs-full:Assets" 
    contextRef="ctx_2024_12_31" 
    unitRef="EUR" 
    decimals="-6" 
    scale="6" 
    format="ixt:numdotdecimal">
    1823450000000
</ix:nonFraction>
```

#### Parámetros Clave para el Parser:
1. `name`: Concepto IFRS normalizado (ej. `ifrs-full:Assets`, `ifrs-full:EquityAndLiabilities`, `ifrs-full:Revenue`, `ifrs-full:ProfitLoss`).
2. `contextRef`: Contexto temporal (`instant` para balances a fecha de cierre; `duration` para flujos y resultados de periodo) y dimensional (consolidado vs. individual).
3. `unitRef`: Moneda (ISO 4217, típicamente `EUR`, `USD`, `GBP`).
4. `decimals` / `scale`: Factor de escala para normalización a valor monetario exacto (`scale="6"` indica cifras en millones de euros).

### 4.2. Extracción de Estados Financieros Principales
El parser extrae y estandariza cuatro estados contables:

| Estado Financiero | Tag IFRS Raíz | Validación de Cuadre Obligatoria |
| :--- | :--- | :--- |
| **Balance de Situación** | `ifrs-full:StatementOfFinancialPosition` | $\text{Activo Total} = \text{Pasivo Total} + \text{Patrimonio Neto}$ |
| **Cuenta de Pérdidas y Ganancias (PyG)** | `ifrs-full:IncomeStatement` | $\text{Ingresos} - \text{Gastos} = \text{Resultado Neto}$ |
| **Estado de Flujos de Efectivo (EFE)** | `ifrs-full:StatementOfCashFlows` | $\Delta\text{Efectivo} = \text{Flujo Explotación} + \text{Inversión} + \text{Financiación}$ |
| **Estado de Cambios en el Patrimonio Neto (ECPN)** | `ifrs-full:StatementOfChangesInEquity` | $\text{PN Inicial} + \text{Resultado} + \text{Otros} = \text{PN Final}$ |

### 4.3. Regla de Tolerancia Cero: Cuadre A = P + PN
Antes de persistir los datos en el Data Lake, el parser ejecuta la comprobación de integridad contable:

$$\Delta = |\text{Activo Total} - (\text{Pasivo Total} + \text{Patrimonio Neto})|$$

* Si $\Delta = 0$ (o $|\Delta| < 1.0$ por redondeo de escala): **ESTADO VÁLIDO (SEALED)**.
* Si $\Delta \neq 0$: **ALERTA DE DESCUADRE (QUARANTINED)**. El registro se marca con flag de discrepancia para inspección forense.

### 4.4. Esquema de Persistencia en Data Lake DuckDB (MOD_04)

```sql
-- 1. Registro de documentos brutos ingestados
CREATE TABLE raw_documents (
    document_id VARCHAR PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    lei VARCHAR NOT NULL,
    year INTEGER NOT NULL,
    document_type VARCHAR NOT NULL, -- 'ESEF_XHTML', 'ZIP_BUNDLE', 'IAGC', 'IARC'
    file_path VARCHAR NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    sha256_hash VARCHAR(64) NOT NULL,
    ingested_at TIMESTAMP NOT NULL
);

-- 2. Hechos financieros atómicos extraídos
CREATE TABLE financial_facts (
    fact_id VARCHAR PRIMARY KEY,
    document_id VARCHAR REFERENCES raw_documents(document_id),
    ticker VARCHAR NOT NULL,
    year INTEGER NOT NULL,
    period_end DATE NOT NULL,
    concept_qname VARCHAR NOT NULL,     -- ej. 'ifrs-full:Assets'
    concept_label VARCHAR NOT NULL,     -- ej. 'Total Activo'
    statement_type VARCHAR NOT NULL,    -- 'BALANCE', 'INCOME', 'CASH_FLOW'
    numeric_value DOUBLE NOT NULL,
    currency VARCHAR(3) NOT NULL,       -- 'EUR'
    decimals INTEGER,
    is_reconciled BOOLEAN NOT NULL
);

-- 3. Balances normalizados con cuadre contable
CREATE TABLE balance_sheets (
    ticker VARCHAR NOT NULL,
    year INTEGER NOT NULL,
    period_end DATE NOT NULL,
    total_assets DOUBLE NOT NULL,
    total_liabilities DOUBLE NOT NULL,
    total_equity DOUBLE NOT NULL,
    liabilities_and_equity DOUBLE NOT NULL,
    accounting_diff DOUBLE NOT NULL,     -- total_assets - liabilities_and_equity
    is_balanced BOOLEAN NOT NULL,        -- true si diff == 0
    sha256_source VARCHAR(64) NOT NULL,
    PRIMARY KEY (ticker, year)
);
```

---

## 5. CATÁLOGO DE SCRIPTS Y MANUAL OPERATIVO

### 5.1. Scripts Disponibles en el Repositorio

| Script | Ubicación | Función Principal |
| :--- | :--- | :--- |
| **`mod_01_esef_batch_downloader.py`** | `ARGOS_MOTOR/` | Motor de descarga batch con límite de tiempo, filtrado por país, ticker y año vía API XBRL.org y GLEIF. |
| **`organize_and_hash_all_zips.py`** | `ARGOS_MOTOR/` | Localizador, descompresor y organizador canónico de todos los ZIPs con cálculo de SHA-256 y generación de manifiestos. |
| **`mod_01_zip_content_validator.py`** | `ARGOS_MOTOR/` | Validador de contenido real iXBRL en XHTML (balance, PyG, cifras, detección de lorem ipsum/placeholders). |
| **`cnmv_real_downloader.py`** | `ARGOS_MOTOR/mod_01_ingestion/src/` | Módulo de ingesta integrado con soporte dual (API ESEF + Scraper CNMV para 2019 e IAGC/IARC). |

### 5.2. Comandos de Ejecución Práctica

#### A. Descarga Rápida de Comprobación (IBEX 35, 2024):
```bash
python mod_01_esef_batch_downloader.py --tickers SAN IBE MEL GRF BKT --years 2024
```

#### B. Descarga de una Muestra Multianual para un Lote Amplio (2020–2024, 30 minutos máx.):
```bash
python mod_01_esef_batch_downloader.py --tickers SAN BBVA IBE ITX TEF REP CABK AMS CLNX FER GRF MEL ACS IAG MAP NTGY ENG ELE RED BKT UNI SOL --years 2020 2021 2022 2023 2024 --minutes 30
```

#### C. Descarga de TODOS los Paquetes Españoles Disponibles en la Base de Datos (542 filings):
```bash
python mod_01_esef_batch_downloader.py --all-es --years 2024 2023 2022 2021 2020
```

#### D. Descompresión, Organización y Sellado SHA-256 de todos los ZIPs:
```bash
python organize_and_hash_all_zips.py
```

#### E. Validación de Integridad Contable de un Informe Descargado:
```bash
python mod_01_zip_content_validator.py "data/raw/ES_CNMV/2024/IBE_Iberdrola_SA/bundles/ibe_2024_esef_bundle.zip"
```

---

## 6. RESULTADOS VERIFICADOS Y REGISTRO DE SELLOS SHA-256

A continuación se resumen los 14 paquetes regulatorios oficiales ESEF completos descargados, descomprimidos y validados:

| Ticker | Empresa | Ejercicio | Tamaño ZIP | Tamaño XHTML | SHA-256 del Bundle ZIP |
| :---: | :--- | :---: | :---: | :---: | :--- |
| `SAN` | Banco Santander, S.A. | **2024** | 30.74 MB | **111.8 MB** | `47923b30c3763fe448ff8080bb3e38c50ae48d48171986a90947c8be347ccb37` |
| `SAN` | Banco Santander, S.A. | **2023** | 39.34 MB | **99.4 MB** | `1128675e0e6e979ef49db4051fe771515dd8ec42236372549f8dbd7a6210dd1c` |
| `SAN` | Banco Santander, S.A. | **2022** | 42.75 MB | **96.1 MB** | `e4b1aa3e3f673c0675829d19400d940b1c43fe19327406e44cb2dc03d61a653d` |
| `IBE` | Iberdrola, S.A. | **2024** | 26.86 MB | **68.4 MB** | `89dfd3ef65527d1d4378464c2f70fa78b2fb7b4872264eacfa91d3faae1c42b4` |
| `IBE` | Iberdrola, S.A. | **2023** | 37.72 MB | **80.9 MB** | `b91cb80f1d29689e7a0c72efc43a8c6b9d7f93b3b2e569e5717b69b55fa290ce` |
| `IBE` | Iberdrola, S.A. | **2022** | 37.91 MB | **80.0 MB** | `d4238ea7d809b19bc2213e696dd80fa1359bce66c23e84b6e89443bf4377cefd` |
| `MEL` | Meliá Hotels Int., S.A. | **2024** | 54.45 MB | **91.2 MB** | `62ecb5184b0dbd7745f4f893d318dc0304dde5e5776fcdfc5341305250a5b74f` |
| `MEL` | Meliá Hotels Int., S.A. | **2023** | 19.92 MB | **40.8 MB** | `736347dd12ca52acbb6edd8a9f04716aa2eab747c2552a603fbeea1ba66d04b9` |
| `MEL` | Meliá Hotels Int., S.A. | **2022** | 45.71 MB | **80.2 MB** | `bc26aae5425f24d7a2c1e57504b93b24d62b5111cd90bc38faaa9deaba62d7d8` |
| `GRF` | Grifols, S.A. | **2024** | 27.15 MB | **50.4 MB** | `6544f9d1f3b4f7adf45998b6f5da97ace22706fb3bf8fc7d7274d7a94a04c188` |
| `GRF` | Grifols, S.A. | **2023** | 36.61 MB | **61.1 MB** | `444ea4c2c9822c71c78a2d4479453b697e077e1dbaea2605b058b49fb21489ff` |
| `GRF` | Grifols, S.A. | **2022** | 59.79 MB | **106.8 MB** | `212c87d7e4257fe710d204235d3c7119378ae86d3adebe02cb6ac384a2cd6691` |
| `BKT` | Bankinter, S.A. | **2024** | 11.14 MB | **50.9 MB** | `dfa16507a85ec3146fcab9977214715b025f6b5dd810d9645dd39820320f32cb` |
| `BKT` | Bankinter, S.A. | **2023** | 5.33 MB | **32.1 MB** | `ec4f4d138176806b39fc31f1d91f2675444c990bbd949c21dcba489a20ba04ae` |

> [!NOTE]
> Todos los manifiestos, archivos extraídos y el inventario global consolidado se encuentran en [ORGANIZED_INVENTORY_SHA256.json](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/data/raw/ES_CNMV/ORGANIZED_INVENTORY_SHA256.json).
