---
title: SPEC — Infraestructura y Observabilidad (Ops)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 5/6 (Bloque E)
  - SPEC_DATA_LAKE_MULTI_PAIS.md
products_served:
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - Data Lake ARGOS (capa Gold)
---
# SPEC — Infraestructura y Observabilidad (Ops)

##  1. Objetivo y alcance

Construir desde cero la capa **container/k8s que no existe** en el repo(verificado: no hay Dockerfile,, docker-compose,, Helm ni k8s) y el sistema de **observabilidad de produccion**: panel de salud del Data Lake,, deteccion de restatements,, scheduler de descargas,, CI/CD endurecido y backup cifrado. Objetivos: detectar y reaccionar en **< 15 min** a cualquier filing nuevo;; ingesta completa en **< 4 h**.



##  ́2. Contenedores y orquestacion

1. **Dockerfile multi-stage** (python 3.12-slim) para API(FastAPI/uvicorn) y jobs de ingesta;
2. **docker-compose**: `api`, `db` (DuckDB), `redis`, `prometheus`, `grafana`;
3. **Kubernetes/Helm** — crear `deploy/helm/argos/` desde cero:`values.yaml` con **dev/staging/prod**; Deployments `api`, `ingestion-cron`, `dashboard`;; Services,, Ingress,, **HPA** (hasta 500 usuarios); Secrets via **ExternalSecrets/Vault**..

 Criterio: `docker compose up` → `/health`  200 y **88 tests pasan en el contenedor test**;; `helm lint` sin errores y `helm template` renderiza los 3 entornos sin secretos hardcodeados..



##  ́3. CI/CD y secretos

Endurecer `infra/github_actions/ci_pipeline.yml`:

- **Gate**: `python -m pytest ARGOS_MOTOR/ -q` → **>= 88 passed antes de merge a main**;
- Jobs: lint (black,, mypy), build imagen,, push registry,, deploy staging/prod;
- `.env.example` por entorno;; secretos en GitHub Secrets o Vault (**nunca** en el repo);
- **`gitleaks` scan sin leak** (CI gate.

 Criterio: PR con tests fallidos se bloquea;; merge solo con suite verde;; gitleaks limpio.



##  ́4. Backup del Data Lake

- Snapshot Parquet diario:`vYYYYMMDD`; retencion **90 dias**; cifrado en reposo (**AES-256 via KMS o `age`**); test de restore **mensual** documentado..
 Criterio: snapshot automatico existente y un test de restore ejecutado y documentado..



##  ́5. Panel de salud del Data Lake (Grafana + Prometheus)

Dashboards JSON versionados en `deploy/grafana/dashboards/`:

- Emisores `fully_covered` por pais;
- % cobertura documental por pais;
- Alertas de gap: emisor sin CCAA hace >  180 dias tras cierre;
- Errores de descarga por canal: `stater_documents_ingested_total`, `stater_parse_errors_total`, `stater_balance_quarantines_total` (ya en `mod_08_monitor/src/metrics.py`);
- Latencia API:`stater_api_latency_seconds`(P50/P95/P99.

 Criterio: dashboard importado en Grafana de staging con datos reales. Metricas base verificadas: 7 contadores/histogramas Prometheus.



##  ́6. Deteccion de restatements y cambios de criterio

Modulo que compara cada filing nuevo contra el comparativo del ejercicio previo del mismo emisor:

1. Fila `financial_facts_raw` T vs T-1 contra `is_restated=FALSE`;
2. Linea difiere > **5%** sin `is_restated` explicito → **alerta forense** (`alertas_restatement` con `severity`, `delta_pct`, `campos_afectados`);
3. Restatement publicado → `is_restated=TRUE` (append-only.

 Criterio: test: fixture modificado >5% → alerta;; <5% → no alerta.



##  ́7. Scheduler de descargas programadas

Cron jobs (K8s CronJob o APScheduler):

- **ESEF anual**: ventana enero-abril;
- **IPP/trimestral**: Q1-Q4 por pais;
- **Sin colisionar** con ventanas de carga de API regulatoria (definidas por pais en las specs de ingesta); polling 15 min contra `filings.xbrl.org` (endpoint JSON:API.

 Criterio: `stater_documents_ingested_total` crece en cada ejecucion esperada,, sin solapamiento por canal..



##  ́8. Criterios operativos

- **Alerting**: alerta si `time_since_last_filing >  180 days` por emisor;
- **Ingesta automatica** (< 4 h: descarga,, parseo,, validacion,, carga Gold) al detectar filing nuevo;
- **SLO**: deteccion < 15 min;; ingesta < 4 h (staging.

**Criterio de aceptacion global**: `docker compose up` + CI verdes;; helm lint/template OK;; backup con retencion y cifrado verificado;; Grafana poblado con datos reales ES;; alertas gap/restatement con tests;; scheduler operativo;; SLO  15 min /  ́4 h en staging..
