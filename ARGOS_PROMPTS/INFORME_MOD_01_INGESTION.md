# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_01_INGESTION
**Módulo:** Ingestor Transatlántico Multi-Regulador (SEC EDGAR + 5 OAMs Europeos)  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_01_ingestion`  
**Estado:** Implementado con arquitectura de conectores modulares, sellado criptográfico y enrutador.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_01_ingestion/
├── README.md                      (Documentación de arquitectura y tabla de reguladores)
├── src/
│   ├── __init__.py                (Exports de EdgarClient, OAMRouter, ESEFClient, CNMV, AMF, BaFin, CONSOB, AFM)
│   ├── edgar_client.py            (Cliente HTTP para SEC EDGAR con rate-limiting y CIK caching)
│   ├── oam_router.py              (Enrutador dinámico que resuelve el cliente por código de país)
│   ├── esef_client.py             (Cliente base ESEF con soporte de descarga asíncrona)
│   ├── es_cnmv_client.py          (Conector especializado para CNMV España / BME)
│   ├── fr_amf_client.py           (Conector especializado para AMF Francia / Euronext Paris)
│   ├── de_bafin_client.py         (Conector especializado para BaFin Alemania / Xetra)
│   ├── it_consob_client.py        (Conector especializado para CONSOB Italia / Borsa Italiana)
│   ├── nl_afm_client.py           (Conector especializado para AFM Países Bajos / Euronext Amsterdam)
│   ├── sha256_sealer.py           (Sellador criptográfico SHA-256 en bloques de 64 KB)
│   └── storage_uploader.py        (Uploader para persistencia de artefactos raw a disco local)
└── tests/
    ├── __init__.py
    ├── test_edgar_client.py       (Pruebas de inicialización, headers SEC y rate-limiting)
    ├── test_esef_countries.py     (Pruebas del enrutador OAM y formatos canónicos de doc_id)
    └── test_sha256_sealer.py      (Prueba de determinismo criptográfico SHA-256)
```

---

## 2. CLASES, MÉTODOS Y FIRMAS IMPLEMENTADAS EN CÓDIGO

### A. `EdgarClient` (`src/edgar_client.py`)
- **Propósito:** Descarga de submissions, metadatos y documentos 10-K / 10-Q de SEC EDGAR.
- **Atributos:**
  - `user_agent`: Configurado según la política obligatoria de la SEC (`"STATER Transatlantic Financial Engine/1.0 (dev@stater.es)"`).
  - `download_dir`: `Path("data/raw/SEC_EDGAR")`.
  - `rate_limit_delay`: `0.11` segundos (respeta el límite estricto de 10 peticiones/segundo de la SEC).
  - `_cik_cache`: Diccionario en memoria `dict[str, str]` para mapear Ticker → CIK sin llamadas redundantes.
- **Métodos Implementados:**
  - `get_cik(ticker: str) -> Optional[str]`: Descarga `company_tickers.json` de la SEC y resuelve el CIK con padding de 10 dígitos (ej. `0000320193` para AAPL).
  - `get_submissions(cik: str) -> Optional[Dict[str, Any]]`: Consulta `data.sec.gov/submissions/CIK{cik}.json` y extrae los metadatos de los filings recientes.
  - `download_filing(accession_number: str, primary_doc: str, cik: str, ticker: str, fiscal_year: int, form_type: str = "10-K") -> Dict[str, Any]`: Descarga el archivo de SEC Archives, lo guarda en `data/raw/SEC_EDGAR/{year}/{ticker}/`, genera su hash SHA-256 y devuelve el diccionario de metadatos listo para `documents_raw`.

### B. `OAMRouter` (`src/oam_router.py`)
- **Propósito:** Resolver dinámicamente la instancia del cliente regulador adecuado según el código de país.
- **Métodos Implementados:**
  - `get_client(country_code: str)`: Devuelve la instancia correspondiente:
    - `"ES"` → `CNMVClient`
    - `"FR"` → `AMFClient`
    - `"DE"` → `BaFinClient`
    - `"IT"` → `CONSOBClient`
    - `"NL"` → `AFMClient`
  - `list_supported_countries() -> list[str]`: Devuelve `["ES", "FR", "DE", "IT", "NL"]`.

### C. Conectores OAM Nacionales (`es_cnmv_client.py`, `fr_amf_client.py`, `de_bafin_client.py`, `it_consob_client.py`, `nl_afm_client.py`)
Todos comparten una interfaz uniforme:
- **Atributos:** `COUNTRY_CODE`, `REGULATOR_NAME`, `BASE_URL`, `download_dir` (`data/raw/{COUNTRY}_{REGULATOR}`).
- **Métodos Implementados:**
  - `build_doc_id(entity_lei: str, fiscal_year: int, doc_type: str = "ESEF") -> str`: Construye identificadores únicos canónicos (ej. `ES_CNMV_95980020140005534125_2024_ESEF`).
  - `download_filing(download_url: str, entity_lei: str, fiscal_year: int, ticker: Optional[str] = None, company_name: Optional[str] = None, doc_type: str = "ESEF") -> Dict[str, Any]`: Descarga vía stream con `httpx` (timeout 120s), guarda en disco, ejecuta `seal_file()` y devuelve el registro estructurado.

### D. `sha256_sealer.py`
- `seal_file(file_path: Path) -> str`: Lee archivos en chunks de 65.536 bytes (64 KB) con `hashlib.sha256()` para no desbordar memoria con archivos de cientos de megabytes.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_edgar_client_initialization`: Valida creación de directorios y headers de la SEC.
- `test_edgar_client_rate_limit`: Mide el tiempo de espera entre requests consecutivas (>0.1s).
- `test_oam_router_resolution`: Valida que cada código de país instancie la clase reguladora correcta y lance `ValueError` en países no soportados.
- `test_es_cnmv_doc_id_format`, `test_fr_amf_doc_id_format`, etc.: Verifican el cumplimiento del formato canónico del identificador.
- `test_sha256_seal_is_deterministic`: Comprueba que dos llamadas sobre el mismo archivo produzcan el mismo hash exacto y detecta mutaciones.

---

## 4. ANÁLISIS DE CAPACIDADES REALES Y GAPS ACTUALES

### Lo que SÍ está creado y funciona:
1. Toda la lógica de conexión HTTP con streaming, timeouts y headers institucionales.
2. El enrutador OAM y el sistema determinista de nombrado y hashing SHA-256.
3. El cliente EDGAR completo con resolución CIK y rate-limiting automático.

### Gaps / Pendientes para producción:
1. **Scraping / Búsqueda en OAMs Europeos:** Los clientes europeos tienen implementado el método `download_filing(download_url=...)` cuando se les proporciona la URL directa del paquete ESEF ZIP, pero la búsqueda automática por LEI/ISIN en los buscadores web de CNMV/AMF/BaFin requiere un módulo de búsqueda previa o ingesta desde el feed ESEF centralizado de XBRL International / ESMA.
