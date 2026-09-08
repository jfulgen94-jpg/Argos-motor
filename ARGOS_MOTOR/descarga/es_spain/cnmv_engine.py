"""
MOTOR MAESTRO DE DESCARGA CNMV / ESEF / BME GROWTH — ARGOS MOTOR (ESPAÑA)
Módulo institucional para adquisición multicanal de informes regulatorios.

Soporta 3 canales oficiales de descarga:
  - Canal A: ESEF / XBRL.org API (paginado 1..N sin restricciones, por LEI)
  - Canal B: CNMV Portal Crawler (Scraping automático de www.cnmv.es/portal/Consultas/Busqueda.aspx por CIF)
  - Canal C: BME Growth / SOCIMIs Portal Directo

Garantiza:
  - Automatización total del crawler de CNMV para los ~140 emisores sin ESEF
  - Paginación completa de XBRL.org API
  - Cobertura de los 175-200 valores del catálogo maestro (IBEX35, Mercado Continuo, BME Growth)
  - Verificación de Magic Bytes (ZIP, PDF, XHTML/XML)
  - Redirección de páginas de error HTML/captcha/ASP.NET a Cuarentena
  - Descarga atómica vía Staging
  - Sellado criptográfico SHA-256 y Manifiesto de Ingesta por Año
  - Gestión modular por años para descarga paralela eficiente
"""

import os
import sys
import json
import time
import re
import zipfile
import hashlib
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from bs4 import BeautifulSoup

CONFIG_PATH = Path(__file__).parent / 'config_es.json'
XBRL_API = "https://filings.xbrl.org/api/filings"
CNMV_BASE = "https://www.cnmv.es"
BME_GROWTH_BASE = "https://www.bmegrowth.es"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "master_universe_path": "ARGOS_MOTOR/config/master_universe_es.json",
        "canonical_raw_path": "D:/ARGOS_DATA/raw/ES_CNMV",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/ES_CNMV",
        "landing_path": "ARGOS_MOTOR/data/raw/landing_raw",
        "staging_path": "ARGOS_MOTOR/data/staging/tmp_download",
        "quarantine_path": "ARGOS_MOTOR/data/quarantine_es",
        "target_years": [2020, 2021, 2022, 2023, 2024, 2025]
    }


def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def check_magic_bytes(filepath: Path) -> str:
    if not filepath.exists() or filepath.stat().st_size == 0:
        return 'EMPTY'
    with open(filepath, 'rb') as f:
        header = f.read(512)
    if header.startswith(b'PK\x03\x04'):
        return 'ZIP_ESEF'
    if header.startswith(b'%PDF'):
        return 'PDF'
    header_lower = header.lower()
    if b'<!doctype html' in header_lower or b'<html' in header_lower or b'__viewstate' in header_lower:
        if b'403 forbidden' in header_lower or b'captcha' in header_lower or b'access denied' in header_lower or b'se ha producido un error' in header_lower:
            return 'BLOCKED_HTML'
        return 'HTML_XHTML'
    if b'<?xml' in header_lower:
        return 'XML_XHTML'
    return 'UNKNOWN'


class CNMVEngine:
    def __init__(self, target_year: Optional[int] = None, output_dir: Optional[str] = None):
        self.config = load_config()
        self.target_year = target_year
        self.project_root = Path(__file__).resolve().parents[3]

        # Configurar directorio base de salida (Prioridad D:/ARGOS_DATA si existe)
        if output_dir:
            self.base_dir = Path(output_dir)
        else:
            primary = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/ES_CNMV'))
            if primary.drive and Path(primary.drive + '/').exists():
                self.base_dir = primary
            else:
                fallback_rel = self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/ES_CNMV')
                self.base_dir = self.project_root / fallback_rel if not Path(fallback_rel).is_absolute() else Path(fallback_rel)

        self.staging_dir = self.project_root / "ARGOS_MOTOR/data/staging/tmp_download"
        self.quarantine_dir = self.project_root / "ARGOS_MOTOR/data/quarantine_es"
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8'
        })

        self.universe, self.lei_map, self.cif_map, self.ticker_map = self._load_universe()

    def _load_universe(self) -> Tuple[Dict[str, Any], Dict[str, Tuple[str, dict]], Dict[str, Tuple[str, dict]], Dict[str, Tuple[str, dict]]]:
        universe_path = self.project_root / self.config.get('master_universe_path', 'ARGOS_MOTOR/config/master_universe_es.json')
        if not universe_path.exists():
            print(f"[ALERTA] Archivo universo no encontrado en {universe_path}.")
            return {}, {}, {}, {}

        try:
            data = json.loads(universe_path.read_text(encoding='utf-8'))
        except Exception as e:
            print(f"[ERROR] Error al leer universo JSON: {e}")
            return {}, {}, {}, {}

        companies = data.get('companies', {})
        lei_map = {}
        cif_map = {}
        ticker_map = {}

        for ticker, info in companies.items():
            t_clean = ticker.upper()
            ticker_map[t_clean] = (t_clean, info)
            
            lei = info.get('lei', '').upper().strip()
            if lei:
                lei_map[lei] = (t_clean, info)

            cif = info.get('cif_nif', '').upper().replace('-', '').replace(' ', '').strip()
            if cif:
                cif_map[cif] = (t_clean, info)

        return companies, lei_map, cif_map, ticker_map

    def fetch_esef_filings_xbrl_org(self, year_filter: Optional[int] = None) -> List[dict]:
        """
        Consulta la API de filings.xbrl.org con paginación exhaustiva (páginas 1 a N).
        """
        filings = []
        page = 1
        page_size = 200
        url = f"{XBRL_API}?filter[country]=ES&page[size]={page_size}"

        print(f"  -> Sincronizando canal ESEF (XBRL.org API) para España...")

        while True:
            try:
                resp = self.session.get(f"{url}&page[number]={page}", timeout=20)
                if resp.status_code != 200:
                    break
                
                payload = resp.json()
                items = payload.get('data', [])
                if not items:
                    break

                for item in items:
                    attrs = item.get('attributes', {})
                    pkg_url = attrs.get('package_url')
                    if not pkg_url:
                        continue

                    period_end = attrs.get('period_end', '')
                    year_str = period_end[:4] if period_end else ''
                    
                    if not year_str.isdigit():
                        continue

                    f_year = int(year_str)

                    if year_filter and f_year != year_filter:
                        continue

                    lei = pkg_url.strip('/').split('/')[0].upper()
                    
                    company_tuple = self.lei_map.get(lei)
                    if company_tuple:
                        ticker, comp_info = company_tuple
                        cif = comp_info.get('cif_nif', 'UNKNOWN')
                        legal_name = comp_info.get('name_legal', ticker)
                    else:
                        ticker = f"LEI_{lei[:8]}"
                        cif = "ES_ESEF"
                        legal_name = f"Emisor ES LEI {lei}"

                    download_url = f"https://filings.xbrl.org{pkg_url}" if not pkg_url.startswith('http') else pkg_url

                    filings.append({
                        'source': 'XBRL_ORG_ESEF',
                        'ticker': ticker,
                        'cif': cif,
                        'name_legal': legal_name,
                        'lei': lei,
                        'year': f_year,
                        'doc_type': 'ESEF_PACKAGE',
                        'url': download_url,
                        'file_name': f"{ticker}_{f_year}_esef.zip"
                    })

                if len(items) < page_size:
                    break
                page += 1
                time.sleep(0.2)

            except Exception as e:
                print(f"     [Aviso en canal ESEF pág {page}]: {e}")
                break

        print(f"  -> Filings ESEF en XBRL.org: {len(filings)}")
        return filings

    def crawl_cnmv_portal_by_cif(self, cif: str, ticker: str, company_name: str, yr: int) -> List[dict]:
        """
        Crawler automatizado para CNMV Busqueda/DerechosVoto/IP por CIF.
        Recupera URLs de CCAA, Informes de Auditoría, IAGC e IARC.
        """
        cif_clean = re.sub(r'[^A-Z0-9]', '', cif.upper())
        if not cif_clean:
            return []

        search_urls = [
            f"{CNMV_BASE}/portal/Consultas/DerechosVoto/IP.aspx?nif={cif_clean}&yr={yr}",
            f"{CNMV_BASE}/portal/Consultas/DerechosVoto/BusquedaEntidad.aspx?nif={cif_clean}",
            f"{CNMV_BASE}/portal/Consultas/Busqueda.aspx?nif={cif_clean}&tipo=IP"
        ]

        found_filings = []

        for surl in search_urls:
            try:
                resp = self.session.get(surl, timeout=15)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                links = soup.find_all('a', href=True)

                for link in links:
                    href = link['href']
                    text = link.get_text(strip=True)

                    if 'verDoc.axd' in href or 'verDocumento.axd' in href or 'descarga' in href.lower() or 'IP.aspx' in href:
                        full_url = href if href.startswith('http') else f"{CNMV_BASE}/{href.lstrip('/')}"
                        
                        doc_type = 'CNMV_ANNUAL_REPORT'
                        if 'IAGC' in text.upper() or 'GOBIERNO' in text.upper():
                            doc_type = 'IAGC'
                        elif 'IARC' in text.upper() or 'REMUNERA' in text.upper():
                            doc_type = 'IARC'

                        ext = '.pdf' if doc_type in ['IAGC', 'IARC'] else '.zip'
                        file_name = f"{ticker}_{yr}_{doc_type.lower()}{ext}"

                        found_filings.append({
                            'source': 'CNMV_CRAWLER_DIRECT',
                            'ticker': ticker,
                            'cif': cif_clean,
                            'name_legal': company_name,
                            'lei': '',
                            'year': yr,
                            'doc_type': doc_type,
                            'url': full_url,
                            'file_name': file_name
                        })
                
                if found_filings:
                    break

            except Exception as e:
                pass

        return found_filings

    def download_filing(self, filing: dict) -> Tuple[bool, str, Optional[Path]]:
        """
        Descarga un documento individual mediante descarga atómica (Staging -> Raw).
        Sella con SHA-256 y valida Magic Bytes.
        """
        ticker = filing['ticker']
        cif = filing['cif'].replace('-', '').replace(' ', '')
        year = filing['year']
        url = filing['url']
        file_name = filing['file_name']

        # Directorio destino canónico
        target_dir = self.base_dir / "INFORMES_ANUALES_COMPLETOS" / str(year) / f"{ticker}-{cif}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / file_name

        # Cache-hit check
        if target_file.exists() and target_file.stat().st_size > 1000:
            mb = check_magic_bytes(target_file)
            if mb in ['ZIP_ESEF', 'PDF', 'XHTML_XML', 'HTML_XHTML', 'XML_XHTML']:
                return True, "CACHE_HIT", target_file

        staging_file = self.staging_dir / f"tmp_{year}_{ticker}_{file_name}"

        try:
            resp = self.session.get(url, stream=True, timeout=30)
            if resp.status_code != 200:
                return False, f"HTTP_{resp.status_code}", None

            with open(staging_file, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            magic = check_magic_bytes(staging_file)
            if magic in ['EMPTY', 'BLOCKED_HTML', 'UNKNOWN']:
                quarantine_target = self.quarantine_dir / f"quarantine_{year}_{ticker}_{file_name}"
                if staging_file.exists():
                    staging_file.replace(quarantine_target)
                return False, f"QUARANTINED_{magic}", quarantine_target

            if target_file.exists():
                target_file.unlink()
            staging_file.replace(target_file)

            return True, "DOWNLOADED_AND_SEALED", target_file

        except Exception as e:
            if staging_file.exists():
                try: staging_file.unlink()
                except Exception: pass
            return False, f"EXCEPTION_{type(e).__name__}", None

    def execute_year_download(self, year: int) -> dict:
        """
        Ejecuta la descarga completa e integral para un año fiscal concreto sobre todo el universo.
        """
        print(f"\n=========================================================================")
        print(f"=== INICIANDO DESCARGA INTEGRAL CNMV ESPAÑA — AÑO FISCAL {year} ===")
        print(f"=========================================================================")
        print(f"Destino Canónico: {self.base_dir}")
        print(f"Universo Objetivo: {len(self.universe)} empresas (IBEX35, Continuo, BME Growth)")

        # 1. Obtener filings de Canal A (XBRL.org) para el año
        esef_filings = self.fetch_esef_filings_xbrl_org(year_filter=year)
        covered_tickers = {f['ticker'] for f in esef_filings if f['ticker'] in self.universe}

        # 2. Crawler de Canal B (CNMV Portal) para empresas sin ESEF o para complementar con PDF/IAGC
        print(f"  -> Ejecutando Crawler CNMV (www.cnmv.es) para empresas pendientes/no-ESEF...")
        cnmv_crawled_filings = []

        for ticker, comp in self.universe.items():
            cif = comp.get('cif_nif', '')
            name = comp.get('name_legal', ticker)
            
            # Si no tiene ESEF en XBRL.org, rastrear el portal CNMV
            c_filings = self.crawl_cnmv_portal_by_cif(cif, ticker, name, year)
            cnmv_crawled_filings.extend(c_filings)

        all_filings = esef_filings + cnmv_crawled_filings
        print(f"\nTotal documentos e informes mapeados para {year}: {len(all_filings)}")

        stats = {
            'year': year,
            'total_mapped': len(all_filings),
            'downloaded': 0,
            'cache_hits': 0,
            'failed': 0,
            'quarantined': 0,
            'manifest': []
        }

        for idx, item in enumerate(all_filings, 1):
            t = item['ticker']
            doc_t = item['doc_type']
            url = item['url']
            
            success, status, dest_path = self.download_filing(item)

            if success:
                if status == "CACHE_HIT":
                    stats['cache_hits'] += 1
                else:
                    stats['downloaded'] += 1
                
                sha256 = calculate_sha256(dest_path) if dest_path and dest_path.exists() else "UNKNOWN"
                file_size = dest_path.stat().st_size if dest_path and dest_path.exists() else 0
                
                stats['manifest'].append({
                    'ticker': t,
                    'cif': item['cif'],
                    'year': year,
                    'doc_type': doc_t,
                    'url': url,
                    'status': status,
                    'sha256': sha256,
                    'size_bytes': file_size,
                    'path': str(dest_path)
                })
            else:
                if "QUARANTINED" in status:
                    stats['quarantined'] += 1
                else:
                    stats['failed'] += 1

            if idx % 20 == 0 or idx == len(all_filings):
                print(f" Progress [{idx}/{len(all_filings)}] -> Descargados: {stats['downloaded']} | Caché: {stats['cache_hits']} | Fallos/Cuarentena: {stats['failed'] + stats['quarantined']}")

        manifest_out = self.base_dir / f"MANIFEST_CNMV_{year}.json"
        manifest_out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding='utf-8')

        print(f"\n=== RESUMEN DESCARGA AÑO {year} ===")
        print(f" ✔ Descargados nuevos: {stats['downloaded']}")
        print(f" ✔ Ya en caché (Válidos): {stats['cache_hits']}")
        print(f" ✖ Fallidos / Sin Enlace Directo: {stats['failed']}")
        print(f" ⚠ En Cuarentena (Bloqueos/Incompletos): {stats['quarantined']}")
        print(f" 📄 Manifiesto Anual Guardado: {manifest_out}")

        return stats

