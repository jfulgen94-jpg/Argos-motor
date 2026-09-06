# AUDITORÍA TÉCNICA Y ESTADO REAL: MOD_08_MONITOR
**Módulo:** Observabilidad Centralizada, Métricas Prometheus y Reglas de Calidad de Datos  
**Ruta en el repositorio:** `ARGOS_MOTOR/mod_08_monitor`  
**Estado:** Implementado con métricas de instrumentación, logging JSON estructurado y validador de calidad contable.

---

## 1. INVENTARIO REAL DE ARCHIVOS CREADOS

```
ARGOS_MOTOR/mod_08_monitor/
├── README.md                      (Documentación de observabilidad, métricas y reglas de calidad)
├── config/
│   └── monitor_config.env         (Variables de entorno para logs, Prometheus y thresholds de balance)
├── src/
│   ├── __init__.py                (Exports de get_logger, métricas Prometheus y DataQualityChecker)
│   ├── logger.py                  (Logger JSON estructurado con contexto de módulo y correlación)
│   ├── metrics.py                 (Contadores, Histogramas y Gauges Prometheus)
│   └── data_quality_checker.py    (Suite de 7 reglas deterministas de calidad contable)
└── tests/
    ├── __init__.py
    └── test_monitor.py            (Pruebas de logger contextual y reglas de calidad de datos)
```

---

## 2. CLASES, MÉTRICAS Y REGLAS IMPLEMENTADAS

### A. Logger Estructurado (`src/logger.py`)
- **Propósito:** Emisión de logs en formato JSON estructurado para auditoría forense y análisis en tiempo real.
- **Campos Emitidos:** `timestamp` (ISO 8601 UTC), `level` (INFO, WARNING, ERROR), `module` (nombre del módulo ARGOS), `event` (descripción), `context` (pares clave-valor como `ticker`, `n_docs`, `elapsed_s`).

### B. Métricas Prometheus (`src/metrics.py`)
- **Contadores e Histogramas Instrumentados:**
  - `INGEST_DOCS_TOTAL`: Total de documentos ingestados por fuente y país (`source`, `country`).
  - `INGEST_ERRORS_TOTAL`: Errores de ingesta tipados por clase de excepción.
  - `PIPELINE_DURATION_SECONDS`: Histograma de latencia por módulo.
  - `PARSED_FACTS_TOTAL`: Hechos XBRL extraídos por tipo de taxonomía.
  - `BALANCE_CHECK_FAILURES_TOTAL`: Filings rechazados por descuadre contable.
  - `AGENT_REQUESTS_TOTAL`: Solicitudes a modelos de IA por identificador de modelo.

### C. `DataQualityChecker` (`src/data_quality_checker.py`)
- **Propósito:** Reglas de validación antes de consolidar datos en el Data Lake.
- **7 Reglas Contables Implementadas:**
  1. `RULE_BALANCE_SQUARE`: `Total Activo == Total Pasivo + Patrimonio Neto` (tolerancia máxima 100 €).
  2. `RULE_POSITIVE_ASSETS`: `Total Activo > 0`.
  3. `RULE_POSITIVE_REVENUE`: `Revenue >= 0`.
  4. `RULE_VALID_FISCAL_YEAR`: Ejercicio fiscal entre 2000 y el año en curso.
  5. `RULE_VALID_IDENTIFIERS`: Presencia obligatoria de LEI o Ticker.
  6. `RULE_EQUITY_CONSISTENCY`: Patrimonio neto no nulo.
  7. `RULE_CASH_LESS_THAN_ASSETS`: `Efectivo <= Total Activo`.

---

## 3. SUITE DE TESTS IMPLEMENTADOS (`tests/`)
- `test_logger_returns_bound_logger`: Comprueba que `get_logger("mod_01")` retorne una instancia válida.
- `test_logger_module_context`: Verifica que los logs incluyan el módulo emisor.
- `test_quality_checker_catches_imbalanced_panel`: Verifica que un registro descuadrado falle la regla `RULE_BALANCE_SQUARE`.
- `test_quality_checker_passes_balanced_panel`: Comprueba que un registro contablemente íntegro supere el 100% de las reglas.

---

## 4. ANÁLISIS DE CAPACIDADES Y GAPS
- **Capacidad Real:** Observabilidad de grado bancario con logs legibles por máquinas y reglas matemáticas estrictas.
- **Gap:** Falta conectar el endpoint `/metrics` en el servidor FastAPI (`mod_06_api_gateway`) para que servidores Prometheus externos puedan scrapear las métricas en producción.
