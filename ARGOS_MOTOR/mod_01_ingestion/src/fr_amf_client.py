"""
STATER MOTOR ARGOS — MOD_01: Ingestor Nacional Francia (AMF / Data.gouv).
Descarga de Rapports Financiers Annuels (URD / ESEF iXBRL), Déclarations de Performance
Extra-Financière (DPEF / CSRD) y rapports d'audit de l'Autorité des Marchés Financiers (AMF).
"""
import os
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from mod_01_ingestion.src.sha256_sealer import seal_file


class AMFClient:
    """Cliente de ingesta especializado para el mercado francés (AMF / Euronext Paris)."""

    COUNTRY_CODE = "FR"
    REGULATOR_NAME = "AMF"
    BASE_URL = "https://bdif.amf-france.org"

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = Path(download_dir or "data/raw/FR_AMF")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": "STATER Transatlantic Financial Engine/1.0 (France FR-AMF; dev@stater.es)",
            "Accept": "application/zip, application/xhtml+xml, application/pdf, */*"
        }

    def build_doc_id(self, entity_lei: str, fiscal_year: int, doc_type: str = "ESEF") -> str:
        """Genera el identificador canónico de documento para Francia."""
        return f"FR_AMF_{entity_lei}_{fiscal_year}_{doc_type}"

    def download_filing(
        self,
        download_url: str,
        entity_lei: str,
        fiscal_year: int,
        siren_siret: Optional[str] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
        doc_type: str = "ESEF"
    ) -> Dict[str, Any]:
        """
        Descarga el informe oficial de la AMF francesa con sellado criptográfico SHA-256.
        """
        target_dir = self.download_dir / str(fiscal_year) / entity_lei
        target_dir.mkdir(parents=True, exist_ok=True)

        url_filename = download_url.split("/")[-1].split("?")[0]
        if not url_filename:
            extension = ".zip" if doc_type == "ESEF" else ".pdf"
            url_filename = f"amf_{entity_lei}_{fiscal_year}_{doc_type.lower()}{extension}"

        target_path = target_dir / url_filename

        with httpx.Client(headers=self.headers, timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", download_url) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        sha256_digest = seal_file(target_path)
        file_size = target_path.stat().st_size

        return {
            "doc_id": self.build_doc_id(entity_lei, fiscal_year, doc_type),
            "source": "AMF",
            "country_code": self.COUNTRY_CODE,
            "issuer_lei": entity_lei,
            "issuer_isin": None,
            "ticker": ticker,
            "company_name": company_name,
            "doc_type": doc_type,
            "fiscal_year": fiscal_year,
            "download_url": download_url,
            "file_path": str(target_path.as_posix()),
            "file_size_bytes": file_size,
            "sha256_hash": sha256_digest,
            "status": "RAW",
        }
