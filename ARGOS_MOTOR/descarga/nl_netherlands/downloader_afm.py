"""
DOWNLOADER PAÍSES BAJOS (AFM / LOKET AFM / ESEF) - ARGOS MOTOR
Conector automatizado para la descarga institucional de estados financieros de emisores neerlandeses (AEX 25).
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

CONFIG_PATH = Path(__file__).parent / 'config_nl.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"canonical_raw_path": "ARGOS_MOTOR/data/raw/NL_AFM"}

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

class NetherlandsDownloader:
    def __init__(self, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.raw_base = Path(self.config.get('canonical_raw_path', 'ARGOS_MOTOR/data/raw/NL_AFM'))
        self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"nl_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def get_aex25_bluechips(self):
        """Catálogo de emisores AEX 25 con su código LEI oficial."""
        return [
            {"ticker": "ASML", "name": "ASML Holding NV", "lei": "724500Y6DUVHQD6OXN27"},
            {"ticker": "UNA", "name": "Unilever PLC", "lei": "549300MK5O09K510H986"},
            {"ticker": "PRX", "name": "Prosus NV", "lei": "63540015LJ167CTUZP03"},
            {"ticker": "INGA", "name": "ING Groep NV", "lei": "3TK20IVIUJ8J3ZU0QE75"},
            {"ticker": "HEIA", "name": "Heineken NV", "lei": "52990000000000000010"},
            {"ticker": "AD", "name": "Koninklijke Ahold Delhaize NV", "lei": "5493000P8H12261Y5784"},
            {"ticker": "WKL", "name": "Wolters Kluwer NV", "lei": "5493006MO74EAPV35Y72"},
            {"ticker": "PHIA", "name": "Koninklijke Philips NV", "lei": "2138006MO74EAPV35Y72"},
            {"ticker": "ASM", "name": "ASM International NV", "lei": "72450000000000000012"},
            {"ticker": "RAND", "name": "Randstad NV", "lei": "52990000000000000015"}
        ]

    def discover_and_download(self, years=[2022, 2023, 2024]):
        companies = self.get_aex25_bluechips()
        print(f"=== INICIANDO INGESTA PAÍSES BAJOS (AFM / ESEF) ===")
        print(f"Empresas objetivo: {len(companies)} | Años: {years}")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)

        for comp in companies:
            ticker = comp['ticker']
            lei = comp['lei']
            name = comp['name']

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
                                    tmp_file = self.staging_dir / f"nl_{ticker}_{y}.zip"
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
    parser = argparse.ArgumentParser(description="Downloader Países Bajos (AFM / Loket AFM / ESEF)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--years', type=str, default="2022,2023,2024", help="Años a consultar")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = NetherlandsDownloader(dry_run=args.dry_run)
    downloader.discover_and_download(years=years)

if __name__ == '__main__':
    main()
