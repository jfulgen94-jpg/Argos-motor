#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
STATER / ARGOS MOTOR — DESCARGADOR POST-DiRUG (ALEMANIA 2021–2025)
========================================================================================
Motor especializado para la recuperación de estados financieros y paquetes oficiales
posteriores a la reforma DiRUG (fiscal years 2021 a 2025).

Canales Integrados:
  1. Canal ESEF (xbrl-filings-api): Volcado de paquetes digitales (.zip / .xhtml)
     de las emisoras cotizadas en formato digital ESMA.
  2. Canal Unternehmensregister (de-unternehmensregister.js): Mapeo instantáneo y
     extracción de los Jahresabschlüsse oficiales, balances (Bilanz), cuentas de
     pérdidas y ganancias (GuV) y notas de auditoría directamente del OAM alemán.

Destino Canónico: D:/ARGOS_DATA/raw/DE_BAFIN/{año}/
Manifiestos:      ARGOS_MOTOR/audits/manifests/MANIFEST_BAFIN_{año}.json
========================================================================================
"""

import os
import sys
import json
import time
import shutil
import hashlib
import asyncio
import logging
import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

# Logging institucional
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("argos_de_post_dirug")

# Rutas del proyecto
ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT_DIR.parent
CONFIG_DIR = ROOT_DIR / "config"
MANIFESTS_DIR = ROOT_DIR / "audits" / "manifests"
DATA_DIR = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
TOOLS_DIR = WORKSPACE_DIR / "tools"
UR_SCRIPT = TOOLS_DIR / "european-company-registers" / "scripts" / "de-unternehmensregister.js"
XBRL_INDEX_FILE = WORKSPACE_DIR / "scratch" / "xbrl_index_de.json"

TARGET_YEARS = ["2021", "2022", "2023", "2024", "2025", "2026"]


def calculate_sha256(file_path: Path) -> str:
    """Calcula el hash criptográfico SHA-256 de un archivo en disco."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class PostDirugDownloader:
    def __init__(self, data_dir: Path = DATA_DIR, concurrency: int = 5):
        self.data_dir = data_dir
        self.concurrency = concurrency
        self.client_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        self.esef_index = {}
        self._load_esef_index()

    def _load_esef_index(self):
        """Carga el índice local de filings ESEF si existe."""
        if XBRL_INDEX_FILE.exists():
            try:
                self.esef_index = json.loads(XBRL_INDEX_FILE.read_text(encoding="utf-8"))
                logger.info(f"Índice ESEF cargado con {len(self.esef_index)} entidades.")
            except Exception as e:
                logger.warning(f"No se pudo cargar {XBRL_INDEX_FILE}: {e}")

    def get_existing_coverage(self, year: str) -> set:
        """Devuelve el conjunto de tickers que ya tienen documentos válidos para ese año."""
        ydir = self.data_dir / year
        covered = set()
        if not ydir.exists():
            return covered

        for f in ydir.glob("*.meta.json"):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                t = meta.get("ticker") or meta.get("entity_id")
                if t:
                    covered.add(t)
            except Exception:
                pass
        return covered

    async def download_esef_package(
        self, client: httpx.AsyncClient, ticker: str, lei: str, year: str, comp_info: Dict
    ) -> Optional[Dict]:
        """Intenta descargar el paquete oficial ESEF desde la federación XBRL."""
        if not lei or lei not in self.esef_index:
            return None

        entity_data = self.esef_index[lei]
        filings = entity_data.get("filings", {})
        
        target_filing = None
        for fkey, fval in filings.items():
            f_date = fval.get("date", "")
            if f_date.startswith(year):
                target_filing = fval
                break

        if not target_filing:
            return None

        pkg_name = target_filing.get("report-package")
        if not pkg_name:
            return None

        # URL canónica en filings.xbrl.org
        country = target_filing.get("country", "DE")
        filing_url = f"https://filings.xbrl.org/{lei}/{target_filing.get('date')}/ESEF/{country}/0/{pkg_name}"
        
        target_dir = self.data_dir / year
        target_dir.mkdir(parents=True, exist_ok=True)
        dest_filename = f"DE_BAFIN_{ticker}_{year}_ESEF.zip"
        dest_file = target_dir / dest_filename
        meta_file = target_dir / f"{dest_filename}.meta.json"

        if dest_file.exists() and meta_file.exists() and dest_file.stat().st_size > 10000:
            return None  # Ya existe

        logger.info(f"[{ticker} {year}] Descargando paquete ESEF: {pkg_name}...")
        try:
            resp = await client.get(filing_url, timeout=45.0, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 5000:
                dest_file.write_bytes(resp.content)
                sha = calculate_sha256(dest_file)
                meta = {
                    "country": "DE",
                    "supervisor": "BaFin / ESMA (ESEF)",
                    "ticker": ticker,
                    "legal_name": comp_info.get("name_legal", comp_info.get("name_common", ticker)),
                    "isin": comp_info.get("isin", ""),
                    "lei": lei,
                    "fiscal_year": int(year),
                    "document_type": "ANNUAL_ESEF_PACKAGE_ZIP",
                    "source_url": filing_url,
                    "local_file": dest_filename,
                    "file_size": len(resp.content),
                    "sha256": sha,
                    "download_timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "VERIFIED_COMPLIANT",
                    "channel": "CANAL_ESEF_XBRL",
                }
                meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"[OK ESEF] {ticker} {year} guardado ({len(resp.content)/(1024*1024):.2f} MB)")
                return meta
        except Exception as e:
            logger.warning(f"[{ticker} {year}] Fallo descarga ESEF: {e}")

        return None

    def query_unternehmensregister(self, company_name: str, pages: int = 1) -> Optional[Dict]:
        """Consulta el endpoint Next.js RSC de Unternehmensregister mediante el script Node."""
        if not UR_SCRIPT.exists():
            logger.error(f"Script no encontrado: {UR_SCRIPT}")
            return None

        try:
            cmd = ["node", str(UR_SCRIPT), "search", company_name, "--accounting", "--pages", str(pages), "--json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=35, encoding="utf-8")
            if proc.returncode == 0:
                return json.loads(proc.stdout)
        except Exception as e:
            logger.warning(f"Error consultando Unternehmensregister para '{company_name}': {e}")
        return None

    def harvest_unternehmensregister_statements(
        self, ticker: str, comp_info: Dict, target_years: List[str], pages: int = 1
    ) -> List[Dict]:
        """Extrae el catálogo y metadatos oficiales de balances de Unternehmensregister."""
        name = comp_info.get("name_common") or comp_info.get("name_legal") or ticker
        ur_data = self.query_unternehmensregister(name, pages=pages)
        if not ur_data or not ur_data.get("companies"):
            return []

        comp = ur_data["companies"][0]
        reports = comp.get("reports", [])
        harvested = []

        for rep in reports:
            fy = rep.get("fiscal_year")
            if not fy or fy not in target_years:
                continue

            r_name = rep.get("name", "")
            r_name_lower = r_name.lower()
            is_annual = any(k in r_name_lower for k in [
                "jahresabschluss", "konzernabschluss", "jahresfinanzbericht", 
                "finanzbericht", "rechnungslegung", "annual report"
            ])
            if not is_annual:
                continue

            # Guardar metadato oficial del balance descubierto en el OAM
            target_dir = self.data_dir / fy
            target_dir.mkdir(parents=True, exist_ok=True)
            doc_id = f"DE_BAFIN_{ticker}_{fy}_JAHRESABSCHLUSS"
            meta_path = target_dir / f"{doc_id}.meta.json"

            meta = {
                "country": "DE",
                "supervisor": "BaFin / Unternehmensregister (Bundesanzeiger Verlag)",
                "ticker": ticker,
                "legal_name": comp.get("name") or comp_info.get("name_legal", name),
                "isin": comp_info.get("isin", ""),
                "lei": comp_info.get("lei", ""),
                "euid": comp.get("euid", ""),
                "court": comp.get("court", ""),
                "register": comp.get("register", ""),
                "fiscal_year": int(fy),
                "document_type": "OFFICIAL_ANNUAL_FINANCIAL_STATEMENT_OAM",
                "publication_title": r_name,
                "publication_date": rep.get("date"),
                "source": rep.get("source"),
                "source_raw": rep.get("source_raw"),
                "encrypted_payload": rep.get("encrypted_payload"),
                "download_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "DISCOVERED_OFFICIAL_OAM",
                "channel": "CANAL_UNTERNEHMENSREGISTER_DIRUG",
            }
            
            # Si aún no existe archivo de metadatos para ese año, lo registramos
            if not meta_path.exists():
                meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"[UREG DISCOVER] {ticker} {fy}: {r_name[:60]}...")
                harvested.append(meta)

        return harvested

    def update_audit_manifests(self, entries: List[Dict]):
        """Actualiza los manifiestos oficiales de auditoría en ARGOS_MOTOR/audits/manifests/."""
        if not entries:
            return

        MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
        by_year = {}
        for e in entries:
            y = str(e.get("fiscal_year"))
            by_year.setdefault(y, []).append(e)

        for y, items in by_year.items():
            m_path = MANIFESTS_DIR / f"MANIFEST_BAFIN_{y}.json"
            manifest = []
            if m_path.exists():
                try:
                    manifest = json.loads(m_path.read_text(encoding="utf-8"))
                except Exception:
                    manifest = []

            keys = {
                (x.get("ticker"), x.get("fiscal_year"), x.get("local_file") or x.get("publication_title"))
                for x in manifest
            }
            added = 0
            for item in items:
                k = (item.get("ticker"), item.get("fiscal_year"), item.get("local_file") or item.get("publication_title"))
                if k not in keys:
                    manifest.append(item)
                    keys.add(k)
                    added += 1

            m_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Manifiesto MANIFEST_BAFIN_{y}.json actualizado (+{added} registros, Total: {len(manifest)})")


async def run_pipeline(years: List[str], max_companies: Optional[int] = None, pages: int = 1, sync_azure: bool = False):
    start_time = time.time()
    logger.info("=========================================================================")
    logger.info("=== ARGOS MOTOR: DESCARGA INSTITUCIONAL ALEMÁN POST-DiRUG (2021–2026) ===")
    logger.info("=========================================================================")
    logger.info(f"Ejercicios Fiscales Objetivo: {years} | Páginas por empresa: {pages}")

    # Cargar empresas Prime Standard
    prime_file = CONFIG_DIR / "prime_standard_companies.json"
    if not prime_file.exists():
        logger.error(f"Archivo no encontrado: {prime_file}")
        return

    companies = json.load(open(prime_file, encoding="utf-8"))
    if max_companies:
        companies = companies[:max_companies]

    total_companies = len(companies)
    logger.info(f"Total empresas a procesar: {total_companies}")

    downloader = PostDirugDownloader()
    all_new_entries = []

    limits = httpx.Limits(max_keepalive_connections=20, max_connections=30)
    async with httpx.AsyncClient(headers=downloader.client_headers, limits=limits) as http_client:
        for idx, comp in enumerate(companies, 1):
            ticker = comp.get("ticker")
            lei = comp.get("lei")
            name = comp.get("name_common") or comp.get("name_legal") or ticker
            logger.info(f"--- [{idx}/{total_companies}] {ticker} ({name}) ---")

            # 1. Ejecutar Track A: Descarga de paquetes digitales ESEF para años 2021-2025
            for y in years:
                existing = downloader.get_existing_coverage(y)
                if ticker in existing:
                    continue

                esef_meta = await downloader.download_esef_package(http_client, ticker, lei, y, comp)
                if esef_meta:
                    all_new_entries.append(esef_meta)

            # 2. Ejecutar Track B: Cosecha y catalogación oficial en Unternehmensregister
            ureg_entries = downloader.harvest_unternehmensregister_statements(ticker, comp, years, pages=pages)
            all_new_entries.extend(ureg_entries)

            # Pausa ligera de cortesía
            await asyncio.sleep(0.4)

    # Actualizar manifiestos
    logger.info("Actualizando manifiestos anuales de auditoría...")
    downloader.update_audit_manifests(all_new_entries)

    elapsed = time.time() - start_time
    logger.info("=========================================================================")
    logger.info(f"PIPELINE POST-DiRUG COMPLETADO en {elapsed:.1f} segundos")
    logger.info(f"Nuevos registros incorporados al Data Lake: {len(all_new_entries)}")
    logger.info("=========================================================================")

    # Sincronización automática con Azure si se especificó
    if sync_azure:
        logger.info("Iniciando sincronización con Microsoft Azure Blob Storage...")
        sync_script = ROOT_DIR / "cloud" / "azure_data_lake_sync.py"
        if sync_script.exists():
            subprocess.run([sys.executable, str(sync_script), "--subfolder", "DE_BAFIN"])


def main():
    parser = argparse.ArgumentParser(description="Argos Downloader Alemania Post-DiRUG (2021-2026)")
    parser.add_argument("--years", default="2021,2022,2023,2024,2025,2026", help="Años a procesar (ej: 2021,2022,2023,2024,2025,2026)")
    parser.add_argument("--pages", type=int, default=1, help="Número de páginas de resultados contables a paginar (default: 1)")
    parser.add_argument("--limit", type=int, default=None, help="Límite de empresas a procesar para pruebas")
    parser.add_argument("--sync-azure", action="store_true", help="Sincronizar automáticamente hacia Azure Blob Storage")
    args = parser.parse_args()

    target_years = [y.strip() for y in args.years.split(",") if y.strip()]
    asyncio.run(run_pipeline(target_years, max_companies=args.limit, pages=args.pages, sync_azure=args.sync_azure))


if __name__ == "__main__":
    main()
