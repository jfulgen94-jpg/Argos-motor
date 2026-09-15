# PROMPT MAESTRO PARA OPENHANDS (GEMINI 2.5 / 2.0 PRO)
## Módulo: ARGOS MOTOR — Adquisición Histórica Exclusiva Canal B (Alemania 2012–2019)
**Objetivo:** Desarrollar y ejecutar un script aislado y altamente resiliente (`download_canal_b_historico.py`) enfocado exclusivamente en completar las cuentas anuales auditadas de las 1.011 sociedades del universo alemán (`master_universe_de.json`) para los ejercicios 2012 a 2019 a través del Canal B (*Bundesanzeiger Área 22* y *Unternehmensregister*).

---

### INSTRUCCIÓN MAESTRA PARA OPENHANDS:

Copia y pega íntegramente el siguiente bloque en tu sesión de OpenHands:

```markdown
Eres un Ingeniero Senior de Infraestructura Financiera y Data Scraping en STATER Financial Technologies. 
Tu misión es construir y desplegar `ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py` para completar la adquisición histórica (2012 a 2019) de las 1.011 empresas cotizadas del universo alemán (`ARGOS_MOTOR/config/master_universe_de.json`).

### 1. CONTEXTO CRÍTICO Y LECCIONES APRENDIDAS (INCIDENCIAS PREVIAS)
1. **El Canal A (ESEF 2020–2022) YA ESTÁ COMPLETADO:** Existen 306 informes (.zip ESEF) verificados y sellados en `D:/ARGOS_DATA/raw/DE_BAFIN`. NO los toques ni los re-descargues.
2. **Inexistencia de ESEF antes de 2020:** Entre 2012 y 2019 NO existía ESEF. Todas las empresas publicaban en PDF o HTML bajo el Área 22 del Bundesanzeiger y Unternehmensregister (§ 325 HGB).
3. **Peligro del Cascarón Next.js de Unternehmensregister (CRÍTICO):**
   - Una versión anterior descargó 235 archivos de 579 KB con hash `3f418fa1...`. Eran plantillas web vacías de una Single Page Application (Next.js), NO balances reales.
   - REGLA DE ORO: Si un archivo descargado tiene tamaño ~579 KB o hash `3f418fa15253013f4dc73620d471cb567e0f2e1b46f7981c71ffff427ff6ff6b`, o si es HTML y NO contiene los términos clave contables (`Bilanz` o `Jahresabschluss` o `Konzernabschluss`) y el nombre de la empresa, DEBE SER RECHAZADO (`rejected_boilerplate`).
4. **Protección Anti-Bot y Ventana de Enfriamiento:**
   - Los servidores del Bundesanzeiger Verlag (`128.65.211.50` y `128.65.211.86`) bloquean las IPs que envían peticiones masivas concurrentes mediante descarte de paquetes TCP SYN (`ConnectTimeout`).
   - El script debe implementar:
     a) **Timeouts de conexión estrictos:** `httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)`.
     b) **Disyuntor Automático (Circuit Breaker):** Si saltan 2 `ConnectTimeout` consecutivos, activar una pausa de 60 segundos antes de reintentar para no saturar ni prolongar el bloqueo.
     c) **Throttling Humano con Jitter:** Pausa aleatoria de entre 3.0 y 5.5 segundos entre empresas (`time.sleep(random.uniform(3.0, 5.5))`).
     d) **Soporte nativo de Proxy / VPN:** El script debe aceptar el argumento `--proxy` (ej. `--proxy http://127.0.0.1:8080`) o variable de entorno `HTTPS_PROXY` para rotar IP si la IP principal está penalizada.

---

### 2. ESPECIFICACIÓN TÉCNICA DE `download_canal_b_historico.py`

#### A. Entradas y Argumentos CLI:
- `--years`: Lista de ejercicios a procesar (por defecto: `2012,2013,2014,2015,2016,2017,2018,2019`).
- `--tickers`: Filtro opcional por tickers (ej. `--tickers SAP,BMW,ALV`).
- `--segment`: Filtro opcional por segmento (ej. `--segment DAX40`).
- `--proxy`: URL de proxy HTTP/HTTPS opcional para evasión de bloqueos.
- `--delay-min` y `--delay-max`: Rango de jitter humano (defecto: 3.0 a 5.0 s).

#### B. Destino Canónico y Nomenclatura:
- Ruta base: `D:/ARGOS_DATA/raw/DE_BAFIN/{year}/{tax_id}_{ticker}/`
  (Fallback si D: no existe: `ARGOS_MOTOR/data/raw/DE_BAFIN/{year}/{tax_id}_{ticker}/`).
- Nombre del fichero: `{ticker}_{year}_ANUAL.pdf` (si es PDF) o `{ticker}_{year}_ANUAL.html` (si es HTML/XHTML oficial).
- Metadatos obligatorios `{ticker}_{year}_ANUAL.meta.json`:
  ```json
  {
    "file_name": "SAP_2015_ANUAL.pdf",
    "sha256": "abcdef...",
    "byte_size": 1234567,
    "retrieved_at_utc": "2026-09-15T22:00:00Z",
    "source_url": "https://...",
    "reporting_year": 2015,
    "ticker": "SAP",
    "legal_name": "SAP SE",
    "lei": "52990058679Y78EYFG76",
    "hrb_reg": "HRB 719915",
    "segment": "DAX40",
    "magic_mime_verified": "PDF"
  }
  ```
- Manifiesto Anual de Cierre: `D:/ARGOS_DATA/raw/DE_BAFIN/MANIFEST_BAFIN_{year}.json`.

#### C. Lógica de Adquisición Canal B (Dos Vías):
1. **Vía B.1: Bundesanzeiger Área 22 (Rechnungslegung / Finanzberichte)**
   - Iniciar sesión en `https://www.bundesanzeiger.de/pub/de/start`.
   - Realizar búsqueda con `fulltext = "{clean_name} {year}"` y `area_select = "22"`.
   - Parsear enlaces de resultados que contengan `search~table~row~panel-publication~link`.
   - Filtrar publicaciones cuyo texto contenga el año `{year}` y alguna de las palabras clave: `jahresabschluss`, `konzernabschluss`, `jahresfinanzbericht`, `finanzbericht`, `geschäftsbericht`.
   - Si se encuentra enlace a PDF directo o página de informe oficial completa: descargar y verificar Magic Bytes (`%PDF-` o `<!DOCTYPE` / `<html`).
2. **Vía B.2: Unternehmensregister Fallback**
   - Obtener token vía `https://www.unternehmensregister.de/api/search-token`.
   - Buscar con ventana temporal `{year}-01-01` a `{year+1}-12-31` y `formType=ACCOUNTING`.
   - Parsear únicamente publicaciones con enlace directo a PDF o documentos con contenido contable real verificado.

#### D. Validación Criptográfica y Filtro Anti-Boilerplate:
- Calcular SHA-256 en memoria o en staging.
- Si SHA-256 coincide con cascarones conocidos de Next.js (`3f418fa1...` o `2ac7a66b...`) -> DESCARTAR y NO guardar.
- Si es HTML: verificar que `len(html) > 5000` y que contenga (`Bilanz` o `Konzernabschluss` o `Jahresabschluss`).
- Solo tras superar la validación, mover a la carpeta canónica, calcular hash final y escribir `.meta.json`.

---

### 3. PROTOCOLO DE DESPLIEGUE Y VERIFICACIÓN AUTÓNOMA
1. Crea el archivo `ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py`.
2. Prueba primero la conectividad y realiza un test unitario con 1 sola empresa para verificar que no salte bloqueo:
   `python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --tickers SAP --years 2015`
3. Si la conexión responde (o usando `--proxy`), procede a ejecutar la fase piloto de las empresas del DAX40 (2012–2019):
   `python ARGOS_MOTOR/descarga/de_germany/download_canal_b_historico.py --segment DAX40 --years 2012,2013,2014,2015,2016,2017,2018,2019`
4. Al finalizar, audita los hashes en `D:/ARGOS_DATA/raw/DE_BAFIN` para confirmar que el 100% de los archivos descargados son legítimos y no contienen hashes duplicados vacíos.
```
