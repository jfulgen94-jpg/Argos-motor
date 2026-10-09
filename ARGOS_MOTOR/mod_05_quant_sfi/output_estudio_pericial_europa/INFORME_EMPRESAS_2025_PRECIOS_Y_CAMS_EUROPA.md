# INFORME PERICIAL: EJERCICIO 2025 (PUBLICACIONES 2026) — EVOLUCIÓN DE PRECIOS HASTA HOY Y MATRIZ CRUZADA (6 BOLSAS x 3 ESTADOS CAM)

**Entorno:** SFI Quantitative Lab — Argos Motor  
**Base de Datos Oficial:** `ARGOS_MOTOR/data/lake/duckdb/stater_motor.duckdb` (`pericial_informes_2025_europa`)  
**Fecha de Referencia de Mercado:** Octubre 2026  
**Universo Auditado:** Cotizadas europeas de BME (España), XETRA (Alemania), Euronext Paris (Francia), Euronext Amsterdam (Países Bajos) y Borsa Italiana (Italia).

---

## 1. MATRIZ BIDIMENSIONAL CRUZADA (6 BOLSAS x 3 NIVELES DE SEVERIDAD CAM)

Rentabilidad media acumulada desde la fecha exacta de publicación del informe anual 2025 hasta la cotización actual (octubre 2026). En paréntesis se indica la **mediana**:

| Nivel de Severidad CAM (Coordenadas) | Baja Cara | Baja Barata | Media Cara | Media Barata | Buena Cara | Buena Barata |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Rentabilidad CAM Severa** | **$-5,99\%$**<br>($-5,40\%$) | **$-19,98\%$**<br>($-14,42\%$) | *N/A\** | *N/A\** | *N/A\** | *N/A\** |
| **Rentabilidad CAM Media** | *N/A\** | *N/A\** | **$+3,05\%$**<br>($+3,11\%$) | **$+10,29\%$**<br>($+11,09\%$) | **$-0,15\%$**<br>($+4,50\%$) | **$+21,75\%$**<br>($+19,93\%$) |
| **Rentabilidad CAM Leve** | **$-0,87\%$**<br>($-17,56\%$) | **$-31,14\%$**<br>($-31,14\%$) | **$+2,98\%$**<br>($+1,27\%$) | **$+6,14\%$**<br>($+2,09\%$) | **$+0,23\%$**<br>($+4,27\%$) | **$-8,68\%$**<br>($-18,77\%$) |

*\*Nota: En empresas de calidad Media y Buena no se emitieron CAMs Severas en el ejercicio 2025 (las alertas graves se concentraron en las cotizadas de baja calidad operativa y alto endeudamiento).*

---

## 2. MATRIZ DE DISTRIBUCIÓN Y RECUENTO DE COTIZADAS

Número de empresas por cuadrante del modelo:

| Nivel de Severidad CAM | Baja Cara | Baja Barata | Media Cara | Media Barata | Buena Cara | Buena Barata | Total Fila |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **CAM Severa** | 5 | 4 | 0 | 0 | 0 | 0 | **9** |
| **CAM Media** | 0 | 0 | 14 | 12 | 4 | 4 | **34** |
| **CAM Leve** | 5 | 2 | 46 | 6 | 18 | 4 | **81** |
| **Total Columna** | **10** | **6** | **60** | **18** | **22** | **8** | **124** |

---

## 3. PRINCIPALES HALLAZGOS PERICIALES

1. **Destrucción de Valor en "Baja Barata":** 
   - Las empresas con fundamentales débiles y múltiplos aparentemente "baratos" sufrieron las caídas más severas del mercado tras presentar sus informes: **$-19,98\%$** en CAM Severa (Tubos Reunidos $-40,58\%$, Renault $-17,78\%$, Tubacex $-11,06\%$, Telefónica $-10,48\%$) y **$-31,14\%$** en CAM Leve (Stellantis $-42,72\%$, Volkswagen $-19,57\%$). Demuestra la trampa de valor (*value trap*) donde el múltiplo bajo anticipaba el colapso operativo.
2. **Desempeño Extraordinario en "Buena Barata" con CAM Media:**
   - La banca europea de primera línea (BBVA $+29,09\%$, Santander $+10,76\%$, ING Groep $+42,05\%$, BNP Paribas $+5,12\%$) promedió un **$+21,75\%$** desde la fecha de publicación, absorbiendo sin fricción las CAMs medias de modelos de provisiones crediticias IFRS 9.
3. **El Sector Auto en "Buena Barata":**
   - Las cotizadas automotrices de alta calidad contable histórica pero castigadas en ciclo (BMW $-27,35\%$, Mercedes-Benz $-28,23\%$) pesaron a la baja en la celda *Buena Barata con CAM Leve* (media de $-8,68\%$), mientras Acerinox ($+31,06\%$) contrarrestó la tendencia.
4. **Compounders Tecnológicos e Industriales en "Buena Cara":**
   - Compañías como ASML ($+39,34\%$), Schneider Electric ($+18,66\%$), Porsche AG ($+15,89\%$), Bankinter ($+15,55\%$), Dassault Systèmes ($+15,29\%$) y Ferrari ($+12,36\%$) mantuvieron un empuje sólido, compensando el ajuste de múltiplos en lujo extremo (Hermès $-37,04\%$, LVMH $-28,52\%$).

---

## 4. ARCHIVOS GENERADOS

- Dataset completo de empresas 2025: [`06_empresas_2025_evolucion_precios.csv`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/mod_05_quant_sfi/output_estudio_pericial_europa/06_empresas_2025_evolucion_precios.csv)
- Matriz de rentabilidades: [`07_matriz_rentabilidad_cruzada_2025_hasta_hoy.csv`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/mod_05_quant_sfi/output_estudio_pericial_europa/07_matriz_rentabilidad_cruzada_2025_hasta_hoy.csv)
- Matriz de conteos: [`08_matriz_conteo_2025_hasta_hoy.csv`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/mod_05_quant_sfi/output_estudio_pericial_europa/08_matriz_conteo_2025_hasta_hoy.csv)
- Tabla SQL persistente en Data Lake: DuckDB `pericial_informes_2025_europa` en [`stater_motor.duckdb`](file:///c:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/data/lake/duckdb/stater_motor.duckdb).
