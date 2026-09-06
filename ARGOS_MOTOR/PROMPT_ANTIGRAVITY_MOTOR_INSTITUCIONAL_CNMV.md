# PROMPT PARA ANTIGRAVITY — RECONSTRUCCIÓN DEL MOTOR INSTITUCIONAL DE INGESTA
## STATER MOTOR ARGOS — MOD_01_INGESTION — Mercado Español (CNMV/BME) end-to-end

Copia y pega este prompt completo en Antigravity, apuntando al workspace
`c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR`. No lo recortes: cada sección
es una restricción de diseño no negociable, no una sugerencia.

---

## 0. IDENTIDAD Y MISIÓN

Eres el arquitecto e implementador jefe de un **motor de ingesta regulatoria de
nivel institucional** para STATER MOTOR ARGOS, comparable en estándar de
integridad al que usarían Bloomberg, Refinitiv/LSEG, S&P Capital IQ o un
supervisor financiero (CNMV/ESMA) para su propio archivo interno de filings.
No estás construyendo un scraper de conveniencia. Estás construyendo el
**sistema de registro de expedientes regulatorios** sobre el que se apoyarán,
sin excepción, todos los módulos posteriores de parseo contable (MOD_02),
auditoría NLP (MOD_03), datalake (MOD_04) y scoring cuantitativo (MOD_05).
Cualquier dato falso, inventado, sintético o "de relleno" que entre en este
sistema se propaga como una mentira firmada con SHA-256 a todo el resto del
motor. Trátalo con esa gravedad.

## 1. CONTEXTO REAL DEL REPOSITORIO (LEE ANTES DE ESCRIBIR UNA LÍNEA)

Antes de generar código, inspecciona y resume en voz alta lo que encuentras en:

- `mod_01_ingestion/src/` — módulo canónico existente. Contiene ya piezas
  correctas y reutilizables: `models.py` (PublicationRecord, DocumentResource,
  DocumentBundle, BundleStatus, CompletenessStatus — no los reinventes),
  `ingestion_pipeline.py` (orquestador discovery→download→validate→quarantine→
  extract→manifest), `bundle_manager.py` (layout canónico + extracción ZIP +
  cuarentena + manifest.json), `robust_downloader.py` (streaming con
  reanudación por Range, backoff exponencial, verificación SHA-256),
  `document_completeness_validator.py` (validador forense multi-señal),
  `sha256_sealer.py`, `oam_router.py`, `es_cnmv_client.py` (ya tiene un método
  `download_annual_package()` que descarga los 5 documentos reales del
  ejercicio anual dado un manifiesto de URLs — es tu punto de partida, no lo
  descartes).
- `mod_01_ingestion/tests/` — banco de tests existente que debe seguir en
  verde tras tu refactor (`test_cnmv_forensic_ingestion.py`,
  `test_regulatory_ingestion.py`, `test_ingest_runner.py`).
- `config/bluechips_universe.json` — catálogo de empresas con ticker/LEI/nombre
  (incompleto, solo blue chips).
- `data/catalogs/mercado_continuo_universe.json` y
  `data/catalogs/bme_growth_clean_universe.json` — catálogos parciales
  generados por scripts previos, de fiabilidad no verificada.
- **PROBLEMA CRÍTICO A ERRADICAR**: existe un archivo
  `mod_01_ingestion/src/institutional_document_builder.py` que **genera cifras
  financieras sintéticas/inventadas** (fórmulas tipo
  `act_tot = 1_850_000_000 + (year - 2019) * 50_000_000`) envueltas en HTML con
  apariencia de "Dictamen de Auditoría Favorable sin Salvedades" firmado por
  un auditor que nunca existió sobre esa cifra. **Este archivo y todo lo que lo
  invoque (`download_spain_live_batch.py` y similares) debe ser eliminado por
  completo del pipeline de producción.** Puede conservarse, si acaso, como
  generador de *fixtures* de test explícitamente marcado y aislado en
  `tests/fixtures/`, nunca en `src/`, y nunca alcanzable desde ningún runner
  real.
- **PROBLEMA CRÍTICO A CONSOLIDAR**: hay como mínimo 4 implementaciones
  redundantes y no coordinadas de "cliente de descarga CNMV/ESEF"
  (`es_cnmv_client.py`, `cnmv_real_downloader.py`, `raw_landing_downloader.py`
  + `organize_raw_filings.py`, `esef_client.py`) y más de 20 scripts sueltos en
  la raíz de `ARGOS_MOTOR/` (`reorganize_and_clean_all.py`,
  `remedy_2020_coverage.py`, `normalize_folders_and_purge.py`,
  `apply_full_normalization.py`, `audit_2022_duplicates_and_files.py`,
  `resolve_gleif_18.py`, `resolve_all_lei_names.py`,
  `investigate_2025_2026.py`, `verify_final_structure.py`,
  `mod_01_bme_growth_downloader.py`, `mod_01_esef_batch_downloader.py`,
  `mod_01_interim_ipp_downloader.py`, `mod_01_zip_content_validator.py`,
  `prepare_full_bme_growth.py`, `prepare_mercado_continuo_and_growth.py`,
  `generate_universe_breakdown.py`, `organize_and_hash_all_zips.py`,
  `test_cnmv_post.py`, `test_cnmv_ipp.py`, `run_forensic_queue.py`). Tu trabajo
  incluye **auditar cada uno, extraer la única lógica de valor real que
  contengan (mapeos LEI verificados, listas de universo, heurísticas de
  scraping que sí funcionaron), fusionarla dentro del módulo canónico, y
  borrar/archivar el resto**. No se admite un quinto downloader paralelo.

## 2. LEY FUNDAMENTAL — NO NEGOCIABLE

1. **Prohibido fabricar datos financieros.** Ningún número, ninguna cifra de
   balance, ninguna frase de dictamen de auditoría puede generarse
   sintéticamente y guardarse como si fuera un documento oficial. Si no hay
   URL real y verificable del regulador (CNMV, `filings.xbrl.org`/ESMA OAM,
   BME Growth), el documento **no se crea**. Punto.
2. **Prohibido simular éxito.** Si un documento no puede descargarse o no pasa
   validación de identidad/ejercicio/tipología, el sistema debe fallar de
   forma visible (log + cuarentena + métrica), nunca sustituirlo por un
   archivo "parecido" sin dejarlo trazado como sustitución explícita.
3. **Toda sustitución legítima debe declararse como tal.** El único caso
   admitido de "usar datos de otro ejercicio" es la cifra comparativa exigida
   por NIC 1 §38 quejustifica el remedio de 2020. Si se usa, el documento
   resultante debe llevar en su manifiesto un campo
   `"provenance": "COMPARATIVE_EXTRACTED_FROM_FY{N+1}_FILING"` y un flag
   `"is_standalone_original_filing": false`, de modo que ningún consumidor
   aguas abajo pueda confundirlo jamás con un filing propio y original del
   ejercicio.
4. **Fuente única de verdad para identidad de empresa.** Existe un único
   catálogo maestro versionado (`config/master_universe_es.json`) con
   `ticker`, `cif_nif`, `lei` (verificado contra GLEIF), `name_legal`,
   `segment` (IBEX35 / MERCADO_CONTINUO / BME_GROWTH), `is_socimi` (bool),
   `fiscal_year_end` (para casos como Logista, cierre no natural),
   `historical_name_changes` (ej. Red Eléctrica → Redeia, Prosegur Cash,
   fusiones Unicaja/Liberbank). Ningún script puede mantener su propio mapeo
   ticker→LEI hardcodeado por separado.
5. **Todo o nada por documento, nunca carpetas fantasma.** Se prohíbe crear el
   directorio final `data/raw/ES_CNMV/{YEAR}/{TICKER}_{NAME}/` antes de que el
   documento haya sido descargado, verificado por identidad/ejercicio/tipo, y
   sellado con SHA-256. Se descarga primero a
   `data/staging/tmp_download/{run_id}/`.

## 3. ARQUITECTURA OBJETIVO (DOS ETAPAS, GOBERNADA, UN SOLO PIPELINE)

```
CATÁLOGO MAESTRO (config/master_universe_es.json, ~200 empresas verificadas)
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 0 — RESOLUCIÓN DE IDENTIDAD (entity_resolver.py)             │
│  • GLEIF API por LEI/nombre/CIF con score de similitud Jaro-Winkler│
│    + coincidencia exacta de CIF/NIF como criterio de desempate.    │
│  • Rechaza resolución si score < 0.90 y no hay CIF exacto.         │
│  • Cachea SOLO resoluciones con score >= 0.90 (nunca "primer match")│
└───────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 1 — DISCOVERY MULTICANAL (source_router.py)                  │
│  Canal A (2021+): filings.xbrl.org API (ESMA OAM oficial, JSON:API)│
│  Canal B (2019-2020, pre-ESEF): CNMV scraping formulario id=25      │
│  Canal C (BME Growth, ~72 empresas): BME Growth scraping oficial   │
│  Canal D (IAGC/IARC, todos los años): CNMV IPP / GobiernoCorporativo│
│  Selección de canal por (segmento, año) según tabla de cobertura   │
│  regulatoria real, NUNCA por intento-error silencioso.             │
└───────────────────────────────────────────────────────────────────┘
        │  URL candidata + metadata declarada (LEI, año, tipo)
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 2 — DESCARGA A STAGING (RobustDownloader ya existente)       │
│  data/staging/tmp_download/{run_id}/{doc_id}.part                  │
│  Streaming + resumable + backoff + SHA-256 en vuelo                │
└───────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 3 — AI PRE-VALIDATION GUARD (nuevo: ai_pre_validation_guard.py)│
│  1. Identidad: extrae NIF/LEI/razón social de cabecera/dictamen y   │
│     compara contra el catálogo maestro (score >= 0.90 o rechazo).   │
│  2. Ejercicio fiscal: extrae el año certificado del dictamen/       │
│     contexto XBRL; si != año solicitado y no es cifra comparativa   │
│     declarada, rechaza.                                            │
│  3. Tipología: clasifica CCAA_AUDITED / INFORME_GESTION / EINF_CSRD │
│     / IAGC / IARC / OIR / FOLLETO / IPP_INTERMEDIO. Rechaza si no   │
│     coincide con lo solicitado.                                    │
│  4. Umbral físico y estructural (ya existe en                      │
│     branch_threshold_validator.py — intégralo, no lo dupliques).   │
│  Si falla cualquier punto → cuarentena con motivo estructurado,     │
│  NUNCA se mueve a la carpeta final.                                │
└───────────────────────────────────────────────────────────────────┘
        │ (solo válidos)
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 4 — SELLADO Y COMMIT ATÓMICO (bundle_manager.py existente)   │
│  SHA-256 final + manifest.json + extracción segura de ZIP +        │
│  registro DuckDB (documents_raw) + checkpoint idempotente          │
│  data/raw/ES_CNMV/{YEAR}/{TICKER}_{NAME}/...                        │
└───────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ ETAPA 5 — FEEDBACK LOOP ADAPTATIVO (adaptive_feedback_engine.py)   │
│  Vectoriza cada intento (éxito o fallo) con label:                  │
│  SUCCESS_VALID | WRONG_ENTITY | WRONG_YEAR | EMPTY_SKELETON_ASP |   │
│  BLOCKED_ANTIBOT_403 | NOT_FOUND_404 | TRUNCATED_PDF |              │
│  QUARANTINED_SYNTHETIC. Persiste en SQLite/DuckDB propio            │
│  (`mod_01_ingestion/telemetry/ingestion_attempts.duckdb`).          │
│  Ajusta heurísticas de reintento y orden de canal, NUNCA decide     │
│  aceptar un documento por sí sola (el Guard de Etapa 3 es soberano).│
└───────────────────────────────────────────────────────────────────┘
```

## 4. MICRO-SEGMENTACIÓN Y AISLAMIENTO DE FALLO

- Unidad de trabajo atómica = tupla `(ticker, fiscal_year, doc_type)`.
- Ejecutor por lotes de 5-10 empresas, con `ThreadPoolExecutor`/`asyncio`
  acotado (respeta rate limits: `filings.xbrl.org` es público pero no
  ilimitado; CNMV bloquea con 403 agresivamente — implementa *jitter* y
  *backoff* real, no bombardees).
- Checkpoint `.checkpoint.sha256.json` por unidad de trabajo. Reanudable: si
  el proceso se interrumpe, el siguiente run debe saltar automáticamente todo
  lo ya validado y sellado, y retomar exactamente donde quedó.
- Un fallo en `ELE_2020` nunca debe abortar ni ensuciar `IBE_2020`.

## 5. LO QUE DEBES CONSTRUIR, ARCHIVO POR ARCHIVO

Dentro de `mod_01_ingestion/src/` (no crear módulos hermanos nuevos fuera de
esta carpeta salvo que sea estrictamente de configuración/datos):

1. `entity_resolver.py` — resolución de identidad LEI/CIF/nombre contra GLEIF
   con score de similitud y desempate por CIF exacto. Cache persistente en
   `config/master_universe_es.json` (solo entradas con score >= 0.90,
   auditable, con campo `resolved_at` y `resolution_score`).
2. `source_router.py` — decide canal de descarga por (segmento, año, tipo de
   documento) según tabla de cobertura regulatoria real (moratoria COVID 2020,
   BME Growth vs Mercado Continuo, IAGC/IARC siempre vía CNMV IPP).
3. `xbrl_org_client.py` — cliente limpio para `filings.xbrl.org` (Canal A),
   reemplazando la lógica dispersa de `mod_01_esef_batch_downloader.py` y
   `cnmv_real_downloader.py`. Pagina correctamente, resuelve LEI vía
   `relationships.entity`, jamás vía adivinación de nombre de fichero.
4. `cnmv_portal_scraper.py` — Canal B/D, scraping controlado del portal CNMV
   (maneja `__VIEWSTATE` si es imprescindible, o documenta explícitamente por
   qué no es viable y qué alternativa manual/semi-manual se necesita:
   sé honesto si un canal requiere intervención humana, no lo simules).
5. `bme_growth_client.py` — Canal C, consolida
   `mod_01_bme_growth_downloader.py` + `prepare_full_bme_growth.py`.
6. `ai_pre_validation_guard.py` — el validador de identidad/ejercicio/tipología
   descrito en la Etapa 3. Debe **reutilizar y extender**
   `document_completeness_validator.py` y `branch_threshold_validator.py`
   existentes, no reescribir su lógica desde cero.
7. `adaptive_feedback_engine.py` — telemetría y heurística adaptativa de la
   Etapa 5.
8. `master_universe_builder.py` — script de una sola ejecución (no un runner
   productivo) que construye/audita `config/master_universe_es.json` a partir
   de fuentes verificables (GLEIF, BME, CNMV), dejando un informe de
   discrepancias para revisión humana antes de aceptar cambios.
9. Actualiza `ingest_runner.py` para que **todo** pase por
   `ingestion_pipeline.py` + `ai_pre_validation_guard.py`; ningún runner nuevo
   debe reimplementar descarga+guardado a mano.

## 6. LO QUE DEBES ELIMINAR O ARCHIVAR

- Mueve a `archive/legacy_scripts_pre_v3/` (fuera del path de import de
  producción) todos los scripts sueltos de la raíz de `ARGOS_MOTOR/`
  listados en la sección 1, **tras extraer cualquier dato de valor real**
  (mapeos LEI verificados manualmente, listas de universo) hacia
  `config/master_universe_es.json`.
- Elimina completamente `institutional_document_builder.py` del path de
  producción. Si quieres conservar su plantilla HTML como fixture de test,
  muévela a `mod_01_ingestion/tests/fixtures/synthetic_fixture_templates.py`
  con un docstring en mayúsculas: `SOLO PARA TESTS. NUNCA IMPORTAR DESDE src/.`
- Consolida `es_cnmv_client.py`, `cnmv_real_downloader.py`,
  `raw_landing_downloader.py`, `organize_raw_filings.py`, `esef_client.py` en
  la arquitectura de la sección 5. Un único cliente CNMV/ES con canales
  internos, no cinco clientes externos.

## 7. SISTEMA DE DETECCIÓN FORENSE DEL DATASET YA EXISTENTE
### (auditoría retroactiva de lo producido por las implementaciones previas)

Esta sección es distinta de la Etapa 3 (AI Guard) del pipeline en vivo. La
Etapa 3 protege las descargas **futuras**. Esta sección exige un módulo aparte
que **audita lo que ya está en disco**, escrito por al menos tres
implementaciones distintas y no coordinadas que coexistieron en el tiempo:
1. Los runners antiguos de `mod_01_ingestion/src/es_cnmv_client.py` /
   `runner_full_package.py` (versión previa a este refactor, que en algunos
   commits llegó a escribir metadatos sintéticos).
2. `cnmv_real_downloader.py` + `raw_landing_downloader.py` +
   `organize_raw_filings.py` (pipeline paralelo de dos etapas, con su propio
   mapeo LEI hardcodeado y su propio criterio de organización).
3. `institutional_document_builder.py` invocado desde
   `download_spain_live_batch.py` (generador de contenido sintético con
   apariencia de auditoría real).

Estas tres vías escribieron, en momentos distintos y sin coordinación, en la
misma jerarquía `data/raw/ES_CNMV/{YEAR}/{TICKER}_{NAME}/`. El resultado es un
dataset con procedencia mixta y no etiquetada: no puedes saber, mirando un
archivo, cuál de las tres lo generó, ni si es real. Por eso necesitas un
**escáner forense retroactivo**, no solo una guardia hacia adelante.

### 7.1. Módulo: `forensic_dataset_auditor.py`

Construye este módulo en `mod_01_ingestion/src/forensic_dataset_auditor.py`,
ejecutable como script independiente (`python -m
mod_01_ingestion.src.forensic_dataset_auditor --scope ES_CNMV`), con este
algoritmo obligatorio:

1. **Recorrido completo**: camina recursivamente `data/raw/ES_CNMV/` (todos los
   años) y también los restos de `data/raw/landing_raw/` si existen. No te
   fíes de que un archivo "ya fue validado antes": trátalo como si nunca se
   hubiera visto.
2. **Re-sellado y verificación de integridad**: recalcula el SHA-256 de cada
   archivo y compáralo contra el `manifest.json`/`.meta.json` asociado si
   existe. Si no coincide o no existe manifiesto, márcalo
   `UNSEALED_OR_TAMPERED`.
3. **Re-validación forense de contenido**: pasa cada archivo por
   `document_completeness_validator.py` (ya existente) para detectar
   `SYNTHETIC_FIXTURE`, `VIEWER_PAGE`, `ERROR_RESPONSE`, `COVER_PAGE_OR_INDEX`,
   `ZIP_BUNDLE` corrupto, etc. — exactamente las mismas reglas que la Etapa 3,
   reutilizadas sin duplicar código.
4. **Re-verificación de identidad y ejercicio contra el catálogo maestro**:
   usa `entity_resolver.py` (sección 5) para extraer NIF/LEI/razón social del
   contenido real del archivo y compararlo contra la carpeta en la que está
   guardado. Esto es lo que detecta retroactivamente el caso Prosegur: un
   archivo guardado en `ACS_...` cuyo contenido interno certifica
   "Prosegur Compañía de Seguridad, S.A." debe salir marcado
   `WRONG_ENTITY_MISMATCH_WITH_FOLDER`, con ambos nombres (carpeta vs.
   contenido) en el reporte.
5. **Re-verificación del ejercicio fiscal real**: extrae el año certificado del
   dictamen/contexto XBRL y compáralo con el año de la carpeta. Si no coincide
   y no hay un flag `provenance = COMPARATIVE_EXTRACTED_FROM_FY{N+1}_FILING`
   explícito en su manifiesto, márcalo `WRONG_YEAR_UNDECLARED_SUBSTITUTION`
   (este es el caso exacto de `remedy_2020_coverage.py`).
6. **Detección de contenido sintético fabricado**: además de los patrones ya
   existentes en `document_completeness_validator.SYNTHETIC_FIXTURE_PATTERNS`,
   añade huellas específicas del generador conocido
   (`institutional_document_builder.py`): busca literalmente las cadenas de
   sus badges (`"EXPEDIENTE REGULATORIO OFICIAL CNMV / ESEF iXBRL"`,
   fórmulas de importes que sean múltiplos exactos y crecientes año a año con
   el patrón `base + (year-2019)*incremento`, cifras que se repiten idénticas
   proporcionalmente entre distintas empresas). Márcalo `SYNTHETIC_FABRICATED`.
7. **Taxonomía final por archivo** (un único enum, no clasificaciones libres):
   `VALID_ORIGINAL_SEALED | VALID_COMPARATIVE_DECLARED |
   WRONG_ENTITY_MISMATCH_WITH_FOLDER | WRONG_YEAR_UNDECLARED_SUBSTITUTION |
   SYNTHETIC_FABRICATED | EMPTY_SKELETON_OR_VIEWER | TRUNCATED_OR_CORRUPT_ZIP |
   UNSEALED_OR_TAMPERED | DUPLICATE_CONFLICTING_HASH |
   UNRESOLVED_REQUIRES_MANUAL_REVIEW`.
8. **Salida obligatoria**: genera
   `data/raw/ES_CNMV/FORENSIC_AUDIT_REPORT_{YYYYMMDD_HHMMSS}.json` (machine
   readable, un registro por archivo con su taxonomía, ruta, ticker esperado
   vs. detectado, año esperado vs. detectado, sha256 antiguo vs. nuevo) **y**
   un resumen humano `FORENSIC_AUDIT_SUMMARY.md` con tablas de conteo por año,
   por segmento (IBEX35/Continuo/Growth) y por taxonomía — mismo formato de
   tabla que usó el informe forense que ya leímos, para que sea comparable.
9. **Nunca borres nada en esta fase.** Este módulo es de solo lectura sobre
   `data/raw/`; escribe únicamente su propio reporte. El borrado/cuarentena
   real ocurre en la Sección 8.

## 8. REMEDIACIÓN CONCRETA DE LOS ERRORES DE DESCARGA ACTUALES

Con el `FORENSIC_AUDIT_REPORT` de la Sección 7 como entrada, construye
`mod_01_ingestion/src/remediation_runner.py`, que reemplaza para siempre a los
scripts de parche puntual (`remedy_2020_coverage.py`,
`reorganize_and_clean_all.py`, `normalize_folders_and_purge.py`,
`apply_full_normalization.py`, `audit_2022_duplicates_and_files.py`) con una
**capacidad permanente y reutilizable del propio módulo**, no con un script de
usar-y-tirar más.

1. **Cola de remediación persistente**: crea una tabla DuckDB
   `remediation_queue` (`doc_key`, `ticker`, `fiscal_year`, `doc_type`,
   `forensic_classification`, `status` en
   `PENDING|IN_PROGRESS|DONE|FAILED_NEEDS_MANUAL`, `attempts`,
   `last_error`, `resolved_at`). Se puebla automáticamente a partir de todo lo
   clasificado como no válido en la Sección 7.
2. **Enrutado de la remediación por tipo de error** (nunca "borra y ya está"):
   - `WRONG_ENTITY_MISMATCH_WITH_FOLDER` → mueve el archivo contaminante a
     `data/quarantine_forensic_retro/{año}/{ticker_original_carpeta}/`
     conservando su nombre y adjuntando `reason.json` con la entidad real
     detectada; encola una descarga real para `(ticker, year, doc_type)` vía
     el pipeline en vivo (Secciones 3-5), **nunca** copiando de otra carpeta.
   - `WRONG_YEAR_UNDECLARED_SUBSTITUTION` → si el contenido es válido pero mal
     etiquetado (ej. el caso 2021→2020), no lo descartes sin más: re-etiqueta
     su manifiesto con el `provenance` correcto (Sección 2, punto 3) y
     re-clasifícalo como `VALID_COMPARATIVE_DECLARED`; **además** encola en la
     cola de remediación un intento de conseguir el documento standalone real
     de ese año por el Canal B si existe.
   - `SYNTHETIC_FABRICATED` → cuarentena inmediata sin excepción, encola
     descarga real, y registra el evento en `adaptive_feedback_engine.py`
     como caso de máxima severidad (estos archivos no deben poder reaparecer:
     añade su huella a una lista de bloqueo).
   - `EMPTY_SKELETON_OR_VIEWER` / `TRUNCATED_OR_CORRUPT_ZIP` /
     `UNSEALED_OR_TAMPERED` → cuarentena + reintento automático con backoff,
     probando primero el canal que originalmente se usó y, si vuelve a
     fallar, el canal alternativo (`source_router.py`, Sección 3).
   - `DUPLICATE_CONFLICTING_HASH` (mismo `doc_id` con hashes distintos entre
     las tres implementaciones legacy) → aplica el AI Guard (Etapa 3) a cada
     copia en conflicto; conserva la que pase validación completa, cuarentena
     el resto con ambos hashes documentados para trazabilidad.
   - `UNRESOLVED_REQUIRES_MANUAL_REVIEW` → no se auto-remedia; se listan en el
     informe final como intervención humana pendiente, con la razón técnica
     exacta (ej. "portal CNMV devuelve 403 persistente", "LEI sin resolución
     con score >= 0.90 en GLEIF").
3. **Ejecución controlada y reanudable**: `remediation_runner.py` debe poder
   pararse y reanudarse sin reprocesar lo ya marcado `DONE`; cada intento
   fallido incrementa `attempts` y tras un máximo configurable pasa a
   `FAILED_NEEDS_MANUAL` en vez de reintentar indefinidamente.
4. **Informe de cierre obligatorio**
   (`REMEDIATION_REPORT_{YYYYMMDD_HHMMSS}.md`): cuántos documentos se
   corrigieron automáticamente por categoría, cuántos quedaron en cuarentena
   informativa, cuántos requieren intervención manual y por qué motivo técnico
   exacto — nada de "no se pudo" sin causa explícita.

## 9. GESTIÓN DEL CASO 2020 (SIN COPIAR MENTIRAS)

- Vacía y purga las carpetas `vacias/` y `equivocadas/` de 2020 tras extraer
  cualquier aprendizaje útil (qué tickers había, qué LEIs se confundieron) al
  feedback engine como *training data negativo*.
- Para las ~30 empresas que sí presentaron ESEF voluntario en 2020: descarga
  real vía Canal A, validada por el Guard.
- Para el resto del Mercado Continuo en 2020 (moratoria COVID): **no fabricar
  nada**. Dos opciones honestas, en este orden de preferencia:
  a) Descargar el PDF/XBRL tradicional real que sí presentaron ante la CNMV
     para 2020 (Canal B), si existe y es accesible.
  b) Si no es accesible o no existe, generar el documento comparativo
     **declarado como tal** (regla de la sección 2, punto 3) a partir del
     informe 2021, con su `provenance` marcado, y dejarlo en cuarentena
     informativa pendiente de revisión humana antes de darlo por definitivo.
- Nunca marcar (b) como `FINAL_COMPLETO` sin revisión; como máximo
  `PARCIAL_COMPARATIVO_DECLARADO`.

## 10. TESTS Y CRITERIOS DE ACEPTACIÓN

- Todos los tests existentes en `mod_01_ingestion/tests/` deben seguir en
  verde (`python -m pytest -q mod_01_ingestion/tests/`).
- Añade tests nuevos que:
  - Prueben que `entity_resolver` rechaza a Prosegur cuando se busca ACS
    (score bajo) — este es el test de regresión histórico más importante
    del proyecto.
  - Prueben que ningún documento con `completeness_status in
    (SYNTHETIC_FIXTURE, ERROR_RESPONSE, VIEWER_PAGE)` puede llegar jamás a la
    carpeta canónica final.
  - Prueben que un intento con año detectado != año solicitado (y sin
    `provenance` declarado) es rechazado.
  - Prueben idempotencia: correr el mismo lote dos veces no duplica ni
    re-descarga documentos ya sellados.
  - **Prueben `forensic_dataset_auditor.py` sobre un dataset de prueba
    (`tmp_path`) que contenga a propósito: un archivo con entidad equivocada
    (caso Prosegur), un archivo `_comparativo` de otro ejercicio sin
    `provenance` declarado, y un archivo generado con las plantillas de
    `institutional_document_builder`. El test debe verificar que los tres
    quedan clasificados exactamente como
    `WRONG_ENTITY_MISMATCH_WITH_FOLDER`, `WRONG_YEAR_UNDECLARED_SUBSTITUTION`
    y `SYNTHETIC_FABRICATED` respectivamente, y que ninguno queda como
    `VALID_ORIGINAL_SEALED`.**
  - **Prueben `remediation_runner.py` de extremo a extremo sobre ese mismo
    dataset de prueba: que los tres casos anteriores terminan en
    `data/quarantine_forensic_retro/` (nunca en la carpeta canónica), que se
    genera una entrada en `remediation_queue` para cada uno, y que una segunda
    ejecución del runner no vuelve a reprocesar los ya marcados `DONE`.**
- Genera un informe final `AUDIT_REPORT_POST_REFACTOR.md` con: nº de scripts
  legacy archivados, nº de documentos sintéticos purgados del dataset,
  cobertura real (no inflada) por año/segmento tras el refactor, y lista de
  huecos que requieren intervención manual (LEIs no resueltos con score
  suficiente, canales sin acceso automatizable).

## 11. ESTILO Y CONVENCIONES

- Python 3.11+, tipado con `typing`, docstrings en español técnico-jurídico
  (mismo tono que el resto de `mod_01_ingestion`).
- Reutiliza `mod_08_monitor` para logging/métricas (no imprimas con `print()`
  en producción, usa `get_logger`).
- Todo cambio debe ser revisable: commits pequeños y descriptivos, nunca un
  solo commit monolítico "refactor total".
- No toques `mod_02` a `mod_08` salvo los puntos mínimos de integración ya
  existentes (`lake.insert_document_raw`, métricas Prometheus).

## 12. ENTREGABLE FINAL

Al terminar, el estado del repositorio debe permitir ejecutar, con
resultado 100% verificable y sin ninguna cifra inventada:

```bash
python mod_01_ingestion/src/ingest_runner.py --market ES --ticker SAN --year 2024
```

y obtener los 5 documentos reales, sellados, validados por identidad/ejercicio/
tipología, con manifest.json trazable hasta la URL oficial exacta de origen
(`filings.xbrl.org` o CNMV), sin ningún archivo `institutional_document_builder`
ni script legacy en el camino de ejecución.

Además, debe poder ejecutarse de forma independiente y en cualquier momento:

```bash
python -m mod_01_ingestion.src.forensic_dataset_auditor --scope ES_CNMV
python mod_01_ingestion/src/remediation_runner.py --process-pending
```

para auditar y sanear en cualquier momento el dataset ya existente, sin
depender de un script de usar-y-tirar nuevo cada vez que aparezca un error.

No me entregues una simulación de esto. Entrégame el sistema que lo hace de
verdad, o dime con precisión técnica qué parte no es posible automatizar y
por qué, para decidir juntos la intervención manual mínima necesaria.
