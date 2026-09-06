"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Scraper y Conector Oficial del Portal CNMV (Canal B y D).

Gestiona la consulta estructurada y descarga de:
- Depósito Oficial de CCAA e Informes de Auditoría (ID=25) para 2019-2020 y formatos tradicionales.
- Informes de Gobierno Corporativo (IAGC) e Informes Anuales de Remuneraciones (IARC).
- Informes Periódicos Intermedios (IPP Semestral / Trimestral).
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

CNMV_BASE_URL = "https://www.cnmv.es"
CNMV_DOC_URL = "https://www.cnmv.es/portal/verDoc.axd"
CNMV_IPP_URL = "https://www.cnmv.es/Portal/Consultas/IPP/BusquedaIPP.aspx"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


class CNMVPortalScraper:
    """Conector y Scraper Controlado para los servicios web y portal de la CNMV."""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or DEFAULT_HEADERS)

    def search_annual_filings_by_cif(self, cif: str, fiscal_year: int) -> List[Dict[str, Any]]:
        """
        Consulta los registros oficiales de Cuentas Anuales para un CIF y ejercicio.
        Retorna lista de documentos encontrados con URLs de descarga directa.
        """
        cif_clean = re.sub(r'[^A-Z0-9]', '', cif.upper())
        search_url = f"{CNMV_BASE_URL}/portal/Consultas/DerechosVoto/BusquedaEntidad.aspx?nif={cif_clean}"
        
        results: List[Dict[str, Any]] = []
        try:
            resp = self.session.get(search_url, timeout=20)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            # Buscar enlaces de descarga a verDoc.axd o expedientes
            for link in soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(strip=True)
                if "verDoc.axd" in href or "descarga" in href.lower():
                    full_url = href if href.startswith("http") else f"{CNMV_BASE_URL}/{href.lstrip('/')}"
                    results.append({
                        "doc_title": text or f"CNMV_CCAA_{cif_clean}_{fiscal_year}",
                        "download_url": full_url,
                        "cif": cif_clean,
                        "fiscal_year": fiscal_year,
                        "source": "CNMV_PORTAL_REGISTRO_OFICIAL"
                    })
        except Exception as e:
            print(f"  [CNMVPortalScraper] Error buscando CIF {cif_clean} año {fiscal_year}: {e}")

        return results

    def download_document_stream(self, document_url: str, target_path: Path) -> Dict[str, Any]:
        """Descarga en streaming un documento PDF/XHTML oficial de la CNMV y calcula su SHA-256."""
        target_path.parent.mkdir(parents=True, exist_ok=True)

        resp = self.session.get(document_url, timeout=120, stream=True)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} al descargar de la CNMV desde {document_url}")

        sha = hashlib.sha256()
        bytes_written = 0

        with open(target_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    sha.update(chunk)
                    bytes_written += len(chunk)

        calculated_sha = sha.hexdigest()

        # Detección de páginas ASP.NET de error o HTMLs skeleton
        if bytes_written < 25000:
            with open(target_path, "rb") as f:
                first_kb = f.read(1024).decode("utf-8", errors="ignore")
            if "__VIEWSTATE" in first_kb or "CookiesPolicy" in first_kb or "Se ha producido un error" in first_kb:
                target_path.unlink(missing_ok=True)
                raise ValueError("Respuesta de la CNMV contiene página de sesión/error ASP.NET en vez del documento real.")

        return {
            "sha256": calculated_sha,
            "size_bytes": bytes_written,
            "size_mb": round(bytes_written / (1024 * 1024), 2),
            "mime_type": resp.headers.get("Content-Type", "application/pdf"),
            "downloaded_at": datetime.now(timezone.utc).isoformat()
        }
