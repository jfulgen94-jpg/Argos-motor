# PROMPT MAESTRO PARA OPENHANDS (SESIÓN v3.1 -- GEMINI 2.5 PRO)
## Proyecto: ARGOS MOTOR -- Motor Unificado Alemania v3.1 (Correcciones Inmediatas del Motor)

Eres el Ingeniero Principal de Infraestructura de Datos Financieros de STATER Financial Technologies.
Tu misión es aplicar cuatro (4) correcciones técnicas críticas e inmediatas sobre el motor institucional de Alemania:
`ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py`

---

### 1. MAPA DEL ENTORNO Y RUTAS (DOCKER / LOCAL)

- **Entorno Docker OpenHands:**
  - Workspace: `/opt/workspace_base/`
  - Data Lake Canónico: `/opt/argos_data/raw/DE_BAFIN/` (montado en `D:/ARGOS_DATA/raw/DE_BAFIN`)
  - Python Environment: Python 3.12 / 3.13 con `httpx`, `beautifulsoup4`, `lxml` y `playwright` disponibles.
- **Estado Actual del Data Lake (INMUTABLE, PRESERVAR):**
  - 303 paquetes ZIP ESEF (2020-2022).
  - 42 PDFs anuales auditados (2012-2019).
  - 5 HTMLs interactivos (2023-2025).
  - Manifiestos `MANIFEST_BAFIN_{YEAR}.json`.

---

### 2. ARCHIVOS INVOLUCRADOS Y TRANSFORMACIONES

1. **`ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py`** (Archivo principal a modificar):
   - Corrección 1: Canal 1 (ESEF) — Reparar schema del índice y cachear `filings.xbrl.org/index.json`.
   - Corrección 2: Caché Local — Normalizar detección de metadatos (`{fname}.meta.json` y `{prefix}.meta.json`).
   - Corrección 3: Canal 4 (Web) — Eliminar variable global `DDG_DISABLED` y añadir reintentos resilientes.
   - Corrección 4: Evaluador de `dry-run` — Reconocer y propagar hits de dry-run sin marcarlos como `missing`.
2. **`scratch/xbrl_index_de.json`** (Archivo de caché persistente de red):
   - Almacenará el índice JSON descargado de `https://filings.xbrl.org/index.json` con TTL para evitar re-descargas masivas.

---

### 3. ESPECIFICACIÓN DETALLADA DE LAS 4 CORRECCIONES EN `downloader_germany_v3.py`

#### TAREA 1: Reparar Schema y Cachear `filings.xbrl.org` (Canal 1)
- **Problema actual:** El código asume que `index.json` es una lista o contiene `{"filings": [...]}`. En realidad es un diccionario donde cada clave es un LEI: `{"52990013XU4D9J44C520": {"filings": {...}}}`. `idx.get('filings', [])` retorna siempre `[]`, anulando el canal. Además, descarga el archivo de 20 MB en cada empresa/año.
- **Implementación requerida:**
  1. Crear una función de carga y caché `get_xbrl_index(client)`:
     - Comprobar si `_XBRL_INDEX_CACHE` ya está en memoria. Si no, verificar si existe `scratch/xbrl_index_de.json` y tiene menos de 24 horas.
     - Si no está disponible localmente, descargarlo una sola vez desde `https://filings.xbrl.org/index.json` y guardarlo en disco y memoria.
  2. En `channel1_esef(company, year, comp_dir, dry_run)`:
     - Obtener `lei = company.get('lei', '')`. Si no hay LEI, retornar `None`.
     - Acceder directamente por clave: `entity = idx.get(lei)`.
     - Si `entity` existe, iterar sobre `entity.get('filings', {}).items()`:
       * Extraer `filing_key` (ej. `52990013XU4D9J44C520/2020-12-31/ESEF/DE/0`).
       * Extraer la fecha: `filing_data.get('date', '')` o del segundo segmento del `filing_key`.
       * Si `date[:4] == str(year)`:
         * Obtener `pkg = filing_data.get('report-package', '')`.
         * Si existe `pkg`: la URL canónica es `f"https://filings.xbrl.org/{filing_key}/{pkg}"`.
         * Si `dry_run`: retornar `f"DRY_RUN:ESEF:{zip_url}"`.
         * Descargar mediante `client.get(zip_url, timeout=60)` y sellar con `seal_document()`.

#### TAREA 2: Normalizar la Comprobación de Caché Local (`check_local_cache`)
- **Problema actual:** Los archivos en disco tienen `.meta.json` de dos formas:
  - Formato tradicional: `BEFE_2_2020_ESEF.meta.json`
  - Formato nuevo: `AIRB_2018_ANUAL.pdf.meta.json`
  `check_local_cache()` busca exclusivamente `{fname}.meta.json`, lo que genera un `None` (miss) en todos los archivos del formato tradicional.
- **Implementación requerida:**
  - En `check_local_cache(comp_dir, ticker, year)`:
    Para cada extensión `ext` en `['.pdf', '.zip', '.html', '.xhtml', '.htm']` y cada `suffix` en `['_ANUAL', '_ESEF']`:
    * Candidato payload: `fpath = comp_dir / f"{ticker}_{year}{suffix}{ext}"`
    * Candidatos de metadata:
      1. `comp_dir / f"{ticker}_{year}{suffix}{ext}.meta.json"`
      2. `comp_dir / f"{ticker}_{year}{suffix}.meta.json"`
    * Si `fpath.exists()` y cualquiera de las dos rutas de metadata existe:
      - Validar que `actual_hash == stored_hash`.
      - Si coincide, retornar `{'status': 'cache_hit', 'file': str(fpath), 'sha256': actual_hash}`.

#### TAREA 3: Eliminar Desconexión Global `DDG_DISABLED` en Canal 4
- **Problema actual:** Al primer timeout de conexión, `DDG_DISABLED = True` apaga de forma irreversible el Canal 4 para todas las empresas de la sesión.
- **Implementación requerida:**
  - Eliminar la variable global `DDG_DISABLED`.
  - Reemplazar por un mecanismo local con reintentos (máximo 2), retardo de cortesía (`time.sleep(RATE_LIMIT_DELAY)`), y fallback alternativo entre:
    * `https://html.duckduckgo.com/html/?q=...`
    * `https://lite.duckduckgo.com/lite/?q=...`
  - Si una búsqueda falla para una empresa en particular, capturar la excepción, loguear un aviso puntual y permitir que las siguientes empresas continúen usando el Canal 4 normalmente.

#### TAREA 4: Corregir el Evaluador de `dry-run` en `process_company_year`
- **Problema actual:** En las líneas 771, 777, 783, 789:
  `if result and not str(result).startswith('DRY_RUN'):`
  hace que en modo dry-run se ignoren todos los aciertos de canales y caiga al bloque final que imprime:
  `[X] DRY_RUN_CHECKED: {ticker} {year} -- sin fuente encontrada`
- **Implementación requerida:**
  - Modificar las comprobaciones de canal en `process_company_year()` para que:
    ```python
    if result:
        if dry_run and str(result).startswith('DRY_RUN'):
            channel_name = str(result).split(':')[1] if ':' in str(result) else 'DRY_RUN'
            print(f"  [DRY-RUN HIT] {ticker} {year} detectado via {channel_name}: {result}")
            return {**result_base, 'status': 'dry_run_hit', 'channel': channel_name, 'file': str(result)}
        elif not str(result).startswith('DRY_RUN'):
            return {**result_base, 'status': 'downloaded', 'channel': channel_tag, 'file': result}
    ```

---

### 4. PROTOCOLO DE VERIFICACIÓN POST-IMPLEMENTACIÓN

1. **Compilación y sintaxis:**
   ```bash
   python -m py_compile ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py
   ```

2. **Validación de Caché Normalizada (Debe detectar los 303 ESEF preexistentes):**
   ```bash
   python -c "from pathlib import Path; import sys; sys.path.insert(0, 'ARGOS_MOTOR/descarga/de_germany'); from downloader_germany_v3 import check_local_cache, resolve_data_root; root = resolve_data_root(); print('Test cache 2020 BEFE_2:', check_local_cache(root / '2020' / '222100VXGA8L6J4ZWG61_BEFE_2', 'BEFE_2', 2020))"
   ```
   *Resultado esperado:* `status: cache_hit` (no `None`).

3. **Prueba Dry-Run de Canal 1 (ESEF 2020 con nuevo schema):**
   ```bash
   python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --tickers SAPS --years 2020 --dry-run
   ```
   *Resultado esperado:* Detección exitosa del filing ESEF desde el índice XBRL sin descargar payload.

4. **Prueba Dry-Run Multicanal corregida:**
   ```bash
   python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --tickers ADID,SAPS --years 2018-2020 --dry-run
   ```
   *Resultado esperado:* `dry_run_hit` o `cache_hit` sin marcar falsos `missing`.

5. **Auditoría final de integridad del Data Lake:**
   ```bash
   python ARGOS_MOTOR/descarga/de_germany/downloader_germany_v3.py --audit
   ```
