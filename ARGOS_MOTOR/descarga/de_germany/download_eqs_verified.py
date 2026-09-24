#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STATER / ARGOS MOTOR — Descargador Masivo de Informes Anuales Verificados EQS (Alemania)
========================================================================================
Descarga concurrentemente los 368 informes anuales verificados de EQS Group a disco D:,
valida los bytes mágicos (%PDF), genera el hash criptográfico SHA-256, crea los
sidecars .meta.json y actualiza los manifiestos oficiales de auditoría de 2012 a 2025.

Destino: D:/ARGOS_DATA/raw/DE_BAFIN/{año}/
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import httpx
except ImportError:
    print("ERROR: httpx es requerido. pip install httpx")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eqs_downloader")

ROOT = Path(__file__).resolve().parents[2]
VERIFIED_FILE = ROOT / "config" / "eqs_verified_links.json"
MANIFESTS_DIR = ROOT / "audits" / "manifests"
DATA_DIR = Path("D:/ARGOS_DATA/raw/DE_BAFIN")

CONCURRENCY = 15
TIMEOUT = 30.0


async def download_report(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    ticker: str,
    name: str,
    isin: str,
    year: str,
    rep_info: Dict,
) -> Tuple[bool, str]:
    target_dir = DATA_DIR / year
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"DE_BAFIN_{ticker}_{year}.pdf"
    file_path = target_dir / filename
    meta_path = target_dir / f"{filename}.meta.json"

    # Si ya existe y es válido, omitir descarga
    if file_path.exists() and meta_path.exists():
        if file_path.stat().st_size > 10000:
            return True, f"[SKIP] {ticker} {year} ya existe ({file_path.stat().st_size} bytes)"

    url = rep_info.get("resolved_url") or rep_info.get("source_url")
    if not url:
        return False, f"[FAIL] {ticker} {year}: URL no disponible"

    async with semaphore:
        for attempt in range(3):
            try:
                resp = await client.get(url, follow_redirects=True, timeout=TIMEOUT)
                if resp.status_code == 200:
                    content = resp.content
                    if len(content) < 5000:
                        return False, f"[ERR] {ticker} {year}: contenido demasiado pequeño ({len(content)} bytes)"
                    
                    # Validar cabecera PDF (%PDF-)
                    if not content.startswith(b"%PDF"):
                        # Intentar buscar %PDF dentro de los primeros 1024 bytes (algunos CDNs meten espacios o BOM)
                        idx = content[:1024].find(b"%PDF")
                        if idx != -1:
                            content = content[idx:]
                        else:
                            return False, f"[ERR] {ticker} {year}: no es un PDF válido"

                    # Guardar archivo binario
                    file_path.write_bytes(content)

                    # Calcular SHA-256
                    sha256 = hashlib.sha256(content).hexdigest()

                    # Metadatos del sidecar
                    meta = {
                        "country": "DE",
                        "supervisor": "BaFin / EQS Group (DGAP)",
                        "ticker": ticker,
                        "legal_name": name,
                        "isin": isin,
                        "fiscal_year": int(year),
                        "document_type": "ANNUAL_REPORT_PDF",
                        "source_url": rep_info.get("source_url"),
                        "resolved_url": str(resp.url),
                        "slug": rep_info.get("slug"),
                        "lang": rep_info.get("lang"),
                        "version": rep_info.get("version"),
                        "local_file": filename,
                        "file_size": len(content),
                        "sha256": sha256,
                        "download_timestamp": datetime.utcnow().isoformat() + "Z",
                        "status": "VERIFIED_COMPLIANT",
                        "channel": "CANAL_EQS_DGAP",
                    }
                    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                    return True, f"[OK] {ticker} {year}: {len(content)/1024/1024:.2f} MB guardado"
                elif resp.status_code in (404, 403):
                    return False, f"[FAIL {resp.status_code}] {ticker} {year}: {url}"
            except Exception as e:
                if attempt == 2:
                    return False, f"[EXC] {ticker} {year}: {str(e)}"
                await asyncio.sleep(1.0)

    return False, f"[FAIL] {ticker} {year}: no se pudo descargar tras 3 intentos"


def update_manifests(downloaded_reports: List[Dict]):
    """Incorpora los nuevos informes a los manifiestos oficiales de auditoría."""
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    by_year = {}
    for r in downloaded_reports:
        y = str(r["fiscal_year"])
        by_year.setdefault(y, []).append(r)

    for y, entries in by_year.items():
        manifest_path = MANIFESTS_DIR / f"MANIFEST_BAFIN_{y}.json"
        existing_manifest = []
        if manifest_path.exists():
            try:
                existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Filtrar duplicados por ticker/local_file
        existing_keys = {
            (item.get("ticker"), item.get("fiscal_year"), item.get("local_file"))
            for item in existing_manifest
        }

        added = 0
        for entry in entries:
            key = (entry.get("ticker"), entry.get("fiscal_year"), entry.get("local_file"))
            if key not in existing_keys:
                existing_manifest.append(entry)
                existing_keys.add(key)
                added += 1

        manifest_path.write_text(
            json.dumps(existing_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(f"Manifiesto {manifest_path.name} actualizado: +{added} informes (Total: {len(existing_manifest)})")


async def main_async():
    start_time = time.time()
    logger.info("=== STATER / ARGOS MOTOR — DESCARGA MASIVA CANAL EQS ===")

    if not VERIFIED_FILE.exists():
        logger.error(f"No existe el archivo de enlaces verificados: {VERIFIED_FILE}")
        return

    data = json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))
    companies = data.get("companies", {})

    tasks_info = []
    for ticker, cinfo in companies.items():
        name = cinfo.get("name", "")
        isin = cinfo.get("isin", "")
        reports = cinfo.get("reports", {})
        for y, rep in reports.items():
            tasks_info.append((ticker, name, isin, str(y), rep))

    total = len(tasks_info)
    logger.info(f"Total de informes a descargar: {total}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(CONCURRENCY)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/pdf,*/*",
    }
    limits = httpx.Limits(max_keepalive_connections=30, max_connections=50)

    success_entries = []
    failed_count = 0

    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT, limits=limits) as client:
        batch_size = 30
        for i in range(0, total, batch_size):
            chunk = tasks_info[i : i + batch_size]
            tasks = [
                download_report(client, semaphore, t, n, isin, y, rep)
                for t, n, isin, y, rep in chunk
            ]
            results = await asyncio.gather(*tasks)
            for (ok, msg), (t, n, isin, y, rep) in zip(results, chunk):
                if ok:
                    logger.info(msg)
                    # Cargar metadato creado para agregarlo al manifiesto
                    m_file = DATA_DIR / y / f"DE_BAFIN_{t}_{y}.pdf.meta.json"
                    if m_file.exists():
                        try:
                            success_entries.append(json.loads(m_file.read_text(encoding="utf-8")))
                        except Exception:
                            pass
                else:
                    logger.warning(msg)
                    failed_count += 1

    # Actualizar manifiestos
    logger.info("Actualizando manifiestos oficiales de auditoría...")
    update_manifests(success_entries)

    elapsed = time.time() - start_time
    logger.info("=" * 65)
    logger.info(f"DESCARGA COMPLETADA en {elapsed:.1f} segundos")
    logger.info(f"Informes descargados y sellados con éxito: {len(success_entries)} / {total}")
    if failed_count > 0:
        logger.info(f"Informes fallidos: {failed_count}")
    logger.info("=" * 65)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
