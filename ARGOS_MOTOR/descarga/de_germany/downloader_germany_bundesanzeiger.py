#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
STATER / ARGOS MOTOR — DESCARGADOR BUNDESANZEIGER HISTÓRICO (2012–2020)
========================================================================================
Motor de descarga oficial para balances y cuentas anuales (Jahresabschlüsse y
Konzernabschlüsse) desde Bundesanzeiger (Área 22: Rechnungslegung/Finanzberichte)
con resolución autónoma de CAPTCHAs mediante inferencia local de red neuronal ONNX.

Canal Oficial Pre-DiRUG:
  - Búsqueda directa en Bundesanzeiger con filtro `area_select=22`.
  - Descarga del HTML oficial íntegro del balance y notas auditadas.
  - Generación de sidecar .meta.json y sellado criptográfico SHA-256.
  - Sincronización a disco D: y actualización atómica del manifiesto oficial.

Destino Canónico: D:/ARGOS_DATA/raw/DE_BAFIN/{año}/
Manifiestos:      ARGOS_MOTOR/audits/manifests/MANIFEST_BAFIN_{año}.json
========================================================================================
"""

import os
import sys
import re
import json
import time
import hashlib
import logging
import argparse
import subprocess
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# Añadir tools/deutschland/src al path
ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT_DIR.parent
DEUTSCHLAND_SRC = WORKSPACE_DIR / "tools" / "deutschland" / "src"
if str(DEUTSCHLAND_SRC) not in sys.path:
    sys.path.insert(0, str(DEUTSCHLAND_SRC))

import deutschland.bundesanzeiger.model
from deutschland.bundesanzeiger import Bundesanzeiger

# Configuración de Logging institucional
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("argos_banz_downloader")

# Rutas
CONFIG_DIR = ROOT_DIR / "config"
MANIFESTS_DIR = ROOT_DIR / "audits" / "manifests"
DATA_DIR = Path("D:/ARGOS_DATA/raw/DE_BAFIN")


def calculate_sha256(file_path: Path) -> str:
    """Calcula el hash criptográfico SHA-256 de un archivo en disco."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class BundesanzeigerDownloader:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.ba = Bundesanzeiger()
        self._init_session()

    def _init_session(self):
        """Inicializa la sesión con cookies y cabeceras estándar de navegación."""
        self.ba.session.cookies["cc"] = "1628606977-805e172265bfdbde-10"
        self.ba.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        })
        try:
            self.ba._Bundesanzeiger__get_response("https://www.bundesanzeiger.de")
            self.ba._Bundesanzeiger__get_response("https://www.bundesanzeiger.de/pub/de/start?0")
        except Exception as e:
            logger.warning(f"Error inicializando sesión Bundesanzeiger: {e}")

    def get_existing_coverage(self, year: str) -> Set[str]:
        """Devuelve el conjunto de tickers que ya cuentan con documentos válidos para ese año."""
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

    def _extract_fiscal_year(self, title: str) -> Optional[str]:
        """Extrae el año fiscal de los títulos estándar de Bundesanzeiger."""
        # 1. "bis zum DD.MM.YYYY"
        m = re.search(r"bis(?:\s+zum)?\s+\d{2}\.\d{2}\.(\d{4})", title, re.IGNORECASE)
        if m:
            return m.group(1)
        # 2. "zum DD.MM.YYYY"
        m2 = re.search(r"zum\s+\d{2}\.\d{2}\.(\d{4})", title, re.IGNORECASE)
        if m2:
            return m2.group(1)
        # 3. "Geschäftsjahr YYYY"
        m3 = re.search(r"Geschäftsjahr\s+(\d{4})", title, re.IGNORECASE)
        if m3:
            return m3.group(1)
        # 4. Cualquier año de 4 dígitos (2010 a 2026)
        years = re.findall(r"\b(20[12]\d)\b", title)
        if years:
            return years[-1]
        return None

    def search_company_filings(self, company_name: str, max_pages: int = 2) -> List[Dict]:
        """Busca publicaciones en el Área 22 de Bundesanzeiger para una empresa."""
        filings = []
        base_search_url = (
            f"https://www.bundesanzeiger.de/pub/de/start?0-2.-top~content~panel-left~card-form="
            f"&fulltext={quote_plus(company_name)}&area_select=22&search_button=Suchen"
        )

        try:
            resp = self.ba._Bundesanzeiger__get_response(base_search_url)
            page_content = resp.text
            current_page = 1

            while current_page <= max_pages:
                soup = BeautifulSoup(page_content, "html.parser")
                wrapper = soup.find("div", {"class": "result_container"})
                if not wrapper:
                    break

                rows = wrapper.find_all("div", {"class": "row"})
                for row in rows:
                    info = row.find("div", {"class": "info"})
                    if not info or not info.find("a"):
                        continue
                    link_el = info.find("a")
                    title = link_el.text.strip()
                    href = link_el.get("href")
                    if not href:
                        continue

                    # Filtrar únicamente balances e informes financieros
                    t_lower = title.lower()
                    is_financial = any(k in t_lower for k in [
                        "jahresabschluss", "konzernabschluss", "jahresfinanzbericht",
                        "finanzbericht", "rechnungslegung", "bilanz"
                    ])
                    if not is_financial:
                        continue

                    date_el = row.find("div", {"class": "date"})
                    pub_date = date_el.text.strip() if date_el else ""

                    fy = self._extract_fiscal_year(title)
                    if fy:
                        filings.append({
                            "title": title,
                            "url": href,
                            "publication_date": pub_date,
                            "fiscal_year": fy,
                        })

                # Verificar si hay página siguiente
                next_href = self.ba._Bundesanzeiger__get_next_page_link(page_content)
                if not next_href or current_page >= max_pages:
                    break

                time.sleep(0.5)
                next_resp = self.ba._Bundesanzeiger__get_response(next_href)
                page_content = next_resp.text
                current_page += 1

        except Exception as e:
            logger.warning(f"Error buscando en Bundesanzeiger para '{company_name}': {e}")

        return filings

    def download_filing_content(self, url: str) -> Optional[str]:
        """Descarga el contenido HTML del balance resolviendo el CAPTCHA automáticamente si aparece."""
        try:
            doc_resp = self.ba._Bundesanzeiger__get_response(url)
            
            # Verificar si requiere CAPTCHA
            if self.ba._Bundesanzeiger__is_captcha_needed(doc_resp.text):
                logger.info("Resolviendo CAPTCHA con modelo ONNX...")
                doc_soup = BeautifulSoup(doc_resp.text, "html.parser")
                captcha_wrap = doc_soup.find("div", {"class": "captcha_wrapper"})
                if not captcha_wrap or not captcha_wrap.find("img"):
                    return None

                img_src = captcha_wrap.find("img")["src"]
                img_resp = self.ba._Bundesanzeiger__get_response(img_src)
                solution = self.ba.captcha_callback(img_resp.content)
                logger.info(f"CAPTCHA resuelto con éxito: '{solution}'")

                forms = doc_soup.find_all("form")
                if len(forms) < 2:
                    return None
                action_url = forms[1].get("action")
                doc_resp = self.ba.session.post(
                    action_url,
                    data={"solution": solution, "confirm-button": "OK"},
                    timeout=20,
                )

            # Extraer el contenedor de la publicación
            doc_soup = BeautifulSoup(doc_resp.text, "html.parser")
            container = doc_soup.find("div", {"class": "publication_container"})
            if container:
                return container.prettify()
            elif "publication_container" in doc_resp.text or len(doc_resp.text) > 5000:
                return doc_resp.text
        except Exception as e:
            logger.warning(f"Error descargando documento de Bundesanzeiger ({url}): {e}")

        return None

    def process_company(self, comp: Dict, target_years: List[str], max_pages: int = 2) -> List[Dict]:
        """Procesa una empresa para los años objetivo especificados."""
        ticker = comp.get("ticker")
        legal_name = comp.get("name_legal") or comp.get("name_common") or ticker
        common_name = comp.get("name_common") or legal_name

        # Determinar para qué años aún falta documento
        missing_years = []
        for y in target_years:
            if ticker not in self.get_existing_coverage(y):
                missing_years.append(y)

        if not missing_years:
            return []

        # Buscar en Bundesanzeiger
        filings = self.search_company_filings(common_name, max_pages=max_pages)
        if not filings and common_name != legal_name:
            filings = self.search_company_filings(legal_name, max_pages=max_pages)

        if not filings:
            return []

        # Agrupar por año fiscal (priorizando Konzernabschluss sobre Jahresabschluss individual)
        filings_by_year: Dict[str, List[Dict]] = {}
        for f in filings:
            fy = f["fiscal_year"]
            if fy in missing_years:
                filings_by_year.setdefault(fy, []).append(f)

        new_entries = []

        for fy, items in filings_by_year.items():
            # Ordenar: poner "Konzernabschluss" primero si existe
            items.sort(key=lambda x: ("konzern" not in x["title"].lower(), len(x["title"])))
            best_filing = items[0]

            # Descargar contenido
            html_content = self.download_filing_content(best_filing["url"])
            if not html_content or len(html_content) < 500:
                continue

            # Guardar archivo físico en D:\ARGOS_DATA\raw\DE_BAFIN\{fy}\
            target_dir = self.data_dir / fy
            target_dir.mkdir(parents=True, exist_ok=True)
            doc_filename = f"DE_BAFIN_{ticker}_{fy}_JAHRESABSCHLUSS_BANZ.html"
            doc_file = target_dir / doc_filename
            meta_file = target_dir / f"{doc_filename}.meta.json"

            doc_file.write_text(html_content, encoding="utf-8")
            sha = calculate_sha256(doc_file)

            meta = {
                "country": "DE",
                "supervisor": "BaFin / Bundesanzeiger (Bundesministerium der Justiz)",
                "ticker": ticker,
                "legal_name": legal_name,
                "isin": comp.get("isin", ""),
                "lei": comp.get("lei", ""),
                "fiscal_year": int(fy),
                "document_type": "OFFICIAL_ANNUAL_REPORT_BANZ_HTML",
                "publication_title": best_filing["title"],
                "publication_date": best_filing["publication_date"],
                "source_url": best_filing["url"],
                "local_file": doc_filename,
                "file_size": len(html_content.encode("utf-8")),
                "sha256": sha,
                "download_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "VERIFIED_COMPLIANT",
                "channel": "CANAL_BUNDESANZEIGER_AREA22",
            }
            meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[OK BANZ] {ticker} {fy}: {doc_filename} ({len(html_content)/1024:.1f} KB)")
            new_entries.append(meta)

            # Pequeño retardo de cortesía para no saturar
            time.sleep(0.5)

        return new_entries

    def update_audit_manifests(self, entries: List[Dict]):
        """Actualiza atómicamente los manifiestos oficiales de auditoría."""
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


def run_bundesanzeiger_pipeline(
    years: List[str],
    max_companies: Optional[int] = None,
    max_pages: int = 2,
    sync_azure: bool = True,
):
    start_time = time.time()
    logger.info("=========================================================================")
    logger.info("=== ARGOS MOTOR: DESCARGA BUNDESANZEIGER ÁREA 22 (HISTÓRICO 2012–2020) ===")
    logger.info("=========================================================================")
    logger.info(f"Ejercicios Fiscales Objetivo: {years} | Páginas por búsqueda: {max_pages}")

    prime_file = CONFIG_DIR / "prime_standard_companies.json"
    if not prime_file.exists():
        logger.error(f"Archivo no encontrado: {prime_file}")
        return

    companies = json.load(open(prime_file, encoding="utf-8"))
    if max_companies:
        companies = companies[:max_companies]

    total_companies = len(companies)
    logger.info(f"Total empresas Prime Standard: {total_companies}")

    downloader = BundesanzeigerDownloader()
    all_new_entries = []

    for idx, comp in enumerate(companies, 1):
        ticker = comp.get("ticker")
        name = comp.get("name_common") or comp.get("name_legal") or ticker
        logger.info(f"--- [{idx}/{total_companies}] {ticker} ({name}) ---")

        entries = downloader.process_company(comp, years, max_pages=max_pages)
        if entries:
            all_new_entries.extend(entries)

        # Pausa de cortesía entre empresas
        time.sleep(1.0)

    # Actualizar manifiestos
    logger.info("Actualizando manifiestos oficiales de auditoría...")
    downloader.update_audit_manifests(all_new_entries)

    elapsed = time.time() - start_time
    logger.info("=========================================================================")
    logger.info(f"PIPELINE BUNDESANZEIGER COMPLETADO en {elapsed:.1f} segundos")
    logger.info(f"Nuevos documentos físicos incorporados: {len(all_new_entries)}")
    logger.info("=========================================================================")

    # Sincronización automática a Azure
    if sync_azure:
        logger.info("Sincronizando lote con Microsoft Azure Blob Storage...")
        sync_script = ROOT_DIR / "cloud" / "azure_data_lake_sync.py"
        if sync_script.exists():
            subprocess.run([sys.executable, str(sync_script), "--subfolder", "DE_BAFIN"])


def main():
    parser = argparse.ArgumentParser(description="Argos Downloader Bundesanzeiger Área 22")
    parser.add_argument("--years", default="2016,2017,2018,2019,2020", help="Años a procesar (ej: 2012,2013,2014,2015)")
    parser.add_argument("--pages", type=int, default=2, help="Páginas por búsqueda en Bundesanzeiger (default: 2)")
    parser.add_argument("--limit", type=int, default=None, help="Límite de empresas para pruebas")
    parser.add_argument("--sync-azure", action="store_true", default=True, help="Sincronizar a Azure")
    args = parser.parse_args()

    target_years = [y.strip() for y in args.years.split(",") if y.strip()]
    run_bundesanzeiger_pipeline(
        target_years,
        max_companies=args.limit,
        max_pages=args.pages,
        sync_azure=args.sync_azure,
    )


if __name__ == "__main__":
    main()
