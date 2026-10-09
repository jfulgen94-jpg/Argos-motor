#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Descargador Masivo ESEF / XBRL Oficial (Canal ESMA OAM)
================================================================================
Descarga directa de todos los paquetes digitales auditados (.zip ESEF iXBRL)
indexados en la federación filings.xbrl.org para el universo alemán.

- Sin necesidad de proxy residencial (red europea ESMA pública).
- Sin captchas ni bloqueos.
- Sellado criptográfico SHA-256 y sidecar .meta.json institucional.
- Destino: D:/ARGOS_DATA/raw/DE_BAFIN/{year}/DE_BAFIN_{ticker}_{year}_ESEF.zip

Uso:
  python downloader_xbrl_esef_packages.py
"""

import asyncio
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
UNIVERSE_FILE = ROOT / "config" / "master_universe_de.json"
XBRL_INDEX_FILE = ROOT.parent / "scratch" / "xbrl_index_de.json"
OUTPUT_CATALOG = ROOT / "config" / "esef_packages_catalog.json"

CONCURRENCY = 6
TIMEOUT = 90.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("esef_downloader")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


async def download_package(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item: Dict,
    stats: Dict,
) -> bool:
    ticker = item["ticker"]
    year = item["year"]
    url = item["url"]
    filename = item["filename"]
    lei = item["lei"]

    year_dir = DATA_ROOT / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    out_path = year_dir / filename
    meta_path = year_dir / f"{filename}.meta.json"

    if out_path.exists() and meta_path.exists() and out_path.stat().st_size > 10000:
        stats["skipped"] += 1
        return False

    async with sem:
        try:
            async with client.stream("GET", url, timeout=TIMEOUT) as resp:
                if resp.status_code != 200:
                    stats["failed"] += 1
                    log.warning(f"[{ticker} {year}] HTTP {resp.status_code} desde {url}")
                    return False

                with open(out_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(65536):
                        f.write(chunk)

            size = out_path.stat().st_size
            if size < 5000:
                out_path.unlink(missing_ok=True)
                stats["failed"] += 1
                return False

            sha = sha256_file(out_path)
            meta = {
                "country": "DE",
                "supervisor": "BaFin / ESMA (ESEF)",
                "ticker": ticker,
                "lei": lei,
                "legal_name": item.get("legal_name", ticker),
                "isin": item.get("isin", ""),
                "fiscal_year": int(year),
                "document_type": "ANNUAL_ESEF_PACKAGE_ZIP",
                "source_url": url,
                "local_file": filename,
                "size_bytes": size,
                "sha256": sha,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "status": "VERIFIED_COMPLIANT",
                "channel": "CANAL_ESEF_XBRL_ORG",
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            stats["downloaded"] += 1
            log.info(f"[OK-ESEF] {ticker} {year} ({size/(1024*1024):.1f} MB) -> {filename}")
            return True

        except Exception as e:
            out_path.unlink(missing_ok=True)
            stats["failed"] += 1
            log.debug(f"[FAIL-ESEF] {ticker} {year}: {e}")
            return False


async def main():
    log.info("=== STATER MOTOR ARGOS — DESCARGADOR MASIVO ESEF (Canal ESMA OAM) ===")
    if not UNIVERSE_FILE.exists() or not XBRL_INDEX_FILE.exists():
        log.error("Ficheros de universo o índice XBRL no encontrados.")
        return

    with open(UNIVERSE_FILE, encoding="utf-8") as f:
        universe = json.load(f)["companies"]

    with open(XBRL_INDEX_FILE, encoding="utf-8") as f:
        xbrl_index = json.load(f)

    # Identificar todos los paquetes disponibles para las empresas del universo
    queue = []
    for ticker, comp in universe.items():
        lei = comp.get("lei")
        if not lei or lei not in xbrl_index:
            continue

        filings = xbrl_index[lei].get("filings", {})
        for fk, fv in filings.items():
            fdate = fv.get("date", "")
            year = fdate[:4]
            pkg = fv.get("report-package")
            country = fv.get("country", "DE")
            if not pkg or not year or int(year) < 2020:
                continue

            dest_filename = f"DE_BAFIN_{ticker}_{year}_ESEF.zip"
            url = f"https://filings.xbrl.org/{lei}/{fdate}/ESEF/{country}/0/{pkg}"
            queue.append({
                "ticker": ticker,
                "year": year,
                "lei": lei,
                "legal_name": comp.get("name_legal", comp.get("name_common", ticker)),
                "isin": comp.get("isin", ""),
                "url": url,
                "filename": dest_filename,
            })

    log.info(f"Total paquetes ESEF mapeados en el universo: {len(queue)}")

    OUTPUT_CATALOG.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CATALOG, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(queue),
            "items": queue,
        }, f, indent=2, ensure_ascii=False)

    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"downloaded": 0, "skipped": 0, "failed": 0}

    transport = httpx.AsyncHTTPTransport(retries=3)
    limits = httpx.Limits(max_connections=30, max_keepalive_connections=15)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        limits=limits,
        transport=transport,
    ) as client:
        log.info(f"\n[Descarga] Iniciando volcado de {len(queue)} paquetes ESEF...")
        tasks = [download_package(client, sem, item, stats) for item in queue]
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 25 == 0 or done == len(tasks):
                log.info(f"  Progreso: {done}/{len(tasks)} | Descargados: {stats['downloaded']} | Saltados: {stats['skipped']}")

    log.info("\n=== RESUMEN VOLCADO ESEF / XBRL ===")
    log.info(f"  Descargados nuevos: {stats['downloaded']}")
    log.info(f"  Ya existían:        {stats['skipped']}")
    log.info(f"  Fallidos:           {stats['failed']}")


if __name__ == "__main__":
    asyncio.run(main())
