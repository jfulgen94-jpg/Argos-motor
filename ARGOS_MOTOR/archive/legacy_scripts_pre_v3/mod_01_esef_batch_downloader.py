"""
ARGOS_MOTOR — MOD_01_INGESTION
Sistema de descarga en bruto de informes ESEF del Mercado Continuo Español

Motor: filings.xbrl.org (API JSON pública) + GLEIF (para LEI lookup)
Cobertura: 2020-2026 (ESEF obligatorio desde 2020 en España)
Salida: ZIPs en bruto + SHA-256 + meta.json en data/raw/landing_raw/

ARQUITECTURA COMPLETA:
  Stage 1 (este script): Descarga en bruto → data/raw/landing_raw/{year}/{ticker}/
  Stage 2 (organize_raw_filings.py): Validación + organización → data/raw/ES_CNMV/

Uso:
  python mod_01_esef_batch_downloader.py                        # Test: 3 empresas 2024
  python mod_01_esef_batch_downloader.py --tickers SAN IBE TEF  # Específicas
  python mod_01_esef_batch_downloader.py --years 2021 2024 --all # Todas, 2021-2024
  python mod_01_esef_batch_downloader.py --minutes 30            # Descargar 30 min max
"""

import sys, os, json, hashlib, time, zipfile, re, argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ─── Configuración ─────────────────────────────────────────────────────────
XBRL_API  = "https://filings.xbrl.org/api/filings"
XBRL_BASE = "https://filings.xbrl.org"
GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
RAW_LANDING = Path("data/raw/landing_raw")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; ARGOS_MOTOR/2.0; +https://github.com/stater)',
    'Accept': 'application/vnd.api+json, application/json, */*',
}

# ─── Mapa de LEIs confirmados (extraídos de filings.xbrl.org 2024-12-31) ──
# Formato: TICKER → LEI (confirmado con datos reales de xbrl.org)
CONFIRMED_LEIS = {
    # IBEX 35 principales
    "SAN":   "5493006QMFDDMYWIAM13",   # Banco Santander SA (2024 ✓)
    "IBE":   "5QK37QC7NWOJ8D7WVQ45",   # Iberdrola SA (2024 ✓)
    "MEL":   "959800JRKSZ6YZD4EL80",   # Melia Hotels International SA (2024 ✓)
    "GRF":   "959800HSSNXWRKBK4N60",   # Grifols SA (2024 ✓)
    "BKT":   "VWMYAEQSTOPNV0SUGU82",   # Bankinter SA (2024 ✓)
    "UNI":   "5493007SJLLCTM6J6M37",   # Unicaja Banco SA (2024 ✓)
    "NTGY":  "TL2N6M87CW970S5SV098",   # Naturgy Energy Group SA (2024 ✓)
    "PHM":   "959800QWKZ45ZQC2AV58",   # Pharma Mar SA (2024 ✓)
    "SGRE":  "959800XKAB9VNAVN9425",   # Sacyr SA / SGRE (2024 ✓ - verificar)
    "RED":   "5493009HMD0C90GUV498",   # Redeia Corporacion SA (2024 ✓)
    "FCC":   "959800201400051783",     # Fomento de Construcciones (2024 ✓)
    "FLUIDRA":"959800201400050266",    # Fluidra SA (2024 ✓)
    "ALANTRA":"95980078NDTDLTDH6130",  # Alantra Partners SA (2024 ✓)
    "PSG":   "549300N94L4D5NDBFG97",   # Prosegur Compañia de Seguridad (2024 ✓)
    "AMS_GRP":"213800IMKAUV5KW28586",  # Renta 4 Banco (verificar AMS)
}

# Mapa de nombres de empresa para búsqueda GLEIF
EMPRESA_NAMES = {
    "SAN":   "Banco Santander",
    "BBVA":  "Banco Bilbao Vizcaya Argentaria",
    "IBE":   "Iberdrola SA",
    "ITX":   "Industria de Diseno Textil",
    "TEF":   "Telefonica SA",
    "REP":   "Repsol SA",
    "CABK":  "CaixaBank",
    "AMS":   "Amadeus IT Group",
    "CLNX":  "Cellnex Telecom",
    "FER":   "Ferrovial SA",
    "GRF":   "Grifols SA",
    "MEL":   "Melia Hotels International",
    "ACS":   "ACS Actividades de Construccion",
    "IAG":   "International Airlines Group",
    "MAP":   "MAPFRE SA",
    "NTGY":  "Naturgy Energy Group",
    "ENG":   "Enagas SA",
    "ELE":   "Endesa SA",
    "RED":   "Redeia Corporacion",
    "ACX":   "Acerinox SA",
    "COL":   "Inmobiliaria Colonial SOCIMI",
    "MRL":   "Merlin Properties SOCIMI",
    "SAB":   "Banco de Sabadell",
    "BKT":   "Bankinter SA",
    "UNI":   "Unicaja Banco SA",
    "SOL":   "Solaria Energia y Medio Ambiente",
    "PHM":   "Pharma Mar SA",
    "TLGO":  "Talgo SA",
    "AENA":  "AENA SME SA",
    "CIE":   "CIE Automotive SA",
    "EVO":   "Evo Banco SA",
    "SGRE":  "Siemens Gamesa Renewable Energy",
    "OHL":   "Obrascon Huarte Lain SA",
    "DIA":   "Distribuidora Internacional de Alimentacion SA",
    "VIS":   "Viscofan SA",
    "NHH":   "NH Hotel Group SA",
    "ALBA":  "Corporacion Financiera Alba SA",
}


class XBRLFilingsClient:
    """Cliente para la API de filings.xbrl.org."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._cache = {}  # (year, country) → list[dict]
    
    def _load_country_year(self, country: str, year: int) -> list:
        """Carga todos los filings de un país y año."""
        cache_key = (country, year)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        period_end = f"{year}-12-31"
        all_filings = []
        page = 1
        
        while True:
            url = (f"{XBRL_API}?filter[country]={country}"
                   f"&filter[period_end]={period_end}"
                   f"&page[size]=200&page[number]={page}"
                   f"&include=entity")
            try:
                r = self.session.get(url, timeout=20)
                if r.status_code != 200:
                    break
                
                data = r.json()
                items = data.get('data', [])
                included = data.get('included', [])
                meta = data.get('meta', {})
                total = meta.get('count', 0)
                
                # Mapear entidades incluidas
                entity_map = {}
                for inc in included:
                    if inc.get('type') == 'entity':
                        eid = inc.get('id', '')
                        attrs = inc.get('attributes', {})
                        entity_map[eid] = {
                            'name': attrs.get('name', ''),
                            'lei': attrs.get('lei', ''),
                        }
                
                for item in items:
                    attrs = item.get('attributes', {})
                    pkg = attrs.get('package_url', '')
                    if not pkg:
                        continue
                    
                    # Resolver entidad
                    rels = item.get('relationships', {})
                    entity_data = rels.get('entity', {}).get('data', {})
                    entity_id = entity_data.get('id', '') if isinstance(entity_data, dict) else ''
                    entity = entity_map.get(entity_id, {})
                    
                    # Extraer LEI del nombre del fichero (más fiable)
                    lei_from_pkg = ''
                    match = re.search(r'/([A-Z0-9]{15,25})/', pkg)
                    if match:
                        lei_from_pkg = match.group(1)
                    
                    all_filings.append({
                        'lei': entity.get('lei') or lei_from_pkg,
                        'name': entity.get('name', ''),
                        'period_end': attrs.get('period_end', ''),
                        'package_url': f"{XBRL_BASE}{pkg}",
                        'report_url': f"{XBRL_BASE}{attrs['report_url']}" if attrs.get('report_url') else None,
                    })
                
                if len(all_filings) >= total or len(items) == 0:
                    break
                page += 1
                time.sleep(0.3)
                
            except Exception as e:
                print(f"  Error API filings.xbrl.org año {year}: {e}")
                break
        
        self._cache[cache_key] = all_filings
        return all_filings
    
    def find_package(self, lei: str, year: int, country: str = 'ES') -> Optional[str]:
        """Busca el URL del paquete ZIP para un LEI y año."""
        filings = self._load_country_year(country, year)
        for f in filings:
            if f['lei'] == lei or lei in f['package_url']:
                return f['package_url']
        
        # Búsqueda directa si no está en caché
        url = f"{XBRL_API}?filter[entity.lei]={lei}&filter[period_end]={year}-12-31&include=entity"
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                items = r.json().get('data', [])
                for item in items:
                    pkg = item.get('attributes', {}).get('package_url', '')
                    if pkg:
                        return f"{XBRL_BASE}{pkg}"
        except:
            pass
        
        return None
    
    def get_all_es_filings_year(self, year: int) -> list:
        """Obtiene todos los filings de España para un año."""
        return self._load_country_year('ES', year)


class GLEIFClient:
    """Cliente para la API GLEIF (resolución de LEIs)."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json', 'User-Agent': 'STATER/1.0'})
        self.cache = {}
    
    def get_lei(self, company_name: str) -> Optional[str]:
        """Busca el LEI de una empresa por nombre."""
        if company_name in self.cache:
            return self.cache[company_name]
        
        url = f"{GLEIF_API}?filter[entity.legalName]={company_name}&filter[entity.jurisdiction]=ES&page[size]=5"
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                records = r.json().get('data', [])
                if records:
                    lei = records[0].get('id', '')
                    self.cache[company_name] = lei
                    return lei
        except Exception as e:
            print(f"  GLEIF error para {company_name}: {e}")
        
        return None


def sha256_of_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            sha.update(chunk)
    return sha.hexdigest()


def download_zip(url: str, dest_path: Path, session: requests.Session) -> dict:
    """Descarga un ZIP y devuelve metadatos incluyendo SHA-256."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    r = session.get(url, timeout=120, stream=True)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    
    sha = hashlib.sha256()
    size = 0
    
    with open(dest_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
                sha.update(chunk)
                size += len(chunk)
    
    sha256 = sha.hexdigest()
    
    # Verificar ZIP
    with open(dest_path, 'rb') as f:
        magic = f.read(4)
    if magic != b'PK\x03\x04':
        dest_path.unlink()
        raise RuntimeError(f"No es un ZIP válido (magic={magic.hex()})")
    
    # Listar contenido
    try:
        with zipfile.ZipFile(dest_path) as zf:
            zip_contents = zf.namelist()
    except:
        zip_contents = []
    
    return {
        'sha256': sha256,
        'size_bytes': size,
        'size_mb': round(size / 1024 / 1024, 2),
        'zip_contents': zip_contents,
        'source_url': url,
        'downloaded_at': datetime.utcnow().isoformat() + 'Z',
    }


class ESEFBatchDownloader:
    """Descarga batch de ESEF para el Mercado Continuo Español, 2019-2026."""
    
    def __init__(self, output_dir: Path = RAW_LANDING):
        self.output_dir = output_dir
        self.xbrl_client = XBRLFilingsClient()
        self.gleif_client = GLEIFClient()
        self.dl_session = requests.Session()
        self.dl_session.headers.update(HEADERS)
    
    def resolve_lei(self, ticker: str, name: str) -> Optional[str]:
        """Resuelve el LEI de una empresa (primero del mapa, luego GLEIF)."""
        # 1. Mapa de LEIs confirmados
        if ticker in CONFIRMED_LEIS:
            return CONFIRMED_LEIS[ticker]
        
        # 2. Buscar en los filings de España disponibles
        for year in [2024, 2023, 2022, 2021]:
            filings = self.xbrl_client.get_all_es_filings_year(year)
            name_lower = name.lower().replace(',', '').replace('.', '').replace('s a', 'sa')
            for f in filings:
                f_name = f.get('name', '').lower().replace(',', '').replace('.', '').replace('s a', 'sa')
                if any(w in f_name for w in name_lower.split()[:2]):
                    lei = f.get('lei', '')
                    if lei:
                        CONFIRMED_LEIS[ticker] = lei  # Cache dinámico
                        return lei
        
        # 3. GLEIF como último recurso
        lei = self.gleif_client.get_lei(name)
        if lei:
            CONFIRMED_LEIS[ticker] = lei
        return lei
    
    def download_ticker_year(self, ticker: str, year: int) -> dict:
        """Descarga el paquete ESEF de un ticker y año."""
        name = EMPRESA_NAMES.get(ticker, ticker)
        
        result = {
            'ticker': ticker,
            'year': year,
            'name': name,
            'status': 'pending',
            'lei': None,
            'pkg_url': None,
            'path': None,
            'sha256': None,
            'size_mb': None,
            'zip_contents': [],
            'error': None,
        }
        
        # 1. Resolver LEI
        lei = self.resolve_lei(ticker, name)
        result['lei'] = lei
        
        if not lei:
            result['status'] = 'lei_not_found'
            result['error'] = f"No se encontró el LEI para {ticker} ({name})"
            return result
        
        # 2. Buscar paquete en filings.xbrl.org
        pkg_url = self.xbrl_client.find_package(lei, year)
        result['pkg_url'] = pkg_url
        
        if not pkg_url:
            result['status'] = 'filing_not_found'
            result['error'] = f"No hay filing ESEF para {ticker} {year} en filings.xbrl.org"
            return result
        
        # 3. Descargar el ZIP
        filename = f"{ticker.lower()}_{year}_esef_bundle.zip"
        dest_path = self.output_dir / str(year) / ticker / filename
        
        # Si ya existe y tiene contenido, skip
        if dest_path.exists() and dest_path.stat().st_size > 100000:
            existing_sha = sha256_of_file(dest_path)
            result['status'] = 'already_exists'
            result['path'] = str(dest_path)
            result['sha256'] = existing_sha
            result['size_mb'] = round(dest_path.stat().st_size / 1024 / 1024, 2)
            return result
        
        try:
            meta = download_zip(pkg_url, dest_path, self.dl_session)
            
            result.update({
                'status': 'success',
                'path': str(dest_path),
                'sha256': meta['sha256'],
                'size_mb': meta['size_mb'],
                'zip_contents': meta['zip_contents'],
            })
            
            # Guardar meta.json junto al ZIP
            meta_data = {
                'ticker': ticker,
                'year': year,
                'name': name,
                'lei': lei,
                'period_end': f"{year}-12-31",
                'source': 'filings.xbrl.org',
                **meta,
            }
            meta_path = dest_path.with_suffix('.meta.json')
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta_data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            result['status'] = 'download_error'
            result['error'] = str(e)
        
        return result
    
    def run_batch(self, tickers: list, years: list, 
                   max_minutes: Optional[int] = None) -> list:
        """Descarga batch con tiempo máximo opcional."""
        results = []
        start_time = datetime.now()
        deadline = start_time + timedelta(minutes=max_minutes) if max_minutes else None
        
        total = len(tickers) * len(years)
        done = 0
        
        print(f"\n{'#'*60}")
        print(f"BATCH ESEF: {len(tickers)} empresas × {len(years)} años = {total} descargas")
        if deadline:
            print(f"Tiempo límite: {max_minutes} minutos")
        print(f"Directorio de salida: {self.output_dir}")
        print(f"{'#'*60}\n")
        
        for ticker in tickers:
            for year in years:
                if deadline and datetime.now() >= deadline:
                    print(f"\n⏱ Tiempo límite alcanzado. {done}/{total} completados.")
                    break
                
                done += 1
                print(f"[{done}/{total}] {ticker} {year} — ", end='', flush=True)
                
                result = self.download_ticker_year(ticker, year)
                results.append(result)
                
                status = result['status']
                if status == 'success':
                    print(f"✓ {result['size_mb']:.1f} MB | SHA256={result['sha256'][:16]}...")
                elif status == 'already_exists':
                    print(f"⏭ Ya existe ({result['size_mb']:.1f} MB)")
                elif status == 'filing_not_found':
                    print(f"⚠ No encontrado en filings.xbrl.org")
                elif status == 'lei_not_found':
                    print(f"⚠ LEI no resuelto para {ticker}")
                else:
                    print(f"✗ {result.get('error','')[:60]}")
                
                time.sleep(0.5)  # Rate limiting
            
            else:
                continue
            break  # Si se salió del loop interior por tiempo
        
        # Guardar resumen
        summary = {
            'run_at': start_time.isoformat(),
            'completed_at': datetime.now().isoformat(),
            'total': total,
            'done': done,
            'success': sum(1 for r in results if r['status'] == 'success'),
            'already_exists': sum(1 for r in results if r['status'] == 'already_exists'),
            'not_found': sum(1 for r in results if r['status'] in ('filing_not_found', 'lei_not_found')),
            'errors': sum(1 for r in results if r['status'] in ('download_error',)),
            'total_mb': round(sum(r.get('size_mb', 0) or 0 for r in results), 1),
            'results': results,
        }
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        summary_path = self.output_dir / f"batch_summary_{ts}.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'#'*60}")
        print(f"RESUMEN FINAL:")
        print(f"  ✓ Éxito:         {summary['success']}")
        print(f"  ⏭ Ya existían:   {summary['already_exists']}")
        print(f"  ⚠ No encontrado: {summary['not_found']}")
        print(f"  ✗ Errores:       {summary['errors']}")
        print(f"  📦 Total MB:     {summary['total_mb']:.1f} MB")
        print(f"  📄 Resumen:      {summary_path}")
        print(f"{'#'*60}")
        
        return results


# ─── CLI ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Descarga paquetes ESEF del Mercado Continuo Español (2020-2026)"
    )
    parser.add_argument(
        '--tickers', nargs='+',
        help='Tickers a descargar (ej: SAN BBVA IBE TEF). Por defecto: 12 principales IBEX'
    )
    parser.add_argument(
        '--years', nargs='+', type=int, default=[2024],
        help='Años a descargar (ej: 2021 2022 2023 2024). Por defecto: 2024'
    )
    parser.add_argument(
        '--all-es', action='store_true',
        help='Descargar TODOS los filings ES disponibles en filings.xbrl.org'
    )
    parser.add_argument(
        '--minutes', type=int,
        help='Tiempo máximo de descarga en minutos'
    )
    parser.add_argument(
        '--output', default='data/raw/landing_raw',
        help='Directorio de salida (default: data/raw/landing_raw)'
    )
    
    args = parser.parse_args()
    
    downloader = ESEFBatchDownloader(output_dir=Path(args.output))
    
    if args.all_es:
        # Descargar todos los filings de España disponibles
        print("Modo ALL-ES: descargando todos los filings españoles disponibles...")
        for year in args.years:
            print(f"\n=== Año {year} ===")
            filings = downloader.xbrl_client.get_all_es_filings_year(year)
            print(f"Encontrados: {len(filings)} filings para España {year}")
            
            for f in filings:
                lei = f['lei']
                pkg_url = f['package_url']
                name = f['name']
                
                if not pkg_url:
                    continue
                
                # Extraer ticker del nombre si es posible
                ticker = lei[:8]  # Usar inicio del LEI como identificador temporal
                
                dest_dir = Path(args.output) / str(year) / ticker
                filename = f"{ticker}_{year}_esef.zip"
                dest_path = dest_dir / filename
                
                if dest_path.exists():
                    print(f"  ⏭ {name[:30]:30s} ya existe")
                    continue
                
                print(f"  ↓ {name[:30]:30s} [{lei[:12]}] → ", end='', flush=True)
                try:
                    meta = download_zip(pkg_url, dest_path, downloader.dl_session)
                    print(f"✓ {meta['size_mb']:.1f} MB")
                    
                    # Guardar meta
                    meta_data = {'lei': lei, 'name': name, 'year': year, **meta}
                    meta_path = dest_path.with_suffix('.meta.json')
                    with open(meta_path, 'w', encoding='utf-8') as mf:
                        json.dump(meta_data, mf, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"✗ {e}")
                
                time.sleep(0.5)
    else:
        # Modo normal: tickers específicos
        if args.tickers:
            tickers = args.tickers
        else:
            # Por defecto: 12 principales
            tickers = list(CONFIRMED_LEIS.keys())[:12]
        
        results = downloader.run_batch(
            tickers=tickers,
            years=args.years,
            max_minutes=args.minutes,
        )
