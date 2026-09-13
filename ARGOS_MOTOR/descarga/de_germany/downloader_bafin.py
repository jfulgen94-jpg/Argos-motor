"""
DOWNLOADER INSTITUCIONAL ALEMANIA (BAFIN / ESEF / UNTERNEHMENSREGISTER) — ARGOS MOTOR
Conector multicanal para la adquisición y sellado criptográfico de cuentas anuales auditadas de Alemania.
"""

import os
import sys
import json
import time
import re
import hashlib
import argparse
import asyncio
import httpx
from pathlib import Path
from datetime import datetime, timezone

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CONFIG_PATH = Path(__file__).parent / 'config_de.json'
UNIVERSE_PATH = Path(__file__).resolve().parents[2] / 'config' / 'master_universe_de.json'

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        "canonical_raw_path": "D:/ARGOS_DATA/raw/DE_BAFIN",
        "fallback_raw_path": "ARGOS_MOTOR/data/raw/DE_BAFIN",
        "staging_path": "D:/ARGOS_DATA/staging",
        "rate_limit": {"delay_between_requests_seconds": 1.0, "concurrent_downloads": 3},
        "retry_policy": {"max_retries": 3, "backoff_factor": 10},
        "user_agent": "ARGOS-Institutional-Data-Auditor/1.0 (Compliance; Regulatory Research)"
    }

def calculate_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def check_magic_bytes(filepath):
    if not filepath.exists() or filepath.stat().st_size == 0:
        return 'EMPTY'
    with open(filepath, 'rb') as f:
        header = f.read(32)
    if header.startswith(b'PK\x03\x04'):
        return 'ZIP_ESEF'
    if header.startswith(b'%PDF'):
        return 'PDF'
    header_lower = header.lower()
    if b'<!doctype html' in header_lower or b'<html' in header_lower or b'<?xml' in header_lower:
        return 'HTML_XHTML'
    return 'UNKNOWN'

def load_master_universe():
    if UNIVERSE_PATH.exists():
        data = json.loads(UNIVERSE_PATH.read_text(encoding='utf-8'))
        return data.get('companies', {})
    return {}

class GermanyDownloader:
    def __init__(self, segment=None, dry_run=False):
        self.config = load_config()
        self.dry_run = dry_run
        self.segment = segment

        # Detección de ruta canónica de almacenamiento
        canonical = Path(self.config.get('canonical_raw_path', 'D:/ARGOS_DATA/raw/DE_BAFIN'))
        if canonical.parent.exists():
            self.raw_base = canonical
        else:
            self.raw_base = Path(self.config.get('fallback_raw_path', 'ARGOS_MOTOR/data/raw/DE_BAFIN'))
        self.raw_base.mkdir(parents=True, exist_ok=True)

        staging_cfg = Path(self.config.get('staging_path', 'D:/ARGOS_DATA/staging'))
        if staging_cfg.parent.exists():
            self.staging_dir = staging_cfg / f"de_run_{time.strftime('%Y%m%d_%H%M%S')}"
        else:
            self.staging_dir = Path("ARGOS_MOTOR/data/staging/tmp_download") / f"de_run_{time.strftime('%Y%m%d_%H%M%S')}"

        self.universe = load_master_universe()
        max_conn = self.config.get('rate_limit', {}).get('concurrent_downloads', 3)
        self.semaphore = asyncio.Semaphore(max_conn)
        self.client = httpx.AsyncClient(
            headers={"User-Agent": self.config.get('user_agent', 'ARGOS-Compliance/1.0')},
            limits=httpx.Limits(max_connections=max_conn, max_keepalive_connections=max_conn),
            timeout=httpx.Timeout(60.0)
        )
        self.esef_index = {}

    async def load_esef_central_index(self):
        """Carga y cachea el índice central europeo filings.xbrl.org/index.json"""
        index_cache_file = Path("scratch/esef_index.json")
        data = None
        if index_cache_file.exists() and (time.time() - index_cache_file.stat().st_mtime) < 86400:
            try:
                data = json.loads(index_cache_file.read_text(encoding='utf-8'))
                print(f"  -> [Caché Local] Índice ESEF cargado ({len(data)} entidades).")
            except Exception:
                pass

        if not data:
            print("  -> Descargando índice central europeo ESEF (filings.xbrl.org/index.json)...")
            try:
                resp = await self.client.get("https://filings.xbrl.org/index.json", timeout=30.0)
                if resp.status_code == 200:
                    data = resp.json()
                    index_cache_file.parent.mkdir(parents=True, exist_ok=True)
                    index_cache_file.write_text(json.dumps(data), encoding='utf-8')
                    print(f"  -> [OK] Índice ESEF indexado y guardado en caché local ({len(data)} entidades).")
            except Exception as e:
                print(f"  -> [Aviso] No se pudo descargar index.json de XBRL.org: {e}")
                data = {}

        # Mapear por LEI y Año
        self.esef_index = {}
        for lei, ent in (data or {}).items():
            filings = ent.get('filings', {})
            for f_key, f_val in filings.items():
                dt = f_val.get('date', '')
                yr_str = dt[:4] if dt else ''
                pkg = f_val.get('report-package', '')
                if yr_str.isdigit() and pkg:
                    y = int(yr_str)
                    k = (lei.upper(), y)
                    self.esef_index[k] = {
                        'url': f"https://filings.xbrl.org/{f_key}/{pkg}",
                        'sha256': f_val.get('sha256sum', ''),
                        'date': dt,
                        'pkg': pkg
                    }
        print(f"  -> Filings ESEF mapeados en índice europeo: {len(self.esef_index)} registros.")

    def get_target_companies(self):
        comps = list(self.universe.values())
        if self.segment:
            segments = [s.strip().upper() for s in self.segment.split(',')]
            filtered = []
            for c in comps:
                c_seg = c.get('segment', '').upper()
                if any(s in c_seg for s in segments):
                    filtered.append(c)
            return filtered
        return comps

    async def discover_and_download_async(self, years=[2021, 2022, 2023, 2024]):
        await self.load_esef_central_index()
        companies = self.get_target_companies()

        print("\n=========================================================================")
        print("=== INICIANDO DESCARGA INSTITUCIONAL ALEMANIA (BAFIN / ESEF) ===")
        print("=========================================================================")
        print(f"Directorio Canónico Base: {self.raw_base.resolve()}")
        print(f"Empresas en Universo:     {len(companies)} (Filtro Segmento: {self.segment or 'TODOS'})")
        print(f"Ejercicios Fiscales:      {years}")
        print("=========================================================================\n")

        if not self.dry_run:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.raw_base.mkdir(parents=True, exist_ok=True)

        tasks = []
        for comp in companies:
            for year in years:
                tasks.append(self.download_filing(comp, year))

        results = await asyncio.gather(*tasks)

        for year in years:
            self.generate_manifest(year, results)

        await self.client.aclose()

    async def download_filing(self, comp, year):
        ticker = comp['ticker']
        lei = comp.get('lei', '')
        name = comp.get('name_legal', comp.get('name_common', ticker))
        segment = comp.get('segment', 'DE')
        hrb = comp.get('hrb_reg', '')

        tax_id = hrb.replace(' ', '_') if hrb else lei
        tax_id = re.sub(r'[^A-Za-z0-9_\-]', '_', tax_id) if tax_id else "UNKNOWN"
        comp_dir = self.raw_base / str(year) / f"{tax_id}_{ticker}"

        # 1. Comprobación de Caché Inmutable
        canonical_file = comp_dir / f"{ticker}_{year}_ESEF.zip"
        canonical_meta = comp_dir / f"{ticker}_{year}_ESEF.meta.json"

        if canonical_file.exists() and canonical_file.stat().st_size > 1000:
            sha = calculate_sha256(canonical_file)
            if canonical_meta.exists():
                try:
                    meta = json.loads(canonical_meta.read_text(encoding='utf-8'))
                    if meta.get('sha256') == sha:
                        return {
                            "status": "cache_hit", "ticker": ticker, "year": year,
                            "file_path": str(canonical_file), "sha256": sha,
                            "byte_size": canonical_file.stat().st_size, "format": "ZIP_ESEF"
                        }
                except Exception:
                    pass
            # Si existe el archivo pero no el meta, generar meta
            meta = {
                "file_name": canonical_file.name,
                "sha256": sha,
                "byte_size": canonical_file.stat().st_size,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_url": "CACHE_LOCAL",
                "reporting_year": year,
                "ticker": ticker,
                "legal_name": name,
                "lei": lei,
                "hrb_reg": hrb,
                "segment": segment,
                "magic_mime_verified": "ZIP_ESEF"
            }
            canonical_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
            return {
                "status": "cache_hit", "ticker": ticker, "year": year,
                "file_path": str(canonical_file), "sha256": sha,
                "byte_size": canonical_file.stat().st_size, "format": "ZIP_ESEF"
            }

        if self.dry_run:
            # Comprobar si existe en índice ESEF
            esef_hit = (lei.upper(), year) in self.esef_index if lei else False
            status_str = "DISPONIBLE_ESEF" if esef_hit else "CONSULTA_BAFIN"
            print(f"[DRY-RUN] [{segment}] {ticker:<6} | {name[:26]:<26} (LEI: {lei[:10]}...) | Año {year} -> {status_str}")
            return {"status": "dry_run", "ticker": ticker, "year": year, "esef_available": esef_hit}

        # 2. Canal A: ESEF Central Repository (Index Match)
        esef_info = self.esef_index.get((lei.upper(), year)) if lei else None
        if esef_info:
            pkg_url = esef_info['url']
            return await self.download_and_process(pkg_url, comp, year, "ESEF", official_sha=esef_info.get('sha256'))

        return {"status": "not_found", "ticker": ticker, "year": year}

    async def download_and_process(self, url, comp, year, tag, official_sha=""):
        async with self.semaphore:
            ticker = comp['ticker']
            lei = comp.get('lei', '')
            name = comp.get('name_legal', comp.get('name_common', ticker))
            hrb = comp.get('hrb_reg', '')
            segment = comp.get('segment', 'DE')

            tax_id = hrb.replace(' ', '_') if hrb else lei
            tax_id = re.sub(r'[^A-Za-z0-9_\-]', '_', tax_id) if tax_id else "UNKNOWN"
            comp_dir = self.raw_base / str(year) / f"{tax_id}_{ticker}"

            for attempt in range(self.config.get('retry_policy', {}).get('max_retries', 3)):
                try:
                    async with self.client.stream("GET", url, timeout=90) as resp:
                        if resp.status_code == 200:
                            tmp_file = self.staging_dir / f"de_{ticker}_{year}_{tag}.bin"
                            with open(tmp_file, 'wb') as f:
                                async for chunk in resp.aiter_bytes(chunk_size=65536):
                                    f.write(chunk)

                            magic = check_magic_bytes(tmp_file)
                            if magic in ['ZIP_ESEF', 'PDF']:
                                comp_dir.mkdir(parents=True, exist_ok=True)
                                ext = ".zip" if magic == 'ZIP_ESEF' else ".pdf"
                                dest_file = comp_dir / f"{ticker}_{year}_{tag}{ext}"
                                if dest_file.exists():
                                    dest_file.unlink()
                                tmp_file.replace(dest_file)

                                sha = calculate_sha256(dest_file)
                                meta = {
                                    "file_name": dest_file.name,
                                    "sha256": sha,
                                    "byte_size": dest_file.stat().st_size,
                                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "source_url": url,
                                    "reporting_year": year,
                                    "ticker": ticker,
                                    "legal_name": name,
                                    "lei": lei,
                                    "hrb_reg": hrb,
                                    "segment": segment,
                                    "magic_mime_verified": magic
                                }
                                meta_dest = comp_dir / f"{ticker}_{year}_{tag}.meta.json"
                                meta_dest.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
                                print(f"  [OK] Descargado y sellado: {dest_file.name} ({round(dest_file.stat().st_size/1024/1024, 2)} MB) | SHA: {sha[:12]}...")
                                await asyncio.sleep(0.3)
                                return {
                                    "status": "downloaded", "ticker": ticker, "year": year,
                                    "file_path": str(dest_file), "sha256": sha,
                                    "byte_size": dest_file.stat().st_size, "format": magic
                                }
                            else:
                                if tmp_file.exists(): tmp_file.unlink()
                                print(f"  [-] Archivo corrupto o no reconocido ({magic}) para {ticker} {year}")
                                return {"status": "quarantined", "ticker": ticker, "year": year}
                        elif resp.status_code in [429, 503]:
                            backoff = self.config.get('retry_policy', {}).get('backoff_factor', 10) * (attempt + 1)
                            print(f"  [429/503 Rate limit] {ticker} {year}. Esperando {backoff}s...")
                            await asyncio.sleep(backoff)
                        else:
                            break
                except Exception as e:
                    print(f"  [Error descarga {ticker} {year} intento {attempt+1}]: {e}")
                    await asyncio.sleep(2)

            return {"status": "failed", "ticker": ticker, "year": year}

    def generate_manifest(self, year, results):
        manifest = {
            "year": year,
            "country": "DE",
            "supervisor": "BaFin",
            "oam": "Unternehmensregister / ESEF",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "total_mapped": len(self.universe),
            "downloaded": 0,
            "cache_hits": 0,
            "failed": 0,
            "quarantined": 0,
            "manifest": []
        }

        for res in results:
            if res and res.get('year') == year:
                if res['status'] == 'cache_hit':
                    manifest['cache_hits'] += 1
                elif res['status'] == 'downloaded':
                    manifest['downloaded'] += 1
                elif res['status'] == 'quarantined':
                    manifest['quarantined'] += 1
                elif res['status'] == 'failed':
                    manifest['failed'] += 1

                if res['status'] in ['cache_hit', 'downloaded']:
                    manifest['manifest'].append({
                        "ticker": res['ticker'],
                        "year": year,
                        "doc_type": "ESEF_PACKAGE",
                        "status": res['status'].upper(),
                        "sha256": res['sha256'],
                        "size_bytes": res['byte_size'],
                        "path": res['file_path']
                    })

        manifest_path = self.raw_base / f"MANIFEST_BAFIN_{year}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"[MANIFEST] Manifiesto anual {year} guardado en: {manifest_path}")

        # Copia de seguridad en audits/manifests para versionado Git
        git_manifest_dir = Path("ARGOS_MOTOR/audits/manifests")
        git_manifest_dir.mkdir(parents=True, exist_ok=True)
        git_manifest_path = git_manifest_dir / f"MANIFEST_BAFIN_{year}.json"
        git_manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description="Downloader Institucional Alemania (BaFin / ESEF / Unternehmensregister)")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin descargar")
    parser.add_argument('--segment', type=str, default=None, help="Filtrar por índice: DAX40, MDAX, SDAX, PRIME_STANDARD")
    parser.add_argument('--years', type=str, default="2021,2022,2023,2024", help="Años a consultar separados por coma")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(',') if y.strip().isdigit()]
    downloader = GermanyDownloader(segment=args.segment, dry_run=args.dry_run)
    asyncio.run(downloader.discover_and_download_async(years=years))

if __name__ == '__main__':
    main()
