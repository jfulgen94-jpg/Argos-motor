# PLAN DE DESARROLLO — DESCARGA SEMANAL AL 100% (ES · DE · FR · IT · NL + EEUU)

**Fecha:** 2026-10-09 · **Base:** repo `Argos-motor` + auditoría Fases 0-3 (`audits/`, local, no versionado)
**Objetivo:** motor que, cada semana, descubre y descarga *cuentas anuales auditadas* e *informes de gestión* de las OAM públicas, sin duplicar y sin dejar archivos corruptos.

> Etiquetas: **[HECHO]** verificado en código o en prueba de Fase 3 · **[INFERENCIA]** deducción técnica · **[NO VERIFICADO]** requiere prueba contra la fuente real (Fase 3 no tocó internet).

---

## 0. PUNTO DE PARTIDA (qué tenemos y qué le pasa)

### Lo que ya funciona [HECHO]
| Pieza | Ruta | Qué aporta |
|---|---|---|
| Descargador robusto | `mod_01_ingestion/src/robust_downloader.py` | streaming, `.part`, `Range`, backoff+jitter, `Retry-After`, SHA-256 |
| Cliente ESEF | `mod_01_ingestion/src/xbrl_org_client.py` | API JSON:API de `filings.xbrl.org`, magic bytes `PK\x03\x04` |
| Clientes por OAM | `es_cnmv_client`, `de_bafin_client`, `fr_amf_client`, `it_consob_client`, `nl_afm_client`, `edgar_client` | un cliente por país/fuente |
| Enrutado | `source_router.py`, `oam_router.py` | canal determinista por (segmento, año, tipo) |
| Validación forense | `document_completeness_validator.py` | firma, ZIP, documento primario, estados contables |
| Sellado y manifiesto | `sha256_sealer.py`, `bundle_manager.py` | SHA-256, `manifest.json`, cuarentena, Zip-Slip protegido |
| Descargadores DE | `descarga/de_germany/*` | EQS, Bundesanzeiger, ESEF packages, IR crawlers |

### Lo que le pasa (defectos Fase 3) [HECHO]
1. `DEFECT-01` el validador **se cuelga** con `zlib.error` en ZIP corrupto.
2. `DEFECT-02` los 5xx se enmascaran como `CONNECTION_DROPPED` (se pierde el código HTTP).
3. `DEFECT-03` sin `flush/fsync` antes del `rename`.
4. `DEFECT-04` sin locks entre workers.
5. `DEFECT-05` `descarga/` escribe directo al destino final (sin `.part`).
6. `DEFECT-06` sin transacción raw↔manifiesto↔DuckDB (origen de las 1.449 rutas desincronizadas).
7. `DEFECT-07` sin almacenamiento por contenido (843 grupos duplicados, 14,12 GiB).
8. `DEFECT-08` sin `run_id`/`job_id`. `DEFECT-09` sin límite por dominio.
9. `argos.py download` solo enruta a **de, nl, es, fr** (falta **it** y **us**) y lo hace por `subprocess` a scripts de `descarga/`, no a `mod_01`.

### Lo que NO sabemos [NO VERIFICADO]
- Cobertura real hoy por país/año/tipo (falta un *ledger* esperado-vs-tenido).
- Comportamiento real de cada portal ante 304/429/403.
- Disponibilidad de ESEF para años < 2020 (ESEF obligatorio desde ejercicios 2020 en UE) → [INFERENCIA] antes de 2020 hay PDF/HTML, no iXBRL.

> **"100%" no es una afirmación, es una puerta medible:** `cobertura = documentos_validados / documentos_esperados` por (país, emisor, año, tipo). Solo se declara 100% cuando el ledger lo demuestre y el resto esté justificado como `NO_PUBLICADO` con evidencia.

---

## 1. ARQUITECTURA OBJETIVO COMÚN (vale para las tres opciones)

```
Universo (emisores) ─▶ Descubrimiento ─▶ Cola ─▶ Descarga(.part,fsync) ─▶ Validación
                                                                           │
          Ledger de cobertura ◀── Catálogo DuckDB ◀── Manifiesto ◀── Promoción atómica (CAS)
```
Reglas innegociables: una sola ruta (`mod_01`); `.part → fsync → validar → rename`; lock por `document_id`; límite por dominio; `run_id/job_id` en cada intento; nunca promover sin validar.

---

## 2. CÓMO "NO IR" — IMAGINAR EL FALLO Y BUSCAR SOLUCIÓN

| Qué imagino que pasa | Síntoma | Solución buscada |
|---|---|---|
| La OAM bloquea la IP por exceso de peticiones | 429/403 en bloque | límite por dominio, `Retry-After`, horario nocturno |
| El portal cambia el HTML | el scraper devuelve 0 resultados sin error | prueba *canario* semanal + alerta de "0 resultados" |
| Devuelve una página de error con extensión `.zip/.pdf` | archivo "válido" falso | firma mágica + estructura + cuarentena |
| Se corta la descarga a mitad | archivo final truncado | `.part` + `Range` + hash |
| Dos workers bajan lo mismo | corrupción / duplicado | lock por documento + CAS |
| Cae el proceso tras guardar, antes del manifiesto | huérfano en raw | transacción en dos fases / reconciliador |
| El documento se republica (corrección) | versión nueva con mismo `document_id` | versionado por SHA-256, no sobrescribir |
| El año no existe en la fuente | falso "hueco" eterno | estado `NO_PUBLICADO` con evidencia fechada |

---

## 3. OPCIÓN 1 — LÓGICA PURA ("como dicen los manuales")

**Idea:** cada OAM publica según su norma. Se usa la fuente *oficial y estructurada* de cada una, en orden de fiabilidad: **ESEF (`filings.xbrl.org`) para UE ≥ 2020**, **API oficial SEC** para EEUU, y **portal OAM nacional** para históricos y para lo que ESEF no cubre (PDF, informes de gestión, auditoría previa a 2020).

**Cómo funciona:** un *conector* por fuente con contrato único; un *runner* que aplica el ciclo completo y estricto.

```python
# core/contract.py  — contrato único de conector
from dataclasses import dataclass
from typing import Iterator, Protocol

@dataclass(frozen=True)
class Candidate:
    document_id: str          # estable: f"{country}:{lei_or_cik}:{year}:{doctype}"
    url: str
    country: str
    issuer_id: str            # LEI (UE) o CIK (US)
    period: str
    doctype: str              # CCAA_AUDITED | INFORME_GESTION | ESEF_PACKAGE | FORM_10K
    expected_mime: str
    source: str               # nombre del conector

class OamConnector(Protocol):
    name: str
    domains: tuple[str, ...]  # para el limitador por dominio
    def discover(self, issuer_id: str, year: int) -> Iterator[Candidate]: ...
```

```python
# connectors/esef_xbrl_org.py  — UE ≥2020 (ES, DE, FR, IT, NL)
import httpx
API = "https://filings.xbrl.org/api/filings"

class EsefConnector:
    name, domains = "ESEF_XBRL_ORG", ("filings.xbrl.org",)
    def __init__(self, client: httpx.Client): self.c = client
    def discover(self, lei, year):
        r = self.c.get(API, params={"filter[entity.identifier]": lei,
                                    "filter[period_end]": f"{year}-12-31"})
        r.raise_for_status()
        for f in r.json().get("data", []):
            a = f["attributes"]
            yield Candidate(f"EU:{lei}:{year}:ESEF_PACKAGE",
                            "https://filings.xbrl.org" + a["package_url"],
                            a.get("country", "EU"), lei, str(year),
                            "ESEF_PACKAGE", "application/zip", self.name)
```
> [NO VERIFICADO] los nombres exactos de los filtros; el cliente actual `xbrl_org_client.py` ya resuelve por LEI y es la referencia a reutilizar.

```python
# connectors/sec_edgar.py  — EEUU (API oficial, UA identificado, ≤10 req/s)
class SecConnector:
    name, domains = "SEC_EDGAR", ("data.sec.gov", "www.sec.gov")
    def discover(self, cik, year):
        j = self.c.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json").json()
        rec = j["filings"]["recent"]
        for i, form in enumerate(rec["form"]):
            if form in ("10-K", "20-F", "40-F") and rec["reportDate"][i].startswith(str(year)):
                acc = rec["accessionNumber"][i].replace("-", "")
                doc = rec["primaryDocument"][i]
                yield Candidate(f"US:{cik}:{year}:{form}",
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}",
                    "US", str(cik), str(year), "FORM_10K", "text/html", self.name)
```
```python
# core/runner.py  — ciclo estricto, un solo camino
def ingest(c: Candidate, ctx):
    with ctx.locks.document(c.document_id):                     # DEFECT-04
        if ctx.catalog.has(c.document_id): return "ALREADY_PRESENT"
        with ctx.limiter.domain(c.url):                         # DEFECT-09
            part = ctx.downloader.fetch(c.url, ctx.tmp / f"{c.document_id}.part")  # fsync inside
        v = ctx.validator.validate(part, c)                     # DEFECT-01 corregido
        if not v.ok:
            return ctx.quarantine(part, c, v.reasons)
        sha = ctx.cas.promote(part)                             # rename atómico a blobs/ab/cd/<sha>
        ctx.catalog.register(c, sha, run_id=ctx.run_id)         # manifiesto+DuckDB en 1 transacción
        return "PROMOTED"
```
**Ventajas:** simple, auditable, respeta cada norma. **Riesgo:** depende de que cada portal siga su documentación; los históricos pre-2020 y los informes de gestión no salen de ESEF.

---

## 4. OPCIÓN 2 — CREATIVA ("cómo viaja realmente el archivo de su servidor al nuestro")

**Idea:** en vez de *buscar* emisor a emisor, tratar cada OAM como un **flujo de publicaciones**: una OAM es un almacén que recibe presentaciones con fecha. Pedimos "qué hay de nuevo desde la última vez" (delta) con **peticiones condicionales** (`ETag`/`If-Modified-Since`) y bajamos solo lo nuevo. Se hace un **espejo incremental** semanal en lugar de recorrer todo el universo.

**Cómo viaja el archivo [INFERENCIA]:** emisor → agente/almacén autorizado de la OAM → índice público → URL de descarga (a menudo detrás de CDN). Nuestro cliente solo necesita: (1) leer el índice incremental, (2) resolver la URL final siguiendo redirecciones validadas por dominio, (3) descargar con `Range` y comprobar hash.

```python
# delta/mirror.py — sincronización incremental con caché condicional
import json, pathlib
STATE = pathlib.Path("state/etag_cache.json")

def conditional_get(client, url, cache):
    h = {}
    if (e := cache.get(url)):
        h["If-None-Match"] = e.get("etag", "")
        h["If-Modified-Since"] = e.get("last_modified", "")
    r = client.get(url, headers={k: v for k, v in h.items() if v})
    if r.status_code == 304:                    # DEFECT: hoy 304 se trata como EMPTY_FILE
        return None, "NOT_MODIFIED"
    r.raise_for_status()
    cache[url] = {"etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified")}
    return r, "CHANGED"

def weekly_delta(client, feed_url, since_iso, connector):
    cache = json.loads(STATE.read_text()) if STATE.exists() else {}
    r, st = conditional_get(client, feed_url, cache)
    STATE.write_text(json.dumps(cache))
    if st == "NOT_MODIFIED":
        return []
    return [connector.parse(item) for item in r.json()["data"]
            if item["attributes"]["processed"] >= since_iso]   # solo lo nuevo
```
```python
# validación de redirecciones (anti-desvío): solo dominios de la lista blanca por conector
ALLOWED = {"ESEF_XBRL_ORG": {"filings.xbrl.org"}, "SEC_EDGAR": {"www.sec.gov", "data.sec.gov"}}
def safe_final_url(resp, connector):
    host = resp.url.host
    if host not in ALLOWED[connector]:
        raise ValueError(f"redirección a dominio no permitido: {host}")
    if resp.url.scheme != "https":
        raise ValueError("degradación a HTTP")
```
**Ventajas:** carga mínima para la OAM (educado, menos riesgo de bloqueo), semanal barato, resuelve el 304 y la validación de redirecciones. **Riesgo:** exige que cada fuente tenga un índice con fecha de proceso [NO VERIFICADO para CNMV/AMF/CONSOB/AFM; ESEF y EDGAR sí lo tienen en principio]. Para las que no, hay que caer a Opción 1.

---

## 5. OPCIÓN 3 — IMAGINATIVA ("el descargador que yo construiría para nuestros servidores")

**Idea:** un **mensajero autónomo guiado por huecos**. No parte de "qué descargo hoy" sino de **"qué me falta"**. Mantiene un *ledger* `esperado vs tenido` por (país, emisor, año, tipo). Cada noche calcula los huecos, los prioriza, elige **la mejor fuente para cada hueco según su historial** (aprende de la telemetría) y cierra el ciclo con reconciliación. Lo que no existe se marca `NO_PUBLICADO` con evidencia — así "100%" tiene significado.

```python
# gap/ledger.py — cobertura como consulta SQL sobre DuckDB (sandbox-first)
GAPS_SQL = """
SELECT e.country, e.issuer_id, e.year, e.doctype
FROM expected e
LEFT JOIN documents d USING (country, issuer_id, year, doctype)
WHERE d.document_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM not_published n
                  WHERE n.country=e.country AND n.issuer_id=e.issuer_id
                    AND n.year=e.year AND n.doctype=e.doctype
                    AND n.checked_at > now() - INTERVAL 90 DAY)
ORDER BY e.priority DESC, e.year DESC
"""
```
```python
# gap/source_ranking.py — elegir fuente por historial (bandido simple, explicable)
import random
def pick_source(stats, sources, eps=0.1):
    """stats[s] = (éxitos, intentos). Explora con prob. eps, explota si no."""
    if random.random() < eps:
        return random.choice(sources)
    return max(sources, key=lambda s: (stats[s][0] + 1) / (stats[s][1] + 2))   # Laplace

# gap/scheduler.py — un ciclo nocturno
def nightly(ctx):
    for gap in ctx.db.execute(GAPS_SQL).fetchall():
        src = pick_source(ctx.stats(gap), ctx.sources_for(gap))
        res = ingest_gap(ctx, gap, src)               # reutiliza runner de Opción 1
        ctx.stats.update(src, ok=(res == "PROMOTED"))
        if res == "NOT_FOUND_ON_ALL_SOURCES":
            ctx.db.mark_not_published(gap, evidence=ctx.last_evidence)
    ctx.reconcile()                                    # raw ↔ manifiesto ↔ DuckDB (DEFECT-06)
    ctx.canary()                                       # 1 emisor conocido por fuente; alerta si 0
```
**Ventajas:** convierte "100%" en un número auditable; auto-prioriza; detecta portales rotos con canarios; reduce duplicados por CAS; encaja con el reconciliador que necesitamos para las 1.449 rutas. **Riesgo:** más piezas (ledger + universo esperado). El universo esperado por país es lo más difícil de obtener y [NO VERIFICADO] su completitud.

---

## 6. COMPARATIVA Y RECOMENDACIÓN

| Criterio | Op.1 Lógica | Op.2 Creativa | Op.3 Imaginativa |
|---|---|---|---|
| Esfuerzo | Bajo | Medio | Alto |
| Carga sobre la OAM | Media | **Mínima** | Baja |
| Demuestra el "100%" | No | No | **Sí** |
| Cubre históricos | Sí (portales) | Parcial | Sí |
| Depende de índices con fecha | No | **Sí** | No |
| Resuelve 304/redirecciones | No | **Sí** | Vía Op.2 |

**Recomendación (híbrido por capas):** Op.1 como **núcleo** (contrato + runner + defectos corregidos), Op.2 como **modo semanal incremental** donde exista índice, Op.3 como **capa de gobierno** (ledger, huecos, canarios, reconciliación). Orden de construcción: 1 → 3 → 2.

---

## 7. HOJA DE RUTA POR PAÍS

| País | Fuente primaria | Fallback | Observaciones |
|---|---|---|---|
| ES | ESEF (`filings.xbrl.org`) ≥2020 | CNMV (cliente `es_cnmv_client`) | CNMV para 2019-2020 pre-ESEF e informes de gestión |
| DE | ESEF ≥2020 | Bundesanzeiger / EQS / IR | scripts `descarga/de_germany/*` a migrar; sesión Wicket [NO VERIFICADO] |
| FR | ESEF ≥2020 | AMF BDIF (`fr_amf_client`) | URD/DEU pre-ESEF vía AMF |
| IT | ESEF ≥2020 | CONSOB / storage autorizado (`it_consob_client`) | **no está en `argos.py`**; verificar acceso |
| NL | ESEF ≥2020 | AFM (`nl_afm_client`) | **no es cierto que AFM publique el documento**: [NO VERIFICADO], depende de ESEF |
| US | SEC API oficial (`edgar_client`) | — | UA identificado, ≤10 req/s; 10-K/20-F/40-F |

## 8. FASES, ENTREGABLES Y PUERTAS

| Fase | Contenido | Puerta de salida |
|---|---|---|
| 4A | Corregir DEFECT-01/02/03 (parches mínimos, con tests de Fase 3 como regresión) | T08 y T14 pasan a PASS |
| 4B | `LockManager`, `DomainRateLimiter`, `run_id/job_id` | T20/T21/T26 pasan a PASS |
| 4C | CAS + transacción raw↔manifiesto↔DuckDB + reconciliador | las 1.449 rutas reconciliadas en sandbox; 0 huérfanos |
| 5 | Contrato `OamConnector` + migrar ES y US (los más estables) | ciclo T01 real en **entorno controlado** con autorización |
| 6 | Migrar DE, FR, IT, NL; deprecar `descarga/` | `argos.py download` cubre los 6 mercados |
| 7 | Ledger de cobertura + canarios + modo delta semanal | informe de cobertura por país; "100%" o `NO_PUBLICADO` justificado |
| 8 | Programación semanal (cron) + alertas | 4 semanas consecutivas sin intervención |

**Reglas de seguridad para pasar a red real (Fase 5+):** autorización expresa, User-Agent identificado, respetar `robots.txt`/términos y `Retry-After`, límites por dominio, sin credenciales en el repo.

---

## 9. LISTADO DE REPOSITORIOS — DESCARGA AUTOMÁTICA DE INFORMES (GESTIÓN Y CUENTAS ANUALES)

*Datos (estrellas, última actividad, licencia) consultados vía API pública de GitHub el 2026-10-09. Ningún repo se ha ejecutado ni incorporado como código.*

### 9.1 Ya clonados localmente (en `tools/`, ignorados por Git)
| Repo | ★ | Último push | Licencia | Para qué |
|---|---|---|---|---|
| [bundesAPI/deutschland](https://github.com/bundesAPI/deutschland) | 1423 | 2026-04-28 | Apache-2.0 | APIs públicas alemanas (Bundesanzeiger incluido) |
| [tfbecker/european-company-registers](https://github.com/tfbecker/european-company-registers) | 2 | 2026-07-09 | MIT | Registros DE/FR/PL/UK, CLI + agente |

### 9.2 EEUU (SEC)
| Repo | ★ | Último push | Licencia | Notas |
|---|---|---|---|---|
| [dgunning/edgartools](https://github.com/dgunning/edgartools) | 2780 | 2026-10-08 | MIT | descarga + parseo 10-K/XBRL; throttling y caché |
| [jadchaar/sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader) | 716 | 2026-06-22 | MIT | descarga simple por ticker/CIK |
| [psachdev/sec_data_downloader](https://github.com/psachdev/sec_data_downloader) | 2 | 2026-09-27 | — | batch 10-K (baja madurez) |

### 9.3 Europa (ESEF / XBRL)
| Repo | ★ | Último push | Licencia | Notas |
|---|---|---|---|---|
| [European-Securities-Markets-Authority/esef_toolkit](https://github.com/European-Securities-Markets-Authority/esef_toolkit) | 9 | 2025-09-25 | EUPL-1.2 | oficial ESMA; **lectura/extracción**, no descarga masiva [INFERENCIA] |
| [Arelle/Arelle](https://github.com/Arelle/Arelle) | 251 | 2026-10-09 | NOASSERTION | motor XBRL de referencia |
| [manusimidt/py-xbrl](https://github.com/manusimidt/py-xbrl) | 154 | 2026-09-13 | GPL-3.0 | parser XBRL/iXBRL (¡GPL!) |
| [ggravlingen/pyesef](https://github.com/ggravlingen/pyesef) | 13 | 2026-01-03 | MIT | extrae datos de ESEF |
| [reeyarn/openesef](https://github.com/reeyarn/openesef) | 10 | 2026-07-12 | — | manejo ESEF en Python |
| [selgamal/xbrl-reports-indexes](https://github.com/selgamal/xbrl-reports-indexes) | 2 | 2024-02-10 | — | índice de filings ESEF y SEC (solo metadatos) |
| [pipeworx-io/mcp-esef-filings](https://github.com/pipeworx-io/mcp-esef-filings) | 1 | 2026-09-30 | — | envoltorio MCP de `filings.xbrl.org` |
| [financial-reports/financial-reports-mcp-server](https://github.com/financial-reports/financial-reports-mcp-server) | 2 | 2026-10-09 | — | servidor MCP comercial de filings regulatorios |

### 9.4 Alemania (Bundesanzeiger)
| Repo | ★ | Último push | Notas |
|---|---|---|---|
| [dre808/bundesanzeiger-scraper](https://github.com/dre808/bundesanzeiger-scraper) | 9 | 2024-07-02 | balances y cuentas; puede estar roto por cambios del portal |
| [tom-finance/short_seller](https://github.com/tom-finance/short_seller) | 3 | 2020-09-12 | DE (Bundesanzeiger) e IT (Consob), solo posiciones cortas; obsoleto |
| [themineworks/bundesanzeiger-scraper](https://github.com/themineworks/bundesanzeiger-scraper) | 0 | 2026-10-07 | cliente de servicio de pago (Apify) — **no recomendable** |

### 9.5 Genéricos
| Repo | ★ | Último push | Notas |
|---|---|---|---|
| [calogerobra/scraper_annual_reports](https://github.com/calogerobra/scraper_annual_reports) | 8 | 2021-01-07 | plantilla de descarga masiva de PDF; sin licencia declarada |

### 9.6 Huecos detectados
- **ES (CNMV), FR (AMF/BDIF), IT (CONSOB), NL (AFM):** la búsqueda en GitHub **no devolvió** repos específicos y mantenidos. [HECHO sobre la búsqueda realizada; no prueba que no existan]. Estos cuatro conectores dependen del código propio de `mod_01`.
- Una afirmación previa de la búsqueda web citaba `xbrl-filings-api` (`fitnr/...`) y otros slugs: **no existen en esa ruta (404)**; se descartan hasta verificar el nombre correcto.

### 9.7 Cautelas de licencia
Antes de **reutilizar código** (no solo de usarlo como referencia): `py-xbrl` es GPL-3.0 (copyleft); `Arelle` figura como NOASSERTION; varios repos no declaran licencia. Usar como referencia o dependencia externa, no copiar.

---

## 10. QUÉ NECESITO DE TI PARA PASAR A EJECUCIÓN
1. Autorización expresa para tocar código productivo (Fase 4A).
2. Decisión: ¿híbrido recomendado (1 → 3 → 2) o una sola opción?
3. Autorización explícita y alcance para las primeras pruebas contra red real (Fase 5).
4. Fuente del **universo esperado** por país (¿`bluechips_universe.json` y catálogos existentes bastan?).
