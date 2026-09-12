# PROMPT INSTITUCIONAL: SANEAMIENTO, JERARQUÍA CANÓNICA Y DESCARGA OFICIAL ESPAÑA (CNMV)

## 1. CONTEXTO INSTITUCIONAL
- **Proyecto**: STATER Financial Technologies — Data Lake Multi-País ARGOS (MOD_01 Ingestion).
- **Jurisdicción**: España (`country_code: "ES"`).
- **Supervisor**: Comisión Nacional del Mercado de Valores (CNMV).
- **Directorio de Datos**: `D:/ARGOS_DATA/raw/ES_CNMV` (con fallback a `ARGOS_MOTOR/data/raw/ES_CNMV`).
- **Problema Detectado y Corregido**:
  1. El scraper antiguo capturaba enlaces del pie de página de la CNMV (`cnmv_2030.pdf`, `codigo_de_conducta.pdf`, etc.) cuando una empresa no tenía cuentas ese año, generando miles de archivos basura duplicados.
  2. La jerarquía de carpetas estaba desordenada e invertida (`{CIF}/{AÑO}` en lugar de `{AÑO}/{CIF}_{TICKER}`).

---

## 2. ARQUITECTURA Y CONTRATO DOCUMENTAL CANÓNICO
La jerarquía de España debe ser estrictamente idéntica a la de Francia:
```text
D:\ARGOS_DATA\raw\ES_CNMV\
├── 2012\
│   └── A08000143_SAB\
│       ├── SAB_2012_cnmv_annual_report_14126.pdf
│       └── SAB_2012_cnmv_annual_report_14126.meta.json
├── ...
├── 2024\
│   ├── A39000013_SAN\
│   │   ├── SAN_2024_cuentas_consolidadas.zip
│   │   └── SAN_2024_cuentas_consolidadas.meta.json
│   └── A48265169_BBVA\
├── MANIFEST_CNMV_2012.json
└── MANIFEST_CNMV_2025.json
```

---

## 3. REGLAS DE DESCARGA E INTEGRIDAD (ANTI-JUNK)
1. **Regla de Filtrado de Documentos de Auditoría (Pre-ESEF 2012-2019)**:
   - Solo se aceptan PDFs oficiales de la CNMV cuyo enlace y nombre contengan el número de registro regulatorio de auditoría (`/AUDITA/<AÑO>/<REGISTRO>.pdf`).
   - Queda estrictamente prohibido descargar PDFs genéricos del pie de página institucional (`codigo_de_conducta`, `cnmv_2030`, `sostenibilidad`, `folletos`).
2. **Regla ESEF (2020 a 2025)**:
   - Paquetes ZIP oficiales etiquetados con Inline XBRL (`_consolidada.zip`, `_individual.zip`) validados con magic bytes `PK\x03\x04` y comprobación del tag `<xbrli:identifier>` correspondiente al LEI de la sociedad.
3. **Cero Carpetas Vacías**:
   - Si una entidad no cotizaba o no depositó cuentas en un ejercicio particular, no se crea carpeta vacía.

---

## 4. INSTRUCCIONES DE EJECUCIÓN AUTÓNOMA PARA OH

### Scripts Disponibles en el Repositorio:
- Motor corregido de ingesta CNMV: `ARGOS_MOTOR/descarga/es_spain/cnmv_engine.py`
- Consolidador canónico y generador de manifiestos: `ARGOS_MOTOR/descarga/es_spain/consolidar_espana_definitivo.py`
- Descargador masivo histórico España: `ARGOS_MOTOR/descarga/es_spain/download_es_historico.py`

### Comandos de Ejecución:
```bash
# 1. Ejecutar consolidación, normalización de jerarquía a {AÑO}/{CIF}_{TICKER} y eliminación de carpetas vacías:
python ARGOS_MOTOR/descarga/es_spain/consolidar_espana_definitivo.py

# 2. Descargar filings limpios pendientes para la serie histórica (2012-2019) sin enlaces basura:
python ARGOS_MOTOR/descarga/es_spain/download_es_historico.py

# 3. Presentar resumen forense indicando:
#    - Total de filings válidos por año en MANIFEST_CNMV_*.json
#    - Cero archivos basura en el árbol
#    - Confirmación de la estructura {AÑO}/{CIF}_{TICKER}
```
