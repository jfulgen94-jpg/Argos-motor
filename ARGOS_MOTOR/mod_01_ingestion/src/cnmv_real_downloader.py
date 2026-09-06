"""
ARGOS_MOTOR — MOD_01_INGESTION
Motor de descarga real de informes regulatorios del Mercado Continuo Español

Fuentes:
  - 2021-2026: filings.xbrl.org (API JSON) → paquetes ESEF ZIP con CCAA + IGESTION + EINF
  - 2019-2020:  CNMV portal scraping → paquetes ZIP históricos
  - IAGC/IARC:  CNMV portal scraping → documentos PDF/XBRL individuales

Arquitectura:
  1. LEI_RESOLVER   : GLEIF API → LEI por nombre/NIF de empresa
  2. ESEF_DOWNLOADER: filings.xbrl.org → ZIP por LEI + año (2021+)
  3. CNMV_SCRAPER   : Formulario id=25 → ZIP por NIF + año (2019-2020)
  4. MANIFEST_BUILDER: genera el manifiesto con los 5 documentos
  5. RAW_LANDER     : descarga binaria + SHA-256 + meta.json

Uso:
  python mod_01_cnmv_real_downloader.py --ticker SAN --year 2024
  python mod_01_cnmv_real_downloader.py --all --years 2021 2024
"""

import sys, os, json, hashlib, time, zipfile, re
import argparse
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup

# ─── Configuración ─────────────────────────────────────────────────────────
GLEIF_API  = "https://api.gleif.org/api/v1/lei-records"
XBRL_API   = "https://filings.xbrl.org/api/filings"
XBRL_BASE  = "https://filings.xbrl.org"
CNMV_BASE  = "https://www.cnmv.es"

RAW_LANDING = Path("data/raw/landing_raw")
RAW_ES_CNMV = Path("data/raw/ES_CNMV")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; ARGOS_MOTOR/1.0; regulatory-data)',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'es-ES,es;q=0.9',
}

# ─── Universo de empresas del Mercado Continuo Español ─────────────────────
# Formato: ticker → {name, nif, lei (si conocido)}
MERCADO_CONTINUO = {
    "SAN":   {"name": "Banco Santander SA",              "nif": "A39000013",  "lei": "7245000NHIQTPK869X55"},
    "BBVA":  {"name": "Banco Bilbao Vizcaya Argentaria", "nif": "A48265169",  "lei": None},
    "IBE":   {"name": "Iberdrola SA",                    "nif": "A95066230",  "lei": "5QK37QC7NWOJ8D7WVQ45"},
    "ITX":   {"name": "Industria de Diseno Textil SA",   "nif": "A15075062",  "lei": None},
    "TEF":   {"name": "Telefonica SA",                   "nif": "A28015865",  "lei": None},
    "REP":   {"name": "Repsol SA",                       "nif": "A78374725",  "lei": None},
    "CABK":  {"name": "CaixaBank SA",                    "nif": "A08663619",  "lei": None},
    "AMS":   {"name": "Amadeus IT Group SA",             "nif": "A84236934",  "lei": None},
    "CLNX":  {"name": "Cellnex Telecom SA",              "nif": "A64907306",  "lei": None},
    "FER":   {"name": "Ferrovial SE",                    "nif": "A81939209",  "lei": None},
    "GRF":   {"name": "Grifols SA",                      "nif": "A58389123",  "lei": None},
    "MEL":   {"name": "Melia Hotels International SA",   "nif": "A07012829",  "lei": None},
    "ACS":   {"name": "ACS Actividades de Construccion", "nif": "A28004890",  "lei": None},
    "IAG":   {"name": "International Airlines Group SA", "nif": "A85845535",  "lei": None},
    "MAP":   {"name": "MAPFRE SA",                       "nif": "A08055741",  "lei": None},
    "NTGY":  {"name": "Naturgy Energy Group SA",         "nif": "A78210653",  "lei": None},
    "ENG":   {"name": "Enagás SA",                       "nif": "A61748986",  "lei": None},
    "ELE":   {"name": "Endesa SA",                       "nif": "A28023430",  "lei": None},
    "RED":   {"name": "REE Red Electrica de Espana SA",  "nif": "A78901946",  "lei": None},
    "SGRE":  {"name": "Siemens Gamesa Renewable Energy", "nif": "A01011253",  "lei": None},
    "ACX":   {"name": "Acerinox SA",                     "nif": "A08004593",  "lei": None},
    "COL":   {"name": "Inmobiliaria Colonial SOCIMI SA", "nif": "A08035498",  "lei": None},
    "EDP":   {"name": "EDP Renovaveis SA",               "nif": "A27356850",  "lei": None},
    "MRL":   {"name": "Merlin Properties SOCIMI SA",     "nif": "A86434793",  "lei": None},
    "SAB":   {"name": "Banco de Sabadell SA",            "nif": "A08000143",  "lei": None},
    "BKT":   {"name": "Bankinter SA",                    "nif": "A28157360",  "lei": None},
    "UNI":   {"name": "Unicaja Banco SA",                "nif": "A93480794",  "lei": None},
    "CLNX":  {"name": "Cellnex Telecom SA",              "nif": "A64907306",  "lei": None},
    "SOL":   {"name": "Solaria Energia y Medio Ambiente","nif": "A28590624",  "lei": None},
    "PHM":   {"name": "Pharma Mar SA",                   "nif": "A78985988",  "lei": None},
}


class LEIResolver:
    """Resuelve LEIs usando la API GLEIF."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json', 'User-Agent': 'ARGOS_MOTOR/1.0'})
        self.cache = {}
    
    def get_lei(self, company_info: dict) -> Optional[str]:
        """Obtiene el LEI de una empresa."""
        # Si ya está configurado, usarlo directamente
        if company_info.get('lei'):
            return company_info['lei']
        
        name = company_info['name']
        if name in self.cache:
            return self.cache[name]
        
        try:
            # Buscar por nombre legal exacto
            url = f"{GLEIF_API}?filter[entity.legalName]={name}&filter[entity.jurisdiction]=ES&page[size]=5"
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                records = r.json().get('data', [])
                if records:
                    lei = records[0].get('id', '')
                    self.cache[name] = lei
                    return lei
        except Exception as e:
            print(f"  GLEIF error para {name}: {e}")
        
        return None


class ESEFDownloader:
    """Descarga paquetes ESEF desde filings.xbrl.org."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._es_filings_cache = {}
        self._loaded_years = set()
    
    def _load_es_filings_for_year(self, year: int):
        """Carga todos los filings de España para un año específico."""
        if year in self._loaded_years:
            return
        
        period_end = f"{year}-12-31"
        page = 1
        filings = []
        
        while True:
            url = (f"{XBRL_API}?filter[country]=ES"
                   f"&filter[period_end]={period_end}"
                   f"&page[size]=100&page[number]={page}")
            try:
                r = self.session.get(url, timeout=15)
                if r.status_code != 200:
                    break
                data = r.json()
                items = data.get('data', [])
                meta = data.get('meta', {})
                total = meta.get('count', 0)
                
                for item in items:
                    attrs = item.get('attributes', {})
                    lei = attrs.get('lei', '')
                    pkg = attrs.get('package_url', '')
                    if lei and pkg:
                        filings.append({
                            'lei': lei,
                            'period_end': attrs.get('period_end', ''),
                            'package_url': f"{XBRL_BASE}{pkg}",
                            'report_url': f"{XBRL_BASE}{attrs['report_url']}" if attrs.get('report_url') else None,
                        })
                        self._es_filings_cache[lei] = self._es_filings_cache.get(lei, [])
                        self._es_filings_cache[lei].append(filings[-1])
                
                if len(filings) >= total or len(items) == 0:
                    break
                page += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"  Error cargando filings año {year} página {page}: {e}")
                break
        
        self._loaded_years.add(year)
        print(f"  Año {year}: {len(filings)} filings ES cargados en caché")
    
    def get_package_url(self, lei: str, year: int) -> Optional[str]:
        """Obtiene la URL del paquete ESEF para un LEI y año."""
        self._load_es_filings_for_year(year)
        
        filings = self._es_filings_cache.get(lei, [])
        year_str = str(year)
        for f in filings:
            if f['period_end'].startswith(year_str):
                return f['package_url']
        
        # Búsqueda directa por LEI si no está en caché
        url = f"{XBRL_API}?filter[entity.lei]={lei}&filter[period_end]={year}-12-31"
        try:
            r = self.session.get(url, timeout=10)
            if r.status_code == 200:
                items = r.json().get('data', [])
                for item in items:
                    attrs = item.get('attributes', {})
                    pkg = attrs.get('package_url', '')
                    if pkg:
                        return f"{XBRL_BASE}{pkg}"
        except:
            pass
        
        return None
    
    def download_package(self, url: str, dest_path: Path) -> dict:
        """Descarga un paquete ZIP y calcula SHA-256."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        r = self.session.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} al descargar {url}")
        
        sha = hashlib.sha256()
        size = 0
        
        with open(dest_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    sha.update(chunk)
                    size += len(chunk)
        
        sha256 = sha.hexdigest()
        
        # Verificar que es un ZIP válido
        with open(dest_path, 'rb') as f:
            magic = f.read(4)
        
        if magic != b'PK\x03\x04':
            raise RuntimeError(f"El archivo descargado no es un ZIP válido: magic={magic.hex()}")
        
        return {
            'path': str(dest_path),
            'size_bytes': size,
            'sha256': sha256,
            'downloaded_at': datetime.utcnow().isoformat() + 'Z',
            'source_url': url,
        }


class CNMVScraper:
    """Scraper del portal CNMV para informes 2019-2020 y para IAGC/IARC."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._cookies_accepted = False
    
    def _accept_cookies(self):
        """Acepta las cookies del portal CNMV."""
        if self._cookies_accepted:
            return
        
        url = f"{CNMV_BASE}/portal/Consultas/busqueda?id=25&lang=es"
        r = self.session.get(url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        fields = {inp.get('name'): inp.get('value', '') 
                  for inp in soup.find_all('input') if inp.get('name')}
        
        self.session.post(url, timeout=10,
                          data={'__EVENTTARGET': 'ctl00$WucCookiesPolicy$btnCookiesConfirmAll',
                                '__EVENTARGUMENT': '',
                                '__VIEWSTATE': fields.get('__VIEWSTATE', ''),
                                '__VIEWSTATEGENERATOR': fields.get('__VIEWSTATEGENERATOR', ''),
                                '__EVENTVALIDATION': fields.get('__EVENTVALIDATION', ''),
                                'ctl00$WucCookiesPolicy$btnCookiesConfirmAll': 'Aceptar todas'},
                          headers={'Content-Type': 'application/x-www-form-urlencoded',
                                   'Referer': url})
        self._cookies_accepted = True
    
    def search_annual_report(self, nif: str, year: int) -> Optional[str]:
        """Busca el informe anual de una empresa en el portal CNMV."""
        self._accept_cookies()
        
        base_url = f"{CNMV_BASE}/portal/Consultas/busqueda?id=25&lang=es"
        
        # Obtener ViewState fresco
        r = self.session.get(base_url, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        fields = {inp.get('name'): inp.get('value', '') 
                  for inp in soup.find_all('input') if inp.get('name')}
        
        # POST de búsqueda con fecha del ejercicio
        year_start = f"01/01/{year}"
        year_end   = f"31/12/{year}"
        
        payload = {
            '__EVENTTARGET': '',
            '__EVENTARGUMENT': '',
            '__VIEWSTATE': fields.get('__VIEWSTATE', ''),
            '__VIEWSTATEGENERATOR': fields.get('__VIEWSTATEGENERATOR', ''),
            '__EVENTVALIDATION': fields.get('__EVENTVALIDATION', ''),
            'ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion': '',
            'ctl00$ContentPrincipal$wFechas$fecha_desde': year_start,
            'ctl00$ContentPrincipal$wFechas$fecha_hasta': year_end,
            'ctl00$ContentPrincipal$btnOk': 'Buscar',
        }
        
        r2 = self.session.post(base_url, data=payload, timeout=20,
                               headers={'Content-Type': 'application/x-www-form-urlencoded',
                                        'Referer': base_url})
        
        # Analizar respuesta en busca del link de descarga con verdocumento
        soup2 = BeautifulSoup(r2.text, 'html.parser')
        
        # Buscar links de descarga en la respuesta
        for a in soup2.find_all('a', href=True):
            href = a['href']
            if 'verdocumento' in href.lower() or '.zip' in href.lower():
                # Construir URL completa si es relativa
                if href.startswith('/'):
                    return f"{CNMV_BASE}{href}"
                elif href.startswith('http'):
                    return href
                else:
                    return f"{CNMV_BASE}/Portal/Consultas/{href}"
        
        return None


class ManifestBuilder:
    """Construye el manifiesto de documentos para el pipeline de ingesta."""
    
    def build(self, ticker: str, year: int, 
               esef_path: Optional[Path],
               esef_meta: Optional[dict],
               iagc_path: Optional[Path] = None,
               iarc_path: Optional[Path] = None) -> dict:
        """Construye el manifiesto con los documentos disponibles."""
        
        manifest = {
            'ticker': ticker,
            'year': year,
            'source': 'CNMV_ES',
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'documents': {}
        }
        
        if esef_path and esef_path.exists():
            # El ZIP ESEF contiene CCAA + IGESTION + EINF
            manifest['documents']['ESEF_BUNDLE'] = {
                'path': str(esef_path),
                'sha256': esef_meta.get('sha256', '') if esef_meta else '',
                'size_bytes': esef_meta.get('size_bytes', 0) if esef_meta else 0,
                'source_url': esef_meta.get('source_url', '') if esef_meta else '',
                'type': 'ZIP_ESEF',
                'contains': ['CCAA_AUDITED', 'INFORME_GESTION', 'EINF_CSRD'],
            }
        
        if iagc_path and iagc_path.exists():
            manifest['documents']['IAGC'] = {
                'path': str(iagc_path),
                'type': 'PDF_IAGC',
            }
        
        if iarc_path and iarc_path.exists():
            manifest['documents']['IARC'] = {
                'path': str(iarc_path),
                'type': 'PDF_IARC',
            }
        
        return manifest


class CNMVRealDownloader:
    """Orquestador del sistema de descarga real de informes del Mercado Continuo."""
    
    def __init__(self, output_dir: Path = Path("data/raw/ES_CNMV_REAL")):
        self.output_dir = output_dir
        self.lei_resolver  = LEIResolver()
        self.esef_dl       = ESEFDownloader()
        self.cnmv_scraper  = CNMVScraper()
        self.manifest_bl   = ManifestBuilder()
        self.results = []
    
    def download_company_year(self, ticker: str, year: int, company_info: dict) -> dict:
        """Descarga todos los documentos disponibles para ticker+año."""
        
        result = {
            'ticker': ticker,
            'year': year,
            'name': company_info['name'],
            'status': 'pending',
            'documents': [],
            'errors': [],
        }
        
        print(f"\n{'='*60}")
        print(f"  {ticker} — {year} — {company_info['name']}")
        print(f"{'='*60}")
        
        # 1. Resolver LEI
        lei = self.lei_resolver.get_lei(company_info)
        print(f"  LEI: {lei or 'NOT FOUND'}")
        
        # 2. Crear directorio de destino
        dest_dir = self.output_dir / str(year) / ticker
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # 3. Intentar descargar el ESEF bundle (2021+)
        esef_path = None
        esef_meta = None
        
        if lei and year >= 2021:
            print(f"  Buscando ESEF en filings.xbrl.org...")
            pkg_url = self.esef_dl.get_package_url(lei, year)
            
            if pkg_url:
                print(f"  ✓ ESEF encontrado: {pkg_url[-60:]}")
                esef_filename = f"{ticker.lower()}_{year}_esef_bundle.zip"
                esef_path = dest_dir / esef_filename
                
                try:
                    esef_meta = self.esef_dl.download_package(pkg_url, esef_path)
                    print(f"  ✓ Descargado: {esef_meta['size_bytes']/1024/1024:.1f} MB, SHA256={esef_meta['sha256'][:16]}...")
                    result['documents'].append({
                        'type': 'ESEF_BUNDLE',
                        'path': str(esef_path),
                        'size_mb': round(esef_meta['size_bytes']/1024/1024, 2),
                        'sha256': esef_meta['sha256'],
                        'source_url': pkg_url,
                    })
                except Exception as e:
                    err = f"Error descargando ESEF: {e}"
                    print(f"  ✗ {err}")
                    result['errors'].append(err)
            else:
                print(f"  ⚠ No hay ESEF para {ticker} {year} en filings.xbrl.org")
        
        # 4. Fallback: scraping CNMV para años pre-ESEF
        if esef_path is None and year < 2021:
            nif = company_info.get('nif')
            if nif:
                print(f"  Buscando en CNMV (año {year}, pre-ESEF)...")
                try:
                    doc_url = self.cnmv_scraper.search_annual_report(nif, year)
                    if doc_url:
                        print(f"  ✓ URL CNMV: {doc_url[-60:]}")
                        # TODO: implementar descarga del doc CNMV
                        result['errors'].append(f"Descarga CNMV pre-ESEF pendiente de implementar")
                    else:
                        print(f"  ✗ No encontrado en CNMV")
                        result['errors'].append("No encontrado en portal CNMV")
                except Exception as e:
                    result['errors'].append(f"Error scraping CNMV: {e}")
        
        # 5. Guardar manifiesto
        manifest = self.manifest_bl.build(ticker, year, esef_path, esef_meta)
        manifest_path = dest_dir / f"{ticker.lower()}_{year}_manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        # 6. Resultado final
        if result['documents']:
            result['status'] = 'success'
        elif result['errors']:
            result['status'] = 'partial' if esef_path is None else 'error'
        else:
            result['status'] = 'not_found'
        
        return result
    
    def run_batch(self, tickers: list[str], years: list[int]) -> list[dict]:
        """Ejecuta la descarga batch para múltiples empresas y años."""
        results = []
        total = len(tickers) * len(years)
        done = 0
        
        print(f"\n{'#'*70}")
        print(f"BATCH: {len(tickers)} empresas × {len(years)} años = {total} combinaciones")
        print(f"{'#'*70}")
        
        for ticker in tickers:
            if ticker not in MERCADO_CONTINUO:
                print(f"  ⚠ Ticker {ticker} no encontrado en MERCADO_CONTINUO")
                continue
            
            company_info = MERCADO_CONTINUO[ticker]
            
            for year in years:
                try:
                    result = self.download_company_year(ticker, year, company_info)
                    results.append(result)
                    done += 1
                    
                    status_icon = "✓" if result['status'] == 'success' else "✗"
                    print(f"\n  {status_icon} [{done}/{total}] {ticker} {year}: {result['status']}")
                    if result['documents']:
                        for doc in result['documents']:
                            print(f"    → {doc['type']}: {doc.get('size_mb',0):.1f} MB")
                    if result['errors']:
                        for err in result['errors']:
                            print(f"    ✗ {err[:80]}")
                    
                    time.sleep(1)  # Rate limiting cortés
                    
                except Exception as e:
                    print(f"\n  ERROR {ticker} {year}: {e}")
                    results.append({'ticker': ticker, 'year': year, 'status': 'exception', 'error': str(e)})
                    done += 1
        
        # Guardar resumen
        summary = {
            'run_at': datetime.utcnow().isoformat() + 'Z',
            'total': total,
            'done': done,
            'success': sum(1 for r in results if r.get('status') == 'success'),
            'not_found': sum(1 for r in results if r.get('status') == 'not_found'),
            'errors': sum(1 for r in results if r.get('status') in ('error', 'exception')),
            'results': results,
        }
        
        summary_path = self.output_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'#'*70}")
        print(f"RESUMEN: {summary['success']} OK | {summary['not_found']} no encontrados | {summary['errors']} errores")
        print(f"Guardado en: {summary_path}")
        print(f"{'#'*70}")
        
        return results


# ─── CLI ──────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Descarga informes regulatorios del Mercado Continuo Español")
    parser.add_argument('--ticker', nargs='+', help='Tickers a descargar (ej: SAN BBVA IBE)')
    parser.add_argument('--years', nargs='+', type=int, default=[2024], help='Años a descargar')
    parser.add_argument('--all', action='store_true', help='Descargar todas las empresas configuradas')
    parser.add_argument('--output', default='data/raw/ES_CNMV_REAL', help='Directorio de salida')
    parser.add_argument('--test', action='store_true', help='Modo test: solo SAN+BBVA+IBE, año 2024')
    
    args = parser.parse_args()
    
    downloader = CNMVRealDownloader(output_dir=Path(args.output))
    
    if args.test:
        tickers = ['SAN', 'BBVA', 'IBE']
        years = [2024]
    elif args.all:
        tickers = list(MERCADO_CONTINUO.keys())
        years = args.years
    elif args.ticker:
        tickers = args.ticker
        years = args.years
    else:
        # Por defecto: test rápido
        print("Modo test: SAN + IBE, año 2024 (usa --ticker y --years para personalizar)")
        tickers = ['SAN', 'IBE']
        years = [2024]
    
    results = downloader.run_batch(tickers, years)
    
    print(f"\n✓ Proceso completado. {len(results)} resultados.")
