#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Crawler y Verificador Asíncrono EQS / DGAP (Alemania)
=============================================================================
Verifica la existencia de cuentas anuales históricas (2012–2025) en el repositorio
regulatorio de EQS Group para las 172 empresas de Prime Standard de Alemania.

No requiere CAPTCHA ni navegación pesada (Wicket session). Emplea peticiones HEAD
asíncronas concurrentes con redirección automática 301/302 a `ir-api.eqs.com`.

Entrada:  ARGOS_MOTOR/config/eqs_company_slugs.json
Salida:   ARGOS_MOTOR/config/eqs_verified_links.json
          scratch/eqs_verified_links.json (fallback/scratch)
"""

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eqs_crawler")

ROOT = Path(__file__).resolve().parents[2]
SLUGS_FILE = ROOT / "config" / "eqs_company_slugs.json"
OUTPUT_CONFIG = ROOT / "config" / "eqs_verified_links.json"
OUTPUT_SCRATCH = ROOT.parent / "scratch" / "eqs_verified_links.json"

YEARS = list(range(2012, 2026))  # 2012 a 2025 inclusive
LANGUAGES = ["EQ-D", "EQ-E"]    # Alemán prioritario (mandato WpHG), inglés alternativo
VERSIONS = ["00", "01"]         # Variantes de archivo EQS
CONCURRENCY = 25                # Semáforo asíncrono
TIMEOUT = 7.0                   # Timeout HEAD en segundos


async def verify_target(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    ticker: str,
    isin: str,
    slugs: List[str],
    year: int,
) -> Optional[Dict]:
    """Prueba candidatos para un (ticker, isin, year) ordenadamente."""
    async with semaphore:
        for slug in slugs:
            for lang in LANGUAGES:
                for ver in VERSIONS:
                    url = f"https://irpages2.eqs.com/Download/Companies/{slug}/Annual%20Reports/{isin}-JA-{year}-{lang}-{ver}.pdf"
                    try:
                        resp = await client.head(url)
                        if resp.status_code == 200:
                            ctype = resp.headers.get("content-type", "").lower()
                            # Aceptamos PDF directo o tipo genérico octet-stream
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


async def crawl_company(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    ticker: str,
    info: Dict,
    existing_reports: Dict[str, Dict],
) -> Tuple[str, Dict[str, Dict]]:
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
            y = res["year"]
            company_reports[y] = res

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

    # Cargar enlaces verificados previos si existen (idempotencia)
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
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=TIMEOUT,
        limits=limits,
    ) as client:
        company_tasks = []
        for ticker, info in companies.items():
            existing = verified_db.get(ticker, {}).get("reports", {})
            company_tasks.append(
                crawl_company(client, semaphore, ticker, info, existing)
            )

        logger.info(f"Iniciando crawling asíncrono ({CONCURRENCY} peticiones simultáneas)...")
        results = await asyncio.gather(*company_tasks)

        # Compilar base de datos
        for ticker, reports in results:
            info = companies[ticker]
            verified_db[ticker] = {
                "isin": info.get("isin", ""),
                "name": info.get("name", ""),
                "slugs": info.get("slugs", []),
                "reports_count": len(reports),
                "reports": reports,
            }

    # Estadísticas por año
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

    # Guardar en config oficial y en scratch
    OUTPUT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CONFIG.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Guardado catálogo verificado -> {OUTPUT_CONFIG}")

    try:
        OUTPUT_SCRATCH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_SCRATCH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Guardado scratch verificado -> {OUTPUT_SCRATCH}")
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
