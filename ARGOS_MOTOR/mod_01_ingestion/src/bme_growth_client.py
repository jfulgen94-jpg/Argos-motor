"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Cliente Oficial de Ingesta para BME Growth (Canal C: ~72 Empresas en Expansión).

Descarga directa de Informes Financieros Anuales y Semestrales Auditados en PDF
desde el portal oficial de Bolsas y Mercados Españoles (bmegrowth.es) y el
registro de Otra Información Relevante (OIR) de la CNMV.
"""

import sys
import os
import json
import hashlib
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BME_GROWTH_BASE = "https://www.bmegrowth.es"
BME_EMPRESAS_URL = "https://www.bmegrowth.es/esp/Empresas.aspx"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ARGOS_MOTOR/3.0; BME Growth Ingestion; +https://stater.es)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
}


class BMEGrowthClient:
    """Cliente oficial para la descarga de informes de auditoría en BME Growth."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)

    def find_annual_report_pdf_url(self, ticker: str, fiscal_year: int) -> Optional[Dict[str, Any]]:
        """
        Localiza la URL oficial del informe financiero anual auditado para un ticker de BME Growth y año.
        """
        t_clean = ticker.strip().upper()
        # Ruta estándar de BME Growth para ficha de empresa e información financiera
        url = f"{BME_GROWTH_BASE}/esp/Ficha/{t_clean}"
        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            year_str = str(fiscal_year)

            # Buscar enlaces PDF relacionados con Cuentas Anuales o Informe Financiero
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                
                is_pdf = href.endswith(".pdf") or "verdoc" in href.lower() or "descarga" in href.lower()
                is_relevant_text = any(k in text for k in ["auditor", "anual", "cuentas", "financier", year_str])
                
                if is_pdf and (year_str in href or is_relevant_text):
                    full_url = href if href.startswith("http") else f"{BME_GROWTH_BASE}/{href.lstrip('/')}"
                    return {
                        "ticker": t_clean,
                        "fiscal_year": fiscal_year,
                        "doc_title": a.get_text(strip=True) or f"{t_clean}_{fiscal_year}_informe_anual_auditado.pdf",
                        "download_url": full_url,
                        "source": "BME_GROWTH_OFFICIAL_PORTAL"
                    }
        except Exception as e:
            print(f"  [BMEGrowthClient] Error consultando ficha BME Growth para {t_clean}: {e}")

        return None

    def download_growth_pdf(self, download_url: str, target_pdf_path: Path) -> Dict[str, Any]:
        """Descarga en streaming un PDF de BME Growth y calcula su SHA-256 en vuelo."""
        target_pdf_path.parent.mkdir(parents=True, exist_ok=True)

        resp = self.session.get(download_url, timeout=120, stream=True)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} al descargar de BME Growth desde {download_url}")

        sha = hashlib.sha256()
        bytes_written = 0

        with open(target_pdf_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    sha.update(chunk)
                    bytes_written += len(chunk)

        calculated_sha = sha.hexdigest()

        # Validar magic bytes %PDF-
        with open(target_pdf_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            target_pdf_path.unlink(missing_ok=True)
            raise ValueError(f"Fichero descargado de BME Growth no es un PDF válido (magic={magic.hex()})")

        return {
            "sha256": calculated_sha,
            "size_bytes": bytes_written,
            "size_mb": round(bytes_written / (1024 * 1024), 2),
            "mime_type": "application/pdf",
            "downloaded_at": datetime.now(timezone.utc).isoformat()
        }
