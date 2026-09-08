"""
DOWNLOADER FRANCIA (AMF / INFO-FINANCIÈRE / ESEF) - ARGOS MOTOR
Conector automatizado para la descarga institucional de informes financieros franceses (CAC 40 / SBF 120).
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

CONFIG_PATH = Path(__file__).parent / 'config_fr.json'

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {"canonical_raw_path": "ARGOS_MOTOR/data/raw/FR_AMF"}

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

class FranceDownloader:
    def __init__(self, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.raw_base = Path(self.config.get('canonical_raw_path', 'ARGOS_MOTOR/data/raw/FR_AMF'))
        self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"fr_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def get_cac40_bluechips(self):
        """Devuelve el catálogo maestro de blue chips francesas con LEI oficial."""
        return [
            {"ticker": "AIR", "name": "Airbus SE", "lei": "2138006MO74EAPV35Y72"},
            {"ticker": "AI", "name": "Air Liquide SA", "lei": "969500A405E15C9N4409"},
            {"ticker": "BNP", "name": "BNP Paribas SA", "lei": "ROMO35KN90MYTXN7RH42"},
            {"ticker": "MC", "name": "LVMH Moët Hennessy Louis Vuitton SE", "lei": "I04210SI5551L170X807"},
            {"ticker": "TTE", "name": "TotalEnergies SE", "lei": "529900S2157HIQB8BW92"},
            {"ticker": "SAN", "name": "Sanofi SA", "lei": "549300E9PC51EN656011"},
            {"ticker": "SU", "name": "Schneider Electric SE", "lei": "969500A1YF1X8D1N6470"},
            {"ticker": "OR", "name": "L'Oréal SA", "lei": "529900JI1GG6F7RKVI72"},
            {"ticker": "RMS", "name": "Hermès International SCA", "lei": "969500P145781E71L832"},
            {"ticker": "DG", "name": "Vinci SA", "lei": "2138001O81I86H7E2792"}
        ]

    def discover_and_download(self, years=[2022, 2023, 2024]):
        companies = self.get_cac40_bluechips()
        print(f"=== INICIANDO INGESTA FRANCIA (AMF / OAM / ESEF) ===")
        print(f"Empresas objetivo: {len(companies)} | Años: {years}")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)

        for comp in companies:
            ticker = comp['ticker']
            lei = comp['lei']
            name = comp['name']

            for y in years:
                # Comprobar si ya existe en disco
                comp_dir = self.raw_base / str(y) / f"{ticker}_{name.replace(' ', '_').replace(',', '')}"
                if comp_dir.exists() and any(f.suffix in ['.zip', '.xhtml', '.htm'] for f in comp_dir.iterdir() if f.is_file()):
                    print(f"[{ticker}] {y} -> YA PRESENTE EN DISCO. Omitiendo.")
                    continue

                print(f"Consultando [{ticker}] {name} (LEI: {lei}) para ejercicio {y}...")
                if self.dry_run:
                    continue

                # Query a filings.xbrl.org
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
                                    tmp_file = self.staging_dir / f"fr_{ticker}_{y}.zip"
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
    parser = argparse.ArgumentParser(description="Downloader Francia (AMF / info-financiere / ESEF)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--years', type=str, default="2022,2023,2024", help="Años a consultar")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = FranceDownloader(dry_run=args.dry_run)
    downloader.discover_and_download(years=years)

if __name__ == '__main__':
    main()
