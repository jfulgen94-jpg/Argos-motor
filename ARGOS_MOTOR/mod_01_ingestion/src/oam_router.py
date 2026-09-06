"""
STATER MOTOR ARGOS — MOD_01: Transatlantic OAM Router.
Enrutador unificado que despacha descargas a los clientes especializados de cada país:
- 🇺🇸 EE.UU.: SEC EDGAR (EdgarClient)
- 🇪🇸 España: CNMV (CNMVClient)
- 🇫🇷 Francia: AMF (AMFClient)
- 🇩🇪 Alemania: BaFin / Unternehmensregister (BaFinClient)
- 🇮🇹 Italia: CONSOB (CONSOBClient)
- 🇳🇱 Países Bajos: AFM (AFMClient)
"""
from typing import Dict, Any, Optional
from pathlib import Path

from mod_01_ingestion.src.edgar_client import EdgarClient
from mod_01_ingestion.src.es_cnmv_client import CNMVClient
from mod_01_ingestion.src.fr_amf_client import AMFClient
from mod_01_ingestion.src.de_bafin_client import BaFinClient
from mod_01_ingestion.src.it_consob_client import CONSOBClient
from mod_01_ingestion.src.nl_afm_client import AFMClient


class OAMRouter:
    """Enrutador de ingesta transatlántica regulada."""

    SUPPORTED_MARKETS = ["US", "ES", "FR", "DE", "IT", "NL"]

    def __init__(self, base_download_dir: Optional[Path] = None):
        self.base_dir = Path(base_download_dir or "data/raw")
        self.edgar = EdgarClient(download_dir=self.base_dir / "SEC_EDGAR")
        self.cnmv = CNMVClient(download_dir=self.base_dir / "ES_CNMV")
        self.amf = AMFClient(download_dir=self.base_dir / "FR_AMF")
        self.bafin = BaFinClient(download_dir=self.base_dir / "DE_BAFIN")
        self.consob = CONSOBClient(download_dir=self.base_dir / "IT_CONSOB")
        self.afm = AFMClient(download_dir=self.base_dir / "NL_AFM")

    def get_client(self, market_code: str):
        """Retorna la instancia del cliente especializado para el mercado dado."""
        code = market_code.upper().strip()
        if code in ("US", "SEC", "SEC_EDGAR"):
            return self.edgar
        elif code in ("ES", "SPAIN", "CNMV"):
            return self.cnmv
        elif code in ("FR", "FRANCE", "AMF"):
            return self.amf
        elif code in ("DE", "GERMANY", "BAFIN", "UNTERNEHMENSREGISTER"):
            return self.bafin
        elif code in ("IT", "ITALY", "CONSOB", "1INFO"):
            return self.consob
        elif code in ("NL", "NETHERLANDS", "AFM"):
            return self.afm
        else:
            raise ValueError(f"Mercado no soportado: {market_code}. Mercados soportados: {self.SUPPORTED_MARKETS}")
