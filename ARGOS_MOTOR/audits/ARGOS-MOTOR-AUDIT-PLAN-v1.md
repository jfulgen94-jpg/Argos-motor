# Plan Maestro: Inyección de Coherencia y Auditoría Forense del Data Lake (España)

**Documento:** `ARGOS-MOTOR-AUDIT-PLAN-v1.md`  
**Autor:** Arquitecto Cuantitativo Senior, ARGOS MOTOR  
**Fecha:** 2026-09-13  
**Objetivo:** Garantizar la integridad, coherencia y calidad institucional del corpus documental de renta variable española (378 sociedades, 15 años) para habilitar su procesamiento en pipelines cuantitativos y de IA.

---

## 1. Visión General y Filosofía de Auditoría

Este plan establece un protocolo de **confianza cero** (`zero-trust`) para la validación de datos no estructurados (PDFs) y semi-estructurados (XBRL/ESEF). No se asumirá que la nomenclatura de un archivo o su ubicación son correctas; cada punto de dato será verificado criptográficamente y mediante análisis de contenido antes de ser admitido en el entorno de producción cuantitativo.

El proceso se automatizará mediante un script maestro de auditoría en Python, generando un informe interactivo en HTML como entregable final para la revisión humana de anomalías.

## 2. Herramientas y Entorno de Ejecución

El pipeline de auditoría se ejecutará con el siguiente stack tecnológico:

| Componente | Herramienta / Librería | Propósito |
| :--- | :--- | :--- |
| **Orquestación y Lógica** | Python 3.10+ | Scripting, control de flujo y lógica de negocio. |
| **Inventario de Archivos** | `find`, `glob` (Python `pathlib`) | Generación del inventario inicial de todos los filings. |
| **Análisis de PDF** | `pypdf`, `pdfplumber`, `PyPDF2` | Extracción de texto y metadatos internos de los PDFs. |
| **Análisis de ESEF/ZIP**| `zipfile`, `xml.etree.ElementTree` | Descompresión en memoria y parseo de taxonomías XBRL. |
| **Verificación Criptográfica**| `hashlib` | Cálculo de hashes SHA-256 para validación de integridad. |
| **Gestión de Datos** | `pandas` | Manipulación y análisis de grandes volúmenes de metadatos. |
| **Generación de Informes** | `jinja2`, `markdown` | Creación de reportes dinámicos en HTML y Markdown. |
| **Sistema de Ficheros** | Almacenamiento Canónico Disco D: | Acceso al data lake (`D:\ARGOS_DATA\raw\ES_CNMV`). |

---

## 3. Estructura y Fases del Plan de Ejecución

### Fase I: Inventario y Carga Inicial (Setup)
**Objetivo:** Crear un DataFrame con la lista completa de todos los archivos a auditar y el universo maestro como referencia.
1. **Script:** `audit_forensics_spain.py`
2. **Acción 1.1:** Escaneo recursivo de `D:\ARGOS_DATA\raw\ES_CNMV` para listar todos los `.pdf` y `.zip`.
3. **Acción 1.2:** Carga de `ARGOS_MOTOR/config/master_universe_es.json` (378 sociedades).
4. **Acción 1.3:** Carga de los 15 manifiestos (`MANIFEST_CNMV_*.json`) con sus hashes SHA-256 esperados.

### Fase II: Pipeline de Verificación Forense (Por Archivo)
**Objetivo:** Procesar cada archivo a través de validadores rigurosos:
1. **Paso 2.1: Verificación de Nomenclatura vs. Universo Maestro:**
   - Extraer Ticker, CIF y Año.
   - Assert 1: Coincidencia de CIF y Ticker con el universo maestro.
2. **Paso 2.2: Verificación de Contenido Interno:**
   - PDF: Magic bytes `%PDF`, validación de estructura de cabecera y cuerpo sin corrupción.
   - ZIP (ESEF): Magic bytes `PK\x03\x04`, validación de archivo ZIP íntegro en memoria, localización de reportes XHTML/XML.
3. **Paso 2.3: Verificación Criptográfica vs. Manifiesto:**
   - Cálculo de hash SHA-256 en disco.
   - Assert 5: Coincidencia exacta con el hash registrado en el manifiesto oficial.

### Fase III: Agregación de Resultados y Generación del Informe
**Objetivo:** Consolidar métricas y generar `audit_report.html` con KPIs, desglose por segmento, cobertura histórica (2012-2026), cobertura SOCIMIs y lista de anomalías.
