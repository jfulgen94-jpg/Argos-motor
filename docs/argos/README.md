# ARGOS documental — Stater

**ARGOS documental** es un módulo futuro, independiente y aislado dentro del workspace `Stater`.

Su finalidad prevista es gobernar y auditar documentación financiera y regulatoria de empresas cotizadas mediante un flujo posterior de:

```text
Descubrimiento → Descarga → Validación → Extracción → Normalización → Auditoría
```

## Estado actual

La fase actual se limita exclusivamente a documentación, gobierno y diseño conceptual.

No existen todavía, ni están autorizados en esta fase:

- Conectores de red, APIs, scrapers o descargadores.
- Parsers PDF o HTML.
- Extractores, normalizadores o validadores.
- Catálogos SQLite, bases DuckDB o ficheros Parquet.
- Scripts de ingesta, descarga o procesamiento documental.
- Pruebas de integración.
- Configuración de fuentes externas.
- Acceso a datos externos.

## Ámbito previsto

El primer ámbito previsto es España.

La cobertura histórica futura se contempla aproximadamente desde 2012 hasta la fecha actual, comenzando por documentos publicados durante 2026.

En fases posteriores podrían considerarse mercados españoles como BME Continuo, BME Exchange y BME Growth. No se han autorizado fuentes, conectores ni ámbitos europeos o estadounidenses concretos.

## Aislamiento del motor ARGOS

ARGOS documental **no sustituye** ni reutiliza el motor ARGOS existente.

Los siguientes componentes deben permanecer intactos:

- `ARGOS_MOTOR/`
- `Argos_BD/`
- `argos.py`
- `mod_01_ingestion/`
- `data/raw/`
- `data/lake/`
- `config/` y sus archivos existentes
- Scripts, salidas, datos y procesos SFI
- `PLAN_MAESTRO_ARGOS_v1.md`
- `PLAN_MAESTRO_ARGOS_v2.md`
- `AGENTS.md`
- `requirements.txt`
- `pyproject.toml`

El namespace reservado para el módulo documental es `argos_docs/`, para evitar colisiones con el archivo raíz `argos.py`.

No debe crearse ningún paquete, carpeta o módulo nuevo llamado simplemente `argos`.

## Datos externos

La futura raíz externa prevista para los datos de ARGOS documental es:

```text
D:\ARGOS_DATA
```

En la fase actual no está permitido acceder a `D:\ARGOS_DATA`, crear rutas operativas bajo esa raíz ni configurar fuentes, catálogos o procesos que la utilicen.

Antes de utilizar datos externos, deberá verificarse de forma explícitamente autorizada la naturaleza de `ARGOS_DATA_DISK`, ubicado en la raíz del workspace. No debe asumirse que es una carpeta, junction, enlace simbólico, shortcut, montaje o carpeta espejo.

No se permite duplicar documentación o datos de ARGOS documental dentro de `data/raw/` ni `data/lake/`.