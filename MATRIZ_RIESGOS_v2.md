---
title: MATRIZ DE RIESGOS — ARGOS / STATER v2
version: 2.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-09
depends_on:
  - PLAN_MAESTRO_ARGOS_v2.md
  - Baseline de Tests v2
data_root: configurable via ARGOS_DATA_ROOT (default: D:\ARGOS_DATA)
products_served:
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - Data Lake ARGOS (capa Gold)
---

# MATRIZ DE RIESGOS — ARGOS / STATER v2

> Evaluación y mitigación de riesgos técnicos, operativos, de concurrencia y de datos.  
> Escala de Impacto (I) y Probabilidad (P): de 1 (mínimo) a 5 (máximo). Exposición = $I \times P$.

---

## 1. Resumen Ejecutivo de Riesgos

| ID | Riesgo | Impacto (1-5) | Probabilidad (1-5) | Exposición ($I \times P$) | Fase Crítica | Estado |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **R7** | Parser insuficiente para contextos XBRL reales y dimensiones | 5 | 4 | **20** | Fase 2 | Activo / Mitigándose |
| **R1** | Bloqueo 403/429 del canal CNMV / OAMs | 4 | 4 | **16** | Fase 1 | Mitigado por Discovery-First |
| **R5** | Bloqueo por concurrencia en DuckDB (> 100 req/s) | 4 | 4 | **16** | Fase 4/5 | **Resuelto en v2 por Desacoplamiento** |
| **R10** | Sobreestimación de datos externos sin manifiesto auditable | 4 | 3 | **12** | Fase 1 | **Nuevo en v2 (Discovery Audit)** |
| **R2** | Cambio de esquema ESEF por ESMA | 4 | 3 | **12** | Fases 2/7 | Mitigado por bridges |
| **R4** | Caída o indisponibilidad de `filings.xbrl.org` | 4 | 3 | **12** | Fases 1/7 | Mitigado por caché local en D: |
| **R6** | Rotura de scrapers por rediseño de portales reguladores | 4 | 3 | **12** | Fases 1/7 | Mitigado por canal API prioritario |
| **R8** | Taxonomía canónica incompleta (EBITDA, FCF faltantes) | 3 | 4 | **12** | Fase 2 | Mitigado por fórmulas derivadas |
| **R9** | Desconexión física o indisponibilidad de `DATA_ROOT` (Disco D:) | 4 | 2 | **8** | Fases 1-8 | **Nuevo en v2 (Configuración dinámica)** |
| **R3** | Licencias y restricciones legales sobre datos derivados OAM | 3 | 2 | **6** | Fase 5/6 | Mitigado por atribución y auditoría |

---

## 2. Fichas Detalladas de Mitigación y Planes B

### R7 — Parser insuficiente para contextos XBRL reales y dimensiones
- **Descripción**: `xbrl_parser.py` solo procesa elementos planos sin resolver `contextRef`, períodos (`instant` vs `duration`), unidades ni factores de escala (`decimals`). Si no se extiende, el 80% de los balances reales no cuadran.
- **Mitigación**: Implementar resolución formal de contextos en Fase 2; añadir pruebas de regresión con fixtures reales de IBEX 35 sin romper el baseline de tests.
- **Plan B**: Integración de motor iXBRL complementario basado en `lxml` con XPath específico para taxonomías ESEF ESMA.

### R5 — Bloqueo por concurrencia multi-usuario en DuckDB (Actualizado v2)
- **Descripción**: DuckDB es una base de datos OLAP embebida para un único escritor. Intentar atender 100 req/s concurrentes desde FastAPI directamente sobre el archivo genera excepciones `DatabaseLockedError`.
- **Mitigación (Arquitectura v2)**: **DuckDB se utiliza exclusivamente para ingesta fuera de línea**. Para la API se exportan snapshots inmutables en Parquet particionado y réplicas de solo lectura (SQLite / Parquet) respaldadas por Redis (hit ratio $\ge 80\%$).
- **Plan B**: Migración transparente de la capa de servicio a PostgreSQL o DuckDB sobre S3 en caso de escalar a $> 500$ usuarios simultáneos.

### R10 — Sobreestimación de datos en disco sin manifiesto reproducible (Nuevo v2)
- **Descripción**: Asumir que existen 1.060 paquetes válidos y 93.4% de cobertura en disco sin comprobar su integridad estructural ni generar un hash reproducible puede llevar a errores en cascada.
- **Mitigación**: Fase 1 Discovery-First: Antes de dar por válidos los archivos, un script del repositorio recorre `D:\ARGOS_DATA\raw\ES_CNMV`, verifica `magic bytes`, recalcula SHA-256 y emite el `DATA_ROOT_MANIFEST_2022.json` oficial.
- **Plan B**: Si un paquete está corrupto o incompleto, se traslada a cuarentena y se añade automáticamente a la lista de descarga de gaps.

### R1 — Bloqueo 403 / 429 por descargas masivas
- **Descripción**: La CNMV o ESMA bloquean la IP del servidor si se lanzan descargas concurrentes de paquetes de 100 MB.
- **Mitigación**:
  1. Descarga exclusiva de gaps (se evita volver a descargar los ~1.000 paquetes que ya están en disco).
  2. Rate limit estricto: 0.3 segundos de espera mínima entre peticiones.
  3. Reutilización de sesiones HTTP y backoff exponencial con jitter ante código 429.
- **Plan B**: Rotación de canal: conmutar a clientes directos por emisor (`cnmv_portal_scraper.py` o descarga HITL asistida).

### R9 — Indisponibilidad o fallo de montaje de `DATA_ROOT` (Nuevo v2)
- **Descripción**: Si la unidad `D:` se desconecta o cambia de letra, los scripts que tengan rutas fijas fallarán con `FileNotFoundError`.
- **Mitigación**: Todas las referencias a rutas de datos resuelven a través de la función centralizada `get_data_root()`, que lee la variable de entorno `ARGOS_DATA_ROOT` y valida la existencia física antes de cualquier operación.
- **Plan B**: Alerta explícita en consola indicando la ruta esperada y fallback automático a ruta de contingencia configurada.

---

## 3. Matriz de Priorización de Acciones Inmediatas

```text
CRÍTICA INMEDIATA (Semana 1):
├── [R10] Certificar con manifiesto reproducible los archivos reales de D:\ARGOS_DATA\raw\ES_CNMV.
├── [R7]  Extender xbrl_parser.py con contextos y dimensiones.
└── [R8]  Mapear EBITDA y FCF con tests contables.

ALTA PRIORIDAD (Semana 2 - 3):
├── [R5]  Implementar exportación Parquet desacoplada y réplica de lectura.
├── [R1]  Descargar únicamente los gaps confirmados de 2022.
└── [R2]  Blindar tests de contrato de esquemas para multi-país.
```
