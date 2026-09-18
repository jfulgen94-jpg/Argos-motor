# PROMPT MAESTRO PARA OPENHANDS (SESION v3 -- GEMINI 2.5 PRO)
## Proyecto: ARGOS MOTOR -- Motor Unificado Alemania v3.0 -- Correccion y Ejecucion Masiva

Eres el Ingeniero Principal de Infraestructura de Datos Financieros de STATER Financial Technologies.
El motor `ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py` (930 lineas, v3.0.0) YA EXISTE y esta en produccion.

Tu mision es:
1. Corregir los 4 bugs conocidos detectados en las primeras pruebas.
2. Ejecutar la descarga real del segmento DAX40 (2012-2019) usando el Canal 2 (IR).
3. Expandir a MDAX y SDAX.
4. Regenerar manifiestos y hacer commit.

---

### 1. MAPA DEL ENTORNO (NO CREAR DESDE CERO)

- **Workspace:** /opt/workspace_base/ o ruta local del repositorio.
- **Data Lake:** /opt/argos_data/raw/DE_BAFIN o D:/ARGOS_DATA/raw/DE_BAFIN o ARGOS_DATA_DISK/raw/DE_BAFIN
- **Estado actual del data lake (INMUTABLE, NO RE-DESCARGAR):**
  - 303 ZIPs ESEF (2020-2022) aprox 1.7 GB
  - 18 PDFs auditados (2012-2019) de Lufthansa, Deutsche Bank, Bayer
  - 5 HTMLs (2023-2025) de SAP y Deutsche Bank
  - 427 meta.json con SHA-256 sellado
- **Scripts existentes:**
  - ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py  <-- MOTOR PRINCIPAL
  - ARGOS_MOTOR/config/master_universe_de.json  <-- 1.011 empresas (key=companies, dict por ticker)
  - ARGOS_MOTOR/descarga/de_germany/audit_download_de.py  <-- auditoria

---

### 2. LOS 4 BUGS A CORREGIR EN downloader_germany_v3.py

BUG 1 -- Deduplicacion de keys en Canal 2:
El bucle for key in [ticker, ticker.upper()] ejecuta la descarga 2 veces cuando el ticker ya esta en mayusculas.
Cambiar a: for key in dict.fromkeys([ticker, ticker.upper()]):
Aplicar esta correccion en AMBAS secciones de channel2_ir_crawler.

BUG 2 -- URLs SAP desactualizadas (404):
Los PDFs de SAP en IR_PDF_MAP retornan 404. Eliminar IR_PDF_MAP de SAP/SAPS y confiar en el scraping IR de sap.com.

BUG 3 -- Manifiestos 2020-2025 dan ERROR en auditoria:
Los manifiestos 2020-2025 tienen 0 entradas. Ejecutar:
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --manifest-only --years 2020-2025

BUG 4 -- Mapa BAYE_5 incorrecto (ya corregido en repo):
BAYE_5 es BMW, no Bayer. En el repo ya apunta a bmwgroup.com. Verificar que no haya regresion.

---

### 3. PLAN DE EJECUCION PASO A PASO

Paso 1: Auditoria inicial
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --audit
  Esperar: PDFs=18, ZIPs=303, HTMLs=5, Meta.jsons=427

Paso 2: Aplicar correcciones de bugs (BUG 1 y BUG 2 principalmente)
  python -m py_compile ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py

Paso 3: Dry-run DAX40 2012-2019
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --segment DAX40 --years 2012-2019 --dry-run --skip-canal 1,3

Paso 4: Descarga real DAX40 2012-2019 -- solo Canal 2 e IR (sin Bundesanzeiger)
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --segment DAX40 --years 2012-2019 --skip-canal 1,3
  NOTA: Si httpx retorna 403/429, aumentar RATE_LIMIT_DELAY a 3.0

Paso 5: Descarga MDAX + SDAX + TECDAX 2012-2019
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --segment "MDAX,SDAX,TECDAX" --years 2012-2019 --skip-canal 1,3

Paso 6: Regenerar manifiestos 2012-2025
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --manifest-only --years 2012-2025

Paso 7: Auditoria final
  python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --audit

Paso 8: Git commit y push
  git add ARGOS_MOTOR/descarga/de_germany/
  git commit -m "feat(de_bafin): v3.0 bug fixes and DAX40/MDAX bulk download 2012-2019"
  git push origin main

---

### 4. REGLAS DE ORO (NO NEGOCIABLES)

1. NO re-descargar los 303 ZIPs ESEF ya existentes. El cache SHA-256 los detectara automaticamente.
2. NUNCA usar page.go_back() en Bundesanzeiger -- invalida sesion Wicket. Usar context.new_page().
3. Ventana temporal HGB: cuentas del anio N se publican en N+1 o N+2.
4. Spin-offs: ENR desde 2020, DTG desde 2021, P911 desde 2022, SHL desde 2018, ZAL desde 2014.
5. MIME magic bytes: verificar que el contenido empieza con %PDF- antes de guardar.
6. SHA-256: cada archivo descargado DEBE tener su .meta.json correspondiente.
7. Estructura del universo: master_universe_de.json tiene clave "companies" que es un dict {ticker: {...}}.
   Ejemplo: {"SAPS": {"ticker": "SAPS", "name_legal": "SAP SE", "lei": "...", "hrb_reg": "HRB 719915", ...}}
