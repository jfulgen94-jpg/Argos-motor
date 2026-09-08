# SUBMÓDULO DE DESCARGA: ESPAÑA (CNMV / BME / ESEF)

## 1. Identificación Institucional
* **Autoridad Nacional Competente (NCA)**: Comisión Nacional del Mercado de Valores (CNMV).
* **Mecanismo Centralizado Oficial (OAM)**: Registro Oficial de Información Regulada de la CNMV (`www.cnmv.es`).
* **Bolsas y Mercados**: BME (Bolsas y Mercados Españoles - BME Exchange, Mercado Continuo, BME Growth).
* **Repositorio ESEF Europeo**: European Electronic Access Point / filings.xbrl.org / ESMA.
* **Universo Objetivo**: **~200 Valores Cotizados** (IBEX 35: 34-35 emisores, Mercado Continuo: 87 emisores, BME Growth: ~54-80 emisores).

---

## 2. Método de Descarga e Ingesta Técnica
El pipeline de descarga opera mediante tres canales oficiales:

### Canal A: Ingesta ESEF / XBRL Oficial (2021 en adelante)
* **Formato**: Paquete ZIP que contiene la instancia principal xHTML (`.xhtml`) y la carpeta de taxonomía local (`.xsd`, `.xml` de etiquetas, presentación y cálculo).
* **Endpoint Primario**: `https://filings.xbrl.org/` y el portal de difusión de ESEF de la CNMV.
* **Identificador de Búsqueda**: Código LEI de 20 caracteres alfanuméricos (resuelto y validado contra el catálogo oficial GLEIF).

### Canal B: Registro Oficial CNMV (IP - Información Periódica)
* **Endpoint Consulta Emisores**: `https://www.cnmv.es/portal/Consultas/DerechosVoto/IP.aspx?nif={CIF}`
* **Documentación Histórica (2005 - 2020)**: Formularios IPP (Información Financiera Periódica Semestral y Trimestral) descargados vía lotes ZIP oficiales de la CNMV.
* **Cuentas Anuales Auditadas**: Descarga directa de archivos PDF/ZIP sellados con código seguro de verificación (CSV).

### Canal C: BME y BME Growth
* **Endpoint BME Growth**: Publicaciones periódicas de estados financieros auditados semestrales y anuales para empresas en expansión y SOCIMIs cotizadas.

---

## 3. Estado de Evidencia en Disco (Auditoría Forense)
A fecha de auditoría en `data/raw/`:
* **Archivos Brutos en `ES_CNMV`**: **3.949 archivos** (18,35 GB).
* **Paquetes Anuales COMPLETOS en `INFORMES_ANUALES_COMPLETOS`**: **257 paquetes anuales** (2020: 35, 2021: 62, 2022: 53, 2023: 54, 2024: 53).
* **Paquetes ESEF indexados por LEI en `landing_raw`**: **464 paquetes anuales** (11,8 GB) correspondientes a 122 emisores únicos.
* **Cobertura del Universo Maestro de 175 empresas**:
  - Emisores ya con paquetes completos en disco: **115 emisores**.
  - Emisores pendientes de descarga para cerrar el universo cotizado: **60-80 emisores**.

---

## 4. Ejecución del Downloader
Para ejecutar la descarga sobre los emisores pendientes del universo español:

```bash
python ARGOS_MOTOR/descarga/es_spain/downloader_cnmv.py --all-200 --years 2020,2021,2022,2023,2024
```

### Opciones de Ejecución:
* `--all-200`: Procesa los 200 valores del catálogo maestro (IBEX35, Continuo y BME Growth).
* `--missing-only`: Solo descarga los valores que aún no tienen informe completo en disco.
* `--dry-run`: Verifica disponibilidad en la API de CNMV / ESEF sin descargar archivos físicos.

---

## 5. Auditoría de la Propia Descarga
Una vez finalizada la descarga, se ejecuta automáticamente el script de verificación criptográfica:

```bash
python ARGOS_MOTOR/descarga/es_spain/audit_download_es.py
```

El script valida:
1. Magic bytes (`PK\x03\x04` o `%PDF-`).
2. Hash SHA-256 contrastado con el manifest de CNMV.
3. Descarte de HTMLs de bloqueo o páginas de error 404 (movimiento a cuarentena).
4. Integridad del fichero ZIP mediante prueba de descompresión en memoria.
