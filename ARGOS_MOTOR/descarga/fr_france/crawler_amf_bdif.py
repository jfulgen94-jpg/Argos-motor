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
                    with urllib.request.urlopen(req, timeout=25) as resp:
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

                            # Priorizar documentos del emisor (docRegulateur == False)
                            # Si no existen, recurrir al documento del regulador
                            issuer_docs = [d for d in docs if not d.get('docRegulateur') and d.get('path')]
                            target_docs = issuer_docs if issuer_docs else [d for d in docs if d.get('path')]

                            for d_idx, d in enumerate(target_docs):
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
                                    'doc_index': d_idx,
                                    'total_docs_in_filing': len(target_docs),
                                    'is_regulator_doc': d.get('docRegulateur', False),
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

        print(f"  [OK] Total documentos identificados en BDIF para {year}: {len(catalog)}")
        return catalog

    def _download_single_filing(self, item, yr):
        raw_name = item['company_name'].replace('/', '_').replace('\\', '_')
        safe_name = "".join(c for c in raw_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        if not safe_name:
            safe_name = item['jeton'] or "COMPANY"

        target_dir = self.raw_base / str(yr) / safe_name
        if item.get('total_docs_in_filing', 1) > 1 and item.get('doc_index', 0) > 0:
            filename = f"{safe_name}_{yr}_{item['doc_type']}_doc{item['doc_index']+1}.pdf"
            meta_filename = f"{safe_name}_{yr}_{item['doc_type']}_doc{item['doc_index']+1}.meta.json"
        else:
            filename = f"{safe_name}_{yr}_{item['doc_type']}.pdf"
            meta_filename = f"{safe_name}_{yr}_{item['doc_type']}.meta.json"

        target_file = target_dir / filename
        meta_file = target_dir / meta_filename

        # Omisión inteligente:
        # Si el archivo ya existe y supera 100 KB (informe real, no simple ficha de depósito), omitir
        if target_file.exists() and target_file.stat().st_size >= 100_000:
            return "SKIPPED", safe_name, target_file

        tmp_path = self.staging_dir / f"tmp_{yr}_{abs(hash(item['download_url']))}_{int(time.time()*1000)}.tmp"

        # Reintentos de descarga
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(item['download_url'], headers={'User-Agent': self.ua, 'Referer': f"{BDIF_BASE}/"})
                with urllib.request.urlopen(req, timeout=45) as resp:
                    with open(tmp_path, 'wb') as f_out:
                        while chunk := resp.read(65536):
                            f_out.write(chunk)

                if not check_pdf_magic(tmp_path):
                    tmp_path.unlink(missing_ok=True)
                    return "FAILED", safe_name, "Fichero no es PDF valido o corrupto"

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
                    "is_regulator_doc": item.get('is_regulator_doc', False),
                    "nom_fichier": item.get('nom_fichier'),
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
                return "OK", safe_name, f"{target_file.name} ({size_mb:.2f} MB | SHA256: {sha[:10]}...)"
            except Exception as e:
                last_error = e
                time.sleep(1 + attempt)

        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return "FAILED", safe_name, str(last_error)

    def run_download(self, target_years, max_downloads=None, doc_types=None, workers=4):
        import concurrent.futures
        print("=========================================================================")
        print("=== CRAWLER & DESCARGADOR OFICIAL BDIF AMF (FRANCIA) — ARGOS MOTOR ===")
        print("=========================================================================")
        print(f"Destino Canónico: {self.raw_base}")
        print(f"Años Objetivo: {target_years}")
        print(f"Hilos concurrentes: {workers}")

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

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_item = {executor.submit(self._download_single_filing, item, yr): item for item in filings}
                done_count = 0
                total_count = len(filings)

                for future in concurrent.futures.as_completed(future_to_item):
                    done_count += 1
                    status, name, info = future.result()
                    if status == "OK":
                        downloaded += 1
                        print(f"[{done_count:03d}/{total_count:03d}] [OK] {name}: {info}")
                    elif status == "SKIPPED":
                        skipped += 1
                        if done_count % 25 == 0 or done_count == total_count:
                            print(f"[{done_count:03d}/{total_count:03d}] [OMITIDO] {name} (ya descargado y verificado)")
                    else:
                        failed += 1
                        print(f"[{done_count:03d}/{total_count:03d}] [ERROR] {name}: {info}")

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
    parser.add_argument('--years', type=str, default="2012,2013,2014,2015,2016,2017", help="Años contables separados por coma")
    parser.add_argument('--max', type=int, default=None, help="Límite máximo de descargas por año")
    parser.add_argument('--workers', type=int, default=4, help="Número de descargas concurrentes")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar ficheros")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    crawler = AMFBDIFCrawler(dry_run=args.dry_run)
    crawler.run_download(target_years=years, max_downloads=args.max, workers=args.workers)

if __name__ == '__main__':
    main()
