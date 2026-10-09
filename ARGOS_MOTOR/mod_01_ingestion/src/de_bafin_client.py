"""
STATER MOTOR ARGOS — MOD_01: Ingestor Nacional Alemania (BaFin / Unternehmensregister).
Descarga de Jahresfinanzberichte (ESEF iXBRL / ZIP), Konzernabschlüsse, Lageberichte
y Bestätigungsvermerke des Abschlussprüfers del Unternehmensregister / Bundesanzeiger.
"""
import os
import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from mod_01_ingestion.src.sha256_sealer import seal_file


class BaFinClient:
    """Cliente de ingesta especializado para el mercado alemán (BaFin / Deutsche Börse)."""

    COUNTRY_CODE = "DE"
    REGULATOR_NAME = "BAFIN_UNTERNEHMENSREGISTER"
    BASE_URL = "https://www.unternehmensregister.de"

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = Path(download_dir or "data/raw/DE_BAFIN")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {
            "User-Agent": "STATER Transatlantic Financial Engine/1.0 (Germany DE-BaFin; dev@stater.es)",
            "Accept": "application/zip, application/xhtml+xml, application/pdf, */*"
        }

    def build_doc_id(self, entity_lei: str, fiscal_year: int, doc_type: str = "ESEF") -> str:
        """Genera el identificador canónico de documento para Alemania."""
        return f"DE_BAFIN_{entity_lei}_{fiscal_year}_{doc_type}"

    def download_filing(
        self,
        download_url: str,
        entity_lei: str,
        fiscal_year: int,
        hrb_number: Optional[str] = None,
        ticker: Optional[str] = None,
        company_name: Optional[str] = None,
        doc_type: str = "ESEF"
    ) -> Dict[str, Any]:
        """
        DEPRECATED / LEGACY_BRIDGE (Fase 4): delega en el núcleo unificado
        (``mod_01_ingestion.src.unified``). Se conserva la firma y el dict de retorno.
        Ya no descarga con lógica propia (antes: sin .part ni validación, DEFECT-05).
        """
        from mod_01_ingestion.src.unified.legacy_bridge import bafin_download_filing_via_unified
        return bafin_download_filing_via_unified(
            self.download_dir, download_url, entity_lei, fiscal_year, ticker=ticker,
            company_name=company_name, doc_type=doc_type)
