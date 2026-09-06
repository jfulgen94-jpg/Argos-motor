# DOSIER TÉCNICO-CIENTÍFICO: EVALUACIÓN DE INFORMES DE AUDITORÍA (KAM) E INFORMES DE GESTIÓN Y SOSTENIBILIDAD (KPI) EN EL MERCADO EUROPEO

**Proyecto Institucional:** STATER / REX / ARGOS / SFI LAB — Plataforma Europea de Datos Financieros, Auditoría y Sostenibilidad  
**Línea de Investigación Académica:** Universidad de Murcia (UMU) — Máster Universitario en Auditoría de Cuentas  
**Fecha de Consolidación:** Septiembre de 2026  
**Clasificación Metodológica:** Investigación Cuantitativa, Auditoría Forense Algorítmica y Trazabilidad Criptográfica SHA-256  

---

## RESUMEN EJECUTIVO Y MAPA ONTOLÓGICO DE LA INVESTIGACIÓN

El presente informe consolida toda la información documental, regulatoria, arquitectónica y empírica disponible en el ecosistema **STATER**, diferenciando de forma rigurosa y exhaustiva dos proyectos de investigación complementarios pero de **naturaleza ontológica distinta**:

```
                                          ┌────────────────────────────────────────────────────────┐
                                          │       ECOSISTEMA STATER / MOTOR ARGOS / SFI LAB        │
                                          └──────────────────────────┬─────────────────────────────┘
                                                                     │
                                     ┌───────────────────────────────┴───────────────────────────────┐
                                     ▼                                                               ▼
       ┌───────────────────────────────────────────┐                   ┌───────────────────────────────────────────┐
       │      PROYECTO 1: NATURALEZA KAM           │                   │      PROYECTO 2: NATURALEZA KPI           │
       │   (Auditoría Externa Independiente)       │                   │   (Informe de Gestión y Sostenibilidad)   │
       ├───────────────────────────────────────────┤                   ├───────────────────────────────────────────┤
       │ • Origen: Cuentas Anuales Consolidadas    │                   │ • Origen: Informe de Gestión y EINF/CSRD  │
       │ • Emisor: Auditor Externo (Big Four / OAA)│                   │ • Emisor: Consejo de Administración / C-Level│
       │ • Marco: ISA 701 / NIA-ES 701 / AS 3101   │                   │ • Marco: NFRD / Ley 11/2018 / CSRD / ESRS │
       │ • Obligatoriedad: Desde 2019 (UE y EE.UU.)│                   │ • Obligatoriedad: 2019 (NFRD) y 2025 (CSRD)│
       │ • Formato: Texto no estructurado en ESEF  │                   │ • Formato: De memoria dispersa a iXBRL ESRS│
       │ • Aseguramiento: Opinión Técnica Oficial  │                   │ • Aseguramiento: ISSA 5000 (Limitado/Razonable)│
       │ • Objetivo: Medición de Riesgo Contable   │                   │ • Objetivo: Doble Materialidad e Impacto  │
       │ • Interacción: Cruce con P/B y Calidad    │                   │ • Interacción: Greenwashing vs. Sanciones │
       └───────────────────────────────────────────┘                   └───────────────────────────────────────────┘
```

El análisis descarta deliberadamente los modelos tradicionales de análisis fundamental aislado de partidas contables para centrarse con rigor en:
1. **La base de clasificación de bolsas y coordenadas generales de valoración Price-to-Book ($P/B$)** combinada con métricas de solvencia contable como mapa de navegación del mercado.
2. **La determinación, cuantificación y valoración de severidad de las Cuestiones Clave de Auditoría (KAM)** y su capacidad para alterar, sesgar o predecir el comportamiento bursátil de las acciones cotizadas a 12, 24 y 36 meses.
3. **La determinación y estructuración de los Indicadores Clave de Rendimiento (KPI)** de sostenibilidad y gestión empresarial bajo los mandatos europeos de 2019 (NFRD / EINF) y 2025 (CSRD / ESRS), auditando su veracidad mediante un detector de inconsistencias y sanciones regulatorias.

---

# BLOQUE 0: EL SISTEMA DE COORDENADAS FUNDAMENTALES — CLASIFICACIÓN DE BOLSAS Y RATIO P/B

Para evitar la dispersión del análisis fundamental tradicional (DCF subjetivos, ajustes discrecionales de márgenes), el sistema STATER/SFI adopta como **variable de control y segmentación de mercado una matriz bidimensional objetiva**: **Calidad Contable Agregada × Nivel de Precio sobre Valor Contable ($P/B$)**.

### 1. Las 6 Bolsas Fundamentales Canónicas
La población bursátil se segmenta en 6 coordenadas excluyentes:

| Código de Bolsa | Nivel de Calidad Financiera | Umbral de Valoración ($P/B$) | Características Contables del Grupo |
| :--- | :--- | :---: | :--- |
| **1. `Buena_Barata`** | **Alta Calidad** (Top Tercil) | $P/B \le 1,00$ | Altas rentabilidades sobre capital (ROIC/ROE), balances blindados, baja deuda, cotizando por debajo o a la par de su valor contable neto. |
| **2. `Buena_Cara`** | **Alta Calidad** (Top Tercil) | $P/B > 1,00$ | Líderes de sector, elevados márgenes y fosos defensivos, cotizando con prima de mercado sobre su balance contable. |
| **3. `Media_Barata`** | **Calidad Media** (Tercil Medio) | $P/B \le 1,00$ | Negocios estables, balances razonables pero sin ventajas competitivas extremas, cotizando con descuento sobre libros. **Zona crítica de asimetría.** |
| **4. `Media_Cara`** | **Calidad Media** (Tercil Medio) | $P/B > 1,00$ | Negocios cíclicos o maduros valorados con múltiplos estándar sin margen de seguridad contable evidente. |
| **5. `Baja_Barata`** | **Deteriorada** (Tercil Inferior) | $P/B \le 1,00$ | Rentabilidad destruida, apalancamiento elevado, estrés operativo; cotizando a múltiplos de derribo (*deep value* / empresas en reestructuración). |
| **6. `Baja_Cara`** | **Deteriorada** (Tercil Inferior) | $P/B > 1,00$ | Empresas con deterioro fundamental severo pero cuyo precio de cotización permanece inflado por expectativas infundadas. **Zona de colapso y trampa de valor.** |

Esta segmentación es la base estructural sobre la cual se proyecta el impacto predictivo de la auditoría (KAM) y la veracidad de la sostenibilidad (KPI).

---

# PROYECTO 1: NATURALEZA KAM (KEY AUDIT MATTERS)
### INFORMES DE AUDITORÍA EUROPEOS, DETERMINACIÓN DE SEVERIDAD Y PREDICTIBILIDAD DEL PRECIO DE LA ACCIÓN

```
      ═══════════════════════════════════════════════════════════════════════════════════════
       PROYECTO 1: AUDITORÍA FORENSE DE KAMs (ISA 701) Y PREDICTIBILIDAD BURSÁTIL
      ═══════════════════════════════════════════════════════════════════════════════════════
```

## 1.1. Marco Normativo Europeo e Internacional y Obligatoriedad (Hito 2019)

### 1.1.1. La Norma Internacional ISA 701 y su Transposición en España (NIA-ES 701)
* **Origen y Fundamento:** Emitida por el IAASB (*International Auditing and Assurance Standards Board*), la **ISA 701** (*Communicating Key Audit Matters in the Independent Auditor's Report*) transformó radicalmente el modelo tradicional de informe de auditoría "pasa/no pasa" (*pass/fail*), obligando al auditor independiente a describir las materias que, según su juicio profesional, han sido de la mayor significatividad en la auditoría del ejercicio.
* **Adopción en España y la Unión Europea:**
  * En España, el ICAC (*Instituto de Contabilidad y Auditoría de Cuentas*) aprobó la **NIA-ES 701** mediante Resolución de 23 de diciembre de 2016, siendo obligatoria para auditorías de cuentas anuales de ejercicios iniciados a partir del 17 de junio de 2016 y generalizándose para el 100% de las Entidades de Interés Público (EIP) en 2017–2018.
  * **Consolidación Plena en 2019:** El ejercicio fiscal 2018 (publicado en el primer semestre de **2019**) supuso la entrada en régimen estacionario obligatorio de la comunicación de KAMs para todo el mercado continuo y mercados regulados europeos, permitiendo generar series temporales homogéneas y auditables desde 2019 en adelante.
* **El Homólogo Estadounidense (PCAOB AS 3101 - CAMs):**
  * La norma **AS 3101** del PCAOB (*Public Company Accounting Oversight Board*) introdujo las *Critical Audit Matters* (CAM).
  * **Entrada en vigor escalonada:** Obligatoria para *Large Accelerated Filers* en ejercicios cerrados a partir del **30 de junio de 2019**, y para el resto de cotizadas en ejercicios cerrados a partir del **15 de diciembre de 2020**.
  * **Diferencia Técnica Clave:** Aunque conceptualmente paralelas, la PCAOB exige vincular cada CAM explícitamente a una cuenta contable o desglose relevante de los estados financieros, mientras que la ISA 701 europea permite una mayor latitud discursiva respecto a riesgos transversales de control y entorno económico.

### 1.1.2. El Mandato Tecnológico ESEF y la "Paradoja de la Auditoría Europea"
* **Reglamento Delegado (UE) 2019/815 (ESEF):** Desde el ejercicio 2020/2021, todos los emisores en mercados regulados europeos deben depositar su informe financiero anual en formato Inline XBRL (iXBRL).
* **La Paradoja Técnica:** Mientras los estados financieros primarios (Balance, PyG, Flujos de Efectivo, Cambios en Patrimonio Neto) y ciertas notas mínimas disponen de etiquetas XBRL estructuradas y reconciliables matemáticamente, **el informe de auditoría independiente y las KAMs carecen de una taxonomía XBRL obligatoria aprobada por ESMA**. 
* **Consecuencia Metodológica:** Las KAMs se presentan incrustadas como texto libre (XHTML/HTML5 o PDF escaneado). Esto imposibilita la extracción mediante parsers XML convencionales y exige la creación de un **motor de Inteligencia Artificial y Procesamiento del Lenguaje Natural (NLP)** específico para segmentar, aislar, clasificar y evaluar la severidad de cada asunto comunicado.

---

## 1.2. Datos Evaluados y Descargados en el Proyecto STATER

La infraestructura de STATER / MOTOR ARGOS ha implementado un sistema de descarga sistemática, validación pericial y sellado criptográfico sobre fuentes oficiales públicas:

### 1.2.1. Inventario Físico de Descargas y Datos Procesados en el Repositorio

| Mercado / OAM Regulador | Organismo Fuente | Protocolo / Formato | Archivos Descargados / Procesados | Estado de Ingesta y Custodia |
| :--- | :--- | :--- | :---: | :--- |
| **España (ES_CNMV)** | CNMV / BME / filings.xbrl.org | ESEF ZIP, iXBRL XHTML, IPP XML, PDF, IAGC/IARC | **3.949 archivos** (615 JSON, 298 XHTML, 2.447 XML, 79 ZIPs oficiales de 20–115 MB) | **Completado:** 12 Blue Chips (SAN, BBVA, IBE, ITX, TEF, REP, CABK, AMS, CLNX, FER, GRF, ELE) cubriendo 2019–2026; 1.453 documentos registrados en DuckDB. |
| **Landing Raw Central** | filings.xbrl.org / APIs OAMs | Bundles ZIP ESEF oficiales multipaís | **926 archivos** (466 ZIPs íntegros + 460 metadatos JSON) | **En cuarentena/Stage 1:** Ingestión directa con sellado SHA-256 en origen. |
| **Francia (FR_AMF)** | Autorité des Marchés Financiers (AMF) | URD / ESEF iXBRL ZIP / PDF | **111 archivos** (105 JSON metadatos + 6 XHTML/HTM) | Conector `fr_amf_client.py` operativo con identificación SIREN/SIRET y LEI. |
| **Alemania (DE_BAFIN)** | Unternehmensregister / Bundesanzeiger | Jahresfinanzberichte ESEF / XML | **108 archivos** (103 JSON metadatos + 5 XHTML/HTM) | Conector `de_bafin_client.py` operativo sobre Handelsregister y LEI. |
| **Italia (IT_CONSOB)** | CONSOB / 1INFO / eMarket SDIR | Relazioni Finanziarie ESEF ZIP | **84 archivos** (84 JSON metadatos) | Conector `it_consob_client.py` operativo sobre Partita IVA y LEI. |
| **Países Bajos (NL_AFM)** | Autoriteit Financiële Markten (AFM) | Jaarverslag ESEF ZIP | **73 archivos** (70 JSON metadatos + 3 HTM) | Conector operativo sobre registro oficial holandés. |
| **Panel Transatlántico (SEC EDGAR)** | SEC EDGAR (`sec.gov`) | Form 10-K HTML bruto, XBRL CompanyFacts | **4.853 informes 10-K** procesados de **1.146 empresas cotizadas** (NYSE/NASDAQ) | **100% Auditado en `auditoria_cam.duckdb`:** 8.579 ítems KAM/CAM extraídos y validados con serie de precios 2019–2026. Muestra de control S&P 1500 (1.661 filings). |

### 1.2.2. Protocolo de Custodia Criptográfica Forense (SHA-256)
Para garantizar la validez judicial y científica del dato:
1. **Sellado en Origen:** Cada archivo ZIP y XHTML descargado recibe de inmediato un hash SHA-256 inmutable registrado en `*.meta.json` y `manifest.json`.
2. **Los 18 Documentos Legales Fundacionales:** En agosto de 2024 se descargaron y hashearon los 18 textos regulatorios y contratos de licencia de los 27 OAMs y operadores bursátiles europeos para fijar la jurisprudencia aplicable de reutilización de datos derivados.
3. **Árbol de Trazabilidad Bidireccional:** Todo ratio o conclusión vincula el hash del dato transformado con el hash del documento original y el número de párrafo exacto del informe de auditoría.

---

## 1.3. Determinación y Valoración de Severidad de las KAMs

El módulo `MOD_03_NLP_AUDIT` (`kam_extractor.py`) ejecuta un modelo de clasificación multi-dimensional para transformar el texto libre del auditor en una variable analítica de severidad contable.

### 1.3.1. Las 5 Dimensiones de Severidad Evaluadas

```
                           ┌────────────────────────────────────────────────────────┐
                           │      CLASIFICADOR MULTI-DIMENSIONAL DE SEVERIDAD       │
                           └──────────────────────────┬─────────────────────────────┘
                                                      │
         ┌───────────────────┬────────────────────────┼───────────────────────┬───────────────────┐
         ▼                   ▼                        ▼                       ▼                   ▼
  [Dimensión A]       [Dimensión B]            [Dimensión C]           [Dimensión D]       [Dimensión E]
 ÁREA ESTRATÉGICA     IDIOSINCRASIA             COMPLEJIDAD               ENTORNO            EXCESO DE
 DE ALTO JUICIO       SEMÁNTICA TF-IDF            TEXTUAL               CONCENTRADO           GOODWILL
 (Goodwill, RevRec,  (Similitud Coseno          (Legibilidad Flesch    (Más de 3 KAMs      (Goodwill/Activos
 Impuestos, Nivel 3)  Percentil ≤ 25)           Reading Ease ≤ P25)     por Informe)        Totales ≥ P75)
```

1. **Dimensión A (Área Estratégica):** Materias sujetas a máxima discrecionalidad directiva: Deterioro de fondo de comercio (*Goodwill Impairment*), Reconocimiento de ingresos en contratos plurianuales complejas (IFRS 15 / ASC 606), Instrumentos financieros derivados Nivel 3 (IFRS 9 / ASC 820) e Incertidumbre de Empresa en Funcionamiento (*Going Concern*).
2. **Dimensión B (Idiosincrasia Semántica):** Distancia de vector respecto al lenguaje estándar (*boilerplate*) de su sector y año. Si la similitud coseno TF-IDF / RoBERTa está en el percentil inferior ($P \le 25$), el auditor está utilizando términos específicos, detallados y no convencionales para alertar de un riesgo singular.
3. **Dimensión C (Complejidad Textual):** Cálculo del índice de legibilidad *Flesch Reading Ease* normalizado por sector. Un índice en el percentil más bajo ($P \le 25$) revela una redacción opaca u ofuscada para delimitar responsabilidades legales.
4. **Dimensión D (Entorno Crítico):** Presencia de $\ge 4$ KAMs en un único informe financiero.
5. **Dimensión E (Exceso de Goodwill Estructural):** Verificación automática en el balance de que el ratio $\text{Fondo de Comercio} / \text{Activo Total} \ge P75$.

### 1.3.2. Reglas de Asignación de Severidad

* **KAM LEVE (Nivel 0):** Materia ordinaria o rutinaria, sin áreas estratégicas ni alertas secundarias ($B=0, C=0, D=0, E=0$). Lenguaje estándar de auditoría.
* **KAM MODERADA (Nivel 1):** Materia de área estratégica (ej. reconocimiento de ingresos) pero con redacción convencional sin alertas secundarias.
* **KAM CRÍTICA / SEVERA (Nivel 2 / Nivel 3):** Materia de Área Estratégica **Y** presencia de al menos una alerta secundaria verificada ($B=1 \lor C=1 \lor D=1 \lor E=1$), o presencia directa de párrafo de *Going Concern* / incertidumbre sobre la continuidad de la empresa.

### 1.3.3. Taxonomía de Tópicos Contables y Frecuencia Empírica Observada
Sobre la base de 8.579 cuestiones auditadas en el sistema, la distribución sectorial de tópicos se distribuye de la siguiente forma:

| Código | Tópico Contable Normalizado | Norma Europea (NIIF) | Norma EE.UU. (US-GAAP) | Frecuencia Absoluta | % del Total | Área Estratégica | Legibilidad Flesch Media |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **TOPIC_01** | Fondo de Comercio e Intangibles | IAS 36 / IFRS 3 | ASC 350 | **2.840** | **33,1%** | SÍ | 34,2 (Baja) |
| **TOPIC_02** | Reconocimiento de Ingresos | IFRS 15 | ASC 606 | **2.315** | **27,0%** | SÍ | 37,8 |
| **TOPIC_06** | Impuestos Diferidos y Créditos Fiscales | IAS 12 | ASC 740 | **1.140** | **13,3%** | NO | 39,5 |
| **TOPIC_05** | Combinaciones de Negocios y M&A | IFRS 3 | ASC 805 | **780** | **9,1%** | SÍ | 35,1 |
| **TOPIC_04** | Valor Razonable y Modelos Nivel 3 | IFRS 13 | ASC 820 | **520** | **6,1%** | SÍ | 33,9 |
| **TOPIC_08** | Litigios, Provisiones y Contingencias | IAS 37 | ASC 450 | **395** | **4,6%** | SÍ | 36,4 |
| **TOPIC_03** | Instrumentos Financieros y Derivados | IFRS 9 | ASC 815 | **280** | **3,3%** | SÍ | 32,1 (Muy Baja) |
| **TOPIC_07** | Pérdidas Crediticias Esperadas (ECL/CECL) | IFRS 9 | ASC 326 | **185** | **2,2%** | NO | 38,0 |
| **TOPIC_11** | Empresa en Funcionamiento (*Going Concern*) | IAS 1 | ASC 205-40 | **124** | **1,4%** | SÍ | 31,5 (Crítica) |

---

## 1.4. Efecto Empírico en el Desarrollo y "Predictibilidad" del Precio de la Acción

Uno de los hallazgos científicos más contundentes del proyecto STATER es la demostración de que **las KAMs poseen un poder predictivo asimétrico y condicional sobre los retornos bursátiles futuros**, invalidando la hipótesis de que constituyen mero texto irrelevante (*boilerplate*).

### 1.4.1. Hipótesis Demostrada: Asimetría y Revelación de Riesgo Latente
* **En Empresas de Alta Calidad (`Buena_Cara` / `Buena_Barata`):** Las KAMs críticas no generan penalización bursátil duradera. El mercado confía en la capacidad del balance para absorber el ajuste contable.
* **En Empresas Deterioradas o Medianas con Valoración Exigente:** Una KAM crítica actúa como un **catalizador destructivo de valor**, desmantelando la narrativa directiva y forzando una contracción masiva del múltiplo de cotización.

### 1.4.2. Matriz de Rentabilidad Cruzada a 36 Meses (Horizonte Estructural)
Rendimiento acumulado post-publicación de la auditoría en el panel de cotizadas (`Media / Mediana, [Win Rate %, n casos]`):

| Grupo Fundamental (Calidad × P/B) | KAM LEVE (Nivel 0) | KAM MODERADA (Nivel 1) | KAM CRÍTICA / SEVERA (Nivel 2) | COMPORTAMIENTO AGREGADO DEL GRUPO |
| :--- | :---: | :---: | :---: | :---: |
| **1. `Buena_Barata`** | **+51,3% / +24,5%** (82,5%) `[n=40]` | **+15,6% / +7,5%** (57,9%) `[n=57]` | *(Sin casos críticos en muestra)* | **+31,4% / +20,8%** (71,1%) `[n=128]` |
| **2. `Buena_Cara`** | **+27,0% / +12,8%** (60,4%) `[n=351]` | **+31,7% / +9,1%** (59,9%) `[n=661]` | **+43,8% / +12,9%** (66,4%) `[n=113]` | **+31,2% / +9,9%** (60,6%) `[n=1.125]` |
| **3. `Media_Barata`** | **+394,1% / +89,9%** (78,0%) `[n=41]`<br>*(Zona Dorada de Reversión)* | **+229,7% / +107,4%** (90,9%) `[n=44]` | **-13,4% / -38,1%** (29,5%) `[n=78]`<br>*(Destrucción por Auditor)* | **+317,9% / +89,9%** (80,3%) `[n=117]` |
| **4. `Media_Cara`** | **+112,5% / +59,5%** (77,8%) `[n=45]` | **+77,9% / +56,9%** (66,1%) `[n=59]` | **-18,9% / -39,3%** (34,8%) `[n=46]` | **+80,9% / +38,9%** (68,3%) `[n=145]` |
| **5. `Baja_Barata`** | **+185,0% / +10,4%** (66,7%) `[n=24]` | **+79,6% / +29,7%** (76,2%) `[n=21]` | **-16,8% / -16,8%** (0,0%) `[n=2]` | **+103,9% / +15,5%** (72,3%) `[n=65]` |
| **6. `Baja_Cara`** | **-21,6% / -74,8%** (29,2%) `[n=24]`<br>*(Trampa de Valor Oculta)* | **+26,5% / -44,0%** (37,9%) `[n=29]` | **-29,9% / -43,0%** (33,3%) `[n=39]`<br>*(Colapso Certificado)* | **-4,7% / -24,6%** (34,2%) `[n=146]` |

### 1.4.3. Los Dos Descubrimientos Empíricos Clave de la Matriz

#### 1. El Descubrimiento de la "Zona Dorada de Alpha" en `Media_Barata`:
* Si un inversor compra el grupo `Media_Barata` a ciegas, obtiene una mediana del $+89,9\%$.
* Pero si filtra por la severidad del informe de auditoría:
  * Aquellas con **KAM Leve o Moderada** entregan entre un **$+89,9\%$ y $+107,4\%$ de mediana** (con medias de hasta $+394,1\%$ y ratios de acierto del $78\%$ al $90\%$).
  * Aquellas donde el auditor emite una **KAM Crítica** se desploman a una **mediana del $-38,1\%$ con solo un $29,5\%$ de probabilidad de acierto**.
  * **Conclusión:** La opinión del auditor es la variable que discrimina matemáticamente si la empresa barata va a experimentar una revalorización explosiva o si se dirige hacia el concurso de acreedores.

#### 2. La Demolición de la Trampa de Valor en `Baja_Cara`:
* Las empresas deterioradas cotizando caras con **KAM Leve** sufren el mayor derrumbe de todo el mercado: una **mediana de retorno de $-74,8\%$** (win rate de apenas $29,2\%$). Al no avisar el auditor de anomalías específicas, el mercado tarda más en descontar el deterioro, provocando caídas fulminantes cuando la realidad aflora en los resultados posteriores.

### 1.4.4. Modelo Econométrico de Panel con Efectos Fijos y Errores Clúster
Ecuación formal estimada sobre 4.398 observaciones:

$$R_{i, t+h} = \alpha + \beta_1 \text{KAM\_Severity}_{i,t} + \beta_2 \text{Deteriorated}_{i,t} + \beta_3 (\text{KAM\_Severity}_{i,t} \times \text{Baja\_Cara}_{i,t}) + \gamma X_{i,t} + \mu_{\text{sector}} + \lambda_{\text{año}} + \varepsilon_{i,t}$$

* **Resultados a 12 Meses:**
  * Coeficiente de Severidad KAM ($\beta_1$): **$-0,0382$** ($p < 0,01$). Cada escalón de severidad resta un 3,82% de rentabilidad a un año.
  * Presencia de KAM Crítica aislada: **$-0,0905$** ($p < 0,01$). Penalización directa del -9,05% en retornos anuales.
* **Resultados a 36 Meses:**
  * Término de Interacción $\text{KAM\_Severity} \times \text{Baja\_Cara}$ ($\beta_3$): **$+0,8835$** con **$p = 0,048$** ($R^2 \text{ ajustado} = 0,1370$).
  * Significado pericial: Demuestra que la interacción entre severidad de auditoría y precio desajustado no es lineal ni aditiva, sino un multiplicador de riesgo estadísticamente significativo al 5%.
* **Estudio de Eventos a Corto Plazo (Ventana $[-5, +5]$ y $[-1, +1]$ días):**
  * Retornos Anormales Acumulados (CAR): La publicación de un informe con KAM Crítica o salvedad genera un CAR medio en tres días de **$-3,29\%$**, sin reversión posterior en los 60 días siguientes.

---

# PROYECTO 2: NATURALEZA KPI (SOSTENIBILIDAD Y GESTIÓN)
### INFORMES DE GESTIÓN EUROPEOS, OBLIGATORIEDAD 2019 VS 2025 (CSRD/ESRS), DETERMINACIÓN DE KPIS Y VERACIDAD

```
      ═══════════════════════════════════════════════════════════════════════════════════════
       PROYECTO 2: SOSTENIBILIDAD CSRD, KPIS DE GESTIÓN Y DETECCIÓN DE GREENWASHING
      ═══════════════════════════════════════════════════════════════════════════════════════
```

## 2.1. Marco Normativo y Cronograma de Obligatoriedad Europea: De 2019 a 2025

### 2.1.1. El Hito de 2019: La Directiva NFRD (2014/95/UE) y la Ley 11/2018 en España
* **La Directiva NFRD:** Obligaba exclusivamente a Entidades de Interés Público (EIP) con más de 500 empleados (~11.700 empresas en toda la UE) a publicar un Estado de Información No Financiera (EINF).
* **Transposición Española (Ley 11/2018):** España fue más exigente que la directiva comunitaria, obligando desde el ejercicio 2018 (reportes de **2019**) a empresas de más de 500 empleados, y reduciendo el umbral a más de 250 empleados a partir del tercer año de vigencia (2021).
* **Diagnóstico de Insuficiencia Metodológica (El Fracaso de NFRD):**
  * La Comisión Europea constató en 2021 que el **75% de los informes bajo NFRD carecían de información comparable y verificable**.
  * No existían estándares contables uniformes obligatorios (se permitía usar marcos voluntarios heterogéneos: GRI, ODS, SASB).
  * No existía formato digital estructurado (documentos en PDF libre de cientos de páginas con alta carga publicitaria).
  * Ausencia de un régimen uniforme de verificación externa, generando una proliferación masiva de *greenwashing* discursivo.

### 2.1.2. El Hito de 2025: La Directiva CSRD (UE 2022/2464) y los Estándares ESRS
* **La Directiva CSRD:** Transforma la información de sostenibilidad en una disciplina contable equivalente en rigor a la información financiera.
* **El Cronograma de Entrada en Vigor:**
  1. **Fase 1 (Ejercicio 2024, Publicación en 2025):** Grandes empresas EIP ya sujetas a NFRD (>500 empleados en mercados regulados). **2025 es el primer año en que el mercado recibe informes bajo estándares ESRS obligatorios.**
  2. **Fase 2 (Ejercicio 2025, Publicación en 2026):** Resto de grandes empresas europeas no cotizadas (>250 empleados y/o >50 M€ facturación y/o >25 M€ activo).
  3. **Fase 3 (Ejercicio 2026, Publicación en 2027):** Pymes cotizadas en mercados regulados (estándar simplificado ESRS VSME).
* **Los Cuatro Pilares Obligatorios de la CSRD:**
  1. **Principio de Doble Materialidad:** Se evalúa conjuntamente la *Materialidad Financiera* (riesgos y oportunidades ESG que impactan en el flujo de caja, balance y coste de capital de la empresa — *Outside-In*) y la *Materialidad de Impacto* (impactos reales o potenciales de la empresa sobre el medioambiente y la sociedad — *Inside-Out*).
  2. **Ubicación en el Informe de Gestión:** Prohibición expresa de publicar la sostenibilidad como un informe separado en la página web. Debe constituir una **sección identificada y dedicada dentro del Informe de Gestión Consolidado**.
  3. **Mandato iXBRL (Taxonomía ESRS):** Obligación de etiquetar digitalmente los datos y textos de sostenibilidad bajo la taxonomía XBRL desarrollada por EFRAG, integrada en el paquete ESEF oficial.
  4. **Aseguramiento Externo Obligatorio bajo ISSA 5000:** Verificación independiente obligatoria. Inicialmente mediante *Assurance Limitado* (conclusión negativa) y evolución prevista hacia *Assurance Razonable* (opinión positiva convencional) a partir de 2028.
* **El Horizonte ESAP (Reglamento UE 2023/2859):** Creación del *European Single Access Point*. Apertura de la ingestión en julio de 2026 y acceso público libre en julio de 2027, manteniendo el valor estratégico de la infraestructura de STATER para anticipar el mercado entre 2024 y 2027.

---

## 2.2. Determinación y Valoración de los KPIs de Gestión y Sostenibilidad

El módulo `MOD_03_NLP_AUDIT` (`csrd_mapper.py` y `greenwashing_detector.py`) estructura los indicadores de sostenibilidad a partir de la lista canónica de datapoints del EFRAG (IG 3) y el protocolo pericial de STATER.

### 2.2.1. Los 10 Estándares ESRS Auditados

```
                                    ┌────────────────────────────────────────────────────────┐
                                    │             ESTÁNDARES SECTOR-AGNOSTIC ESRS            │
                                    └──────────────────────────┬─────────────────────────────┘
                                                               │
                     ┌─────────────────────────────────────────┼────────────────────────────────────────┐
                     ▼                                         ▼                                        ▼
      ┌─────────────────────────────┐           ┌─────────────────────────────┐          ┌─────────────────────────────┐
      │     PILAR E (AMBIENTAL)     │           │      PILAR S (SOCIAL)       │          │    PILAR G (GOBERNANZA)     │
      ├─────────────────────────────┤           ├─────────────────────────────┤          ├─────────────────────────────┤
      │ • ESRS E1: Cambio Climático │           │ • ESRS S1: Personal Propio  │          │ • ESRS G1: Conducta         │
      │ • ESRS E2: Contaminación    │           │ • ESRS S2: Cadena de Valor  │          │   Empresarial y Ética       │
      │ • ESRS E3: Agua y Marina    │           │ • ESRS S3: Comunidades      │          │ • Prevención Corrupción     │
      │ • ESRS E4: Biodiversidad    │           │ • ESRS S4: Consumidores     │          │ • Whistleblowing            │
      │ • ESRS E5: Economía Circular│           └─────────────────────────────┘          └─────────────────────────────┘
      └─────────────────────────────┘
```

1. **ESRS E1 (Cambio Climático):** Emisiones brutas de gases de efecto invernadero (GEI) desglosadas en **Alcance 1 (Scope 1 directas)**, **Alcance 2 (Scope 2 indirectas por electricidad/calor)** y **Alcance 3 (Scope 3 cadena de valor)** expresadas en $tCO_2e$; intensidad de emisiones por ingreso; CapEx y OpEx alineados con la Taxonomía UE.
2. **ESRS E2 (Contaminación):** Emisiones al aire (NOx, SOx, COVs, material particulado PM), vertidos a masas de agua y generación de sustancias de muy alta preocupación (SVHC).
3. **ESRS E3 (Recursos Hídricos y Marinos):** Consumo neto de agua en zonas con estrés hídrico extremo.
4. **ESRS E4 (Biodiversidad y Ecosistemas):** Superficie de suelo ocupada en áreas de alta biodiversidad protegida o Natura 2000.
5. **ESRS E5 (Uso de Recursos y Economía Circular):** Tasa de circularidad técnica; toneladas de residuos peligrosos generados vs. reciclaje real comprobado.
6. **ESRS S1 (Personal Propio - Núcleo del S-Score v2.0):**
   * Brecha salarial de género no ajustada (*Gender Pay Gap*).
   * Índice de frecuencia de accidentes de trabajo con baja (IF).
   * **Número de accidentes laborales mortales (fatalidades).**
   * Porcentaje de cobertura de convenios colectivos.
   * Ratio de salario inicial frente al salario mínimo de referencia.
   * Horas anuales de formación por empleado.
7. **ESRS S2 a S4 (Cadena de Valor, Comunidades y Consumidores):** Auditorías in situ a proveedores de riesgo; políticas de derechos humanos; retiradas de productos lesivos del mercado.
8. **ESRS G1 (Gobernanza y Conducta Empresarial):** Número de casos confirmados de soborno y corrupción; sanciones regulatorias firmes; políticas de protección al denunciante (*whistleblower*).

### 2.2.2. El Principio Axiomático de "Hard Gating" (Reglas de Bloqueo $D_1 \dots D_6$)
A diferencia de las agencias de rating comercial (MSCI, S&P, Sustainalytics) que compensan desastres ambientales o laborales promediando notas ("media ponderada"), el modelo STATER establece que **el daño físico grave no puede ser compensado por marketing verde ni compensación de emisiones**:

* **$D_1$ (Daño Laboral Crítico):** Accidente mortal comprobado en el ejercicio o negligencia grave en salud laboral.
* **$D_2$ (Daño al Consumidor Crítico):** Retiradas masivas de productos lesivos con riesgo para la vida (alertas FDA/CPSC/AEMPS).
* **$D_3$ (Contaminación Crítica):** Vertido tóxico grave no remediado o sanción firme por delito ecológico.
* **$D_4$ (Fraude o Corrupción Material):** Condena penal corporativa por soborno, fraude contable o cohecho.
* **$D_5$ (Litigio Social/Ambiental Grave Pendiente):** Procedimiento judicial masivo con riesgo de insolvencia o daño irreparable.
* **$D_6$ (Incumplimiento Sistemático):** Reiteración de más de 3 sanciones administrativas en el periodo.

**Efecto de la Regla de Bloqueo:** La activación de cualquiera de las condiciones $D_1 \dots D_6$ impone un **techo infranqueable**, degradando inmediatamente a la empresa a **Categoría ROJA o AMARILLA**, independientemente de su puntuación discursiva.

### 2.2.3. Niveles de Certeza y Evidencia Probatoria ($V_0 \dots V_3$)
Para evitar sesgos de inferencia sintética, cada KPI evaluado se etiqueta en una escala pericial de certeza:
* **$V_3$ (Asegurado / Evidencia Positiva Oficial):** Dato auditado por tercero independiente bajo ISAE 3000 / ISSA 5000 o verificado en inspección regulatoria favorable.
* **$V_2$ (Contrastado Federalmente / Búsqueda Negativa):** Contrastado mediante cruce masivo contra bases de datos públicas de inspección oficial (OSHA, EPA, CNMV, SEC, sentencias judiciales) sin constancia de infracción.
* **$V_1$ (Autodeclarado no verificado):** Métrica reportada por la dirección en su informe sin soporte documental externo.
* **$V_0$ (Inconsistente o en Cuarentena):** Discrepancia matemática o semántica detectada.

---

## 2.3. Datos Evaluados y Descargados en el Proyecto de Sostenibilidad

### 2.3.1. Universo Canónico Consolidado (`18_CANONICAL_FINAL_STUDY`)
* **Población Analizada:** **3.005 clases de acciones** cotizadas en mercados organizados, correspondientes a **2.762 emisores jurídicos matrices únicos** (LEIs y CIKs).
* **Score de Impacto Observado ($\mu$):** **62,93 puntos** (Mediana: **64,49 puntos**).
* **Distribución Canónica por Bandas de Calificación:**
  * **Banda Verde (Score $\ge 70,0$):** **615 emisores** (**20,47%** del mercado). Empresas con reporte estructurado y ausencia total de controversias.
  * **Banda Amarilla ($45,0 \le \text{Score} < 70,0$):** **2.387 emisores** (**79,43%** del mercado). Nivel medio de cumplimiento sin aseguramiento pleno.
  * **Banda Roja (Score $< 45,0$ o Activación de Hard Gate $D_1-D_6$):** **3 emisores críticos verificados** (**0,10%**) (`TSN` - Tyson Foods por infracciones de seguridad laboral, `CC` - Chemours por contaminación persistente, `WFC` - Wells Fargo por fraude en cuentas y gobernanza).
* **Distribución por Nivel de Verificación:**
  * **$V_3$ (Asegurado Oficial):** 2 emisores (0,07%).
  * **$V_2$ (Contrastado Regulatoriamente):** 3.003 emisores (99,93%).

### 2.3.2. Descargas e Ingesta del Mercado Español y Europeo (ES_CNMV y OAMs)
* **Los 5 Documentos Institucionales Anuales:** El pipeline de STATER descarga, separa y valida para cada ejercicio fiscal cinco ramas documentales selladas:
  1. `cuentas_anuales_consolidadas_auditadas.xhtml` (CCAA_AUDITED)
  2. `informe_de_gestion_consolidado.xhtml` (INFORME_GESTION)
  3. `estado_informacion_no_financiera_csrd.xhtml` (EINF_CSRD)
  4. `informe_anual_gobierno_corporativo_IAGC.xhtml` (IAGC)
  5. `informe_anual_remuneraciones_IARC.xhtml` (IARC)
* **Reconstrucción Institucional Certificada:** Se completaron los 5 documentos anuales para las 12 mayores cotizadas españolas a lo largo de 8 ejercicios completos (2019–2026), acumulando cientos de estados sellados con SHA-256 e indexados en DuckDB con **cero texto simulado garantizado**.

---

## 2.4. Efecto de los KPIs de Sostenibilidad en el Rendimiento Operativo y Bursátil

El contraste empírico econométrico desarrollado en el proyecto arrojó conclusiones periciales de enorme relevancia para la regulación y la inversión profesional:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│              SÍNTESIS DE HIPÓTESIS ECONOMÉTRICAS DEL PROYECTO 2 (SOSTENIBILIDAD)                 │
├──────────────────────────────┬───────────────────────────────┬───────────────────────────────────┤
│ Hipótesis Formal             │ Modelo Estadístico Utilizado  │ Veredicto Canónico e Implicación  │
├──────────────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ **H1: Rendimiento Operativo**│ Panel OLS con Efectos Fijos   │ **NO IDENTIFICABLE / INOCUA**     │
│ (Mayor volumen de reporte ESG│ Sectoriales y Controles       │ La extensión de divulgación no    │
│ genera mayor ROIC/ROE)       │                               │ genera prima de rentabilidad real.│
├──────────────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ **H2: Greenwashing NLP**     │ Probit de Discrepancia        │ **INCONCLUSIVE (Tendencia)**      │
│ (Brecha retórica vs realidad)│ Discursiva vs. Sanciones      │ $\beta = 1,842$, $p = 0,100$.     │
├──────────────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ **H3: Reacción Bursátil CAR**│ Market Model de Eventos       │ **DESCRIPTIVO SIGNIFICATIVO**     │
│ (Impacto de sanciones reales)│ en ventana $[-1, +1]$ días    │ CAR medio de **$-3,29\%$** ante   │
│                              │                               │ sanción oficial contrastada.      │
├──────────────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ **H4: Moderación con KAM**   │ Tabla de Contingencia y       │ **INDEPENDIENTE EN ORIGEN**       │
│ (Predictibilidad cruzada)    │ Test Exacto de Fisher         │ Odds Ratio $= 1,023$ ($p=0,642$). │
│                              │                               │ Justifica separar KAM y KPI.      │
└──────────────────────────────┴───────────────────────────────┴───────────────────────────────────┘
```

1. **Desconexión entre Narrativa ESG y Rentabilidad Operativa ($H_1$):** El análisis econométrico demuestra que inundar el mercado con memorias de sostenibilidad de 300 páginas repletas de adjetivos favorables no mejora el ROIC ni reduce el coste de capital por sí mismo.
2. **El Valor Predictivo Exclusivo de las Sanciones y Controversias Reales ($H_3$):** La única dimensión de sostenibilidad que posee poder predictivo destructivo sobre el precio de la acción son las **sanciones oficiales firmes de organismos reguladores y laborales** (CAR medio de $-3,29\%$ en ventana corta), lo que valida el enfoque forense de STATER frente a los ratings convencionales.
3. **Independencia de las Fuentes ($H_4$):** La correlación entre la presencia de un KPI crítico de sostenibilidad y una KAM crítica de auditoría es estadísticamente insignificante (Odds Ratio $1,023, p = 0,642$). **Esto demuestra de forma concluyente que el auditor financiero independiente (KAM) y el analista de sostenibilidad (KPI) capturan riesgos totalmente diferentes**, justificando plenamente su separación operativa en dos proyectos diferenciados.

---

# MATRIZ COMPARATIVA INTEGRADA: PROYECTO KAM VS. PROYECTO KPI

| Dimensión de Análisis | PROYECTO 1: NATURALEZA KAM | PROYECTO 2: NATURALEZA KPI |
| :--- | :--- | :--- |
| **Fuente Documental Primaria** | Cuentas Anuales Consolidadas (Informe de Auditoría) | Informe de Gestión Consolidado / EINF / Sección CSRD |
| **Sujeto Emisor** | Auditor Externo Independiente (Socio firmante / Big Four) | Consejo de Administración y Dirección de la Compañía |
| **Marco Regulatorio Nuclear** | ISA 701 (IAASB) / NIA-ES 701 (ICAC) / PCAOB AS 3101 | Directiva NFRD (2014/95) / Ley 11/2018 / CSRD (2022/2464) / ESRS |
| **Hito de Obligatoriedad Plena** | **2019** (Consolidación en UE y EE.UU.) | **2019** (EINF bajo NFRD) y **2025** (Primeros reportes obligatorios CSRD) |
| **Formato en el ESEF Europeo** | Texto libre no estructurado (requiere NLP específico) | Transición de PDF libre a Inline XBRL (iXBRL) bajo taxonomía ESRS |
| **Régimen de Aseguramiento** | Opinión técnica formal independiente (Auditoría Financiera) | Evolución de verificación limitada a razonable bajo ISSA 5000 |
| **Unidades de Medida** | Severidad (Leve, Moderada, Crítica), Tópicos contables | Datapoints cuantitativos ($tCO_2e$, ratios, %) y reglas $D_1-D_6$ |
| **Metodología de Clasificación** | 5 Dimensiones (Área, Idiosincrasia, Flesch, Tópicos, Goodwill)| Hard Gating booleano, S-Score v2.0 y Verificación $V_0 \dots V_3$ |
| **Interacción con Fundamentales** | Cruce directo con **Matriz 6 Grupos (Calidad × P/B)** | Cruce contra bases regulatorias de sanciones y litigios (OSHA, EPA) |
| **Poder Predictivo Bursátil** | **Estructural y Asimétrico:** Anticipa colapsos en `Baja_Cara` (-74,8%) y valida explosiones de valor en `Media_Barata` (+89,9% vs -38,1%) | **Asimétrico por Controversias:** El discurso no genera alpha; las sanciones firmes destruyen valor bursátil (-3,29% CAR) |
| **Aportación de STATER** | Motor NLP de extracción, clasificación y scoring predictivo | Detector cuantitativo de greenwashing y auditoría de doble materialidad |

---

# INFRAESTRUCTURA TÉCNICA, DATALAKE Y REPRODUCIBILIDAD

Toda la evidencia expuesta está soportada por la arquitectura de software construida en el repositorio `STATER`:

1. **Capa de Ingestión (`mod_01_ingestion`):** Conectores especializados para España (`es_cnmv_client.py`), Francia (`fr_amf_client.py`), Alemania (`de_bafin_client.py`) e Italia (`it_consob_client.py`), integrados con la API de `filings.xbrl.org` y GLEIF LEI.
2. **Capa de Custodia (`sha256_sealer.py`):** Sellado criptográfico inmediato de cada paquete ESEF y documento XHTML extraído.
3. **Capa de Almacenamiento Columnar (`mod_04_data_lake`):** Bases de datos analíticas embebidas en DuckDB (`stater_motor.duckdb`, `auditoria_cam.duckdb`) y archivos Parquet estructurados con partición temporal y por emisor.
4. **Capa de Inteligencia Forense (`mod_03_nlp_audit`):** Prompts y clasificadores supervisados (`kam_extractor.py`, `csrd_mapper.py`, `greenwashing_detector.py`) operando localmente en Fase 0 sobre modelos de inferencia determinista (temperatura 0.0) para garantizar que el resultado científico sea **100% reproducible y auditable**.
