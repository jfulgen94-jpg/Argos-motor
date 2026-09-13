# Informe de Auditoría Universal de Francia (ARGOS MOTOR)

## 1. Desglose del Universo de Empresas Francesas

El universo de búsqueda y clasificación se divide en:

### A) Grandes Capitalizaciones (Large Caps - 60 empresas):
- **CAC 40 (35 empresas con sede en Francia + 5 holdings internacionales)**:
  - Airbus SE (NL), Stellantis NV (NL), STMicroelectronics NV (NL), ArcelorMittal SA (LU), Eurofins Scientific SE (LU).
- **CAC Next 20 (20 empresas)**.

### B) Medianas Capitalizaciones (Mid & Small Caps - SBF 120 / CAC All-Tradable):
- **CAC Mid 60 (60 empresas)**.
- **CAC Small (~150 empresas)**.

### C) Crecimiento y PYMES (Growth & Access - ~450 empresas):
- **Euronext Growth Paris (~280-320 pymes)**: Muchas ya con ESEF ZIP; el resto requiere PDF Crawler AMF.
- **Euronext Access Paris (~150 microcaps)**.

**Total de entidades en el `master_universe_fr.json`: 297**
- CAC40: 35
- CAC_NEXT20: 15
- SBF120_MID60: 54
- EURONEXT_GROWTH_SMALL: 188
- CAC40_FOREIGN_HOLDINGS: 5

## 2. Tratamiento de los 5 Holdings Internacionales (NL/LU)

Los 5 holdings internacionales (Airbus SE, Stellantis NV, STMicroelectronics NV, ArcelorMittal SA, Eurofins Scientific SE) son tratados como parte integral del universo francés debido a su cotización y ponderación en París, a pesar de su sede en Países Bajos (NL) o Luxemburgo (LU) y supervisión por AFM o CSSF. Para efectos de este universo, se consideran entidades relevantes para la adquisición institucional francesa.

## 3. Justificación Legal de los Métodos de Extracción

- **ESEF ZIP Directo (2020-2026)**: A partir del ejercicio fiscal 2020, todas las empresas cotizadas en mercados regulados de la UE (incluido Euronext Paris) están obligadas a presentar sus informes anuales en formato ESEF (European Single Electronic Format), que típicamente incluye un archivo ZIP con XBRL iXBRL. Este es el método preferente para los años cubiertos por esta regulación.
- **PDF Oficial OAM (2012-2019)**: Para los años anteriores a la implementación de ESEF (pre-2020, por ejemplo, 2012-2019), los informes anuales se obtienen de los Organismos de Almacenamiento Oficial (OAM) como la AMF (Autorité des marchés financiers) en formato PDF. Esto asegura la trazabilidad y la oficialidad de la información antes de la obligatoriedad del ESEF.

## 4. Estado de los Archivos Descargados y Hashes SHA-256 (Prueba Controlada)

Se realizó una descarga de prueba controlada de 5 filings representativos del año 2023. Todos los archivos fueron descargados, sellados y almacenados correctamente en `ARGOS_MOTOR/data/raw/FR_AMF/2023`.

**Detalles de los Archivos Descargados:**
- Total de archivos en 2023 (incluyendo `.zip` y `.meta.json`): 10

| Nombre del Archivo | Tamaño (bytes) | Hash SHA-256 |
| :--- | :--- | :--- |
| `AC_2023_esef.zip` | 20.108.455 | `85e8265cd6e1...` |
| `AC_2023_esef.meta.json` | 370 | Metadatos y sello SHA-256 |
| `ATLAND_2023_esef.zip` | 24.216.439 | `eaa7e438a0cb...` |
| `ATLAND_2023_esef.meta.json` | 373 | Metadatos y sello SHA-256 |
| `DIM_2023_esef.zip` | 2.644.514 | `91d5a35fc716...` |
| `DIM_2023_esef.meta.json` | 357 | Metadatos y sello SHA-256 |
| `COVIVI_2023_esef.zip` | 10.944.115 | `8ca0b759667e...` |
| `COVIVI_2023_esef.meta.json` | 361 | Metadatos y sello SHA-256 |
| `SA_2023_esef.zip` | 11.341.253 | `38bf1a1d888a...` |
| `SA_2023_esef.meta.json` | 354 | Metadatos y sello SHA-256 |

Los hashes SHA-256 fueron generados y almacenados en los archivos `.meta.json` correspondientes, garantizando la integridad y autenticidad de los paquetes descargados.
