# Inventario Disco Local — ARGOS Documental (08/10/2026)

## 1. Resumen Ejecutivo Global Multipaís

- **Fecha de auditoría e inventario**: 08/10/2026
- **Ámbito geográfico analizado y en curso**:
  - **Completados y auditados (v)**:
    1. **España (`ES`)** — 199 empresas, 2.493 documentos, 49,94 GB
    2. **Alemania (`DE`)** — 796 empresas, 7.927 documentos, 8,59 GB
    3. **Francia (`FR`)** — 529 empresas, 3.935 documentos, 36,57 GB
    4. **Estados Unidos (`US`)** — 38 empresas en Data Lake (266 docs, 1,41 GB) + 32.280 archivos en Repositorio Econométrico (57,68 GB) + 3 ZIPs masivos SEC (3,32 GB)
  - **En proceso / Incorporados**:
    5. **Países Bajos (`NL`)** — 10 empresas líderes AEX25, 72 documentos/fichas auditadas (153,61 MB)
    6. **Italia (`IT`)** — 12 empresas líderes FTSE MIB, 84 registros sellados CONSOB (2019–2025)
  - **Identificado en repositorio local pendiente de volcado**:
    7. **Reino Unido (`UK`)** — Localizado en `estudios v\CCA_Reino_Unido` con 7.567 archivos (16,66 GB) de 2020 a 2026.

- **Métricas Consolidadas del Data Lake Curado**:
  - **Total de documentos en Data Lake**: **14.626 archivos**
  - **Total de empresas únicas en Data Lake**: **1.564 empresas**
  - **Volumen total en disco del Data Lake**: **96,66 GB**
- **Métricas del Ecosistema Documental Global (Lake + Repositorios en Escritorio)**:
  - Repositorio Econométrico EE.UU. (`Argos_BD\EEUU`): 32.280 archivos (57,68 GB)
  - Repositorio Reino Unido (`estudios v\CCA_Reino_Unido`): 7.567 archivos (16,66 GB)
  - Paquetes Masivos SEC `.ZIP`: 3 archivos (3,32 GB)
  - **Gran Total Repositorio Documental Local Gestionado**: **54.560+ archivos**, **174,32 GB**

---

## 2. Tabla Comparativa Consolidada por País

| País | Estado | Empresas Únicas | Mercados / Segmentos Principales | Rango Años | Total Docs | Formatos Dominantes | Tipos Documentales Principales | Calidad Global y Observaciones |
|:---:|:---:|---:|:---|:---:|---:|:---|:---|:---|
| **ES** | **Auditado (v)** | 199 | IBEX35, BME Continuo, BME Growth, BME Growth SOCIMI, Histórico | 2012–2025 | 2.493 | PDF (68,0 %), ZIP ESEF (30,8 %), Otros (1,2 %) | Informe Anual Auditado (55,0 %), Paquete ESEF (31,2 %), Otro Financiero (13,7 %) | **Media-Alta**: Gran fidelidad contable y visual; duplicidad entre depósitos CNMV e informes anuales; escaneos sin OCR en 2012. |
| **DE** | **Auditado (v)** | 796 | Prime Standard, General Standard, Scale, Freiverkehr, Histórico | 2012–2025 | 7.927 | HTML (85,8 %), ZIP ESEF (7,6 %), PDF (6,5 %) | Balance Cuentas Oficiales / BAnz (81,8 %), Paquete ESEF (7,6 %), Informe Anual (5,0 %) | **Alta**: Gran estandarización legal (Bundesanzeiger / BaFin), texto 100% vectorial nativo en HTML sin dependencia de OCR. |
| **FR** | **Auditado (v)** | 529 | CAC40, CAC Next20, SBF120, Euronext Growth, Histórico | 2012–2026 | 3.935 | PDF (70,8 %), ZIP ESEF (29,1 %), HTM (0,1 %) | Informe Anual Auditado / Document de Référence (70,9 %), Paquete Digital ESEF (29,1 %) | **Muy Alta**: Transición regulatoria perfecta; 2012–2019 en Documentos de Registro Universal (PDF) y 2020–2026 en paquetes ESEF (AMF). |
| **US** | **Auditado (v)** | 38 (Lake) / 1.351 (BD) | S&P 500 Mega Caps, ADRs, Paneles SFI y Control SEC | 2005–2025 | 266 (Lake) + 32.280 (BD) | HTML interactivo (45 %), TXT plano (44 %), ZIP Bulk (3 GB) | Form 10-K Anual Auditado, Form 20-F, Form 6-K, Datapoints CSRD/CAM | **Máxima**: Informes oficiales SEC EDGAR en HTML interactivo con Inline XBRL; dictámenes PCAOB con 8.579 Critical Audit Matters en DuckDB. |
| **NL** | **En proceso (v)** | 10 | AEX 25 (Ámsterdam) | 2019–2025 | 5 (Lake) + 77 (Raw/AFM) | ZIP ESEF (90 %), HTML (10 %) | Paquete Digital ESEF (AFM), Cuentas Anuales Auditadas | **Muy Alta**: Cobertura de las 10 mayores firmas de Países Bajos (ASML, ING, Ahold, Heineken, Philips, etc.) reguladas por AFM. |
| **IT** | **En proceso (v)** | 12 | FTSE MIB (Milán) | 2019–2025 | 84 (Raw/CONSOB) | ZIP ESEF Raw Sealed (100 %) | Metadatos y Paquetes Digitales ESEF (CONSOB) | **Alta**: 12 blue chips italianas selladas año a año con código LEI y hash SHA-256 (Enel, Eni, Intesa Sanpaolo, Ferrari, UniCredit, etc.). |
| **UK** | *Identificado* | *~250+* | FTSE 100, FTSE 250, SmallCap | 2020–2026 | 7.567 (Escritorio) | HTML (78,6 %), PDF (10,9 %), ZIP (6,3 %), XHTML (3,9 %) | Paquetes ESEF / FCA británicos, Informes Anuales | **Pendiente de volcado al Lake**: 16,66 GB en `estudios v\CCA_Reino_Unido`. |
| **TOTAL** | **Consolidado** | **1.564+ Lake** | **Mercados UE (ES, DE, FR, NL, IT) + Wall Street (US)** | **2005–2026** | **54.560+ docs** | **HTML, PDF, ZIP ESEF, TXT SEC EDGAR** | **Repositorio integral multipaís** | **174,32 GB gestionados en el ecosistema Stater** |

---

## 3. Detalle por País: España (`ES`)

### 3.1. Matriz Evolutiva Año a Año por Mercado (España)

| Año | IBEX 35 | Mercado Continuo | BME Growth | BME Growth SOCIMI | Histórico / Expandido | Total Empresas Únicas | Total Archivos | Volumen (MB) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2012** | 23 emp (37 docs) | 13 emp (21 docs) | 0 emp (0 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **36** | **58** | 546,8 MB |
| **2013** | 24 emp (39 docs) | 13 emp (23 docs) | 0 emp (0 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **37** | **62** | 506,3 MB |
| **2014** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 526,3 MB |
| **2015** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 509,2 MB |
| **2016** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 461,8 MB |
| **2017** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 571,4 MB |
| **2018** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 843,6 MB |
| **2019** | 24 emp (39 docs) | 13 emp (21 docs) | 1 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **38** | **62** | 809,7 MB |
| **2020** | 34 emp (84 docs) | 77 emp (114 docs) | 52 emp (59 docs) | 2 emp (2 docs) | 7 emp (7 docs) | **172** | **266** | 7.123,4 MB |
| **2021** | 34 emp (103 docs) | 77 emp (178 docs) | 52 emp (58 docs) | 6 emp (6 docs) | 23 emp (23 docs) | **192** | **368** | 9.047,1 MB |
| **2022** | 34 emp (105 docs) | 77 emp (178 docs) | 52 emp (60 docs) | 6 emp (6 docs) | 22 emp (22 docs) | **191** | **371** | 8.313,4 MB |
| **2023** | 34 emp (107 docs) | 77 emp (179 docs) | 52 emp (60 docs) | 6 emp (6 docs) | 18 emp (18 docs) | **187** | **370** | 8.383,9 MB |
| **2024** | 34 emp (113 docs) | 77 emp (163 docs) | 52 emp (59 docs) | 5 emp (5 docs) | 18 emp (18 docs) | **186** | **358** | 7.900,4 MB |
| **2025** | 34 emp (79 docs) | 77 emp (130 docs) | 52 emp (59 docs) | 0 emp (0 docs) | 0 emp (0 docs) | **163** | **268** | 5.590,3 MB |
| **TOTAL ES** | **34 emp (901 docs)** | **77 emp (1.112 docs)** | **52 emp (367 docs)** | **6 emp (25 docs)** | **30 emp (88 docs)** | **199 emp** | **2.493 docs** | **49,94 GB** |

---

## 4. Detalle por País: Alemania (`DE`)

### 4.1. Matriz Evolutiva Año a Año por Mercado (Alemania)

| Año | Prime Standard | General Standard | Scale / Growth | Freiverkehr (Open Market) | Histórico / Expandido | Total Empresas Únicas | Total Archivos | Volumen (MB) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2012** | 76 emp (102 docs) | 217 emp (221 docs) | 33 emp (34 docs) | 164 emp (172 docs) | 0 emp (0 docs) | **473** | **529** | 289,0 MB |
| **2013** | 83 emp (118 docs) | 222 emp (227 docs) | 32 emp (33 docs) | 176 emp (185 docs) | 0 emp (0 docs) | **493** | **563** | 365,1 MB |
| **2014** | 90 emp (129 docs) | 235 emp (243 docs) | 34 emp (35 docs) | 197 emp (206 docs) | 0 emp (0 docs) | **532** | **613** | 368,3 MB |
| **2015** | 91 emp (132 docs) | 250 emp (262 docs) | 36 emp (36 docs) | 204 emp (214 docs) | 0 emp (0 docs) | **554** | **644** | 428,7 MB |
| **2016** | 98 emp (152 docs) | 261 emp (274 docs) | 38 emp (38 docs) | 218 emp (229 docs) | 0 emp (0 docs) | **584** | **693** | 461,2 MB |
| **2017** | 102 emp (158 docs) | 273 emp (287 docs) | 36 emp (37 docs) | 223 emp (234 docs) | 0 emp (0 docs) | **602** | **716** | 549,3 MB |
| **2018** | 104 emp (161 docs) | 292 emp (309 docs) | 37 emp (39 docs) | 232 emp (244 docs) | 0 emp (0 docs) | **627** | **753** | 490,5 MB |
| **2019** | 108 emp (170 docs) | 293 emp (311 docs) | 42 emp (44 docs) | 237 emp (250 docs) | 0 emp (0 docs) | **636** | **775** | 586,3 MB |
| **2020** | 118 emp (343 docs) | 301 emp (544 docs) | 39 emp (61 docs) | 245 emp (376 docs) | 7 emp (7 docs) | **659** | **1.331** | 2.740,5 MB |
| **2021** | 123 emp (277 docs) | 303 emp (342 docs) | 39 emp (44 docs) | 250 emp (279 docs) | 3 emp (3 docs) | **664** | **945** | 1.012,9 MB |
| **2022** | 90 emp (150 docs) | 50 emp (55 docs) | 6 emp (7 docs) | 35 emp (36 docs) | 1 emp (1 docs) | **176** | **249** | 315,0 MB |
| **2023** | 30 emp (38 docs) | 1 emp (1 docs) | 0 emp (0 docs) | 0 emp (0 docs) | 1 emp (1 docs) | **32** | **40** | 215,9 MB |
| **2024** | 30 emp (36 docs) | 2 emp (2 docs) | 0 emp (0 docs) | 0 emp (0 docs) | 1 emp (1 docs) | **32** | **39** | 518,1 MB |
| **2025** | 31 emp (35 docs) | 1 emp (1 docs) | 0 emp (0 docs) | 0 emp (0 docs) | 1 emp (1 docs) | **33** | **37** | 453,6 MB |
| **TOTAL DE** | **138 emp (2.020 docs)** | **326 emp (2.808 docs)** | **45 emp (391 docs)** | **284 emp (2.295 docs)** | **13 emp (13 docs)** | **796 emp** | **7.927 docs** | **8,59 GB** |

---

## 5. Detalle por País: Francia (`FR`)

### 5.1. Matriz Evolutiva Año a Año por Mercado (Francia)

| Año | CAC 40 | CAC Next 20 | SBF 120 (Mid 60) | Euronext Growth (Small) | Histórico / Expandido | Total Empresas Únicas | Total Archivos | Volumen (MB) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2012** | 23 emp (31 docs) | 11 emp (12 docs) | 24 emp (25 docs) | 96 emp (126 docs) | 153 emp (158 docs) | **307** | **352** | 1.400,9 MB |
| **2013** | 25 emp (30 docs) | 11 emp (11 docs) | 27 emp (30 docs) | 98 emp (129 docs) | 147 emp (151 docs) | **308** | **351** | 1.645,4 MB |
| **2014** | 27 emp (31 docs) | 11 emp (11 docs) | 33 emp (35 docs) | 102 emp (128 docs) | 145 emp (149 docs) | **318** | **354** | 1.850,1 MB |
| **2015** | 29 emp (36 docs) | 11 emp (12 docs) | 36 emp (39 docs) | 108 emp (134 docs) | 136 emp (141 docs) | **320** | **362** | 2.299,4 MB |
| **2016** | 29 emp (34 docs) | 11 emp (12 docs) | 38 emp (41 docs) | 114 emp (140 docs) | 121 emp (125 docs) | **313** | **352** | 1.789,9 MB |
| **2017** | 29 emp (36 docs) | 11 emp (13 docs) | 39 emp (43 docs) | 117 emp (145 docs) | 114 emp (118 docs) | **310** | **355** | 2.525,7 MB |
| **2018** | 29 emp (35 docs) | 12 emp (12 docs) | 42 emp (45 docs) | 122 emp (159 docs) | 95 emp (99 docs) | **300** | **350** | 25,6 MB |
| **2019** | 29 emp (31 docs) | 12 emp (12 docs) | 44 emp (44 docs) | 124 emp (140 docs) | 81 emp (81 docs) | **290** | **308** | 25,7 MB |
| **2020** | 10 emp (12 docs) | 3 emp (3 docs) | 13 emp (13 docs) | 37 emp (39 docs) | 0 emp (0 docs) | **63** | **67** | 961,8 MB |
| **2021** | 28 emp (30 docs) | 13 emp (13 docs) | 38 emp (38 docs) | 119 emp (130 docs) | 0 emp (0 docs) | **198** | **211** | 4.667,7 MB |
| **2022** | 31 emp (33 docs) | 15 emp (15 docs) | 42 emp (43 docs) | 132 emp (146 docs) | 0 emp (0 docs) | **220** | **237** | 4.705,5 MB |
| **2023** | 29 emp (33 docs) | 13 emp (13 docs) | 36 emp (37 docs) | 123 emp (134 docs) | 0 emp (0 docs) | **201** | **217** | 4.675,1 MB |
| **2024** | 29 emp (33 docs) | 12 emp (12 docs) | 39 emp (40 docs) | 125 emp (136 docs) | 0 emp (0 docs) | **205** | **221** | 5.550,2 MB |
| **2025** | 19 emp (23 docs) | 11 emp (11 docs) | 33 emp (34 docs) | 106 emp (115 docs) | 0 emp (0 docs) | **169** | **183** | 5.090,7 MB |
| **2026** | 2 emp (2 docs) | 3 emp (3 docs) | 3 emp (3 docs) | 7 emp (7 docs) | 0 emp (0 docs) | **15** | **15** | 238,7 MB |
| **TOTAL FR** | **34 emp (430 docs)** | **15 emp (165 docs)** | **51 emp (510 docs)** | **181 emp (1.808 docs)** | **248 emp (1.022 docs)** | **529 emp** | **3.935 docs** | **36,57 GB** |

---

## 6. Detalle por País: Estados Unidos (`US`)

### 6.1. Localización Exhaustiva en el Escritorio (Sin Acceso a `D:\`)

- **Nivel 1 — Data Lake Curado (`lake/ESTADOS_UNIDOS`)**:
  - `C:\Users\jfulg\Desktop\Stater\ARGOS_DATA_DISK\lake\ESTADOS_UNIDOS`: **266 documentos**, **1.405,95 MB (1,41 GB)**, **38 empresas líderes**.
  - `SP500_MEGA_CAPS` (31 empresas, 231 docs) e `HISTORICO_O_EXPANDIDO` (7 emisores ADR, 35 docs).
- **Nivel 2 — Repositorio Econométrico (`Argos_BD\EEUU`)**:
  - `C:\Users\jfulg\Desktop\Stater\Argos_BD\EEUU`: **32.280 archivos**, **57,68 GB**.
  - Panel Multianual SEC (6.261 filings Form 10-K, 1.301 CIKs), Benchmark (4.480 filings, 896 empresas), 13.169 filings `.txt` y base DuckDB con 4.853 auditorías PCAOB y 8.579 CAMs.
- **Nivel 3 — Paquetes Oficiales Masivos SEC EDGAR (.ZIP)**:
  - `submissions.zip` (1.481,15 MB), `companyfacts.zip` (1.325,64 MB), `d_us_txt.zip` (512,90 MB).
- **Ficheros JSON Maestros**: [audit_batch_us.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_us.json) (266 fichas) y [sec_panel_us_summary.json](file:///c:/Users/jfulg/Desktop/Stater/sec_panel_us_summary.json).

### 6.2. Matriz Evolutiva Año a Año en el Data Lake Curado (`lake/ESTADOS_UNIDOS`)

| Año | SP500 Mega Caps | Histórico / Expandido (ADR 20-F) | Total Empresas Únicas | Total Archivos | Volumen (MB) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **2005** | 4 emp (4 docs) | 0 emp (0 docs) | **4** | **4** | 6,4 MB |
| **2006** | 4 emp (5 docs) | 0 emp (0 docs) | **4** | **5** | 8,2 MB |
| **2007** | 4 emp (4 docs) | 0 emp (0 docs) | **4** | **4** | 4,8 MB |
| **2008** | 4 emp (4 docs) | 0 emp (0 docs) | **4** | **4** | 5,1 MB |
| **2009** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 5,2 MB |
| **2010** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 1,8 MB |
| **2011** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 2,0 MB |
| **2012** | 2 emp (3 docs) | 0 emp (0 docs) | **2** | **3** | 2,3 MB |
| **2013** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 2,0 MB |
| **2014** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 2,1 MB |
| **2015** | 1 emp (1 docs) | 0 emp (0 docs) | **1** | **1** | 1,8 MB |
| **2016** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 5,0 MB |
| **2017** | 2 emp (3 docs) | 0 emp (0 docs) | **2** | **3** | 12,1 MB |
| **2018** | 2 emp (2 docs) | 0 emp (0 docs) | **2** | **2** | 10,3 MB |
| **2019** | 17 emp (17 docs) | 2 emp (3 docs) | **19** | **20** | 121,9 MB |
| **2020** | 20 emp (20 docs) | 2 emp (3 docs) | **22** | **23** | 132,1 MB |
| **2021** | 23 emp (23 docs) | 2 emp (3 docs) | **25** | **26** | 139,7 MB |
| **2022** | 23 emp (23 docs) | 2 emp (3 docs) | **25** | **26** | 135,7 MB |
| **2023** | 24 emp (25 docs) | 6 emp (8 docs) | **30** | **33** | 200,6 MB |
| **2024** | 31 emp (57 docs) | 7 emp (9 docs) | **38** | **66** | 373,4 MB |
| **2025** | 28 emp (28 docs) | 6 emp (6 docs) | **34** | **34** | 233,4 MB |
| **TOTAL LAKE US** | **31 emp (231 docs)** | **7 emp (35 docs)** | **38 emp** | **266 docs** | **1.405,95 MB (1,41 GB)** |

---

## 7. Detalle por País: Países Bajos (`NL`)

### 7.1. Localización y Estructura en el Repositorio

- **Data Lake Curado (`lake/PAISES_BAJOS`)**:
  - Ubicación: `C:\Users\jfulg\Desktop\Stater\ARGOS_DATA_DISK\lake\PAISES_BAJOS` y `D:\ARGOS_DATA\lake\PAISES_BAJOS`.
  - Mercado: `AEX25` (Bolsa de Ámsterdam / Euronext Amsterdam).
  - Contenido: **5 documentos primarios** oficiales con un volumen de **153,56 MB**:
    - `ASML Holding NV`: Cuentas anuales auditadas en HTML interactivo 2023 (25,2 MB), 2024 (32,3 MB), 2025 (23,7 MB) y paquete ESEF ZIP 2021 (69,6 MB).
    - `ING Groep NV`: Paquete ESEF ZIP oficial 2021 (2,7 MB).
- **Censo de Registros Sellados en Raw (`raw/NL_AFM`)**:
  - Ubicación: `ARGOS_DATA_DISK\raw\NL_AFM` (y réplica en `D:\ARGOS_DATA\raw\NL_AFM`).
  - Regulador: AFM (*Autoriteit Financiële Markten*).
  - Cobertura: **10 empresas líderes** censadas año a año de 2019 a 2025:
    1. ASML Holding NV (`ASML`)
    2. ING Groep NV (`INGA`)
    3. Koninklijke Ahold Delhaize NV (`AD`)
    4. Heineken NV (`HEIA`)
    5. Koninklijke Philips NV (`PHIA`)
    6. Prosus NV (`PROX`)
    7. Randstad NV (`RAND`)
    8. RELX NV (`RELX`)
    9. Unilever PLC (`UNA`)
    10. Wolters Kluwer NV (`WKL`)
  - Archivos: 82 archivos (77 metadatos sellados `.meta.json` + 3 HTML + 2 ZIP), volumen: 153,61 MB.
  - Fichero JSON Maestro: [audit_batch_nl.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_nl.json) (**72 registros auditados**).

### 7.2. Matriz Evolutiva Año a Año (Países Bajos)

| Año | ASML Holding | ING Groep | Otras 8 Firmas AEX (AFM Raw) | Total Empresas | Total Fichas/Docs | Volumen en Disco (MB) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **2019** | 1 ficha | 1 ficha | 8 fichas | **10** | **10** | <1 MB (Sellado) |
| **2020** | 1 ficha | 1 ficha | 8 fichas | **10** | **10** | <1 MB (Sellado) |
| **2021** | 1 doc ZIP ESEF | 1 doc ZIP ESEF | 9 fichas | **10** | **11** | 72,33 MB |
| **2022** | 1 ficha | 1 ficha | 8 fichas | **10** | **10** | <1 MB (Sellado) |
| **2023** | 1 doc HTM Anual | 1 ficha | 8 fichas | **10** | **10** | 25,22 MB |
| **2024** | 1 doc HTM Anual | 1 ficha | 8 fichas | **10** | **10** | 32,30 MB |
| **2025** | 1 doc HTM Anual | 1 ficha | 8 fichas | **10** | **10** | 23,71 MB |
| **TOTAL NL** | **5 docs Lake + 2 fichas** | **1 doc Lake + 6 fichas** | **58 fichas** | **10 emp** | **72 fichas** | **153,61 MB** |

---

## 8. Detalle por País: Italia (`IT`)

### 8.1. Localización y Estructura en el Repositorio

- **Censo de Metadatos Sellados en Raw (`raw/IT_CONSOB`)**:
  - Ubicación: `C:\Users\jfulg\Desktop\Stater\ARGOS_DATA_DISK\raw\IT_CONSOB` y `D:\ARGOS_DATA\raw\IT_CONSOB`.
  - Autoridad Supervisora: CONSOB (*Commissione Nazionale per le Società e la Borsa*).
  - Mercado: FTSE MIB (*Borsa Italiana* / Euronext Milan).
  - Cobertura Temporal: **2019 a 2025** (7 ejercicios completos).
  - Empresas Censadas (12 blue chips del índice FTSE MIB):
    1. Davide Campari-Milano NV (`CPR`)
    2. Enel SpA (`ENEL`)
    3. Eni SpA (`ENI`)
    4. Assicurazioni Generali SpA (`G`)
    5. Intesa Sanpaolo SpA (`ISP`)
    6. Leonardo SpA (`LDO`)
    7. Moncler SpA (`MONC`)
    8. Prysmian SpA (`PRY`)
    9. Ferrari NV (`RACE`)
    10. Snam SpA (`SRG`)
    11. Terna SpA (`TRN`)
    12. UniCredit SpA (`UCG`)
  - Estado Técnico: **84 registros de metadatos sellados** (`RAW_METADATA_SEALED`), con código LEI verificado, hash SHA-256 por ejercicio y nomenclatura estandarizada `IT_CONSOB_<LEI>_<AÑO>_ESEF`.
  - Módulos de Soporte: `ARGOS_MOTOR\descarga\it_italy` y `DOCUMENTACION_LEGAL_BOLSAS_Y_OAMS\05_ITALIA`.
  - Fichero JSON Maestro: [audit_batch_it.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_it.json) (**84 registros auditados**).

### 8.2. Matriz Evolutiva Año a Año (Italia)

| Año | Empresas FTSE MIB Censadas | Total Registros Sellados CONSOB | Auditorías Identificadas (KPMG, PwC, EY, Deloitte) | Formato |
|:---:|:---:|:---:|:---:|:---:|
| **2019** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2020** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2021** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2022** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2023** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2024** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **2025** | 12 emp | 12 fichas | 12 dictámenes | ESEF Raw Sealed |
| **TOTAL IT** | **12 emp** | **84 fichas** | **84 dictámenes legales** | **ZIP ESEF Sealed** |

---

## 9. Inventario de Países Adicionales Identificados: Reino Unido (`UK`)

Durante la exploración forense de los discos locales se ha localizado un volumen masivo de datos documentales correspondiente al Reino Unido que se encuentra fuera del Data Lake curado y disponible para incorporación:

- **Ruta física**: `C:\Users\jfulg\Desktop\estudios v\CCA_Reino_Unido`.
- **Corpus complementario**: `C:\Users\jfulg\Desktop\estudios v\universo\d_uk_txt.zip` (162,76 MB).
- **Módulo de descarga**: `ARGOS_MOTOR\descarga\uk_fca`.
- **Volumen total**: **16,66 GB** (16.655,60 MB) y **7.567 archivos**.
- **Distribución por formatos**:
  - HTML nativo: 5.948 archivos (78,61 %)
  - PDF: 826 archivos (10,92 %)
  - ZIP (Paquetes ESEF / FCA): 478 archivos (6,32 %)
  - XHTML / XBRL: 305 archivos (4,03 %)
  - Otros: 10 archivos (0,12 %)
- **Rango temporal**: **2020 a 2026** (7 ejercicios):
  - 2020: 1.047 archivos (575,9 MB)
  - 2021: 1.079 archivos (1.073,0 MB)
  - 2022: 1.183 archivos (3.660,3 MB)
  - 2023: 1.173 archivos (3.623,8 MB)
  - 2024: 1.147 archivos (2.492,0 MB)
  - 2025: 1.132 archivos (2.667,1 MB)
  - 2026: 806 archivos (2.563,6 MB)

---

## 10. Resumen de Ficheros JSON Maestros Generados en Stater

1. [audit_batch_us.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_us.json): 266 fichas de EE.UU. (358 KB).
2. [sec_panel_us_summary.json](file:///c:/Users/jfulg/Desktop/Stater/sec_panel_us_summary.json): Resumen macro de EE.UU. (3,8 KB).
3. [audit_batch_nl.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_nl.json): 72 fichas de Países Bajos (68 KB).
4. [audit_batch_it.json](file:///c:/Users/jfulg/Desktop/Stater/audit_batch_it.json): 84 fichas de Italia (76 KB).
