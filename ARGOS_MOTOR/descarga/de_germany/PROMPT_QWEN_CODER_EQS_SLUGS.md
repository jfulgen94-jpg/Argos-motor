# PROMPT PARA QWEN CODER: GENERADOR DEL MAPA DE SLUGS EQS / DGAP (ALEMANIA)
## Proyecto: STATER / ARGOS MOTOR — Mapeo Exhaustivo de Empresas Prime Standard a Slugs de EQS Group

Eres el Especialista Principal en Ingeniería de Datos y Normalización de Entidades Financieras de STATER.
Tu misión es generar el archivo de configuración:
`ARGOS_MOTOR/config/eqs_company_slugs.json`

---

### 1. CONTEXTO Y ARQUITECTURA DEL CANAL EQS / DGAP

En Alemania, por mandato de la ley de mercados de valores (*WpHG*), el 95% de las empresas cotizadas difunden obligatoriamente sus cuentas anuales auditadas a través del servicio regulatorio de **EQS Group (antigua DGAP)**.
Las cuentas anuales históricas (2012–2025) están alojadas en el repositorio institucional de EQS con URLs estables, públicas y sin CAPTCHA:

`https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-EQ-D-{Version}.pdf`

Donde:
- `{CompanySlug}`: Nombre o alias corporativo en la ruta del servidor de EQS (ej. `BASF`, `BMW`, `Siemens`, `Continental`, `Daimler`, `HeidelbergCement`, `eads`, `Volkswagen`).
- `{ISIN}`: Código ISIN oficial de 12 caracteres (ej. `DE000BASF111`, `DE0007164600`).
- `{Year}`: Año contable auditado de 4 dígitos (`2012` a `2025`).
- `{Version}`: Variante documental (`00` o `01`).

---

### 2. ARCHIVO DE ENTRADA

Tienes a tu disposición el archivo con las 172 empresas de la Fase 1:
`ARGOS_MOTOR/config/prime_standard_companies.json`

Cada registro contiene:
- `ticker`: Ticker bursátil (ej. `BASF`, `MERC`, `AIRB`, `HEID`).
- `isin`: Código ISIN oficial.
- `name_common`: Nombre comercial habitual (ej. `BASF`, `Mercedes-Benz Group`, `Airbus`, `Heidelberg Materials`).
- `name_legal`: Razón social completa registrada (ej. `BASF SE`, `Mercedes-Benz Group AG`, `Heidelberg Materials AG`).

---

### 3. REGLAS DE GENERACIÓN DE SLUGS CANDIDATOS

Para cada una de las 172 empresas, debes proveer una lista ordenada de **slugs candidatos** (típicamente entre 2 y 5 candidatos por empresa) para que el descargador pruebe la existencia de los PDFs:

1. **Nombre común sin espacios ni caracteres especiales**: ej. `BASF`, `Siemens`, `Continental`, `Infineon`.
2. **Nombre comercial limpio en PascalCase o Upper**: ej. `DeliveryHero`, `TeamViewer`, `Nemetschek`.
3. **Alias históricos o fusiones previas (CRÍTICO PARA 2012–2020)**:
   - `MERC` (Mercedes-Benz Group) -> `["Daimler", "MercedesBenz", "Mercedes-Benz"]`
   - `HEID` (Heidelberg Materials) -> `["HeidelbergCement", "HeidelbergMaterials"]`
   - `AIRB` (Airbus SE) -> `["eads", "Airbus", "EADS"]`
   - `DHLG` (DHL Group / Deutsche Post) -> `["DeutschePost", "dhl", "DHL"]`
   - `FRES` (Fresenius) -> `["Fresenius"]`
   - `FRES_2` (Fresenius Medical Care) -> `["FMC", "FreseniusMedicalCare"]`
   - `MUV2` (Munich Re) -> `["MunichRe", "MuenchenerRueck"]`
   - `HLE` (Hannover Re) -> `["HannoverRueck", "HannoverRe"]`
   - `THYS` (Thyssenkrupp) -> `["Thyssenkrupp", "thyssenkrupp"]`
   - `VOW3` / `VOLK` (Volkswagen) -> `["Volkswagen", "volkswagen"]`
   - `BAYN` (Bayer) -> `["Bayer"]`
   - `ALV` (Allianz) -> `["Allianz"]`
   - `DTE` / `DEUT` (Deutsche Telekom) -> `["DeutscheTelekom", "Telekom"]`
   - `DBK` / `DEUT_2` (Deutsche Bank) -> `["DeutscheBank"]`
   - `CBK` (Commerzbank) -> `["Commerzbank"]`
   - `RWE` (RWE AG) -> `["RWE"]`
   - `EOAN` (E.ON) -> `["EON", "E.ON"]`
   - `SAP` (SAP SE) -> `["SAP"]`
4. **Ticker en mayúsculas y minúsculas**: Siempre incluir el propio ticker como fallback.

---

### 4. FORMATO DE SALIDA REQUERIDO

Debes generar o guardar el archivo:
`ARGOS_MOTOR/config/eqs_company_slugs.json`

Estructura JSON:
```json
{
  "_metadata": {
    "generated_at": "2026-09-23",
    "total_companies": 172,
    "purpose": "EQS / DGAP corporate storage slug mappings for German listed issuers"
  },
  "companies": {
    "BASF": {
      "isin": "DE000BASF111",
      "name": "BASF SE",
      "slugs": ["BASF", "basf"]
    },
    "MERC": {
      "isin": "DE0007100000",
      "name": "Mercedes-Benz Group AG",
      "slugs": ["Daimler", "MercedesBenz", "Mercedes-Benz", "mercedes-benz"]
    },
    "HEID": {
      "isin": "DE0006047004",
      "name": "Heidelberg Materials AG",
      "slugs": ["HeidelbergCement", "HeidelbergMaterials", "heidelbergcement"]
    },
    "AIRB": {
      "isin": "NL0000235190",
      "name": "Airbus SE",
      "slugs": ["eads", "Airbus", "EADS"]
    }
  }
}
```

---

### 5. SCRIPT GENERADOR AUTOMÁTICO (OPCIONAL EN PYTHON)

Si lo prefieres, puedes escribir un script en `scratch/build_eqs_slugs.py` que lea `ARGOS_MOTOR/config/prime_standard_companies.json`, aplique las heurísticas y guarde `ARGOS_MOTOR/config/eqs_company_slugs.json`.

¡Procede a generar el archivo completo para las 172 empresas de Prime Standard!
