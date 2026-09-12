# PROMPT MAESTRO INSTITUCIONAL: CRAWLER Y DESCARGA OFICIAL AMF BDIF (FRANCIA 2012-2025)

## 1. CONTEXTO INSTITUCIONAL Y ARQUITECTURA
- **Proyecto**: STATER Financial Technologies — Data Lake Multi-País ARGOS (MOD_01 Ingestion).
- **Jurisdicción**: Francia (`country_code: "FR"`).
- **Supervisor Oficial**: Autorité des Marchés Financiers (AMF) / Euronext Paris.
- **Estado Actual Canal A (ESEF / XBRL.org)**: 100% completado (2020 a 2026) con 1.235 paquetes sellados y 25,28 GB en `D:\ARGOS_DATA\raw\FR_AMF`.
- **Objetivo Inmediato (Canal B)**: Descargar e indexar los **~4.464 informes anuales regulados oficiales** no-ESEF (periodo 2012-2019 pre-ESEF y 2020-2025 URD/PDF para emisores de Euronext Paris, Euronext Growth y PYMEs).

---

## 2. ESPECIFICACIÓN DE LA API NATIVA DE LA BDIF AMF
La AMF expone a través de su portal `https://bdif.amf-france.org` una API REST que no requiere autenticación:

1. **Endpoint de Búsqueda y Metadatos**:
   - `GET https://bdif.amf-france.org/back/api/v1/informations`
   - Parámetros obligatorios:
     - `AnneesComptables`: Año contable (`2012` a `2025`).
     - `TypesDocument`: `DocumentReference` (2012-2018) y `DocumentEnregistrementUniversel` (2019-2025).
     - `From`: Offset de paginación (0, 50, 100...).
     - `Size`: Tamaño de página (50 recomendado).
   - Headers:
     - `User-Agent`: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`
     - `Referer`: `https://bdif.amf-france.org/`
     - `Accept`: `application/json`

2. **Endpoint Canónico de Descarga de Documento**:
   - `GET https://bdif.amf-france.org/back/api/v1/documents/{doc_path}`
   - `doc_path` proviene directamente del campo `path` dentro del objeto `documents` devuelto por la búsqueda (ejemplo: `2019/D.19-0715/2C7FE1E70982A0B0B75D1B8EE78A0E6999FF63117C8B95D1308B1DB54F6C1C70.pdf`).
   - Retorna directamente el archivo PDF oficial con código HTTP 200 y cabecera `%PDF`.

---

## 3. VOLUMEN AUDITADO POR AÑO (4.464 FILINGS IDENTIFICADOS)
| Ejercicio | Tipo Documental Principal | Filings Anuales Auditados |
| :---: | :---: | :---: |
| **2012** | *Document de Référence* | 340 |
| **2013** | *Document de Référence* | 338 |
| **2014** | *Document de Référence* | 343 |
| **2015** | *Document de Référence* | 344 |
| **2016** | *Document de Référence* | 335 |
| **2017** | *Document de Référence* | 332 |
| **2018** | *Document de Référence* | 351 |
| **2019** | *Document de Référence / URD* | 309 |
| **2020** | *Universal Registration Document (URD)* | 306 |
| **2021** | *Universal Registration Document (URD)* | 295 |
| **2022** | *Universal Registration Document (URD)* | 285 |
| **2023** | *Universal Registration Document (URD)* | 280 |
| **2024** | *Universal Registration Document (URD)* | 262 |
| **2025** | *Universal Registration Document (URD)* | 244 |
| **TOTAL** | **4.464 Documentos Oficiales en PDF** |

---

## 4. INSTRUCCIONES DE EJECUCIÓN AUTÓNOMA PARA OH

### Script Implementado:
`ARGOS_MOTOR/descarga/fr_france/crawler_amf_bdif.py`

### Tarea de Ejecución:
Ejecuta la descarga masiva por lotes o completa de los años históricos sobre la ruta canónica `D:\ARGOS_DATA\raw\FR_AMF`:

```bash
# Para ejecutar los años pre-ESEF (2012 a 2019):
python ARGOS_MOTOR/descarga/fr_france/crawler_amf_bdif.py --years 2012,2013,2014,2015,2016,2017,2018,2019

# Para ejecutar la serie completa no-ESEF (2012 a 2025):
python ARGOS_MOTOR/descarga/fr_france/crawler_amf_bdif.py --years 2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025
```

### Contrato de Almacenamiento y Validación:
1. **Destino canónico**: `D:\ARGOS_DATA\raw\FR_AMF\{year}\{company_name}\`
2. **Nomenclatura**: `{company_name}_{year}_{doc_type}.pdf`
3. **Metadatos criptográficos**: `{company_name}_{year}_{doc_type}.meta.json` con hash SHA-256, tamaño en bytes/MB, fecha y URL de origen.
4. **Validación estricta**: Comprobar magic bytes `%PDF` antes de mover de staging a disco definitivo.
5. **Manifiestos anuales**: Generar `D:\ARGOS_DATA\raw\FR_AMF\MANIFEST_AMF_BDIF_{year}.json` al finalizar cada ejercicio.
