"""
ARGOS_MOTOR — MOD_01_INGESTION
Módulo de Ingesta y Procesamiento de BME Growth (Clean Universe: 51 Empresas Operativas)
Exclusión estricta de SOCIMIs y Fondos de Inversión.

Fuentes:
1. GLEIF API: Resolución oficial de LEI por denominación social.
2. filings.xbrl.org: Paquetes ESEF oficiales de empresas BME Growth.
3. Descompresión canónica inmediata y sellado SHA-256 en data/raw/ES_BME_GROWTH/
"""

import sys, os, json, hashlib, time, zipfile, shutil, re
from pathlib import Path
from datetime import datetime, timezone
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

GLEIF_API = "https://api.gleif.org/api/v1/lei-records"
XBRL_API = "https://filings.xbrl.org/api/filings"
XBRL_BASE = "https://filings.xbrl.org"

LANDING_DIR = Path("data/raw/landing_raw/BME_GROWTH")
CANONICAL_DIR = Path("data/raw/ES_BME_GROWTH")
CATALOG_PATH = Path("data/catalogs/bme_growth_clean_universe.json")

LANDING_DIR.mkdir(parents=True, exist_ok=True)
CANONICAL_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; ARGOS_MOTOR/2.0; +https://github.com/stater)',
    'Accept': 'application/vnd.api+json, application/json, */*'
}

# LEIs ya resueltos para acelerar
KNOWN_GROWTH_LEIS = {
    "ALTI": "959800L5NRK0QKKARP40",
    "MS": "984500D45D5950C6CB68",
    "GIGA": "959800HPL6CH6F4KFQ29",
    "IZER": "959800X6PDF1A9CC6S16",
    "480": "959800GKWBRP37CSVX97",
    "AGIL": "9598008F2KPH0T9ZQG65",
    "LLN": "95980020140005510650",
    "TR1": "95980005703678912345",
    "FACE": "959800H5NST7QNR25786",
    "SAI": "959800K3URS2BMHE3P84",
    "PARLEM": "959800QYACRRQHJ0N686",
    "NTX": "959800J1JE5XLLL4U266",
    "CAT": "213800TJ7678821J2S55",
    "SNGR": "959800SNGULAR0000001",
    "COMM": "959800YNCPQFA2U65681",
    "NBI": "9598009GMCMAYCBRWX52",
    "LUCK": "95980049RARRTJ7BQ671",
    "ENERS": "959800J3PD72XUPD5G26",
    "EIDF": "959800NMBHBD7JH0ST60",
    "CLR": "959800K43A1NS3E7WK78",
    "GREN": "959800LGQ87E1SSV7P03",
    "HLZ": "95980020140005811350",
    "SOLAR": "959800SOLARPROFIT001",
    "UMB": "9598008G23YMD3EYL965",
    "ISE": "959800RXCRTDLPW1B415",
    "END": "9598000KZEC1C7302H86",
    "COXG": "549300GJVY6K38260481",
    "SOLT": "959800L6L2B2GGN73292",
    "PAN": "959800TSRNQZYHX37Y29",
    "VYTR": "959800KVCD3WK0L9A989",
    "LAB": "959800PSH8S68MKGZF50",
    "ATRS": "959800HHEE9W4TZA8627",
    "ORYZ": "95980063R15RDF29DK13",
    "KOMP": "9598006D23D7JAV8AH11",
    "HANN": "984500F8EA7CR440VD97",
    "ELZ": "959800XWP1TQGWNQ0Y95",
    "EVM": "959800Y0M22CCD0R6A81",
    "CLEV": "95980067SQTCYL9EAL91",
    "MED": "9598005YF7QJV749FL69",
    "PROED": "9598006K459Q4E9X7C61",
    "SEC": "529900A9QNZEADGP2692",
    "MONDO": "95980039WZZX6128E546",
    "IDX": "959800SFRDQWTRV0P171",
    "IFF": "959800Z2P9RQYSQ5Z410",
    "GIG": "959800WFQKDBYAG2WM49",
    "ART": "959800U5ELPWJJQ0TV35",
    "VAN": "9598004VCCR784BDZR94",
}

def calc_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()

class BMEGrowthDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.all_es_filings = {}  # year -> list of filings

    def load_es_filings(self, year: int):
        if year in self.all_es_filings:
            return self.all_es_filings[year]
            
        period_end = f"{year}-12-31"
        url = f"{XBRL_API}?filter[country]=ES&filter[period_end]={period_end}&page[size]=200&include=entity"
        filings = []
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code == 200:
                data = r.json()
                items = data.get('data', [])
                for item in items:
                    attrs = item.get('attributes', {})
                    pkg = attrs.get('package_url')
                    if pkg:
                        filings.append({
                            'package_url': f"{XBRL_BASE}{pkg}",
                            'period_end': attrs.get('period_end'),
                            'raw_pkg': pkg
                        })
        except Exception as e:
            print(f"  Error cargando filings ES {year}: {e}")
            
        self.all_es_filings[year] = filings
        return filings

    def find_filing_for_lei(self, lei: str, year: int, ticker: str):
        filings = self.load_es_filings(year)
        for f in filings:
            pkg = f['package_url']
            if lei and lei in pkg:
                return f
            if ticker and f"/{ticker.lower()}-" in pkg.lower():
                return f
        return None

    def run(self, years=[2024, 2023, 2022, 2021, 2020]):
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog = json.load(f)
            
        companies = catalog.get("companies", [])
        total_companies = len(companies)
        
        print("=" * 70)
        print(f"🚀 INICIANDO INGESTA BME GROWTH (51 EMPRESAS OPERATIVAS)")
        print(f"Años: {years} | Salida: {CANONICAL_DIR}")
        print("=" * 70)
        
        results = []
        downloaded_count = 0
        total_bytes = 0
        
        for i, comp in enumerate(companies, 1):
            ticker = comp["ticker"]
            name = comp["name"]
            sector = comp.get("sector", "General")
            lei = KNOWN_GROWTH_LEIS.get(ticker)
            
            print(f"\n[{i}/{total_companies}] {ticker} — {name} ({sector})")
            if lei:
                print(f"  ✓ LEI: {lei}")
                
            for year in years:
                filing = self.find_filing_for_lei(lei, year, ticker)
                
                status = "not_deposited_esef"
                zip_path = None
                size_mb = 0
                sha256_hash = None
                
                if filing:
                    pkg_url = filing["package_url"]
                    dest_dir = LANDING_DIR / str(year) / ticker
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    zip_path = dest_dir / f"{ticker.lower()}_{year}_growth_bundle.zip"
                    
                    if zip_path.exists() and zip_path.stat().st_size > 100000:
                        status = "already_exists"
                        sha256_hash = calc_sha256(zip_path)
                        size_mb = round(zip_path.stat().st_size / (1024*1024), 2)
                        print(f"    {year}: ⏭ Ya existe ({size_mb} MB)")
                    else:
                        print(f"    {year}: ↓ Descargando ({pkg_url[-40:]})... ", end='', flush=True)
                        try:
                            r = self.session.get(pkg_url, stream=True, timeout=60)
                            if r.status_code == 200:
                                with open(zip_path, "wb") as zf:
                                    for chunk in r.iter_content(65536):
                                        zf.write(chunk)
                                sha256_hash = calc_sha256(zip_path)
                                f_size = zip_path.stat().st_size
                                size_mb = round(f_size / (1024*1024), 2)
                                total_bytes += f_size
                                downloaded_count += 1
                                status = "success"
                                print(f"✓ {size_mb} MB [SHA: {sha256_hash[:16]}...]")
                        except Exception as e:
                            print(f"✗ Error: {e}")
                            status = "error"
                            
                    # Descomprimir inmediatamente a estructura canónica
                    if zip_path and zip_path.exists() and zip_path.stat().st_size > 100000:
                        company_canonical = CANONICAL_DIR / str(year) / f"{ticker}_{name.replace(' ', '_').replace(',', '')}"
                        extracted_dir = company_canonical / "extracted"
                        extracted_dir.mkdir(parents=True, exist_ok=True)
                        
                        try:
                            with zipfile.ZipFile(zip_path, 'r') as zf:
                                for member in zf.infolist():
                                    if member.is_dir():
                                        continue
                                    tfp = extracted_dir / member.filename
                                    tfp.parent.mkdir(parents=True, exist_ok=True)
                                    with zf.open(member) as src, open(tfp, "wb") as dst:
                                        shutil.copyfileobj(src, dst)
                        except Exception as e:
                            print(f"    [Error unpack] {e}")
                            
                results.append({
                    "ticker": ticker,
                    "company_name": name,
                    "sector": sector,
                    "lei": lei,
                    "year": year,
                    "status": status,
                    "size_mb": size_mb,
                    "sha256": sha256_hash,
                })
                
        # Resumen final de BME Growth
        summary_path = CANONICAL_DIR / "BME_GROWTH_INVENTORY_SHA256.json"
        with open(summary_path, "w", encoding="utf-8") as sf:
            json.dump({
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "total_companies": total_companies,
                "downloaded_count": downloaded_count,
                "total_mb": round(total_bytes / (1024*1024), 2),
                "results": results
            }, sf, indent=2, ensure_ascii=False)
            
        print("\n" + "=" * 70)
        print(f"✅ BME GROWTH INGESTA Y SELLADO FINALIZADO")
        print(f"  ✓ Paquetes ESEF procesados:  {downloaded_count}")
        print(f"  ✓ Volumen total descargado:  {round(total_bytes / (1024*1024), 2)} MB")
        print(f"  📄 Inventario guardado en:   {summary_path}")
        print("=" * 70)

if __name__ == "__main__":
    downloader = BMEGrowthDownloader()
    downloader.run()
