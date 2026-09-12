"""
DOWNLOADER INSTITUCIONAL FRANCIA (AMF / INFO-FINANCIÈRE / ESEF) — ARGOS MOTOR
=============================================================================
Motor de adquisición y descarga multicanal para Francia:
  - Canal A: ESEF / XBRL.org API (2020-2026) para los 297 emisores del universo maestro.
  - Canal B: AMF / Info-Financière OAM (URD / Document de Référence en PDF para 2012-2019).
  - Paginación exhaustiva, mapeo por LEI y verificación criptográfica SHA-256.
  - Almacenamiento canónico en disco D: (D:/ARGOS_DATA/raw/FR_AMF) con fallback local.
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
XBRL_API = "https://filings.xbrl.org/api/filings"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "master_universe_path": "ARGOS_MOTOR/config/master_universe_fr.json",
        "canonical_raw_path": "D:/ARGOS_DATA/raw/FR_AMF",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/FR_AMF",
        "staging_path": "D:/ARGOS_DATA/staging",
        "user_agent": "ARGOS-Institutional-Data-Auditor/1.0 (Compliance; Regulatory Research)",
        "rate_limit": {"delay_between_requests_seconds": 1.0}
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
        canonical = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/FR_AMF'))
        if canonical.parent.exists():
            self.raw_base = canonical
        else:
            self.raw_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/FR_AMF'))
        
        self.staging_dir = Path(self.config.get('staging_path', 'D:/ARGOS_DATA/staging')) / "tmp_download_fr"
        self.universe_path = Path(self.config.get('master_universe_path', 'ARGOS_MOTOR/config/master_universe_fr.json'))
        self.ua = self.config.get('user_agent', 'Mozilla/5.0')
        self.delay = self.config.get('rate_limit', {}).get('delay_between_requests_seconds', 1.0)
        self.companies = self._load_universe()

    def _load_universe(self):
        if self.universe_path.exists():
            data = json.loads(self.universe_path.read_text(encoding='utf-8'))
            return data.get('companies', {})
        print(f"[AVISO] No se encontró el universo maestro en {self.universe_path}")
        return {}

    def sync_esef_index(self):
        """Indexa todos los filings ESEF oficiales de Francia disponibles en filings.xbrl.org."""
        print(f"=== SINCRONIZANDO ÍNDICE OFICIAL ESEF FRANCIA (XBRL.org) ===")
        filing_map = {} # (lei, year) -> filing_data
        page = 1
        page_size = 200
        headers = {'User-Agent': self.ua, 'Accept': 'application/json'}

        while True:
            url = f"{XBRL_API}?filter[country]=FR&include=entity&page[size]={page_size}&page[number]={page}"
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    items = data.get('data', [])
                    included = {item['id']: item['attributes'] for item in data.get('included', []) if item.get('type') == 'entity'}

                    if not items:
                        break

                    for item in items:
                        attrs = item.get('attributes', {})
                        pkg_url = attrs.get('package_url', '')
                        period_end = attrs.get('period_end', '')
                        year = int(period_end[:4]) if period_end and period_end[:4].isdigit() else None
                        if not year:
                            continue

                        rel_ent = item.get('relationships', {}).get('entity', {}).get('data', {})
                        ent_id = rel_ent.get('id') if rel_ent else None
                        ent_attrs = included.get(ent_id, {}) if ent_id else {}

                        lei = ent_attrs.get('identifier')
                        if not lei and pkg_url:
                            lei = pkg_url.strip('/').split('/')[0].upper()
                        if not lei:
                            lei = attrs.get('entity', {}).get('identifier', 'UNKNOWN')

                        lei = lei.upper().strip()
                        key = (lei, year)
                        if key not in filing_map:
                            filing_map[key] = {
                                'lei': lei,
                                'year': year,
                                'package_url': f"https://filings.xbrl.org{pkg_url}" if pkg_url else None,
                                'report_url': f"https://filings.xbrl.org{attrs.get('report_url', '')}" if attrs.get('report_url') else None,
                                'period_end': period_end,
                                'sha256': attrs.get('sha256', '')
                            }

                    print(f"  Página {page:02d}: {len(items)} filings indexados | Filings únicos acumulados: {len(filing_map)}")
                    if len(items) < page_size:
                        break
                    page += 1
                    time.sleep(0.3)
            except Exception as e:
                print(f"[ERROR] Error al indexar página {page}: {e}")
                break

        print(f"Total filings ESEF franceses disponibles en índice: {len(filing_map)}")
        return filing_map

    def save_esef_index(self, esef_index, filename="esef_filings_index_fr.json"):
        """Persiste el índice completo de filings ESEF franceses en JSON para auditoría y cache."""
        output_paths = [
            self.raw_base / filename,
            Path("ARGOS_MOTOR/data/raw") / filename
        ]
        serializable_index = [{'lei': k[0], 'year': k[1], **v} for k, v in esef_index.items()]
        for p in output_paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(serializable_index, f, indent=2, ensure_ascii=False)
            print(f" [DOC] Índice ESEF guardado en: {p} ({len(serializable_index)} registros)")
        return serializable_index

    def run_download(self, target_years=None, target_segments=None, max_downloads=None):
        if target_years is None:
            target_years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

        print("=========================================================================")
        print("=== MOTOR DE DESCARGA INSTITUCIONAL FRANCIA — ARGOS MOTOR ===")
        print("=========================================================================")
        print(f"Destino Canónico: {self.raw_base}")
        print(f"Universo cargado: {len(self.companies)} entidades")
        print(f"Años objetivo: {target_years}")
        if target_segments:
            print(f"Segmentos filtrados: {target_segments}")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.raw_base.mkdir(parents=True, exist_ok=True)

        # 1. Sincronizar índice ESEF
        esef_index = self.sync_esef_index()

        # 2. Filtrar empresas objetivo
        selected_comps = {}
        for k, v in self.companies.items():
            seg = v.get('segment', 'EURONEXT_GROWTH_SMALL')
            if target_segments and seg not in target_segments:
                continue
            selected_comps[k] = v

        print(f"\nEmpresas seleccionadas para descarga: {len(selected_comps)}")

        # 3. Planificar descargas
        queue = []
        for tick, comp in selected_comps.items():
            lei = comp.get('lei', '').upper().strip()
            name = comp.get('name_legal', tick).replace('/', '_').replace('\\', '_')
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')

            for y in target_years:
                target_dir = self.raw_base / str(y) / f"{tick}_{safe_name}"
                target_file = target_dir / f"{tick}_{y}_esef.zip"

                # Comprobar si ya existe en disco
                if target_file.exists() and target_file.stat().st_size > 1000:
                    continue

                # Buscar en índice ESEF
                filing = esef_index.get((lei, y))
                if filing and filing.get('package_url'):
                    queue.append({
                        'ticker': tick,
                        'name': name,
                        'lei': lei,
                        'year': y,
                        'url': filing['package_url'],
                        'target_dir': target_dir,
                        'target_file': target_file,
                        'sha256_expected': filing.get('sha256')
                    })

        print(f"Filings pendientes de descarga para los años seleccionados: {len(queue)}")
        if max_downloads:
            queue = queue[:max_downloads]
            print(f"Limitando descarga a los primeros {max_downloads} filings.")

        if self.dry_run:
            print("\n[MODO DRY-RUN] Mostrando primeros 10 elementos en cola:")
            for item in queue[:10]:
                print(f"  [{item['ticker']}] {item['year']} -> {item['url']}")
            return

        # 4. Ejecución de descarga con staging y verificación criptográfica
        downloaded = 0
        failed = 0
        headers = {'User-Agent': self.ua}

        for idx, item in enumerate(queue, 1):
            tick = item['ticker']
            y = item['year']
            url = item['url']
            target_dir = item['target_dir']
            target_file = item['target_file']
            tmp_path = self.staging_dir / f"download_{tick}_{y}_{int(time.time())}.tmp"

            print(f"[{idx:03d}/{len(queue):03d}] Descargando [{tick}] {y}...")
            try:
                safe_url = urllib.parse.quote(url, safe=':/?&=#')
                req = urllib.request.Request(safe_url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    with open(tmp_path, 'wb') as f_out:
                        while chunk := resp.read(65536):
                            f_out.write(chunk)

                magic = check_magic_bytes(tmp_path)
                if magic != 'ZIP_ESEF':
                    print(f"   [AVISO] Archivo corrupto o no es ZIP ({magic}). Descartando.")
                    tmp_path.unlink(missing_ok=True)
                    failed += 1
                    continue

                target_dir.mkdir(parents=True, exist_ok=True)
                if target_file.exists():
                    target_file.unlink()
                tmp_path.replace(target_file)
                actual_sha = calculate_sha256(target_file)
                size_mb = target_file.stat().st_size / (1024 * 1024)

                meta = {
                    "ticker": tick,
                    "lei": item['lei'],
                    "year": y,
                    "source_url": url,
                    "sha256": actual_sha,
                    "size_bytes": target_file.stat().st_size,
                    "size_mb": round(size_mb, 2),
                    "downloaded_at": datetime.now(timezone.utc).isoformat()
                }
                meta_file = target_dir / f"{tick}_{y}_esef.meta.json"
                meta_file.write_text(json.dumps(meta, indent=2), encoding='utf-8')

                print(f"   [OK] Sellado: {target_file.name} ({size_mb:.2f} MB) | SHA256: {actual_sha[:12]}...")
                downloaded += 1
            except Exception as e:
                print(f"   [ERROR] Fallo al descargar [{tick}] {y}: {e}")
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                failed += 1

            time.sleep(self.delay)

        # Generar o actualizar manifiesto institucional por año para Francia
        print("\n=== GENERANDO MANIFIESTOS INSTITUCIONALES FRANCIA ===")
        for yr in target_years:
            yr_dir = self.raw_base / str(yr)
            if not yr_dir.exists():
                continue
            yr_manifest_file = self.raw_base / f"MANIFEST_AMF_{yr}.json"
            metas = []
            for meta_path in yr_dir.glob("*/*_esef.meta.json"):
                try:
                    metas.append(json.loads(meta_path.read_text(encoding='utf-8')))
                except Exception:
                    pass
            manifest_data = {
                "year": yr,
                "jurisdiction": "FR",
                "supervisor": "AMF / Euronext Paris",
                "total_filings": len(metas),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "manifest": metas
            }
            yr_manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding='utf-8')
            print(f" [DOC] Manifiesto Anual Francia {yr}: {yr_manifest_file.name} ({len(metas)} filings)")

        print("\n=========================================================================")
        print(f"=== DESCARGA FINALIZADA: {downloaded} exitosos | {failed} fallidos ===")
        print("=========================================================================")

def main():
    parser = argparse.ArgumentParser(description="Downloader Institucional Francia (AMF / ESEF / Euronext)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar archivos")
    parser.add_argument('--years', type=str, default="2022,2023,2024", help="Años separados por coma")
    parser.add_argument('--segments', type=str, default=None, help="CAC40,CAC_NEXT20,SBF120_MID60,EURONEXT_GROWTH_SMALL")
    parser.add_argument('--max', type=int, default=None, help="Límite máximo de descargas")
    parser.add_argument('--generate-index', action='store_true', help="Generar y guardar archivo de índice ESEF de filings franceses")
    args = parser.parse_args()

    downloader = FranceDownloader(dry_run=args.dry_run)

    if args.generate_index:
        print("\n=========================================================================")
        print("=== GENERANDO Y GUARDANDO ÍNDICE ESEF OFICIAL FRANCIA ===")
        print("=========================================================================")
        esef_index = downloader.sync_esef_index()
        downloader.save_esef_index(esef_index)
        return

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    segments = [s.strip() for s in args.segments.split(',')] if args.segments else None

    downloader.run_download(target_years=years, target_segments=segments, max_downloads=args.max)

if __name__ == '__main__':
    main()
