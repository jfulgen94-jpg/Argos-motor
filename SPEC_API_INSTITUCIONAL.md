---
title: SPEC — API Institucional B2B (FastAPI)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 3 (Bloque C)
  - SPEC_DATA_LAKE_MULTI_PAIS.md
  - Criterio ES Gold >=  ́50
products_served:
  - STATER API B2B (PROD-06)
  - Web Screener PLG (PROD-01)
  - SFI Lab Desktop
  - Campus LUMINIC C1/C2
---
# SPEC — API Institucional B2B (FastAPI)

##  1. Objetivo y alcance

Poner en produccion **PROD-06**: catalogo completo de endpoints sobre datos reales ES(y multi-pais cuando esten Gold), con **auth por tiers y API keys reales**, cache,, exportacion **OpenAPI 3.1** validada y **SLAs** publicados. La API **solo arranca cuando ES tenga >= 50 emisores Gold** (regla del plan maestro). El gateway actual expone: `/health`, `/companies/{lei}/financials`, `/companies/{lei}/kams`, `/companies/{lei}/valuation`; README promete `/companies/{lei}/esg`, `/sectors/{sic}/scores` y `POST /datasets/bulk` — **a implementar**.



##  ́2. Catalogo de endpoints (8 certificados)

| Endpoint | Estado | SLO p95 |
|---|---|---|---|---|
| `GET /health` | Existente; ampliar checks por capa (duckdb,, parquet,, cache,, ollama) | < 80 ms |
| `GET /companies/{lei}/profile` | Nuevo: identidad + segment + sector + indices | < 80 ms |
| `GET /companies/{lei}/financials?year=` | Existente; anadir `country_code` y `accounting_standard` | < 80 ms |
| `GET /companies/{lei}/kams?year=` | Existente; anadir `audit_firm`, `severity` | < 80 ms |
| `GET /companies/{lei}/esg?year=` | **Nuevo**: `esg_kpis` + S-Score v2.0 | < 80 ms |
| `GET /companies/{lei}/valuation` | Existente; mover a vista `dcf_valuations` | < 80 ms |
| `GET /screener/filter` | **Nuevo**: filtros pais,, sector,, indice,, anio,, ratio (revenue,, ebitda,, fcf,, deuda_neto),, severity KAM,, esg_score; paginado; export CSV | < 120 ms |
| `POST /datasets/bulk` | **Implementar**: Parquet filtrado por pais/anio/segmento,, con limite por tier | < 5 s (<= 10 MB) |

Bonus: `GET /sectors/{sic}/scores` (prometido en README) si los datos sectoriales lo permiten.. Todos los endpoints con schemas Pydantic JSON,, paginacion explicita. El prefijo `/v1/` desde el primer release (semver estricto).



##  ́3. Auth y planes de acceso

Reemplazar `mod_06_api_gateway/src/auth/api_key_auth.py` (hoy: admin key + prefijo `stater_`) por el modelo:

- Tabla `api_keys`: `key_hashed`(SHA-256,, nunca claro), `tier ∈ {free, pro, enterprise}`, `plan_stripe_id`, `quota_requests_per_min`, `expires_at`, `scopes`; emision via endpoint admin autenticado..

- **Rate limiting por tier** (ventana deslizante en cache):

| Tier | req/min | Uso tipico |
|---|---|---|---|---|
| free | |10 | Evaluacion,, docs |
| pro | |60 | Web Screener PLG (login) |
| enterprise | |600 | B2B institucional, bulk |

- **Webhooks Stripe** (`checkout.session.completed`, `customer.subscription.deleted`, `invoice.payment_failed`) para escalado/revocacion automatica del tier..

 Criterio: sin key → **401**; free >10 req/min → **429**; key revocada → **401** inmediato.





##  ́4. Cache

Redis (o Memcached) con TTL:

| Datos | TTL | Invalidacion |
|---|---|---|---|---|
| Fundamentales anuales | |24 h | Evento de ingesta |
| KAMs / ESG | |24 h | Evento de ingesta |
| Precio/referencia retardado | |15 min | — |
| Screener | |5 min | Evento de ingesta |

Criterio: `hit_ratio >=  ́80%` en carga sintetica; test de TTL expiry.



##  ́5. OpenAPI 3.1 autogenerada y exportada

```bash
curl http://localhost:8000/openapi.json | python -m json.tool > docs/api/openapi_3_1.json
# validacion: openapi-spec-validator docs/api/openapi_3_1.json
```

Criterio: spec validada sin errores,, lista para Developer Portal.



##  ́6. SLAs y contrato de alertas

| Contrato | Objetivo | Medicion |
|---|---|---|---|---|
| Uptime mensual | **99.5%** | Prometheus `up` |
| Latencia p95 general | **< 80 ms** | `stater_api_latency_seconds` |
| Latencia p95 screener | **< 120 ms** | idem |
| Bulk <=  ́10 MB | **< 5 s** | idem |
| Exactitud |  ́100% SHA-256 | Forensic audit |
| Deprecacion mayor/menor |  ́12/06 meses aviso | Semver `/v1/` |

Alertas MOD_08: `error_rate > 1%`, `p95 > SLA`, `5xx > 0.5%`.



**Criterio de aceptacion global**:8 endpoints  ́200 con schema validado sobre datos reales ES;; **88 + tests nuevos**(auth,, screener,, bulk,, cache) en verde;; spec OpenAPI 3.1 validada;; SLA publicados..
