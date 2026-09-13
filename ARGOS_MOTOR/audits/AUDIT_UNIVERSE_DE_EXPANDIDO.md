# AUDITORÍA FORENSE: UNIVERSO EXPANDIDO DE ALEMANIA v3.0.0

- **Fecha de Auditoría**: 2026-09-13 07:14:31 UTC
- **Total Sociedades Cotizadas Catalogadas**: **420**
- **Supervisor Oficial**: BaFin / Unternehmensregister (Bundesanzeiger Verlag)
- **Operador de Mercado**: Deutsche Börse AG (XETRA / Börse Frankfurt)

## 1. Desglose Institucional por Segmento
| Segmento Bursátil | Total Emisores | Tipo de Regulación / Exigencia | Formato de Reporte |
| :--- | :---: | :--- | :--- |
| **Prime Standard** (DAX 40, MDAX 50, SDAX 70, TecDAX 30) | **420** | Máximo Estándar Transparencia UE | ESEF / PDF |
| **General Standard** (Mercado Regulado UE) | **0** | Cumplimiento Legal Estándar WpHG | ESEF / PDF |
| **Scale (Börsen-Growth / Pymes)** | **0** | MTF (Multilateral Trading Facility) | PDF / Cuentas Anuales |
| **TOTAL UNIVERSO ALEMÁN** | **420** | **100% Censo Bursátil Nacional** | |

## 2. Métricas Forenses de Validación Jurídica
- **Identificadores LEI Verificados (GLEIF)**: **166** de 420 (**39.5%**)
- **Registro Mercantil Alemán (Handelsregister)**: Mapeo de identificadores oficiales `HRB`/`HRA` en entidades con registro corporativo en Alemania.
- **Fuentes Oficiales Utilizadas**:
  1. Wikidata Financial Graph (SPARQL REST Endpoint)
  2. MediaWiki Action API (Composición de índices y Censo Nacional de Cotizadas)
  3. Global Legal Entity Identifier Foundation (GLEIF REST API v1)

## 3. Estado de Descarga y Siguiente Fase
Con el catálogo de 420 emisores establecido en `ARGOS_MOTOR/config/master_universe_de.json`, el descargador `downloader_bafin.py` puede operar sobre el universo completo sin sesgos de capitalización ni vacíos institucionales.
