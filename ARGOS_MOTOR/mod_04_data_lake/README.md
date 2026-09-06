# MOD_04 — Data Lake Columnar (DuckDB + Apache Parquet)

## Propósito
Sistema nervioso del motor. Gestiona 4 capas de datos con DuckDB embebido y archivos Parquet. Administra snapshots diarios versionados.

## Arquitectura de Capas
```
RAW       → Registros de documentos descargados (inmutable, sellado SHA-256)
STAGING   → Hechos XBRL granulares y textos NLP sin validar
CORE      → Panel financiero validado y KAMs/ESG verificados
ANALYTICS → Ratios, scores, factores y modelos DCF (generados por MOD_05)
```

## Snapshots
Cada ejecución diaria genera versión `vYYYYMMDD`. Nunca se sobreescriben datos históricos.

## Ejecución
```bash
python src/lake_manager.py --init       # Crear schema inicial
python src/snapshot_manager.py --run    # Crear snapshot de hoy
```
