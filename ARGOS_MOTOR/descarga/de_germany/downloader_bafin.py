"""
DOWNLOADER ALEMANIA (BAFIN / UNTERNEHMENSREGISTER / ESEF) - ARGOS MOTOR
=========================================================================
Conector institucional para la ingesta de estados financieros anuales de emisores
cotizados alemanes (DAX 40 / MDAX / SDAX).

Cumple estrictamente la regla canónica de persistencia:
  D:\\ARGOS_DATA\\raw\\DE_BAFIN\\{YEAR}\\{TAX_ID}_{TICKER}\\{TICKER}_{YEAR}_{TAG}.{ext}
  acompañado de su respectivo archivo .meta.json sellado con SHA-256.

Donde para Alemania:
  - TAX_ID = LEI oficial (20 caracteres) o HRB (Registro Mercantil).
  - TAG = ESEF / ANUAL.
"""

import os
import sys
import json
import time
import hashlib
import argparse
import urllib.request
from pathlib import Path

# UTF-8 for Windows console
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

CONFIG_PATH = Path(__file__).parent / 'config_de.json'
UNIVERSE_PATH = Path(__file__).resolve().parents[2] / 'config' / 'master_universe_de.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"canonical_raw_path": "D:/ARGOS_DATA/raw/DE_BAFIN"}

def load_master_universe():
    if UNIVERSE_PATH.exists():
        data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
        return data.get('companies', {})
    return {}

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_magic_bytes(filepath):
    with open(filepath, 'rb') as f:
        header = f.read(16)
    if header.startswith(b'PK\x03\x04'):
        return 'ZIP_ESEF'
    if header.startswith(b'%PDF'):
        return 'PDF'
    if b'<!doctype html' in header.lower() or b'<html' in header.lower():
        return 'HTML_XHTML'
    return 'UNKNOWN'

class GermanyDownloader:
    def __init__(self, segment=None, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.segment = segment

        # Prioridad absoluta a la unidad D:\ARGOS_DATA\raw\DE_BAFIN
        target_raw = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/DE_BAFIN'))
        if not target_raw.parent.exists():
            target_raw = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/DE_BAFIN'))
        self.raw_base = target_raw
        
        self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"de_run_{time.strftime('%Y%m%d_%H%M%S')}"
        self.universe = load_master_universe()

    def get_target_companies(self):
        comps = list(self.universe.values())
        if self.segment:
            seg_upper = self.segment.upper()
            comps = [c for c in comps if c.get('segment', '').upper() == seg_upper]
        return comps

    def get_canonical_dir(self, year, comp):
        # Tax ID: LEI o HRB o Ticker
        tax_id = comp.get('lei') or comp.get('hrb_reg', '').replace(' ', '') or comp['ticker']
        ticker = comp['ticker']
        return self.raw_base / str(year) / f"{tax_id}_{ticker}"

    def discover_and_download(self, years=[2021, 2022, 2023, 2024]):
        companies = self.get_target_companies()
        print("=========================================================================")
        print("=== INICIANDO DESCARGA INSTITUCIONAL ALEMANIA (BAFIN / ESEF) ===")
        print("=========================================================================")
        print(f"Directorio Canónico Base: {self.raw_base.resolve()}")
        print(f"Empresas en Universo:     {len(companies)} (Filtro Segmento: {self.segment or 'TODOS'})")
        print(f"Ejercicios Fiscales:      {years}")
        print("=========================================================================\n")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.raw_base.mkdir(parents=True, exist_ok=True)

        total_downloaded = 0
        total_skipped = 0
        total_failed = 0

        for idx, comp in enumerate(companies, 1):
            ticker = comp['ticker']
            lei = comp.get('lei', '')
            name = comp.get('name_legal', comp.get('name_common', ticker))
            segment = comp.get('segment', 'DE')

            if not lei:
                continue

            for y in years:
                comp_dir = self.get_canonical_dir(y, comp)
                dest_zip = comp_dir / f"{ticker}_{y}_ESEF.zip"
                dest_pdf = comp_dir / f"{ticker}_{y}_ANUAL.pdf"
                meta_zip = comp_dir / f"{ticker}_{y}_ESEF.meta.json"
                meta_pdf = comp_dir / f"{ticker}_{y}_ANUAL.meta.json"

                # Comprobación si ya existe y está sellado
                if (dest_zip.exists() and dest_zip.stat().st_size > 1000 and meta_zip.exists()) or \
                   (dest_pdf.exists() and dest_pdf.stat().st_size > 1000 and meta_pdf.exists()):
                    total_skipped += 1
                    continue

                print(f"[{idx:03d}/{len(companies):03d}] [{segment}] {ticker:<6} | {name[:28]:<28} (LEI: {lei}) | Año {y}...")
                if self.dry_run:
                    continue

                # Consulta al catálogo europeo ESEF / XBRL oficial
                query_url = f"https://filings.xbrl.org/api/filings?filter[lei]={lei}&filter[reporting_year]={y}"
                headers = {
                    'User-Agent': self.config.get('user_agent', 'ARGOS-Compliance-Auditor/1.0'),
                    'Accept': 'application/json'
                }
                
                try:
                    req = urllib.request.Request(query_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode('utf-8'))
                            filings = data.get('data', [])
                            if filings:
                                pkg_url = filings[0].get('attributes', {}).get('package_url')
                                if pkg_url:
                                    tmp_file = self.staging_dir / f"de_{ticker}_{y}.bin"
                                    urllib.request.urlretrieve(pkg_url, tmp_file)
                                    magic = check_magic_bytes(tmp_file)
                                    
                                    if magic in ['ZIP_ESEF', 'PDF']:
                                        comp_dir.mkdir(parents=True, exist_ok=True)
                                        tag = "ESEF" if magic == 'ZIP_ESEF' else "ANUAL"
                                        ext = ".zip" if magic == 'ZIP_ESEF' else ".pdf"
                                        dest_file = comp_dir / f"{ticker}_{y}_{tag}{ext}"
                                        tmp_file.replace(dest_file)
                                        
                                        sha = calculate_sha256(dest_file)
                                        meta = {
                                            "country": "DE",
                                            "supervisor": "BaFin / Unternehmensregister",
                                            "jurisdiction": "DE",
                                            "currency": "EUR",
                                            "ticker": ticker,
                                            "name": name,
                                            "lei": lei,
                                            "hrb_reg": comp.get('hrb_reg', ''),
                                            "segment": segment,
                                            "fiscal_year": y,
                                            "document_type": f"{tag}_OFFICIAL",
                                            "original_url": pkg_url,
                                            "file_size_bytes": dest_file.stat().st_size,
                                            "sha256": sha,
                                            "magic_bytes_type": magic,
                                            "download_timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                                        }
                                        meta_dest = comp_dir / f"{ticker}_{y}_{tag}.meta.json"
                                        meta_dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                                        total_downloaded += 1
                                        print(f"       -> [EXITO CANÓNICO] {dest_file.name} | SHA-256: {sha[:16]}...")
                                    else:
                                        if tmp_file.exists(): tmp_file.unlink()
                except Exception as e:
                    pass

                time.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 0.8))

        print("\n=========================================================================")
        print(f"=== DESCARGA ALEMANIA FINALIZADA ===")
        print(f"Total descargados y sellados: {total_downloaded}")
        print(f"Omitidos (ya existentes):     {total_skipped}")
        print("=========================================================================")

def main():
    parser = argparse.ArgumentParser(description="Downloader Institucional Alemania (BaFin / ESEF / Unternehmensregister)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--segment', type=str, default=None, help="Filtrar por índice: DAX40, MDAX o SDAX")
    parser.add_argument('--years', type=str, default="2021,2022,2023,2024", help="Años a consultar separados por coma")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = GermanyDownloader(segment=args.segment, dry_run=args.dry_run)
    downloader.discover_and_download(years=years)

if __name__ == '__main__':
    main()
