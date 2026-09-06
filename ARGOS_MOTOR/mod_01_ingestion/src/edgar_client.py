"""
STATER MOTOR ARGOS — MOD_01: SEC EDGAR Client.
Descarga filings oficiales 10-K, 10-Q y 8-K respetando estrictamente
la política de la SEC (máximo 10 requests por segundo y User-Agent institucional).
"""
import os
import time
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from mod_01_ingestion.src.sha256_sealer import seal_file


class EdgarClient:
    """Cliente para la API de SEC EDGAR y submissions JSON."""

    BASE_URL = "https://data.sec.gov"
    ARCHIVES_URL = "https://www.sec.gov/Archives"
    
    def __init__(self, user_agent: Optional[str] = None, download_dir: Optional[Path] = None):
        # Política SEC: User-Agent obligatorio con formato 'Nombre/App Contacto@dominio.com'
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT", "STATER Financial Technologies dev@stater.es")
        self.download_dir = Path(download_dir or "data/raw/SEC_EDGAR")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        self._last_request_time = 0.0
        self._cik_cache: Dict[str, str] = {
            "AAPL": "0000320193", "MSFT": "0000789019", "AMZN": "0001018724", "GOOGL": "0001652044",
            "META": "0001326801", "NVDA": "0001045810", "TSLA": "0001318605", "JPM": "0000019617",
            "BAC": "0000070858", "V": "0001403161", "MA": "0001141391", "WMT": "0000104169",
            "COST": "0000909832", "HD": "0000354950", "DIS": "0001744489", "KO": "0000021344",
            "PEP": "0000077476", "MCD": "0000063908", "IBM": "0000051143", "CSCO": "0000858877",
            "AVGO": "0001730168", "LIN": "0001707925", "LLY": "0000059478", "UNH": "0000731766",
            "JNJ": "0000200406", "MRK": "0000310158", "ABBV": "0001551152", "PG": "0000080424",
            "XOM": "0000034088", "CVX": "0000093410", "ACN": "0001467373"
        }

    def _rate_limit(self) -> None:
        """Garantiza que no se superen 10 requests/segundo (mínimo 0.12s entre llamadas)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.12:
            time.sleep(0.12 - elapsed)
        self._last_request_time = time.time()

    def get_company_cik(self, ticker: str) -> Optional[str]:
        """Obtiene el CIK (10 dígitos con ceros a la izquierda) a partir del ticker con caché."""
        ticker_upper = ticker.upper().strip()
        if ticker_upper in self._cik_cache:
            return self._cik_cache[ticker_upper]

        self._rate_limit()
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            with httpx.Client(headers=self.headers, timeout=15.0) as client:
                r = client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    for item in data.values():
                        t = item.get("ticker", "").upper().strip()
                        c = str(item.get("cik_str")).zfill(10)
                        if t:
                            self._cik_cache[t] = c
                    return self._cik_cache.get(ticker_upper)
        except Exception:
            pass
        return None

    def get_company_submissions(self, cik: str) -> Dict[str, Any]:
        """Obtiene el histórico de filings para un CIK dado."""
        self._rate_limit()
        cik_clean = cik.zfill(10)
        url = f"{self.BASE_URL}/submissions/CIK{cik_clean}.json"
        with httpx.Client(headers=self.headers, timeout=20.0) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()

    def get_cik(self, ticker: str) -> Optional[str]:
        """Alias conveniente para get_company_cik."""
        return self.get_company_cik(ticker)

    def get_submissions(self, cik: str) -> Dict[str, Any]:
        """Alias conveniente para get_company_submissions."""
        return self.get_company_submissions(cik)

    def get_historical_10k_filings(self, cik: str, start_year: int = 2019, end_year: int = 2025) -> List[Dict[str, Any]]:
        """
        Localiza todos los formularios 10-K dentro del rango de años [start_year, end_year].
        Soporta filings recientes y archivos de submissions históricos de SEC EDGAR.
        """
        submissions = self.get_company_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        report_dates = recent.get("reportDate", []) or dates

        results = []
        n_items = min(len(forms), len(dates), len(accessions), len(primary_docs))
        for i in range(n_items):
            form = forms[i]
            f_date = dates[i]
            acc = accessions[i]
            doc = primary_docs[i]
            r_date = report_dates[i] if i < len(report_dates) else f_date
            if form in ("10-K", "10-K/A"):
                try:
                    f_year = int((r_date or f_date)[:4])
                except (ValueError, TypeError):
                    continue

                if start_year <= f_year <= end_year:
                    results.append({
                        "form_type": form,
                        "fiscal_year": f_year,
                        "filing_date": f_date,
                        "report_date": r_date,
                        "accession_number": acc,
                        "primary_doc": doc,
                        "company_name": submissions.get("name")
                    })

        # Si se solicita antes de 2015 y hay archivos adicionales
        if start_year < 2015:
            extra_files = submissions.get("filings", {}).get("files", [])
            for ef in extra_files:
                file_name = ef.get("name")
                if file_name:
                    self._rate_limit()
                    try:
                        url = f"{self.BASE_URL}/submissions/{file_name}"
                        with httpx.Client(headers=self.headers, timeout=20.0) as client:
                            r = client.get(url)
                            if r.status_code == 200:
                                ef_data = r.json()
                                ef_forms = ef_data.get("form", [])
                                ef_dates = ef_data.get("filingDate", [])
                                ef_accs = ef_data.get("accessionNumber", [])
                                ef_docs = ef_data.get("primaryDocument", [])
                                ef_rdates = ef_data.get("reportDate", []) or ef_dates

                                ef_n = min(len(ef_forms), len(ef_dates), len(ef_accs), len(ef_docs))
                                for j in range(ef_n):
                                    form = ef_forms[j]
                                    f_date = ef_dates[j]
                                    acc = ef_accs[j]
                                    doc = ef_docs[j]
                                    r_date = ef_rdates[j] if j < len(ef_rdates) else f_date
                                    if form in ("10-K", "10-K/A"):
                                        try:
                                            f_year = int((r_date or f_date)[:4])
                                        except (ValueError, TypeError):
                                            continue
                                        if start_year <= f_year <= end_year:
                                            results.append({
                                                "form_type": form,
                                                "fiscal_year": f_year,
                                                "filing_date": f_date,
                                                "report_date": r_date,
                                                "accession_number": acc,
                                                "primary_doc": doc,
                                                "company_name": submissions.get("name")
                                            })
                    except Exception:
                        pass

        # Ordenar cronológicamente por año fiscal
        results.sort(key=lambda x: x["fiscal_year"])
        return results

    def download_filing(self, cik: str, accession_number: str, primary_doc_name: str, 
                        fiscal_year: int, doc_type: str = "10-K", ticker: Optional[str] = None,
                        company_name: Optional[str] = None, skip_if_exists: bool = True) -> Dict[str, Any]:
        """
        Descarga el documento primario de un filing, lo guarda en disco y lo sella con SHA-256.
        Si ya existe y skip_if_exists es True, reutiliza el archivo y computa su hash sin re-descargar.
        """
        cik_no_zero = str(int(cik))
        acc_no_hyphen = accession_number.replace("-", "")
        url = f"{self.ARCHIVES_URL}/edgar/data/{cik_no_zero}/{acc_no_hyphen}/{primary_doc_name}"
        
        target_dir = self.download_dir / str(fiscal_year) / (ticker or cik)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{doc_type}_{accession_number}_{primary_doc_name}"

        # Comprobar si ya existe en disco
        if skip_if_exists and target_path.exists() and target_path.stat().st_size > 0:
            sha256 = seal_file(target_path)
            file_size = target_path.stat().st_size
            return {
                "doc_id": f"SEC_{cik}_{accession_number}",
                "source": "SEC_EDGAR",
                "issuer_lei": None,
                "issuer_isin": None,
                "ticker": ticker,
                "company_name": company_name,
                "doc_type": doc_type,
                "fiscal_year": fiscal_year,
                "download_url": url,
                "file_path": str(target_path.as_posix()),
                "file_size_bytes": file_size,
                "sha256_hash": sha256,
                "status": "RAW_CACHED",
            }

        self._rate_limit()
        with httpx.Client(headers=self.headers, timeout=60.0) as client:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        sha256 = seal_file(target_path)
        file_size = target_path.stat().st_size

        return {
            "doc_id": f"SEC_{cik}_{accession_number}",
            "source": "SEC_EDGAR",
            "issuer_lei": None,
            "issuer_isin": None,
            "ticker": ticker,
            "company_name": company_name,
            "doc_type": doc_type,
            "fiscal_year": fiscal_year,
            "download_url": url,
            "file_path": str(target_path.as_posix()),
            "file_size_bytes": file_size,
            "sha256_hash": sha256,
            "status": "RAW",
        }

