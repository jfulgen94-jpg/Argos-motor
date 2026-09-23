# PROMPT PARA OPENHANDS (GEMINI 3.5 PRO): VERIFICADOR Y CRAWLER ASÍNCRONO EQS / DGAP
## Proyecto: STATER / ARGOS MOTOR — Extracción Masiva de Enlaces Verificados EQS (Alemania)

Eres el Ingeniero Senior de Scraping Distribuido e Ingesta Financiera de STATER.
Tu misión es ejecutar en tu entorno Docker de Linux un verificador ultrarrápido y asíncrono que valide todos los informes anuales oficiales disponibles en el servidor regulatorio de **EQS Group (antigua DGAP)** para las 172 empresas del universo Prime Standard de Alemania (2012–2025).

---

### 1. CONTEXTO Y TRABAJO PREVIO DE QWEN CODER

1. **Estrategia Tri-Agente STATER**:
   - **Qwen Coder (Agente 1)**: Ya analizó las 172 empresas del universo y generó el archivo de configuración `ARGOS_MOTOR/config/eqs_company_slugs.json`. Incorporó una tabla de alias históricos por ISIN (ej. Daimler para Mercedes-Benz, eads para Airbus, HeidelbergCement para Heidelberg Materials, flatex para flatexDEGIRO), normalización fonética alemana (`ä->ae`, `ö->oe`, `ü->ue`, `ß->ss`) y eliminación de sufijos legales.
   - **OpenHands / Gemini 3.5 Pro (Agente 2 - TÚ)**: Validas con peticiones HTTP `HEAD` concurrentes cuáles de esos enlaces existen con código `200 OK` en el servidor de EQS, compilando el archivo `ARGOS_MOTOR/config/eqs_verified_links.json`.
   - **Antigravity (Agente 3 - Local)**: Descargará concurrentemente los archivos binarios reales a disco masivo `D:/ARGOS_DATA/raw/DE_BAFIN/`, sellará los hashes SHA-256, generará los metadatos forenses y actualizará los manifiestos de auditoría de 2012–2025.

2. **Arquitectura del Repositorio Regulatorio EQS**:
   Por mandato de la ley alemana de mercados (*WpHG*), las cuentas anuales de los emisores cotizados se alojan en:
   `https://irpages2.eqs.com/Download/Companies/{CompanySlug}/Annual%20Reports/{ISIN}-JA-{Year}-{Lang}-{Version}.pdf`

   - **{CompanySlug}**: Nombre corporativo registrado en EQS (ej. `BASF`, `Daimler`, `Siemens`, `eads`, `Volkswagen`, etc.).
   - **{ISIN}**: Código ISIN oficial de 12 caracteres (ej. `DE000BASF111`, `NL0000235190`).
   - **{Year}**: Año contable auditado (`2012` a `2025`).
   - **{Lang}**: `EQ-D` (Alemán, prioritario por mandato legal) o `EQ-E` (Inglés, utilizado por multinacionales como Airbus o Qiagen).
   - **{Version}**: Variante documental (`00` o `01`).

   Las cabeceras HTTP redirigen con `301/302` a `https://ir-api.eqs.com/media/document/...` con estado final `200 OK` y `Content-Type: application/pdf`.
   **Ventaja crítica**: No hay CAPTCHA, ni sesión Wicket, ni bloqueo de IP. Las peticiones `HEAD` resuelven en ~100-200 ms sin consumir ancho de banda de descarga.

---

### 2. PASOS DE EJECUCIÓN INMEDIATA (PROTOCOLO LLAVE EN MANO)

Ejecuta secuencialmente los siguientes comandos en tu terminal de Linux:

#### Paso 1: Sincronizar el repositorio con la rama principal
```bash
git fetch origin main
git checkout main
git pull origin main
```

#### Paso 2: Instalar la dependencia de red asíncrona
```bash
pip install httpx
```

#### Paso 3: Ejecutar el crawler asíncrono preconfigurado
El script ya está testeado y versionado en el repositorio:
```bash
python ARGOS_MOTOR/descarga/de_germany/crawler_eqs_async.py
```

*Detalles técnicos del script:*
- Utiliza `httpx.AsyncClient` con un semáforo de concurrencia de **25 conexiones simultáneas**.
- Prueba los 14 años (2012–2025) para las 172 empresas (~2.400 combinaciones) en solo 20–45 segundos.
- Evalúa ordenadamente la lista de slugs generada por Qwen Coder, primero en alemán (`EQ-D`) y luego en inglés (`EQ-E`), en versiones `00` y `01`.
- Guarda automáticamente la base de datos de enlaces verificados en:
  - `ARGOS_MOTOR/config/eqs_verified_links.json`
  - `scratch/eqs_verified_links.json`

---

### 3. CÓDIGO FUENTE DE RESPALDO (`crawler_eqs_async.py`)

Si por alguna razón prefieres crearlo o ejecutarlo directamente desde `scratch/`, este es el código íntegro del script:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("ERROR: httpx es requerido. Instálalo con: pip install httpx")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("eqs_crawler")

ROOT = Path(__file__).resolve().parents[2]
SLUGS_FILE = ROOT / "config" / "eqs_company_slugs.json"
OUTPUT_CONFIG = ROOT / "config" / "eqs_verified_links.json"
OUTPUT_SCRATCH = ROOT.parent / "scratch" / "eqs_verified_links.json"

YEARS = list(range(2012, 2026))
LANGUAGES = ["EQ-D", "EQ-E"]
VERSIONS = ["00", "01"]
CONCURRENCY = 25
TIMEOUT = 7.0

async def verify_target(client, semaphore, ticker, isin, slugs, year):
    async with semaphore:
        for slug in slugs:
            for lang in LANGUAGES:
                for ver in VERSIONS:
                    url = f"https://irpages2.eqs.com/Download/Companies/{slug}/Annual%20Reports/{isin}-JA-{year}-{lang}-{ver}.pdf"
                    try:
                        resp = await client.head(url)
                        if resp.status_code == 200:
                            ctype = resp.headers.get("content-type", "").lower()
                            if "pdf" in ctype or "octet-stream" in ctype or not ctype:
                                clen = resp.headers.get("content-length")
                                return {
                                    "year": str(year),
                                    "source_url": url,
                                    "resolved_url": str(resp.url),
                                    "slug": slug,
                                    "lang": lang,
                                    "version": ver,
                                    "size_bytes": int(clen) if clen and clen.isdigit() else 0,
                                }
                    except Exception:
                        pass
    return None

async def crawl_company(client, semaphore, ticker, info, existing_reports):
    isin = info.get("isin", "").strip()
    slugs = info.get("slugs", [])
    if not isin or not slugs:
        return ticker, existing_reports

    company_reports = dict(existing_reports)
    tasks = []
    years_to_check = [y for y in YEARS if str(y) not in company_reports]
    for y in years_to_check:
        tasks.append(verify_target(client, semaphore, ticker, isin, slugs, y))

    results = await asyncio.gather(*tasks)
    for res in results:
        if res:
            company_reports[res["year"]] = res
    return ticker, company_reports

async def main_async():
    start_time = time.time()
    logger.info("=== STATER / ARGOS MOTOR — EQS ASYNC CRAWLER ===")
    if not SLUGS_FILE.exists():
        logger.error(f"No se encuentra el archivo de slugs: {SLUGS_FILE}")
        return

    data = json.loads(SLUGS_FILE.read_text(encoding="utf-8"))
    companies = data.get("companies", {})
    total_companies = len(companies)
    logger.info(f"Cargadas {total_companies} empresas desde {SLUGS_FILE}")

    verified_db = {}
    if OUTPUT_CONFIG.exists():
        try:
            prev = json.loads(OUTPUT_CONFIG.read_text(encoding="utf-8"))
            verified_db = prev.get("companies", {})
            logger.info(f"Cargadas {len(verified_db)} empresas previas en caché.")
        except Exception:
            pass

    semaphore = asyncio.Semaphore(CONCURRENCY)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
    }
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=TIMEOUT, limits=limits) as client:
        tasks = [
            crawl_company(client, semaphore, ticker, info, verified_db.get(ticker, {}).get("reports", {}))
            for ticker, info in companies.items()
        ]
        logger.info(f"Iniciando crawling asíncrono ({CONCURRENCY} peticiones simultáneas)...")
        results = await asyncio.gather(*tasks)

        for ticker, reports in results:
            info = companies[ticker]
            verified_db[ticker] = {
                "isin": info.get("isin", ""),
                "name": info.get("name", ""),
                "slugs": info.get("slugs", []),
                "reports_count": len(reports),
                "reports": reports,
            }

    year_stats = {str(y): 0 for y in YEARS}
    total_hits = 0
    companies_with_hits = 0

    for ticker, cinfo in verified_db.items():
        reps = cinfo.get("reports", {})
        if reps:
            companies_with_hits += 1
            for y in reps:
                if y in year_stats:
                    year_stats[y] += 1
                    total_hits += 1

    payload = {
        "_metadata": {
            "crawled_at": datetime.utcnow().isoformat() + "Z",
            "total_companies_checked": total_companies,
            "companies_with_hits": companies_with_hits,
            "total_verified_filings": total_hits,
            "years_range": f"{YEARS[0]}-{YEARS[-1]}",
            "year_stats": year_stats,
        },
        "companies": verified_db,
    }

    OUTPUT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CONFIG.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Guardado catálogo verificado -> {OUTPUT_CONFIG}")

    try:
        OUTPUT_SCRATCH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_SCRATCH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"CRAWLER FINALIZADO en {elapsed:.1f}s")
    logger.info(f"Empresas con informes verificados: {companies_with_hits} / {total_companies} ({companies_with_hits/total_companies*100:.1f}%)")
    logger.info(f"Total de informes 200 OK encontrados: {total_hits}")
    logger.info("Desglose anual:")
    for y in sorted(year_stats.keys()):
        cnt = year_stats[y]
        pct = (cnt / total_companies) * 100
        logger.info(f"  {y}: {cnt:3d} empresas ({pct:4.1f}%)")
    logger.info("=" * 65)

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
```

---

### 4. SUBIDA DE RESULTADOS A GITHUB (CIERRE DE TAREA)

Una vez termine la ejecución del crawler:

1. Comprueba que el archivo generado existe y tiene contenido:
   ```bash
   ls -lh ARGOS_MOTOR/config/eqs_verified_links.json
   ```

2. Haz commit y push del catálogo a GitHub:
   ```bash
   git add ARGOS_MOTOR/config/eqs_verified_links.json
   git commit -m "feat(de_germany): registrar catalogo de enlaces anuales verificados 2012-2025 en EQS"
   git push origin main
   ```

3. Imprime en el reporte final la tabla resumen de informes encontrados por año.
