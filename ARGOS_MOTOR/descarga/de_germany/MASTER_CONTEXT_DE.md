# ARGOS MOTOR — MASTER CONTEXT DOCUMENT
## Proyecto: Descarga Institucional Alemania (DE_BAFIN)
**Generado:** 2026-09-18 22:50 | **Version motor:** v3.0.0 | **Universe:** 1.011 sociedades (2012-2026)

---

## 1. RESUMEN EJECUTIVO

| Concepto | Valor |
|----------|-------|
| Total sociedades universo | 1.011 |
| Años objetivo | 2012 – 2026 (15 ejercicios) |
| Combinaciones empresa×año | ~15.165 |
| Motor de descarga | `downloader_germany_v3.py` (v3.0.0, 950+ líneas) |
| Data Lake raíz | `D:/ARGOS_DATA/raw/DE_BAFIN` |
| Universo fuente | `ARGOS_MOTOR/config/master_universe_de.json` |
| Especificación JSON modelo | `ARGOS_MOTOR/descarga/de_germany/MASTER_LOTES_DE_2012_2026.json` |

### Estado Data Lake (INMUTABLE — NO RE-DESCARGAR)
| Año | PDF | ZIP ESEF | HTML | Total |
|-----|-----|----------|------|-------|
| 2012 | 4 | 0 | 0 | **4** |
| 2013 | 3 | 0 | 0 | **3** |
| 2014 | 5 | 0 | 0 | **5** |
| 2015 | 4 | 0 | 0 | **4** |
| 2016 | 6 | 0 | 0 | **6** |
| 2017 | 6 | 0 | 0 | **6** |
| 2018 | 7 | 0 | 0 | **7** |
| 2019 | 7 | 0 | 0 | **7** |
| 2020 | 0 | 265 | 0 | **265** |
| 2021 | 0 | 35 | 0 | **35** |
| 2022 | 0 | 3 | 0 | **3** |
| 2023 | 0 | 0 | 1 | **1** |
| 2024 | 0 | 0 | 2 | **2** |
| 2025 | 0 | 0 | 2 | **2** |
| 2026 | 0 | 0 | 0 | **0** |
| **TOTAL** | **42** | **303** | **5** | **350** |

**Tamaño total:** ~1928.4 MB (1.88 GB)
**Meta.jsons sellados (SHA-256):** 451

---

## 2. UNIVERSO DE SOCIEDADES — DISTRIBUCIÓN

### Por segmento de mercado
| Segmento | Empresas | % | Prioridad descarga |
|----------|----------|---|--------------------|
| PRIME_STANDARD | 172 | 17% | 🔴 ALTA (DAX40, MDAX, TecDAX) |
| GENERAL_STANDARD | 376 | 37% | 🟡 MEDIA (SDAX + cotizadas) |
| FREIVERKEHR_OPEN_MARKET | 396 | 39% | 🟢 NORMAL (Freiverkehr) |
| SCALE_GROWTH | 67 | 7% | 🟢 NORMAL (Scale segment) |

### Nota crítica sobre index_membership
> El campo `index_membership` en `master_universe_de.json` tiene DAX40/MDAX/TECDAX marcado
> en **TODAS** las 1.011 empresas (error de construcción del universo).
> Usar `segment` para filtrar por calidad:
> - PRIME_STANDARD = equivalente a DAX40 + MDAX + TecDAX
> - GENERAL_STANDARD = equivalente a SDAX + otras cotizadas reguladas
> - FREIVERKEHR_OPEN_MARKET = mercado alternativo
> - SCALE_GROWTH = segmento growth

---

## 3. ARQUITECTURA DE CANALES — MOTOR v3.0.0

```
Para cada (empresa, año):
  ├── CANAL 0: Caché local SHA-256 (0 peticiones de red, instantáneo)
  ├── CANAL 1: ESEF fast-path via filings.xbrl.org/OAM (solo años ≥2020, por LEI)
  ├── CANAL 2a: PDF directo mapeado (IR_PDF_MAP ~3 empresas curadas)
  ├── CANAL 2b: Scraping página IR oficial (~90 tickers mapeados en IR_PAGE_PATTERNS)
  ├── CANAL 3: Bundesanzeiger Área 22 (Playwright, pestañas independientes)
  │             ⚠️ NUNCA page.go_back() — Wicket session expiry
  │             ⚠️ Requiere --bafin-manual para resolver CAPTCHAs
  └── CANAL 4: DuckDuckGo HTML → PDFs directos .pdf
```

### Comandos de ejecución por canal
```bash
# Solo Canal 2 IR (recomendado para lotes iniciales, sin CAPTCHA)
--skip-canal 1,3

# Solo Canal 1 ESEF (solo años 2020+)
--skip-canal 2,3,4

# Solo Canal 3 Bundesanzeiger (requiere intervención manual)
--skip-canal 1,2,4 --bafin-manual

# Solo Canal 4 Web Search
--skip-canal 1,2,3

# Todos los canales automáticos (sin Bundesanzeiger)
--skip-canal 3
```

---

## 4. PLAN DE LOTES — DESCARGA COMPLETA 2012-2025

### LOTE 1 — IR Curadas Primarias (EN EJECUCIÓN)
**Empresas con mapa IR verificado en universo maestro**
**Comando:**
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --tickers ADID,AIRB,ALLI,BASF,BAYE_5,DEUT,DEUT_19,DEUT_2,DEUT_24,HEID,LUFT,MUTA,PORS,SAPS,SART,SIEM,SIEM_2,SIEM_3,SMTS,SYMR \
    --years 2012-2019 --skip-canal 1,3
```
| Ticker | Empresa | IR Page |
|--------|---------|---------|
| ADID | Adidas | adidas-group.com |
| AIRB | Airbus | airbus.com |
| ALLI | Allianz SE | allianz.com |
| BASF | BASF | basf.com |
| BAYE_5 | BMW (Bayerische Motoren Werke) | bmwgroup.com |
| DEUT / DEUT_19 | Deutsche Telekom | telekom.com |
| DEUT_2 / DEUT_24 | Deutsche Bank | db.com |
| HEID | HeidelbergMaterials | heidelbergmaterials.com |
| LUFT | Lufthansa | lufthansagroup.com |
| MUTA | Mutares / referencia Munich Re | munich-re.com |
| PORS | Porsche AG | porsche.com |
| SAPS | SAP SE | sap.com |
| SART | Sartorius | sartorius.com |
| SIEM / SIEM_2 / SIEM_3 / SMTS | Siemens | siemens.com |
| SYMR | Symrise | symrise.com |

### LOTE 2 — IR Curadas Ampliadas
**Empresas identificadas en universo vía análisis de nombres**
**Comando:**
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --tickers BAYE_3,CONT,COVE,COVE_2,DE_EON,DE_RWE,FRES,FRES_2,FRES_3,INFI,MERC_2,MERC_3,MERC_4,MUNI,SYMR_2,THYS_2,VOLK,VOLK_2,VOLK_3 \
    --years 2012-2019 --skip-canal 1,3
```
| Ticker | Empresa | IR Page |
|--------|---------|---------|
| VOLK / VOLK_2 / VOLK_3 | Volkswagen AG | volkswagen-group.com |
| INFI | Infineon Technologies | infineon.com |
| BAYE_3 | Bayer AG | bayer.com |
| MUNI | Munich Re | munich-re.com |
| CONT | Continental AG | continental.com |
| DE_RWE | RWE AG | rwe.com |
| DE_EON | E.ON SE | eon.com |
| FRES / FRES_3 | Fresenius SE | fresenius.com |
| FRES_2 | Fresenius Medical Care | freseniusmedicalcare.com |
| MERC_2 / MERC_3 / MERC_4 | Merck KGaA | merckgroup.com |
| COVE / COVE_2 | Covestro AG | covestro.com |
| THYS_2 | thyssenkrupp AG | thyssenkrupp.com |
| SYMR_2 | Symrise AG (duplicado) | symrise.com |

### LOTE 3 — PRIME_STANDARD sin IR mapeada (Canal 4 Web + Canal 3 BAFIN)
**144 empresas** del segmento PRIME_STANDARD sin IR curada
**Comando:**
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --segment PRIME_STANDARD --years 2012-2019 --skip-canal 1,2,3
```
*(Canal 4 Web Search primero; Canal 3 Bundesanzeiger en sesión asistida posterior)*

### LOTE 4 — GENERAL_STANDARD (Canal 3 + Canal 4)
**372 empresas** del segmento GENERAL_STANDARD
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --segment GENERAL_STANDARD --years 2012-2019 --skip-canal 1,2
```

### LOTE 5 — FREIVERKEHR_OPEN_MARKET (Canal 3 + Canal 4)
**396 empresas** del Freiverkehr / Mercado Abierto
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --segment FREIVERKEHR_OPEN_MARKET --years 2012-2019 --skip-canal 1,2
```

### LOTE 6 — SCALE_GROWTH
**67 empresas** del segmento Scale
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --segment SCALE_GROWTH --years 2012-2019 --skip-canal 1,2
```

### LOTE 7 — ESEF 2020-2022 (ya descargado, solo completar huecos)
303 ZIPs ESEF ya descargados. Para completar los 1.011 - 303 = 708 faltantes:
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py \
    --years 2020-2022 --skip-canal 2,3,4
```

### LOTE 8 — Años 2023-2026 (ESEF + IR + Web)
```bash
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py     --years 2023-2026 --skip-canal 3,4
```

---

## 5. ESTRUCTURA DEL DATA LAKE

```
D:/ARGOS_DATA/raw/DE_BAFIN/
├── YEAR/                            # 2012 → 2025
│   ├── HRB_REG_TICKER/             # ej: HRB_719915_SAPS/
│   │   ├── SAPS_2019_ANUAL.pdf     # PDF sellado
│   │   ├── SAPS_2019_ANUAL.pdf.meta.json  # SHA-256 + metadatos
│   │   ├── SAPS_2020_ESEF.zip      # ZIP ESEF (iXBRL)
│   │   └── SAPS_2020_ESEF.zip.meta.json
│   └── ...
├── MANIFEST_BAFIN_YEAR.json        # índice anual sellado
└── ...
```

### Estructura de meta.json
```json
{
  "file_name": "SAPS_2019_ANUAL.pdf",
  "sha256": "abc123...",
  "byte_size": 12345678,
  "retrieved_at_utc": "2026-09-18T20:00:00Z",
  "source_url": "https://...",
  "reporting_year": 2019,
  "ticker": "SAPS",
  "legal_name": "SAP SE",
  "name_common": "SAP SE",
  "lei": "...",
  "hrb_reg": "HRB 719915",
  "segment": "PRIME_STANDARD",
  "index_membership": ["DAX40"],
  "magic_mime_verified": "PDF",
  "validation_reason": "PDF válido (2.1 MB)",
  "download_channel": "CANAL2b_IR_SCRAPER",
  "downloader_version": "3.0.0"
}
```

### Estructura del universo maestro (master_universe_de.json)
```json
{
  "metadata": {},
  "companies": {
    "SAPS": {
      "ticker": "SAPS",
      "name_legal": "SAP SE",
      "name_common": "SAP SE",
      "lei": "529900G3SW56SHYNPR95",
      "hrb_reg": "HRB 719915",
      "segment": "PRIME_STANDARD",
      "index_membership": ["DAX40"]
    },
    ...  // 1.011 entradas total
  }
}
```

---

## 6. REGLAS OPERACIONALES (CRÍTICAS)

### Reglas de negocio
1. **Ventana HGB §325**: Los estados financieros del año N se depositan en el Bundesanzeiger en N+1 o N+2
2. **Spin-offs** — no descargar antes del año de constitución:
   - ENR (Siemens Energy): desde 2020
   - DTG / DMLR (Daimler Truck): desde 2021
   - P911 / PORS (Porsche AG): desde 2022
   - SHL / SHLG (Siemens Healthineers): desde 2018
   - SAR / SART (Sartorius AG separado): desde 2021
   - ZAL / ZALN (Zalando): desde 2014
3. **Cache inmutable**: Si `sha256_file(path) == meta.sha256` → cache_hit, NO re-descargar

### Reglas técnicas del motor
4. **MIME verification**: `content[:4] == b'%PDF'` para PDFs, `b'PK'` para ZIPs
5. **Mínimo de tamaño**: PDFs < 5.000 bytes se rechazan automáticamente
6. **Bundesanzeiger Wicket**: NUNCA `page.go_back()` — usar `context.new_page()` para cada publicación
7. **Rate limiting**: 1,2 segundos entre peticiones (httpx), 2,4 segundos en Canal 4 (DuckDuckGo)
8. **Boilerplate detection**: Hash SHA-256 de páginas de error conocidas en BOILERPLATE_HASHES

---

## 7. COMANDOS DE REFERENCIA RÁPIDA

```bash
# Auditoría completa del data lake
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --audit

# Regenerar manifiestos anuales
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --manifest-only --years 2012-2025

# Dry-run de un ticker específico
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --tickers SAPS --years 2019 --dry-run

# Descarga real de un ticker
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --tickers SAPS --years 2012-2019

# Descarga con Bundesanzeiger manual (CAPTCHA)
python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --tickers SAPS --years 2012 --skip-canal 1,2,4 --bafin-manual

# Verificar qué años faltan para un ticker
python -c "
import json
from pathlib import Path
tk = 'SAPS'
root = Path('D:/ARGOS_DATA/raw/DE_BAFIN')
for y in range(2012, 2026):
    files = list((root / str(y)).rglob(tk + '*')) if (root / str(y)).exists() else []
    status = 'OK' if files else 'FALTA'
    print(f'{y}: {status} ({len(files)} archivos)')
"
```

---

## 8. PRIORIDAD DE EJECUCIÓN RECOMENDADA

| Orden | Lote | Empresas | Años | Canal | Estado |
|-------|------|----------|------|-------|--------|
| 1 | Lote 1 IR primarias | 20 | 2012-2019 | 2 IR | ✅ COMPLETADO (+14 PDFs) |
| 2 | Lote 2 IR ampliadas | 19 | 2012-2019 | 2 IR | ⏳ PENDIENTE / LISTO |
| 3 | Lote 7 ESEF huecos | ~708 | 2020-2022 | 1 ESEF | ⏳ PENDIENTE |
| 4 | Lote 8 recientes | 1.011 | 2023-2026 | 1+2 | ⏳ PENDIENTE |
| 5 | Lote 3 PRIME sin IR | ~133 | 2012-2019 | 4+3 | ⏳ PENDIENTE |
| 6 | Lote 4 GENERAL | 376 | 2012-2019 | 3+4 | ⏳ PENDIENTE |
| 7 | Lote 5 FREIVERKEHR | 396 | 2012-2019 | 3+4 | ⏳ PENDIENTE |
| 8 | Lote 6 SCALE | 67 | 2012-2019 | 3+4 | ⏳ PENDIENTE |

**Cobertura estimada alcanzable solo con Canal 2 IR (Lotes 1+2):**
~39 empresas × 8 años = ~312 documentos adicionales

**Cobertura total con Canal 3 Bundesanzeiger (Lotes 3-6):**
~972 empresas × 8 años = ~7.776 documentos (requiere sesiones asistidas)

---

## 9. DEPENDENCIAS Y ENTORNO

```bash
# Instalar dependencias
pip install httpx beautifulsoup4 lxml playwright
playwright install chromium

# Variables de entorno opcionales
export ARGOS_DATA_ROOT=D:/ARGOS_DATA  # sobreescribe detección automática

# Estructura de rutas detectadas automáticamente (en orden de prioridad)
# 1. $ARGOS_DATA_ROOT/raw/DE_BAFIN
# 2. /opt/argos_data/raw/DE_BAFIN         (Docker OpenHands)
# 3. D:/ARGOS_DATA/raw/DE_BAFIN           (Windows host)
# 4. ARGOS_DATA_DISK/raw/DE_BAFIN         (volumen Docker mapeado)
# 5. ARGOS_MOTOR/data/raw/DE_BAFIN        (fallback relativo)
```

---

## 10. ESTADO DE MANIFIESTOS (post-fix BUG3)

| Año | Entradas | OK (sha256) | Missing | Spinoff | Fuente |
|-----|----------|-------------|---------|---------|--------|
| 2012 | 6 | 5 | 0 | 1 | meta.json |
| 2013 | 3 | 2 | 0 | 1 | meta.json |
| 2014 | 3 | 2 | 0 | 1 | meta.json |
| 2015 | 3 | 2 | 0 | 1 | meta.json |
| 2016 | 3 | 2 | 0 | 1 | meta.json |
| 2017 | 3 | 2 | 0 | 1 | meta.json |
| 2018 | 4 | 3 | 0 | 1 | meta.json |
| 2019 | 19 | 3 | 0 | 1 | meta.json |
| 2020 | 280 | 265 | 0 | 0 | meta.json (ESEF ZIPs) |
| 2021 | 50 | 35 | 0 | 0 | meta.json (ESEF ZIPs) |
| 2022 | 18 | 3 | 0 | 0 | meta.json |
| 2023 | 14 | 0 | 0 | 0 | meta.json (HTMLs) |
| 2024 | 15 | 0 | 0 | 0 | meta.json (HTMLs) |
| 2025 | 14 | 0 | 0 | 0 | meta.json (HTMLs) |

*Nota: Los manifiestos crecerán a medida que se completen los lotes de descarga.*

---

## 11. ARCHIVOS CLAVE DEL PROYECTO

| Archivo | Propósito |
|---------|-----------|
| `ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py` | Motor principal v3.0.0 |
| `ARGOS_MOTOR/config/master_universe_de.json` | Universo 1.011 empresas |
| `ARGOS_MOTOR/descarga/de_germany/audit_download_de.py` | Script de auditoría legacy |
| `ARGOS_MOTOR/descarga/de_germany/PROMPT_OPENHANDS_V3.md` | Prompt para OpenHands v3 |
| `ARGOS_MOTOR/descarga/de_germany/OPENHANDS_GEMINI_PLAN.md` | Plan arquitectura multicanal |
| `D:/ARGOS_DATA/raw/DE_BAFIN/MANIFEST_BAFIN_{year}.json` | Manifiestos anuales sellados |

---

*Documento generado automáticamente por ARGOS MOTOR v3.0.0 — 2026-09-18 22:50*
*Repositorio: https://github.com/jfulgen94-jpg/Argos-motor*
