# PLAN DE EJECUCIÓN — DE MOTOR AUDITADO A DESCARGADOR REAL (2012 → HOY)

**Fecha:** 2026-10-19 · **Verificado contra:** rama `feature/unified-download-module` (21 commits por delante de `main`), `D:\ARGOS_DATA`, catálogos de `ARGOS_MOTOR/config/`
**Sustituye en lo operativo a:** `docs/argos/PLAN_DESCARGA_OAM.md` (2026-10-09), que describe como "pendiente" trabajo que ya está hecho.

> Etiquetas: **[VERIFICADO]** comprobado en esta sesión contra código/disco · **[ESTIMADO]** cálculo con supuestos declarados · **[NO VERIFICADO]** requiere red real.

---

## 0. HALLAZGO PRINCIPAL: EL PROBLEMA YA NO ES LA ARQUITECTURA

`main` dice que la Fase 4A está pendiente y que hay que elegir entre tres opciones de diseño. **Eso ya está superado.** La rama `feature/unified-download-module` contiene el híbrido construido:

| Pieza del híbrido | Estado | Módulo |
|---|---|---|
| Op.1 — contrato + runner estricto | **implementado** | `ingest_runner.py`, `source_adapter.py`, `download_service.py` |
| Op.1 — `.part` → fsync → validar → rename | **implementado** | `download_service.py`, `cas_store.py` |
| Op.1 — lock por documento + límite por dominio | **implementado** | `lock_manager.py`, `rate_limiter.py` |
| Op.3 — ledger de cobertura (esperado vs tenido) | **implementado** (sin datos) | `coverage_ledger.py` |
| Op.3 — canarios por fuente | **implementado** (solo sandbox) | `canary.py`, `canary_scheduler.py` |
| Op.3 — reconciliador raw↔CAS↔manifiesto↔catálogo | **implementado** (solo lectura) | `reconciler.py` |
| Op.2 — caché condicional ETag/If-Modified-Since | **parcial** | `download_service.py` |
| Preflight autoritativo (única autoridad de skip) | **implementado** | `application/preflight.py` |
| Aprobaciones con cuatro ojos y huella de contenido | **implementado** | `approvals.py` |
| Transporte efímero y saneado de URLs con token | **implementado** | `domain/transport.py`, `cnmv_u3.py` |

DEFECT-01 a 10 de la Fase 3 están remediados (DEFECT-05 solo en flujos migrados). **Lo que impide descargar no es el motor: son cuatro cosas concretas que detallo abajo.** [VERIFICADO]

---

## 1. ESTADO REAL VERIFICADO

### 1.1 Qué hay en disco (`D:\ARGOS_DATA\raw`) [VERIFICADO]

Documentos reales (PDF/ZIP/XHTML/HTM), excluyendo JSON/CSV/LOG de control:

| País | Informes reales | Volumen | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ES_CNMV | 2.398 | 48,0 GiB | 54 | 58 | 58 | 58 | 58 | 58 | 58 | 58 | 256 | 358 | 362 | 361 | 348 | 259 |
| FR_AMF | 3.929 | 36,6 GiB | 352 | 351 | 354 | 362 | 352 | 355 | 350 | 308 | 67 | 211 | 237 | 217 | 221 | 183 |
| DE_BAFIN | **1.121** | 6,4 GiB | 529 | 563 | 613 | 644 | 693 | 716 | 753 | 775 | 1.331 | 945 | 249 | 40 | 39 | 37 |
| sec_edgar | 265 | 1,4 GiB | 3 | 2 | 2 | 1 | 2 | 3 | 2 | 20 | 22 | 26 | 27 | 33 | 35 | 59 |
| NL_AFM | 5 | 0,15 GiB | — | — | — | — | — | — | — | — | — | 2 | — | 1 | 1 | 1 |
| **IT_CONSOB** | **0** | 0 | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| **TOTAL** | **~7.718** | **96,7 GiB** | | | | | | | | | | | | | | |

> **Trampa del inventario:** la columna de años de DE cuenta 7.927 ficheros, pero **6.801 son páginas HTML de relación con inversores** (0,3 MiB de media), no informes. Los informes alemanes reales son **1.121** (515 PDF + 606 ZIP). Cualquier informe de cobertura que cuente ficheros en bruto sobreestima Alemania en un factor de 7. [VERIFICADO]

### 1.2 Universo esperado en catálogos [VERIFICADO]

| País | Catálogo | Emisores | LEI | ¿Sirve para ESEF? | Veredicto |
|---|---|---|---|---|---|
| ES | `master_universe_es.json` v4.0.0 | **378** (IBEX35 34 · Continuo 87 · Growth 54 · SOCIMI 203) | 100% | Sí | **COMPLETO** |
| DE | `master_universe_de.json` v4.0.0 | **1.011** (Prime 172 · General 376 · Scale 67 · Freiverkehr 396) | 95% (44 sin LEI) | Sí, salvo los 44 | **COMPLETO con hueco menor** |
| FR | `master_universe_fr.json` | **297** (CAC40 35 · Next20 15 · Mid60 54 · Growth 188 · 5 hold.) | 100% | Sí | **COMPLETO** |
| NL | `master_universe_nl.json` | **13** | 100% | Sí | **INSUFICIENTE** (AEX+AMX+AScX ≈ 75) |
| IT | — **no existe** | 12 (solo `bluechips`) | 100% | Sí | **AUSENTE** |
| US | — **no existe** | 31 (solo `bluechips`) | n/a (CIK) | n/a | **AUSENTE** |

Universo UE con identidad utilizable hoy: **1.699 emisores**. Faltan IT y NL completos, y la decisión de alcance de EEUU.

### 1.3 Cobertura: por qué todavía no es un número

Ranuras esperadas con los catálogos actuales (1 informe anual por emisor y ejercicio, 2012-2025 = 14 ejercicios): ES 5.292 · DE 14.154 · FR 4.158 · NL 182 · IT 0 · US 434 → **24.220 ranuras**. Con IT y NL completos: **≈ 28.000**. [ESTIMADO]

Frente a eso tenemos ~7.718 informes, **pero el cociente 7.718/24.220 ≈ 32% no es la cobertura**: en disco hay varios documentos por emisor-ejercicio (ficha IFA + cuentas + IAGC) y no hay nada que case fichero ↔ (emisor, ejercicio, tipo). **La cobertura real es desconocida y seguirá siéndolo hasta sembrar el ledger** (F-02). Es la primera cosa que hay que arreglar, porque sin ella "descargar el mayor número de informes" no tiene criterio de parada.

### 1.4 Entorno y verificabilidad [VERIFICADO]

| Control | Resultado |
|---|---|
| Suite de la rama | **recuperada en esta sesión**: `.venv` con Python 3.13 → **823 tests verdes, 0 fallos** |
| Dependencias ausentes de `requirements.txt` | `scikit-learn`, `prometheus-client`, `PyMuPDF` — sin ellas la suite ni se recolecta (10 fallos en `test_unified_u2.py`). **Corregido** |
| Tests declarados en los informes | 294 verdes (U5A); la suite completa de `mod_01` da 823 |
| Ficheros de test en la rama | 38 |
| Trabajo sin commitear en la rama | `cnmv_canary.py`, `test_unified_cnmv_canary.py`, `config/pilot/cnmv_canary/`, y `adapters/cnmv.py` modificado |
| Disco D: | 834,3 GB libres de 931,5 → **suficiente** |
| Disco C: | 27,6 GB libres de 476,8 → **nada masivo puede ir a C:** |

---

## 2. LAS CUATRO TAREAS BANDERA, RESUELTAS

### 2.1 "Tocar código de producción para empezar Fase 4A"

**La 4A está hecha.** Los defectos que motivaban esa fase (validador colgado con ZIP corrupto, 5xx enmascarados, falta de fsync, falta de locks, falta de transacción, duplicados, sin `run_id`, sin límite por dominio) están remediados en la rama. Lo que queda de "tocar producción" es distinto y más barato:

1. **Reconstruir el entorno** para poder verificar algo (F-01).
2. **Consolidar el trabajo sin commitear** antes de que se pierda (F-10).
3. **Fusionar la rama a `main`** tras pasar la suite en local, porque hoy todo el motor bueno vive fuera de `main` y `argos.py download` sigue enrutando a los scripts antiguos de `descarga/`.
4. **Tres piezas nuevas** que no existen y son las que realmente bloquean la descarga: siembra del universo esperado, canal ESEF, descubrimiento real por fuente (§4, fases D1-D3).

### 2.2 "Elegir el híbrido"

**Decidido: híbrido por capas, en el orden Op.1 → Op.3 → Op.2**, que es exactamente lo que la rama ya materializa. No hay que elegir de nuevo; hay que **terminar la capa Op.2 y conectar la fuente que falta**:

- **Núcleo (Op.1):** completo. Se mantiene como única ruta de ingesta.
- **Gobierno (Op.3):** el ledger y los canarios existen pero están vacíos y en sandbox. Se activan sembrando el esperado y dándoles una fuente real.
- **Delta (Op.2):** `download_service` ya guarda `ETag`/`Last-Modified`, pero **no hay espejo incremental por índice**. Se añade solo donde la fuente tiene índice con fecha: ESEF (`filings.xbrl.org`) y SEC (`full-index`). Para CNMV/AMF/CONSOB/AFM se cae a Op.1, como estaba previsto.

**Añadido al híbrido que el plan anterior no contemplaba:** el canal **ESEF vía `filings.xbrl.org`** es la pieza de mayor rendimiento del proyecto y **no está conectada al módulo unificado**, aunque el cliente legacy `xbrl_org_client.py` existe y funciona. Un solo dominio, API JSON:API, paquetes ZIP con iXBRL, cubre **los cinco países UE a la vez** para ejercicios ≥2020, y los catálogos ya tienen el LEI al 95-100% que esa API necesita. Es el mayor retorno por hora de trabajo de todo el plan (F-04).

### 2.3 "Autorización explícita para las primeras pruebas"

El mecanismo ya está construido y es estricto. **Hoy no hay ni una sola petición real que sea legítima**, porque todos los artefactos están en `PENDING_APPROVAL` y el `user_agent` literalmente dice `PENDING_APPROVAL:NOT_ACTIVATABLE`. [VERIFICADO]

Lo que está preparado y esperando tu firma:

| Artefacto | Fichero | Alcance |
|---|---|---|
| Config de fuente CNMV | `config/pilot/cnmv/source_config.pending.json` | dominio único `www.cnmv.es`, 1 concurrente, ≥5 s entre peticiones, 60 s timeout, 64 MiB máx., 403 = no reintentar |
| Contrato de identidad | `config/pilot/cnmv/identity_contract.pending.json` | política de versionado del documento |
| Plan de piloto | `config/pilot/cnmv/pilot_plan.pending.json` | **1 documento**: Telefónica 2019, `AUDITA/2019/18290.pdf`, 300 s totales |
| Canario | `config/pilot/cnmv_canary/canary_tef_2020.pending.json` | **1 documento**: TEF 2020 ZIP/XBRL, ≤5 peticiones, frase requerida `AUTORIZO CANARIO CNMV TEF 2020 ZIP` |

Para activarlos necesito de ti **tres datos y dos frases**, no un "adelante" genérico:

1. **User-Agent real identificado** — la norma de cortesía exige identificar quién consulta. Propuesta: `ARGOS-MOTOR/1.0 (investigación académica; Universidad de Murcia; <correo de contacto>)`.
2. **Correo de contacto** que irá en ese User-Agent y en el `contact` de la configuración.
3. **Aprobador** distinto del remitente: el registro exige cuatro ojos (`require_distinct_approver=True`). Yo envío, tú apruebas con una referencia.
4. La frase del canario: `AUTORIZO CANARIO CNMV TEF 2020 ZIP`.
5. Una autorización equivalente para el lote de 9 documentos de CNMV-U2 (informes anuales PDF 2018-2019) ya descubiertos.

### 2.4 "Revisar si el universo esperado por país está cubierto en los catálogos"

Respondido en §1.2. Resumen ejecutable: **ES, DE y FR sí; NL, IT y US no.**

| Hueco | Acción | Fuente propuesta |
|---|---|---|
| **IT sin catálogo** | construir `master_universe_it.json` | lista oficial de emisores de Borsa Italiana (FTSE MIB + Mid/Small/STAR) + LEI vía GLEIF |
| **NL con 13 emisores** | ampliar a ~75 | AEX + AMX + AScX de Euronext Ámsterdam + LEI vía GLEIF |
| **US sin catálogo** | decidir alcance y construirlo | `company_tickers.json` de la SEC (universo completo, ~8.000 CIK) filtrado al alcance que decidas |
| **DE: 44 emisores sin LEI** | resolver | GLEIF por nombre legal + HRB; si no hay LEI, el emisor sale del canal ESEF y va por Bundesanzeiger |

---

## 3. FALLOS OBSERVADOS EN ESTA SESIÓN Y SOLUCIÓN PROPUESTA

Son hallazgos **nuevos**, distintos de los DEFECT-01..10 de la Fase 3 (ya remediados).

| # | Fallo | Impacto | Solución |
|---|---|---|---|
| **F-01** | Entorno local sin `pytest` ni `duckdb`; los 294 tests verdes no eran reproducibles aquí. Además `requirements.txt` omitía `scikit-learn`, `prometheus-client` y `PyMuPDF` | **Era bloqueante**: no se podía verificar ningún cambio ni abrir el catálogo | **RESUELTO en esta sesión**: `.venv` con Python 3.13, dependencias añadidas a `requirements.txt`, línea base **823 verdes / 0 fallos** |
| **F-02** | El ledger de cobertura **no tiene siembra del universo esperado**: ninguna función lee `master_universe_*.json` | **Bloqueante**: "100%" no es calculable; no hay cola de descarga derivada de huecos | Añadir `expected_universe.py` que proyecte (emisor × ejercicio × tipo) desde los catálogos a la tabla `expected`, con versión y huella del catálogo (fase **D1**) |
| **F-03** | 5 de 6 adapters son **SANDBOX/REPLAY**: consumen registros de un proveedor inyectado, no descubren nada. Solo CNMV tiene descubrimiento real | Sin esto no hay descarga masiva, solo repetición de enlaces ya conocidos | Descubrimiento real por fuente, en orden de rendimiento: ESEF → SEC → CNMV (hecho) → AMF/CONSOB/AFM/Bundesanzeiger (fases **D2-D3**) |
| **F-04** | El canal **ESEF (`filings.xbrl.org`) no está conectado** al módulo unificado, pese a existir `xbrl_org_client.py` y tener el LEI al 95-100% en catálogo | Se está dejando sin usar la fuente que cubre 5 países a la vez para 2020+ | `adapters/esef_xbrl_org.py` sobre el contrato `SourceAdapter`, reutilizando el cliente legacy como transporte (fase **D2**, máxima prioridad) |
| **F-05** | **IT: 0 documentos y sin catálogo. NL: 13 emisores, 5 documentos** | Dos de los seis mercados están esencialmente vacíos | Construir ambos universos (§2.4) y atacarlos primero por ESEF, que no necesita portal nacional |
| **F-06** | **US: 265 documentos** y sin universo sistemático; nada regular antes de 2019 | EEUU es el mercado más fácil de automatizar y es el que está peor | Adapter SEC con `full-index` trimestral + `submissions`; 10 req/s permitidas con UA identificado — es la fuente más generosa de todas |
| **F-07** | 6.801 de los 7.927 ficheros alemanes son páginas HTML de IR, no informes | Infla la cobertura aparente ×7 y contamina cualquier métrica | Clasificar por tipo en el ledger; las páginas de IR son *evidencia de descubrimiento*, no documentos promovibles |
| **F-08** | **Colapso de cobertura reciente**: DE cae a 249/40/39/37 en 2022-2025; FR cae desde 2020 | Los ejercicios más valiosos (los más recientes) son los peor cubiertos | Priorizar el ledger por ejercicio descendente; los años 2022-2025 están todos dentro del alcance de ESEF |
| **F-09** | **ES con historia fina**: ~58 documentos/año en 2012-2019 frente a 378 emisores del catálogo | El 85% del universo español no tiene nada pre-2020 | CNMV `AUDITA/{año}/{nreg}.pdf` por número de registro; el patrón ya está resuelto en `pilot_batch.expected_url` |
| **F-10** | Trabajo **sin commitear** en la rama (canario CNMV + tests + config) | Riesgo de pérdida de trabajo terminado | Commit inmediato en **D0** antes de cualquier otra cosa |
| **F-11** | `user_agent` y `contact` en `PENDING_APPROVAL:NOT_ACTIVATABLE` | Ninguna petición real es legítima todavía | Los tres datos de §2.3 |
| **F-12** | C: con 27,6 GB libres | Un volcado accidental en C: rompe la máquina | Verificar que `ARGOS_DATA_ROOT=D:\ARGOS_DATA` esté fijado en el entorno y que ninguna ruta de piloto escriba en C: |

---

## 4. PLAN POR FASES, CON PUERTAS MEDIBLES

Cada fase tiene una puerta binaria. Ninguna se declara superada "por parecer lista".

### D0 — Recuperar la capacidad de verificar (sin red) · **HECHO EN ESTA SESIÓN, salvo el commit**
- ✅ `.venv` con Python 3.13 e instalación de `requirements.txt`.
- ✅ Tres dependencias ausentes añadidas a `requirements.txt` de la rama.
- ✅ Línea base registrada: **823 tests verdes, 0 fallos** (`mod_01_ingestion/tests`, sin red).
- ⬜ **Pendiente de tu visto bueno:** commitear el trabajo sin commitear de la rama (canario CNMV + sus tests + config del canario + `adapters/cnmv.py`) y el arreglo de `requirements.txt`.
- ⬜ Comprobar que `ARGOS_DATA_ROOT` está fijado a D: en el entorno del usuario.
- **Puerta:** ✅ suite verde reproducible en esta máquina.

### D1 — Hacer que la cobertura sea un número · *1-2 días* · sin red
- `expected_universe.py`: proyectar los catálogos a la tabla `expected` del ledger — (país, autoridad, emisor, ejercicio 2012-2025, tipo documental), con versión y huella del catálogo de origen.
- Política de tipos por tramo: `ESEF_PACKAGE` para ≥2020 en mercado regulado; `ANNUAL_REPORT_PDF` para 2012-2019 y para segmentos no ESEF (BME Growth, Freiverkehr, Euronext Growth).
- Conciliar lo que ya hay en disco contra el esperado con el `reconciler` (solo lectura) y clasificar los 6.801 HTML alemanes como evidencia, no como documentos.
- **Puerta:** informe de cobertura por país × ejercicio × tipo, con el total de huecos y **cero** ficheros en disco sin clasificar.

### D2 — Canal ESEF: el mayor retorno del plan · *2-3 días* + autorización
- `adapters/esef_xbrl_org.py` sobre el contrato `SourceAdapter`, descubrimiento por LEI y ejercicio, dominio único `filings.xbrl.org`.
- Ventaja descubierta: el motor legacy `descarga/es_spain/cnmv_engine_v5.py` ya apuntaba a `https://filings.xbrl.org/index.json`, es decir **existe un índice completo descargable de una sola vez** — eso convierte el descubrimiento ESEF en una única petición en lugar de 1.699 consultas por LEI, y habilita el modo delta Op.2 de forma natural. [NO VERIFICADO contra la fuente real]
- Modo **delta Op.2** sobre el índice de `filings.xbrl.org` (es la fuente que sí tiene índice con fecha de proceso).
- Canario en sandbox y luego **un** paquete real con autorización.
- **Puerta:** un paquete ESEF real descargado, validado (magic `PK\x03\x04`, documento primario, estados contables), sellado y en el ledger como `PROMOTED`; cobertura ≥2020 recalculada para los cinco países UE.
- **Rendimiento esperado:** cubre de golpe los ejercicios 2020-2025 de los emisores de mercado regulado de ES/DE/FR/IT/NL — justamente los años donde F-08 muestra el colapso. [ESTIMADO ~3.300 paquetes]

### D3 — Mercados vacíos: US, IT, NL · *3-5 días*
- Construir `master_universe_it.json`, ampliar NL a ~75 emisores, decidir y construir el universo US.
- Adapter SEC real: `full-index` trimestral + `submissions`, 10 req/s con UA identificado, formularios 10-K/20-F/40-F. Es la fuente más permisiva: EEUU puede pasar de 265 a varios miles de documentos sin fricción.
- **Puerta:** los tres países con universo sembrado en el ledger y ≥1 documento real promovido en cada uno.

### D4 — Históricos 2012-2019 por portal nacional · *1-2 semanas*
- ES: CNMV `AUDITA/{año}/{nreg}.pdf` por número de registro (patrón ya resuelto) → ataca F-09.
- FR: AMF BDIF para URD/DEU pre-ESEF.
- DE: Bundesanzeiger / EQS con la sesión Wicket fuera del núcleo.
- IT: CONSOB / almacenamiento autorizado. NL: depende de ESEF + IR.
- **Puerta:** cobertura 2012-2019 ≥ 80% del esperado por país, o el resto justificado como `NOT_PUBLISHED` con evidencia fechada.

### D5 — Retirada del legacy y unificación del CLI · *2-3 días*
- `argos.py download` enruta a `mod_01` unificado para los **seis** mercados (hoy solo DE/NL/ES/FR y por `subprocess` a `descarga/`).
- Retirar los 63 scripts de Track A según el plan de retirada, tras el burn-in.
- **Puerta:** un solo camino de ingesta demostrado por AST; cero escrituras directas al destino final.

### D6 — Operación semanal · *continuo*
- Modo delta semanal donde haya índice (ESEF, SEC), barrido por huecos donde no.
- Canarios reales por fuente con alerta ante "0 resultados" y ante cambio de estructura.
- **Puerta:** cuatro semanas consecutivas sin intervención manual.

### D7 — Cierre de cobertura
- **Puerta final:** informe de cobertura por país donde cada ranura esperada está `PROMOTED` o `NOT_PUBLISHED` con evidencia. Ese, y solo ese, es el "100%".

---

## 5. QUÉ NECESITAMOS PARA MAXIMIZAR LOS INFORMES 2012 → HOY

### 5.1 Canal óptimo por país y tramo

| País | 2012-2019 | 2020-2025 | Segmentos no regulados |
|---|---|---|---|
| ES (378) | CNMV `AUDITA` por nº registro | **ESEF** + CNMV IFA | BME Growth/SOCIMI: PDF del portal |
| DE (1.011) | Bundesanzeiger + EQS | **ESEF** (Prime/General) | Freiverkehr (396): solo IR/Bundesanzeiger |
| FR (297) | AMF BDIF (URD/DEU) | **ESEF** | Euronext Growth (188): PDF |
| IT (~220) | CONSOB / 1INFO | **ESEF** | Mid/Small: PDF |
| NL (~75) | IR corporativa | **ESEF** | AScX: PDF |
| US (alcance a decidir) | SEC `full-index` | SEC `full-index` | — |

El patrón es claro: **ESEF resuelve 2020-2025 de los cinco países UE en un solo dominio**, y los portales nacionales solo son imprescindibles para 2012-2019 y para los segmentos no regulados.

### 5.2 Coste y tiempo [ESTIMADO]

| Magnitud | Cifra | Supuesto |
|---|---|---|
| Ranuras esperadas | 24.220 (28.000 con IT+NL) | 1 informe anual por emisor-ejercicio, 2012-2025 |
| Informes ya en disco | ~7.718 | §1.1 |
| Pendientes | ~16.500-20.000 | diferencia |
| Volumen a descargar | **~250-300 GiB** | 15 MiB de media (medido: ES 15,7/31,5 · FR 4,2/22,5 · DE 6,7/5,1) |
| Disco necesario | cabe: 834 GB libres en D: | [VERIFICADO] |
| Tiempo por cortesía | ~23 h de espera pura por fuente a 5 s/petición | 16.500 documentos |
| Tiempo realista | **4-8 semanas** en ventanas nocturnas | 6 fuentes en paralelo (dominios distintos; el limitador es por dominio, así que es legítimo) |
| Descubrimiento ES completo | ~6,3 h por pasada | 378 emisores × ≤12 peticiones × 5 s |

### 5.3 Decisiones que condicionan el volumen

1. **Alcance de EEUU.** Los 31 *bluechips* dan 434 ranuras; el S&P 500 da ~7.000; el universo completo de la SEC, ~110.000. La SEC permite 10 req/s, así que el límite es el disco y tu interés, no la fuente.
2. **SOCIMIs españolas (203 de 378).** Están en el catálogo y hay un `master_universe_es_EXCLUDED_SOCIMIS.json` con una política de exclusión. Si entran, ES pasa de 2.450 a 5.292 ranuras.
3. **Freiverkehr alemán (396 de 1.011).** No está en mercado regulado, luego no tiene ESEF ni obligación de informe en formato único: es el tramo más caro por documento obtenido.
4. **Informes de gestión además de cuentas anuales.** Duplicaría aproximadamente las ranuras.

---

## 6. QUÉ NECESITO DE TI AHORA

| # | Decisión | Por qué no puedo decidirlo yo |
|---|---|---|
| 1 | **User-Agent y correo de contacto** reales | Identificarse ante la OAM es obligación de cortesía y legal; el dato es tuyo |
| 2 | **Aprobador** para el registro de cuatro ojos | El sistema exige que quien aprueba sea distinto de quien envía |
| 3 | Frase `AUTORIZO CANARIO CNMV TEF 2020 ZIP` | Está codificada como requisito en el plan del canario |
| 4 | Autorización del **lote CNMV-U2** (9 PDF, 2018-2019) | Primer tráfico real a escala pequeña |
| 5 | **Alcance de EEUU**: bluechips / S&P 500 / completo | Cambia el volumen en dos órdenes de magnitud |
| 6 | **SOCIMIs: dentro o fuera** | Cambia el esperado español en un ×2 |
| 7 | ¿Solo cuentas anuales auditadas, o también informes de gestión? | Cambia el esperado global en un ×2 |

Con 1-3 puedo cerrar D0-D1 y lanzar el canario; con 5-7 puedo sembrar el ledger con el esperado definitivo.

---

## 7. ORDEN DE ATAQUE RECOMENDADO

1. **D0** (medio día, sin red, sin riesgo): entorno + commit + línea base de tests. **Empiezo por aquí sin esperar nada.**
2. **D1** (sin red): el ledger con el esperado sembrado. Convierte "100%" en un número y genera la cola de trabajo.
3. **D2** (ESEF): el mayor retorno por hora del proyecto; ataca directamente el colapso de 2020-2025.
4. **D3** (US/IT/NL): los tres mercados vacíos, empezando por EEUU que es el más generoso.
5. **D4** (históricos nacionales): el trabajo largo, ya con el ledger diciendo exactamente qué falta.
