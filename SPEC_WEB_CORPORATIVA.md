---
title: SPEC — Web Corporativa PLG (Next.js)
version: 1.0
status: approved
owner: STATER Financial Technologies (Ingeniería ARGOS)
last_updated: 2026-09-07
depends_on:
  - PLAN_MAESTRO_ARGOS_v1.md
  - Fase 4 (Bloque D)
  - SPEC_API_INSTITUCIONAL.md
  - Criterio ES Gold >=  ́50
products_served:
  - Web Screener PLG (PROD-01)
  - Developer Portal
  - Campus LUMINIC C1/C2
---
# SPEC — Web Corporativa PLG (Next.js)

##  1. Objetivo y alcance

Poner en produccion **PROD-01**: web corporativa con hub de productos,, Developer Portal y **Web Screener gratuito** como estrella PLG, operativa con **datos reales desde el dia 1** (cero screenshots simulados,, cero datos hardcodeados). La web consume **solo** la API ARGOS real; si no hay datos para un filtro,, muestra vacio explicito(no rellena con JSON estatico.



##  ́2. Arquitectura

| Decision | Eleccion |
|---|---|---|---|
| Framework | Next.js 15 (App Router) + TypeScript |
| Estilos | Tailwind CSS |
| Despliegue | Vercel (CDN global); preview por PR |
| Dominio canonico | `stater.financial` |
| Repo | Nueva carpeta `web/` en el monorepo |
| Fuente de datos | Solo API ARGOS (prohibido embeder JSON estatico) |

Criterio: `web/` con `npm run build` exitoso y desplegado en preview Vercel.



##  ́3. Estructura de paginas y navegacion

| Ruta | Contenido |
|---|---|---|
| `/` | Landing (mensaje: *"Bloomberg para todos, auditable y trazable"*); CTA al Web Screener |
| `/productos` | Hub: Web Screener,, SFI Lab Desktop,, Campus LUMINIC C1/C2 |
| `/developers` | API docs,, datasets Parquet,, acceso al tier Free (key `free`) |
| `/investigacion` | Papers: KAM vs retornos,, TFM UMU |
| `/empresa` | Mision,, equipo,, RGPD,, aviso legal |
| `/precios` | Tabla: Free / Pro  12 €/mes / Institucional |
| `/screener` | Web Screener embebido (PROD-01) |

Criterio: **0 dead links** (linkinator o sitemap validado en CI).



##  ́4. PROD-01 — Web Screener embebido

Misma especificacion que `GET /screener/filter`:

- **Filtros**: Pais,, Sector,, Indice,, Anio,, Ratio (revenue,, ebitda,, fcf,, deuda_neto),,, Riesgo KAM,, Score ESG;
- **Resultados**: tabla exportable a CSV; ficha por emisor con graficos historicos(3 ejercicios;
- **Modo anonimo** (sin login): indices libres — IBEX 35 + CAC 40 + DAX 30;
- **Modo Pro** (login): universo completo.



Criterio: anonimo → exactamente indices free;; Pro → universo completo al autentificarse. Tests e2e Playwright verifican ambos modos..



##  ́5. Autenticacion web

- **Stack**: Clerk(NextAuth) con JWT + OAuth Google/GitHub + magic link;
- **Vinculacion**: login Pro → emision de API key `pro` via la API admin (Bloque C);
- **Seguridad**: nunca keys en localStorage;; llamadas Pro via server-side (BFF).

 Criterio: flujo e2e login → key → llamada a API con tier correcto verificado en staging.



##  ́6. Calidad: CWV,, SEO,, WCAG

| Dimension | Contrato | Medicion |
|---|---|---|---|---|
| Core Web Vitals | LCP < 2.5 s; CLS < 0.1; FID <  100 ms | Lighthouse CI |
| SEO | sitemap.xml,, canonical tags,, schema.org `FinancialProduct` | Lighthouse |
| Accesibilidad | WCAG 2.1 AA | axe-core en CI |

Criterio: Lighthouse >= **90** en performance/SEO/accessibility en CI.



**Criterio de aceptacion global**: web en preview Vercel conectada unicamente a datos reales de la API;; CWV/SEO/WCAG verificado en CI;; login Pro vinculado a tiers de API keys;; 0 dead links..
