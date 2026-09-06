"""
STATER MOTOR ARGOS — MOD_01: European ESEF & OAM Ingestion Client.
Descarga paquetes ESEF (zip / xhtml con iXBRL) de los 5 OAMs principales:
- España: CNMV (Comisión Nacional del Mercado de Valores)
- Francia: AMF / Data.gouv
- Alemania: Unternehmensregister / BaFin
- Italia: CONSOB / 1INFO
- Países Bajos: AFM
"""
import os
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List
from mod_01_ingestion.src.sha256_sealer import seal_file


class ESEFClient:
    """Cliente de ingesta de informes financieros anuales europeos en formato ESEF."""

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = Path(download_dir or "data/raw/ESEF")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.headers = {"User-Agent": "STATER Transatlantic Financial Engine/1.0 (dev@stater.es)"}

    def download_esef_package(self, oam_source: str, download_url: str, entity_lei: str, 
                              fiscal_year: int, ticker: Optional[str] = None, 
                              company_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Descarga un paquete ESEF (zip o xhtml) desde la URL del regulador nacional,
        lo guarda en disco de forma particionada y calcula el hash SHA-256.
        """
        target_dir = self.download_dir / oam_source.upper() / str(fiscal_year) / entity_lei
        target_dir.mkdir(parents=True, exist_ok=True)
        
        filename = download_url.split("/")[-1].split("?")[0]
        if not filename or filename == "":
            filename = f"esef_report_{entity_lei}_{fiscal_year}.zip"
        
        target_path = target_dir / filename

        with httpx.Client(headers=self.headers, timeout=120.0, follow_redirects=True) as client:
            with client.stream("GET", download_url) as r:
                r.raise_for_status()
                with open(target_path, "wb") as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        sha256 = seal_file(target_path)
        file_size = target_path.stat().st_size

        return {
            "doc_id": f"{oam_source.upper()}_{entity_lei}_{fiscal_year}",
            "source": oam_source.upper(),
            "issuer_lei": entity_lei,
            "issuer_isin": None,
            "ticker": ticker,
            "company_name": company_name,
            "doc_type": "ESEF",
            "fiscal_year": fiscal_year,
            "download_url": download_url,
            "file_path": str(target_path.as_posix()),
            "file_size_bytes": file_size,
            "sha256_hash": sha256,
            "status": "RAW",
        }
