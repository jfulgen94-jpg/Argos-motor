"""
DOWNLOADER ALEMANIA (BAFIN / UNTERNEHMENSREGISTER / ESEF) - ARGOS MOTOR
Conector para la ingesta institucional de estados financieros de emisores alemanes (DAX 40 / MDAX).
"""

import os
import sys
import json
import time
import hashlib
import argparse
import urllib.request
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path(__file__).parent / 'config_de.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"canonical_raw_path": "ARGOS_MOTOR/data/raw/DE_BAFIN"}

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
    def __init__(self, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.raw_base = Path(self.config.get('canonical_raw_path', 'ARGOS_MOTOR/data/raw/DE_BAFIN'))
        self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"de_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def load_universe(self):
        """Carga el universo de empresas desde el archivo master_universe_de.json."""
        universe_path = Path("ARGOS_MOTOR/config/master_universe_de.json")
        if not universe_path.exists():
            print("Error: El archivo master_universe_de.json no existe.")
            return []
        
        data = json.loads(universe_path.read_text(encoding='utf-8'))
        return list(data['companies'].values())

    def discover_and_download(self, years=[2022, 2023, 2024]):
        companies = self.load_universe()
        print(f"=== INICIANDO INGESTA ALEMANIA (BAFIN / UNTERNEHMENSREGISTER / ESEF) ===")
        print(f"Empresas objetivo: {len(companies)} | Años: {years}")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)

        for comp in companies:
            ticker = comp['ticker']
            lei = comp['lei']
            name = comp['name_legal']

            for y in years:
                comp_dir = self.raw_base / str(y) / f"{ticker}_{name.replace(' ', '_').replace(',', '')}"
                if comp_dir.exists() and any(f.suffix in ['.zip', '.xhtml', '.htm'] for f in comp_dir.iterdir() if f.is_file()):
                    print(f"[{ticker}] {y} -> YA PRESENTE EN DISCO. Omitiendo.")
                    continue

                print(f"Consultando [{ticker}] {name} (LEI: {lei}) para ejercicio {y}...")
                if self.dry_run:
                    continue

                query_url = f"https://filings.xbrl.org/api/filings?filter[lei]={lei}&filter[reporting_year]={y}"
                headers = {'User-Agent': self.config.get('user_agent', 'ARGOS-Compliance/1.0'), 'Accept': 'application/json'}
                try:
                    req = urllib.request.Request(query_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode('utf-8'))
                            filings = data.get('data', [])
                            if filings:
                                pkg_url = filings[0].get('attributes', {}).get('package_url')
                                if pkg_url:
                                    tmp_file = self.staging_dir / f"de_{ticker}_{y}.zip"
                                    urllib.request.urlretrieve(pkg_url, tmp_file)
                                    magic = check_magic_bytes(tmp_file)
                                    if magic == 'ZIP_ESEF':
                                        comp_dir.mkdir(parents=True, exist_ok=True)
                                        dest = comp_dir / f"{ticker}_{y}_esef.zip"
                                        tmp_file.replace(dest)
                                        sha = calculate_sha256(dest)
                                        print(f"   [OK] Descargado paquete ESEF: {dest.name} | SHA256: {sha[:12]}...")
                except Exception as e:
                    print(f"   [AVISO] No disponible en canal directo ESEF: {e}")

                time.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 2.0))

def main():
    parser = argparse.ArgumentParser(description="Downloader Alemania (BaFin / Unternehmensregister / ESEF)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--years', type=str, default="2022,2023,2024", help="Años a consultar")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = GermanyDownloader(dry_run=args.dry_run)
    downloader.discover_and_download(years=years)

if __name__ == '__main__':
    main()
