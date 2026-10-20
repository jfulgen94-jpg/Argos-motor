# Stater / ARGOS_MOTOR — contexto para agentes

Stater = descargador, extractor e intérprete de informes financieros (auditoría, gestión y sostenibilidad) de Europa y EE.UU. desde 2012 hasta hoy.
Plan en 3 fases: **(1) descargar todo**, (2) extraer, (3) interpretar. Estamos en la fase 1, en plena auditoría del material ya descargado.

## Dónde está qué (importante: worktree vs. checkout principal)
- Este worktree solo contiene lo versionado en git. Lo **no versionado** vive en el checkout principal `C:\Users\jfulg\Desktop\Stater` (solo lectura desde aquí salvo orden expresa):
  `audits/` (informes Fase 0–3), `Inventario codigo stater 09-10-2026.md`, `inventario disco local 08-10-2026.md`,
  `audit_batch_{us,nl,it}.json`, `sec_panel_us_summary.json`, `Argos_BD/` (EE.UU. econométrico), `ARGOS_MOTOR/data/`.
- Datos descargados → **disco `D:\ARGOS_DATA`** (`raw/{DE_BAFIN,ES_CNMV,FR_AMF,IT_CONSOB,NL_AFM,quarantine_es}`, `lake/{ESPANA,ALEMANIA,FRANCIA,PAISES_BAJOS,ESTADOS_UNIDOS}`, `staging`, `quarantine*`). Copia del código en `D:\ARGOS_MOTOR`. `ARGOS_DATA_DISK` (raíz del checkout) es un symlink a `/d/ARGOS_DATA`.
- Ruta de datos configurable con `ARGOS_DATA_ROOT` (ver `.env.example`); nada de rutas hardcodeadas nuevas.

## Documentos rectores
`PLAN_MAESTRO_ARGOS_v2.md` (reglas cardinales), `SPEC_DATA_LAKE_MULTI_PAIS_v2.md`, `SPEC_INGESTA_{ES_v2,DE,FR,IT,NL,US_SEC}.md`, `MATRIZ_RIESGOS_v2.md`.
Reglas cardinales: solo datos reales (jamás sintéticos; **no ejecutar `clean_and_rebuild_all_institutional.py`**); raw inmutable con SHA-256; descubrir/inventariar antes de descargar (solo gaps); DuckDB de escritura nunca expuesto a la API.

## Estado de la auditoría (carpeta `audits/`, 2026-10-09)
- **Fase 0 Contención**: rama `audit/containment-2026-10-09` + tag `baseline/argos-motor-pre-containment-2026-10-09` sobre `8409f7b`; 5 DuckDB respaldadas; manifiesto 7.386 archivos.
- **Fase 1 Mapa de autoridad**: 7.403 artefactos clasificados; 190 entrypoints; **dos pistas de descarga**: Track A `ARGOS_MOTOR/descarga/*` (scripts por país, .bat) y Track B `mod_01_ingestion/src` (`RobustDownloader`, vía `argos.py`). Ruta productiva única: NO verificada. 1.295 candidatos a huérfano (no borrar).
- **Fase 2 Datos** (40,38 GiB en `ARGOS_MOTOR/data`): 843 grupos duplicados binarios (14,12 GiB); 546/547 ZIP válidos (corrupto: `staging/tmp_download/tmp_2020_NTGY_NTGY_2020_esef.zip`); 4.076 archivos raw sin manifiesto (ES/US); 1.449 `local_path` desincronizados en `documents_raw`; 519 sintéticos en `quarantine_forensic_retro` (mantener en cuarentena).
- **Fase 3 Motor** (27 pruebas sandbox): vertical slice PASS. Defectos: DEFECT-01 crash `zlib.error` en `_validate_zip`; -02 enmascara 5xx/429; -03 sin `fsync`; -04 sin file locks; -05 Track A escribe directo sin `.part`; -06 sin 2PC raw↔catálogo; sin límite de concurrencia por dominio.
- **Pendientes**: **Fase 4 (unificación)** y **Fase 5 (limpieza)**. Decisiones esperando autorización explícita del usuario: dedup (hardlinks/CAS), borrar ZIP corrupto de NTGY, resync `local_path` por hash, rotación de credenciales.

## Cobertura (inventario 08-10-2026)
ES 199 emp/2.493 docs · DE 796/7.927 · FR 529/3.935 · US 38 (lake)+32.280 (Argos_BD) · NL 10 (AEX) · IT 12 (FTSE MIB) · UK 7.567 archivos 16,66 GB en `Desktop\estudios v\CCA_Reino_Unido` sin volcar al lake. Lake: 14.626 docs, 1.564 empresas, 96,66 GB. Faltan: mayoría de NL/IT, UK en lake, resto de Europa.

## Seguridad / límites
- Secretos en claro conocidos: `iniciar_openhands.bat` (token GitHub) y `ARGOS_MOTOR/config/azure_secrets.json`. No imprimirlos ni commitearlos.
- `ARGOS_MOTOR/descarga/de_germany/bafin_browser_session/` = perfil de navegador sensible: no leer ni subir.
- No borrar, mover ni sobrescribir `data/raw`, DuckDB originales ni cuarentena sin autorización expresa.
- `.continue/rules/argos.md` (sin versionar) pertenece a una fase documental anterior y prohíbe código/red/acceso a D:; el usuario ha reabierto el trabajo con D: como destino, pero ante la duda, preguntar.

## Entorno
Windows 11, Python 3.14.4, duckdb 1.5.5, pyarrow, pandas 3, requests/httpx, playwright, bs4/lxml, pytest 9 (todo instalado). Git 2.54; `gh` CLI no instalado. Tests: `pytest -m "not network and not external_data"` desde `ARGOS_MOTOR/`.
