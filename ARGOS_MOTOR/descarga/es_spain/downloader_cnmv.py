"""
DOWNLOADER CNMV / ESEF - ARGOS MOTOR (ESPAÑA)
Módulo institucional para la descarga y sellado de los 200 valores cotizados españoles.
Adquiere paquetes ESEF e informes anuales auditados desde fuentes primarias oficiales
y los almacena en el repositorio de alta capacidad en D:/ARGOS_DATA/raw/ES_CNMV.
"""

import os
import sys
import json
import time
import hashlib
import argparse
import requests
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path(__file__).parent / 'config_es.json'
XBRL_API = "https://filings.xbrl.org/api/filings"
XBRL_BASE = "https://filings.xbrl.org"

def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {
        "master_universe_path": "ARGOS_MOTOR/config/master_universe_es.json",
        "canonical_raw_path": "D:/ARGOS_DATA/raw/ES_CNMV",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/ES_CNMV",
        "landing_path": "ARGOS_MOTOR/data/raw/landing_raw",
        "staging_path": "D:/ARGOS_DATA/staging",
        "target_years": [2021, 2022, 2023, 2024]
    }

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
    if b'<!doctype html' in header.lower() or b'<html' in header.lower() or b'<?xml' in header.lower():
        return 'XHTML_XML'
    return 'UNKNOWN'

class CNMVDownloader:
    def __init__(self, output_dir=None, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.universe_path = Path(self.config['master_universe_path'])

        # Determinar destino principal (Prioridad: D:/ARGOS_DATA)
        if output_dir:
            self.canonical_base = Path(output_dir)
        else:
            primary = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/ES_CNMV'))
            if primary.drive and Path(primary.drive + '/').exists():
                self.canonical_base = primary
            else:
                self.canonical_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/ES_CNMV'))

        self.fallback_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/ES_CNMV'))
        self.landing_base = Path(self.config.get('landing_path', 'ARGOS_MOTOR/data/raw/landing_raw'))

        staging_root = Path(self.config.get('staging_path', 'D:/ARGOS_DATA/staging'))
        if not (staging_root.drive and Path(staging_root.drive + '/').exists()):
            staging_root = Path("ARGOS_MOTOR/data/staging/tmp_download")

        self.staging_dir = staging_root / f"run_es_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.manifest = []
        self.es_filings_by_year = {}

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; ARGOS_MOTOR/3.0; regulatory-data-collector)',
            'Accept': 'application/json'
        })

    def get_universe_entities(self):
        if not self.universe_path.exists():
            print(f"[ERROR] Archivo de universo no encontrado: {self.universe_path}")
            return {}
        data = json.loads(self.universe_path.read_text(encoding='utf-8'))
        return data.get('companies', {})

    def get_existing_coverage(self):
        """Identifica qué empresas y años ya están en disco."""
        coverage = {}
        paths_to_check = [
            self.canonical_base / 'INFORMES_ANUALES_COMPLETOS',
            self.fallback_base / 'INFORMES_ANUALES_COMPLETOS'
        ]

        for base_p in paths_to_check:
            if base_p.exists():
                for y_dir in base_p.iterdir():
                    if not y_dir.is_dir(): continue
                    year = y_dir.name
                    for c_dir in y_dir.iterdir():
                        if not c_dir.is_dir(): continue
                        ticker = c_dir.name.split('-')[0].split('_')[0].upper()
                        files = [f for f in c_dir.rglob('*') if f.is_file()]
                        if files:
                            if ticker not in coverage:
                                coverage[ticker] = set()
                            coverage[ticker].add(year)
        return coverage

    def load_es_filings_index(self, year: int):
        """Descarga e indexa por LEI todos los filings oficiales de España para el año."""
        if year in self.es_filings_by_year:
            return self.es_filings_by_year[year]

        print(f"Cargando índice oficial ESEF España para ejercicio {year}...")
        lei_map = {}
        page = 1

        while True:
            url = f"{XBRL_API}?filter[country]=ES&filter[period_end]={year}-12-31&page[size]=100&page[number]={page}"
            try:
                r = self.session.get(url, timeout=15)
                if r.status_code != 200:
                    break
                data = r.json()
                items = data.get('data', [])
                for item in items:
                    attrs = item.get('attributes', {})
                    pkg_rel = attrs.get('package_url')
                    if pkg_rel:
                        # Extraer LEI desde la ruta de paquete: /<LEI>/<date>/...
                        parts = pkg_rel.strip('/').split('/')
                        if parts:
                            doc_lei = parts[0].upper()
                            lei_map[doc_lei] = {
                                'package_url': f"{XBRL_BASE}{pkg_rel}",
                                'sha256_expected': attrs.get('sha256'),
                                'period_end': attrs.get('period_end')
                            }
                meta = data.get('meta', {})
                total = meta.get('count', 0)
                if len(lei_map) >= total or len(items) == 0:
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  Aviso cargando índice ESEF {year} pág {page}: {e}")
                break

        self.es_filings_by_year[year] = lei_map
        print(f"  -> {len(lei_map)} filings ESEF oficiales indexados para España {year}.")
        return lei_map

    def run_ingestion_pipeline(self, target_years=None, missing_only=True):
        if target_years is None:
            target_years = self.config.get('target_years', [2021, 2022, 2023, 2024])

        entities = self.get_universe_entities()
        existing_coverage = self.get_existing_coverage()

        print("=================================================================")
        print("=== INICIANDO PIPELINE DE DESCARGA CNMV / ESEF (ESPAÑA 200) ===")
        print("=================================================================")
        print(f"Destino de almacenamiento configurado: {self.canonical_base}")
        print(f"Total empresas en catálogo maestro: {len(entities)}")
        print(f"Años objetivo: {target_years}")
        print(f"Modo solo pendientes: {missing_only} | Dry-run: {self.dry_run}")

        if not self.dry_run:
            self.canonical_base.mkdir(parents=True, exist_ok=True)
            self.staging_dir.mkdir(parents=True, exist_ok=True)

        stats = {'total': 0, 'already_present': 0, 'discovered': 0, 'downloaded': 0, 'failed': 0}

        # Pre-cargar índices para cada año objetivo
        for y in target_years:
            self.load_es_filings_index(y)

        for ticker, info in entities.items():
            lei = info.get('lei', '')
            cif = info.get('cif_nif', 'UNKNOWN')
            name = info.get('name_legal', ticker)
            already_years = existing_coverage.get(ticker.upper(), set())

            for year in target_years:
                str_year = str(year)
                stats['total'] += 1

                if missing_only and str_year in already_years:
                    stats['already_present'] += 1
                    continue

                year_index = self.es_filings_by_year.get(year, {})
                filing_meta = None

                if lei and lei.upper() in year_index:
                    filing_meta = year_index[lei.upper()]

                if not filing_meta:
                    stats['failed'] += 1
                    self.manifest.append({
                        'ticker': ticker,
                        'lei': lei,
                        'fiscal_year': year,
                        'status': 'PENDING_DIRECT_CNMV_CRAWLER',
                        'destination_drive': str(self.canonical_base),
                        'timestamp': datetime.now().isoformat()
                    })
                    continue

                stats['discovered'] += 1
                pkg_url = filing_meta['package_url']
                print(f"Descargando [{ticker}] {name} ({year}) -> {pkg_url[:60]}...")

                if self.dry_run:
                    continue

                tmp_file = self.staging_dir / f"{ticker}_{year}_package.zip"
                try:
                    with self.session.get(pkg_url, stream=True, timeout=30) as r:
                        if r.status_code == 200:
                            with open(tmp_file, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=131072):
                                    if chunk:
                                        f.write(chunk)

                            magic = check_magic_bytes(tmp_file)
                            if magic in ['ZIP_ESEF', 'XHTML_XML', 'PDF']:
                                sha = calculate_sha256(tmp_file)
                                dest_dir = self.canonical_base / 'INFORMES_ANUALES_COMPLETOS' / str_year / f"{ticker}-{cif}"
                                dest_dir.mkdir(parents=True, exist_ok=True)
                                dest_file = dest_dir / f"{ticker}_{year}_esef.zip"
                                tmp_file.replace(dest_file)
                                stats['downloaded'] += 1
                                print(f"   [OK -> {self.canonical_base.drive}] Guardado: {dest_file.name} | SHA256: {sha[:12]}...")
                                self.manifest.append({
                                    'ticker': ticker,
                                    'lei': lei,
                                    'fiscal_year': year,
                                    'sha256': sha,
                                    'destination_path': str(dest_file),
                                    'status': 'VALID_ORIGINAL_SEALED',
                                    'timestamp': datetime.now().isoformat()
                                })
                            else:
                                print(f"   [CUARENTENA] Fichero corrupto: {magic}")
                                stats['failed'] += 1
                        else:
                            print(f"   [ERROR HTTP {r.status_code}]")
                            stats['failed'] += 1
                except Exception as ex:
                    print(f"   [ERROR] Fallo en descarga: {ex}")
                    stats['failed'] += 1

                time.sleep(self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 1.0))

        manifest_path = self.canonical_base / f"MANIFEST_DOWNLOAD_ES_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(self.manifest, indent=2), encoding='utf-8')

        print("\n=================================================================")
        print("=== RESUMEN DE LA EJECUCIÓN ===")
        print(f"Destino en disco: {self.canonical_base}")
        print(f"Total objetivos evaluados: {stats['total']}")
        print(f"Ya existentes y válidos (omitiendo duplicados): {stats['already_present']}")
        print(f"Descubiertos en canal primario ESEF: {stats['discovered']}")
        print(f"Descargados y sellados exitosamente en D: : {stats['downloaded']}")
        print(f"Pendientes de crawler CNMV: {stats['failed']}")
        print(f"Manifiesto guardado en: {manifest_path}")

def main():
    parser = argparse.ArgumentParser(description="Downloader CNMV / ESEF España - 200 Valores")
    parser.add_argument('--all-200', action='store_true', help="Evalúa el universo completo de los 200 valores")
    parser.add_argument('--missing-only', action='store_true', default=True, help="Solo procesa las empresas pendientes")
    parser.add_argument('--years', type=str, default="2021,2022,2023,2024", help="Lista de años separados por coma")
    parser.add_argument('--output-dir', type=str, default=None, help="Directorio de destino (por defecto D:/ARGOS_DATA/raw/ES_CNMV)")
    parser.add_argument('--dry-run', action='store_true', help="Solo audita y simula sin descargar")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = CNMVDownloader(output_dir=args.output_dir, dry_run=args.dry_run)
    downloader.run_ingestion_pipeline(target_years=years, missing_only=args.missing_only)

if __name__ == '__main__':
    main()
