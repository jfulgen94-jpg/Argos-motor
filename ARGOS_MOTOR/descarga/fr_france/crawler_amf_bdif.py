"""
STATER MOTOR ARGOS — CRAWLER Y DESCARGADOR OFICIAL BDIF AMF (FRANCIA)
=====================================================================
Motor institucional de adquisición para informes anuales franceses no-ESEF:
  - Canal B: BDIF (Base des Décisions et Informations Financières de l'AMF)
  - Periodo histórico: 2012-2019 (Pre-ESEF: Document de Référence / DDR)
  - Periodo contemporáneo: 2020-2025 (URD / Rapports Financiers Annuels en PDF)
  - API nativa AMF: /back/api/v1/informations y /back/api/v1/documents/
  - Almacenamiento canónico: D:/ARGOS_DATA/raw/FR_AMF/{year}/{ticker_or_company}
  - Verificación criptográfica SHA-256 y magic bytes %PDF.
"""

import os
import sys
import json
import time
import hashlib
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(line_buffering=True)

CONFIG_PATH = Path(__file__).parent / 'config_fr.json'
BDIF_BASE = "https://bdif.amf-france.org"
BDIF_API_SEARCH = f"{BDIF_BASE}/back/api/v1/informations"
BDIF_API_DOC = f"{BDIF_BASE}/back/api/v1/documents"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "canonical_raw_path": "D:/ARGOS_DATA/raw/FR_AMF",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/FR_AMF",
        "staging_path": "D:/ARGOS_DATA/staging",
        "user_agent": "ARGOS-Institutional-Data-Auditor/1.0 (Compliance; Regulatory Research; dev@stater.es)"
    }

def calculate_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_pdf_magic(filepath: Path) -> bool:
    if not filepath.exists() or filepath.stat().st_size < 100:
        return False
    with open(filepath, 'rb') as f:
        header = f.read(16)
    return header.startswith(b'%PDF')

class AMFBDIFCrawler:
    def __init__(self, dry_run: bool = False):
        self.config = load_config()
        self.dry_run = dry_run
        canonical = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/FR_AMF'))
        if canonical.parent.exists():
            self.raw_base = canonical
        else:
            self.raw_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/FR_AMF'))

        self.staging_dir = Path(self.config.get('staging_path', 'D:/ARGOS_DATA/staging')) / "tmp_bdif"
        self.ua = self.config.get('user_agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'application/json',
            'Referer': f"{BDIF_BASE}/"
        }

    def fetch_filings_catalog(self, year: int, doc_types=None):
        """Consulta la API BDIF para obtener todos los documentos anuales del año especificado."""
        if doc_types is None:
            doc_types = ['DocumentReference', 'DocumentEnregistrementUniversel']

        catalog = []
        page_size = 50

        print(f"\n[CATALOG] Consultando BDIF AMF para año contable {year} (Tipos: {doc_types})...")
        for dt in doc_types:
            offset = 0
            while True:
                params = [
                    ('AnneesComptables', str(year)),
                    ('TypesDocument', dt),
                    ('From', str(offset)),
                    ('Size', str(page_size))
                ]
                url = f"{BDIF_API_SEARCH}?{urllib.parse.urlencode(params)}"
                try:
                    req = urllib.request.Request(url, headers=self.headers)
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        results = data.get('result', [])
                        total = data.get('total', 0)

                        if not results:
                            break

                        for item in results:
                            docs = item.get('documents', [])
                            if not docs:
                                continue

                            socs = item.get('societes', [])
                            company_name = socs[0].get('raisonSociale', 'UNKNOWN') if socs else 'UNKNOWN'
                            jeton = socs[0].get('jeton', '') if socs else ''

                            for d in docs:
                                path_val = d.get('path')
                                if not path_val:
                                    continue
                                
                                catalog.append({
                                    'id': item.get('id'),
                                    'numero': item.get('numero'),
                                    'company_name': company_name,
                                    'jeton': jeton,
                                    'year': year,
                                    'doc_type': dt,
                                    'nom_fichier': d.get('nomFichier'),
                                    'doc_path': path_val,
                                    'download_url': f"{BDIF_API_DOC}/{path_val}",
                                    'date_publication': item.get('datePublication')
                                })

                        offset += len(results)
                        if offset >= total or len(results) < page_size:
                            break

                    time.sleep(0.15)
                except Exception as e:
                    print(f"  [ERROR] Error al paginar {dt} offset {offset}: {e}")
                    break

        print(f"  [OK] Total documentos encontrados en BDIF para {year}: {len(catalog)}")
        return catalog

    def run_download(self, target_years, max_downloads=None, doc_types=None):
        print("=========================================================================")
        print("=== CRAWLER & DESCARGADOR OFICIAL BDIF AMF (FRANCIA) — ARGOS MOTOR ===")
        print("=========================================================================")
        print(f"Destino Canónico: {self.raw_base}")
        print(f"Años Objetivo: {target_years}")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.raw_base.mkdir(parents=True, exist_ok=True)

        for yr in target_years:
            filings = self.fetch_filings_catalog(yr, doc_types=doc_types)
            if max_downloads:
                filings = filings[:max_downloads]

            print(f"\n--- Procesando Año {yr}: {len(filings)} filings en cola ---")

            if self.dry_run:
                print(" [DRY-RUN] Mostrando primeros 5 elementos:")
                for item in filings[:5]:
                    print(f"   {item['company_name']} ({item['doc_type']}) -> {item['download_url']}")
                continue

            downloaded = 0
            skipped = 0
            failed = 0

            for idx, item in enumerate(filings, 1):
                raw_name = item['company_name'].replace('/', '_').replace('\\', '_')
                safe_name = "".join(c for c in raw_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
                if not safe_name:
                    safe_name = item['jeton'] or "COMPANY"

                target_dir = self.raw_base / str(yr) / safe_name
                filename = f"{safe_name}_{yr}_{item['doc_type']}.pdf"
                target_file = target_dir / filename
                meta_file = target_dir / f"{safe_name}_{yr}_{item['doc_type']}.meta.json"

                # Check if already downloaded
                if target_file.exists() and target_file.stat().st_size > 5000:
                    skipped += 1
                    continue

                tmp_path = self.staging_dir / f"tmp_{yr}_{idx}_{int(time.time())}.tmp"
                print(f"[{idx:03d}/{len(filings):03d}] Descargando [{safe_name}] {yr} ({item['doc_type']})...")

                try:
                    req = urllib.request.Request(item['download_url'], headers={'User-Agent': self.ua, 'Referer': f"{BDIF_BASE}/"})
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        with open(tmp_path, 'wb') as f_out:
                            while chunk := resp.read(65536):
                                f_out.write(chunk)

                    if not check_pdf_magic(tmp_path):
                        print(f"   [AVISO] Archivo corrupto o no es PDF. Descartando.")
                        tmp_path.unlink(missing_ok=True)
                        failed += 1
                        continue

                    target_dir.mkdir(parents=True, exist_ok=True)
                    if target_file.exists():
                        target_file.unlink()
                    tmp_path.replace(target_file)

                    sha = calculate_sha256(target_file)
                    size_mb = target_file.stat().st_size / (1024 * 1024)

                    meta = {
                        "company_name": item['company_name'],
                        "jeton_amf": item['jeton'],
                        "year": yr,
                        "doc_type": item['doc_type'],
                        "amf_numero": item['numero'],
                        "source_url": item['download_url'],
                        "sha256": sha,
                        "size_bytes": target_file.stat().st_size,
                        "size_mb": round(size_mb, 2),
                        "date_publication_amf": item['date_publication'],
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                        "supervisor": "AMF (France)",
                        "format": "PDF"
                    }
                    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                    print(f"   [OK] Sellado: {target_file.name} ({size_mb:.2f} MB) | SHA256: {sha[:12]}...")
                    downloaded += 1
                except Exception as e:
                    print(f"   [ERROR] Fallo al descargar {item['download_url']}: {e}")
                    if tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)
                    failed += 1

                time.sleep(0.3)

            # Actualizar manifiesto BDIF anual
            manifest_file = self.raw_base / f"MANIFEST_AMF_BDIF_{yr}.json"
            metas = []
            if (self.raw_base / str(yr)).exists():
                for mp in (self.raw_base / str(yr)).glob("*/*_Document*.meta.json"):
                    try:
                        metas.append(json.loads(mp.read_text(encoding='utf-8')))
                    except Exception:
                        pass

            manifest_data = {
                "year": yr,
                "jurisdiction": "FR",
                "supervisor": "AMF (France BDIF)",
                "source": "https://bdif.amf-france.org",
                "total_filings": len(metas),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "manifest": metas
            }
            manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f"\n [DOC] Manifiesto BDIF Anual Francia {yr}: {manifest_file.name} ({len(metas)} filings)")
            print(f" Resumen Año {yr}: {downloaded} descargados | {skipped} existentes | {failed} fallidos")

def main():
    parser = argparse.ArgumentParser(description="Crawler y Descargador Oficial BDIF AMF Francia")
    parser.add_argument('--years', type=str, default="2018,2019", help="Años contables separados por coma")
    parser.add_argument('--max', type=int, default=None, help="Límite máximo de descargas por año")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar ficheros")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    crawler = AMFBDIFCrawler(dry_run=args.dry_run)
    crawler.run_download(target_years=years, max_downloads=args.max)

if __name__ == '__main__':
    main()
