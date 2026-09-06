# ADR 001: Selección de DuckDB + Parquet frente a PostgreSQL

## Estado
Aceptado

## Contexto
El motor ARGOS procesa cientos de miles de estados financieros anuales con consultas analíticas OLAP (ratios, factores y matrices DCF).

## Decisión
Se elige DuckDB embebido + Apache Parquet porque:
1. Rendimiento analítico columnar 10x-50x superior para agregaciones y escaneos de paneles completos.
2. Despliegue embebido sin sobrecoste de infraestructura de servidores en Fase 0.
3. Compatibilidad nativa con Pandas, PyArrow y Azure Blob Storage.
