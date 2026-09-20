import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from typing import List, Dict, Optional, Any
import urllib.parse
import httpx
from bs4 import BeautifulSoup


def resolve_data_root() -> Path:
    env_root = os.environ.get("ARGOS_DATA_ROOT", "")
    candidates = [
        Path(env_root) / "raw" / "NL_AFM" if env_root else None,
        Path(env_root) if env_root else None,
        Path("/opt/argos_data/raw/NL_AFM"),
        Path("D:/ARGOS_DATA/raw/NL_AFM"),
        Path("ARGOS_DATA_DISK/raw/NL_AFM"),
        Path("ARGOS_MOTOR/data/raw/NL_AFM"),
    ]
    for c in candidates:
        if c and c.exists():
            return c
    p = Path(__file__).resolve().parents[2] / "data" / "raw" / "NL_AFM"
    p.mkdir(parents=True, exist_ok=True)
    return p


class NetherlandsDownloader:
    def __init__(self, data_root: Optional[Path] = None, dry_run: bool = False):
        self.data_root = data_root or resolve_data_root()
        self.dry_run = dry_run
        self.master_universe = self.load_master_universe()
        self.xbrl_index = self.load_xbrl_index()
        self.rate_limit_delay = 2.0

    def load_master_universe(self) -> Dict[str, Any]:
        candidates = [
            Path(__file__).resolve().parents[2] / "config" / "master_universe_nl.json",
            Path("ARGOS_MOTOR/config/master_universe_nl.json"),
            Path("/opt/workspace_base/ARGOS_MOTOR/config/master_universe_nl.json"),
        ]
        for p in candidates:
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f).get("companies", {})
        raise FileNotFoundError("master_universe_nl.json not found")

    def load_xbrl_index(self) -> Dict[str, Any]:
        candidates = [
            Path("scratch/xbrl_index_de.json"),
            Path("scratch/xbrl_index_nl.json"),
            Path(__file__).resolve().parent / "scratch" / "xbrl_index_nl.json",
            Path("/opt/workspace_base/scratch/xbrl_index_de.json"),
        ]
        for p in candidates:
            if p.exists() and p.stat().st_size > 100_000:
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        print(f"[ESEF] Índice XBRL cargado desde {p} ({p.stat().st_size / 1024 / 1024:.1f} MB)")
                        return json.load(f)
                except Exception as e:
                    print(f"[!] Error leyendo {p}: {e}")

        scratch_dir = Path("scratch")
        scratch_dir.mkdir(exist_ok=True)
        index_path = scratch_dir / "xbrl_index_nl.json"

        try:
            print("[ESEF] Descargando índice XBRL central europeo desde filings.xbrl.org...")
            url = "https://filings.xbrl.org/index.json"
            with httpx.Client(timeout=60.0) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
                with open(index_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
        except Exception as e:
            print(f"[!] Error descargando índice XBRL: {e}")
            return {}

    def sha256_file(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def check_local_cache(self, ticker: str, year: int) -> Optional[Dict[str, Any]]:
        year_dir = self.data_root / str(year)
        if not year_dir.exists():
            return None

        # Check subdirectories matching ticker
        for comp_dir in year_dir.iterdir():
            if not comp_dir.is_dir():
                continue
            name_lower = comp_dir.name.lower()
            if name_lower.endswith(f"_{ticker.lower()}") or name_lower.startswith(f"{ticker.lower()}_") or name_lower == ticker.lower():
                files = [f for f in comp_dir.iterdir() if f.is_file()]
                for f in files:
                    ext = f.suffix.lower()
                    if ext in [".zip", ".pdf", ".xhtml", ".htm", ".html"] and not f.name.endswith(".meta.json"):
                        if f.stat().st_size > 3000:
                            actual_hash = self.sha256_file(f)
                            return {"status": "cache_hit", "path": str(f), "sha256": actual_hash}
        return None

    def seal_document(self, file_path: Path, metadata: Dict[str, Any]) -> None:
        sha256 = self.sha256_file(file_path)
        metadata["sha256_hash"] = sha256
        metadata["byte_size"] = file_path.stat().st_size
        metadata["sealed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        meta_path = file_path.with_suffix(file_path.suffix + ".meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"  [+] SELLADO: {file_path.name} ({metadata['byte_size']/1024:.1f} KB, SHA256:{sha256[:10]})")

    def download_esef(self, ticker: str, year: int, lei: str, company: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        entity = self.xbrl_index.get(lei)
        if not entity:
            return None

        tax_id = company.get("kvk_reg") or lei or ticker
        comp_dir = self.data_root / str(year) / f"{tax_id}_{ticker}"

        for filing_key, filing_data in entity.get("filings", {}).items():
            report_date = filing_data.get("date", "") or filing_data.get("report_date", "")
            if not report_date:
                try:
                    report_date = filing_key.split("/")[1]
                except IndexError:
                    continue

            if not report_date.startswith(str(year)):
                continue

            pkg = filing_data.get("report-package")
            if not pkg:
                continue

            url = f"https://filings.xbrl.org/{filing_key}/{pkg}"
            file_name = f"{ticker}_{year}_ESEF.zip"
            comp_dir.mkdir(parents=True, exist_ok=True)
            file_path = comp_dir / file_name

            if self.dry_run:
                return {"status": "dry_run_hit", "source": "ESEF", "url": url}

            print(f"  [1] Descargando paquete ESEF: {url}")
            try:
                time.sleep(self.rate_limit_delay)
                with httpx.Client(timeout=90.0, follow_redirects=True) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    if r.content[:4] != b"PK\x03\x04":
                        print(f"  [-] Magic bytes inválidos para ZIP ESEF ({len(r.content)} bytes)")
                        return None
                    file_path.write_bytes(r.content)

                metadata = {
                    "file_name": file_name,
                    "ticker": ticker,
                    "year": year,
                    "doc_type": "ESEF",
                    "source_channel": "CANAL1_ESEF_XBRL",
                    "source_url": url,
                    "company_name": company.get("name_legal", ""),
                    "lei": lei,
                    "kvk_reg": company.get("kvk_reg", ""),
                    "segment": company.get("segment", "AEX25"),
                    "magic_mime_verified": "ZIP_ESEF"
                }
                self.seal_document(file_path, metadata)
                return {"status": "downloaded", "path": str(file_path)}

            except Exception as e:
                print(f"  [!] Error descargando ESEF {ticker} {year}: {e}")
                if file_path.exists():
                    file_path.unlink()
                return None
        return None

    def download_ir_pdf(self, ticker: str, year: int, company: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Curated direct PDF links
        pdf_map = {
            "ASML": {
                2021: "https://www.asml.com/-/media/asml/files/investors/financial-results/annual-reports/2021/asml-annual-report-2021.pdf",
                2020: "https://www.asml.com/-/media/asml/files/investors/financial-results/annual-reports/2020/asml-annual-report-2020.pdf",
                2019: "https://www.asml.com/-/media/asml/files/investors/financial-results/annual-reports/2019/asml-annual-report-2019.pdf",
            },
            "HEIA": {
                2021: "https://www.theheinekencompany.com/storage/media/Financial-statements-2021.pdf",
                2020: "https://www.theheinekencompany.com/storage/media/Financial-statements-2020.pdf",
                2019: "https://www.theheinekencompany.com/storage/media/Financial-statements-2019.pdf",
            }
        }

        tax_id = company.get("kvk_reg") or company.get("lei") or ticker
        comp_dir = self.data_root / str(year) / f"{tax_id}_{ticker}"

        url = pdf_map.get(ticker, {}).get(year)
        if not url:
            return None

        file_name = f"{ticker}_{year}_ANUAL.pdf"
        comp_dir.mkdir(parents=True, exist_ok=True)
        file_path = comp_dir / file_name

        if self.dry_run:
            return {"status": "dry_run_hit", "source": "IR_CURATED", "url": url}

        print(f"  [2] Descargando informe oficial IR: {url}")
        try:
            time.sleep(self.rate_limit_delay)
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                r = client.get(url)
                if r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 10_000:
                    file_path.write_bytes(r.content)
                    metadata = {
                        "file_name": file_name,
                        "ticker": ticker,
                        "year": year,
                        "doc_type": "ANUAL_PDF",
                        "source_channel": "CANAL2_IR_CURATED",
                        "source_url": url,
                        "company_name": company.get("name_legal", ""),
                        "lei": company.get("lei", ""),
                        "magic_mime_verified": "PDF"
                    }
                    self.seal_document(file_path, metadata)
                    return {"status": "downloaded", "path": str(file_path)}
        except Exception as e:
            print(f"  [!] Error descargando IR {ticker} {year}: {e}")
            if file_path.exists():
                file_path.unlink()
        return None

    def download_web_search(self, ticker: str, year: int, company: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = company.get("name_legal") or company.get("name_common", ticker)
        tax_id = company.get("kvk_reg") or company.get("lei") or ticker
        comp_dir = self.data_root / str(year) / f"{tax_id}_{ticker}"

        queries = [
            f'"{name}" jaarverslag {year} filetype:pdf',
            f'"{name}" annual report {year} pdf'
        ]

        if self.dry_run:
            return {"status": "dry_run_hit", "source": "WEB_SEARCH", "query": queries[0]}

        ddg_bases = [
            "https://html.duckduckgo.com/html/?q={}",
            "https://lite.duckduckgo.com/lite/?q={}"
        ]

        client = httpx.Client(
            timeout=20.0, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )

        found_urls = []
        try:
            for query in queries[:2]:
                encoded = urllib.parse.quote(query)
                for base_url in ddg_bases:
                    try:
                        time.sleep(self.rate_limit_delay)
                        r = client.get(base_url.format(encoded))
                        if r.status_code == 200:
                            soup = BeautifulSoup(r.text, "lxml")
                            for a in soup.select("a.result__url, .result__title a, a[href]"):
                                href = a.get("href", "")
                                if "/l/?uddg=" in href:
                                    try:
                                        params = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                                        href = params.get("uddg", [href])[0]
                                    except Exception:
                                        pass
                                if href.startswith("http") and href.lower().endswith(".pdf") and (str(year) in href or str(year + 1) in href):
                                    if href not in found_urls:
                                        found_urls.append(href)
                            if found_urls:
                                break
                    except Exception as e:
                        continue
                if found_urls:
                    break

            for pdf_url in found_urls[:4]:
                try:
                    print(f"  [4] Intentando PDF web: {pdf_url}")
                    time.sleep(self.rate_limit_delay)
                    r = client.get(pdf_url, timeout=60.0)
                    if r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 10_000:
                        file_name = f"{ticker}_{year}_ANUAL.pdf"
                        comp_dir.mkdir(parents=True, exist_ok=True)
                        file_path = comp_dir / file_name
                        file_path.write_bytes(r.content)

                        metadata = {
                            "file_name": file_name,
                            "ticker": ticker,
                            "year": year,
                            "doc_type": "ANUAL_PDF",
                            "source_channel": "CANAL4_WEB_SEARCH",
                            "source_url": pdf_url,
                            "company_name": name,
                            "lei": company.get("lei", ""),
                            "magic_mime_verified": "PDF"
                        }
                        self.seal_document(file_path, metadata)
                        return {"status": "downloaded", "path": str(file_path)}
                except Exception as e:
                    print(f"  [!] Error descargando PDF {pdf_url}: {e}")
        finally:
            client.close()

        return None

    def run_download(self, years: List[int], tickers: Optional[List[str]] = None, segment: Optional[str] = None):
        companies = list(self.master_universe.items())
        if tickers:
            tickers_upper = [t.strip().upper() for t in tickers]
            companies = [(t, c) for t, c in companies if t.upper() in tickers_upper]
        elif segment:
            companies = [(t, c) for t, c in companies if c.get("segment", "").upper() == segment.upper()]

        print(f"\n{'='*60}")
        print(f"ARGOS MOTOR -- DESCARGADOR PAÍSES BAJOS (NL_AFM v3.0)")
        print(f"{'='*60}")
        print(f"  Data root:     {self.data_root}")
        print(f"  Empresas:      {len(companies)}")
        print(f"  Años:          {years}")
        print(f"  Combinaciones: {len(companies) * len(years)}")
        print(f"  Dry-run:       {self.dry_run}\n")

        total = len(companies) * len(years)
        processed = cached = downloaded = missing = 0

        for year in years:
            for ticker, company_data in companies:
                processed += 1
                name = company_data.get("name_legal", ticker)
                print(f"\n[{ticker}] {name} | AÑO {year}")

                # 1. Caché Local Inmutable
                cache = self.check_local_cache(ticker, year)
                if cache:
                    cached += 1
                    print(f"  [CACHE] {Path(cache['path']).name} (SHA256:{cache['sha256'][:10]})")
                    continue

                # 2. Canal 1: ESEF Fast-Path (>= 2020)
                res = None
                if year >= 2020:
                    lei = company_data.get("lei", "")
                    if lei:
                        res = self.download_esef(ticker, year, lei, company_data)

                # 3. Canal 2: IR Official PDF
                if not res:
                    res = self.download_ir_pdf(ticker, year, company_data)

                # 4. Canal 4: Web Search
                if not res:
                    res = self.download_web_search(ticker, year, company_data)

                if res:
                    status = res.get("status")
                    if status == "downloaded":
                        downloaded += 1
                    elif status == "dry_run_hit":
                        downloaded += 1
                        print(f"  [DRY-RUN HIT] Vía {res.get('source')}: {res.get('url') or res.get('query')}")
                else:
                    missing += 1
                    print(f"  [X] MISSING: {ticker} {year} -- sin fuente")

        print(f"\n{'='*60}\nRESUMEN FINAL\n{'='*60}")
        print(f"  Procesadas:   {processed}")
        print(f"  Caché hits:   {cached}")
        print(f"  Descargadas:  {downloaded}")
        print(f"  Sin fuente:   {missing}")
        print(f"  Éxito total:  {100*(cached+downloaded)/max(processed,1):.1f}%\n")

        self.run_manifest_only(years)

    def run_manifest_only(self, years: List[int]):
        for year in years:
            manifest = []
            year_dir = self.data_root / str(year)
            if not year_dir.exists():
                continue

            for comp_dir in year_dir.iterdir():
                if not comp_dir.is_dir():
                    continue
                for f in comp_dir.iterdir():
                    if f.name.endswith(".meta.json"):
                        try:
                            manifest.append(json.load(open(f, encoding="utf-8")))
                        except Exception:
                            pass

            manifest_path = self.data_root / f"MANIFEST_NL_AFM_{year}.json"
            manifest.sort(key=lambda x: str(x.get("ticker", "")))
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            print(f"[MANIFIESTO] MANIFEST_NL_AFM_{year}.json -> {len(manifest)} registros")

    def run_audit(self):
        print(f"\n{'='*60}\nAUDITORIA DATA LAKE PAÍSES BAJOS (NL_AFM)\n{'='*60}")
        print(f"Ruta: {self.data_root}")
        if not self.data_root.exists():
            print("Directorio no existe.")
            return

        files = list(self.data_root.rglob("*.*"))
        zips = [f for f in files if f.suffix.lower() == ".zip"]
        pdfs = [f for f in files if f.suffix.lower() == ".pdf"]
        htmls = [f for f in files if f.suffix.lower() in [".htm", ".html", ".xhtml"] and not f.name.endswith(".meta.json")]
        metas = [f for f in files if f.name.endswith(".meta.json")]

        print(f"  PDFs:       {len(pdfs)}")
        print(f"  ZIPs ESEF:  {len(zips)}")
        print(f"  HTMLs:      {len(htmls)}")
        print(f"  Meta.jsons: {len(metas)}")

        for yr in sorted([d for d in self.data_root.iterdir() if d.is_dir()]):
            y_files = list(yr.rglob("*.*"))
            y_zips = len([f for f in y_files if f.suffix.lower() == ".zip"])
            y_pdfs = len([f for f in y_files if f.suffix.lower() == ".pdf"])
            y_html = len([f for f in y_files if f.suffix.lower() in [".htm", ".html", ".xhtml"] and not f.name.endswith(".meta.json")])
            print(f"    {yr.name}: total={y_zips+y_pdfs+y_html} (ZIP={y_zips}, PDF={y_pdfs}, HTML={y_html})")


def main():
    parser = argparse.ArgumentParser(description="ARGOS MOTOR -- Descargador Oficial Países Bajos v3.0")
    parser.add_argument("--years", default="2020-2024", help="Años a descargar (ej: 2020-2022 o 2021,2022)")
    parser.add_argument("--tickers", help="Filtrar por tickers (ej: ASML,UNA,HEIA)")
    parser.add_argument("--segment", help="Filtrar por segmento (ej: AEX25)")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin descargar")
    parser.add_argument("--audit", action="store_true", help="Auditoría del Data Lake")
    parser.add_argument("--manifest-only", action="store_true", help="Regenerar manifiestos")
    args = parser.parse_args()

    downloader = NetherlandsDownloader(dry_run=args.dry_run)

    if args.audit:
        downloader.run_audit()
        return

    years = []
    if "-" in args.years:
        s, e = args.years.split("-")
        years = list(range(int(s.strip()), int(e.strip()) + 1))
    else:
        years = [int(y.strip()) for y in args.years.split(",") if y.strip().isdigit()]

    if args.manifest_only:
        downloader.run_manifest_only(years)
        return

    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    downloader.run_download(years=years, tickers=tickers, segment=args.segment)


if __name__ == "__main__":
    main()
