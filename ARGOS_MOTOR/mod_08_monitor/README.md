# MOD_08 — Monitor de Calidad, Alertas y Observabilidad

## Propósito
Sistema de observabilidad del motor. Registra de forma estructurada todos los eventos
del pipeline, detecta anomalías de calidad de datos, alerta sobre filings en cuarentena
y monitoriza el uptime de la API Gateway (MOD_06).

## Responsabilidades

| Capa | Qué monitoriza | Herramienta |
|---|---|---|
| **Pipeline** | Fallos de ingesta, descuadres de balance, errores de parser | `loguru` (local) |
| **Agentes IA** | Alucinaciones detectadas, timeouts Ollama, fallback a Azure | `loguru` + contadores |
| **Data Lake** | Integridad de snapshots, tablas vacías, registros duplicados | DuckDB assertions |
| **API Gateway** | Uptime, latencia P95, errores 4xx/5xx por endpoint | `prometheus_client` |
| **Cloud** | Sync Azure Blob: éxito/fallo por archivo | Azure Monitor (Fase 1+) |

## Formato de Log Estructurado
Todos los eventos se registran en JSON (compatible con Azure Monitor / ELK / Grafana).

```json
{
  "ts": "2026-08-24T17:00:00Z",
  "level": "ERROR",
  "module": "MOD_02",
  "event": "balance_quarantine",
  "entity_lei": "2138003EK6LKVJK",
  "fiscal_year": 2024,
  "imbalance_eur": 150000.0,
  "doc_id": "abc-123",
  "action": "QUARANTINE"
}
```

## Niveles de Alerta
- `INFO` — Operación completada correctamente.
- `WARNING` — Anomalía no crítica (rate limit, timeout recuperado).
- `ERROR` — Fallo que afecta a un documento (enviado a cuarentena).
- `CRITICAL` — Fallo sistémico (Data Lake inaccesible, API caída).

## Ejecución
```bash
# Iniciar API de métricas Prometheus (para dashboards Grafana)
python src/metrics_server.py

# Ejecutar chequeo de integridad del Data Lake
python src/data_quality_checker.py --date today

# Ver log del día
python -m loguru tail logs/stater_motor_$(date +%Y%m%d).json
```

## Integración con Módulos
- **Todos los módulos** importan `from mod_08_monitor.src.logger import log` para emitir eventos.
- **MOD_06 (API)** expone el endpoint `GET /metrics` en formato Prometheus.
- **MOD_07 (Agentes)** registra cada llamada a Ollama/Azure con latencia y tokens usados.
