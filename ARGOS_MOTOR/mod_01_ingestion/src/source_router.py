"""
STATER MOTOR ARGOS — MOD_01_INGESTION
Enrutador de Fuentes Regulatorias (Source Router).

Determina de forma determinista y auditable el canal oficial de descarga
según la tupla (Segmento de Mercado, Ejercicio Fiscal, Tipo de Documento),
respetando el régimen regulatorio real español y europeo:

- Canal A (ESEF_XBRL_ORG): filings.xbrl.org API (ESMA OAM oficial) para IBEX35/Continuo >= 2021.
- Canal B (CNMV_PORTAL_CCAA): Portal CNMV (Auditorías 2019-2020 pre-ESEF / Moratoria COVID-19).
- Canal C (BME_GROWTH_OFFICIAL): Portal Oficial BME Growth (PDFs auditados para ~72 empresas en expansión).
- Canal D (CNMV_IPP_GOV): CNMV IPP / Gobierno Corporativo (IAGC, IARC, Informes Intermedios H1/Q1/Q3).
"""

import sys
import os
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class RegulatoryChannel(str, Enum):
    CANAL_A_ESEF_XBRL = "CANAL_A_ESEF_XBRL"
    CANAL_B_CNMV_PORTAL = "CANAL_B_CNMV_PORTAL"
    CANAL_C_BME_GROWTH = "CANAL_C_BME_GROWTH"
    CANAL_D_CNMV_IPP = "CANAL_D_CNMV_IPP"
    CANAL_FALLBACK_MANUAL = "CANAL_FALLBACK_MANUAL"


@dataclass
class ChannelRoutingDecision:
    primary_channel: RegulatoryChannel
    fallback_channel: Optional[RegulatoryChannel]
    rationale: str
    expected_mime_type: str
    is_esef_mandatory: bool


class SourceRouter:
    """
    Enrutador Soberano de Canales de Ingesta Regulatoria.
    """

    @staticmethod
    def route(segment: str, fiscal_year: int, doc_type: str) -> ChannelRoutingDecision:
        """
        Calcula la ruta oficial para un documento dado su segmento, año y tipo.
        """
        seg = segment.upper() if segment else "MERCADO_CONTINUO"
        yr = int(fiscal_year)
        dtype = doc_type.upper() if doc_type else "CCAA_AUDITED"

        # 1. Informes de Gobierno Corporativo y Remuneraciones (IAGC / IARC) o IPP
        if dtype in ("IAGC", "IARC", "IPP_SEMESTRAL", "IPP_TRIMESTRAL"):
            return ChannelRoutingDecision(
                primary_channel=RegulatoryChannel.CANAL_D_CNMV_IPP,
                fallback_channel=RegulatoryChannel.CANAL_B_CNMV_PORTAL,
                rationale=f"Documentos {dtype} se publican centralizadamente en el registro IPP/IAGC de la CNMV.",
                expected_mime_type="application/pdf",
                is_esef_mandatory=False
            )

        # 2. BME Growth (Empresas en Expansión)
        if seg == "BME_GROWTH":
            return ChannelRoutingDecision(
                primary_channel=RegulatoryChannel.CANAL_C_BME_GROWTH,
                fallback_channel=RegulatoryChannel.CANAL_B_CNMV_PORTAL,
                rationale="BME Growth es un MTF (SME Growth Market); las entidades depositan informes anuales auditados en PDF en BME Growth / OIR CNMV, no en repositorios ESEF.",
                expected_mime_type="application/pdf",
                is_esef_mandatory=False
            )

        # 3. Mercado Continuo e IBEX 35 (>= 2021)
        if yr >= 2021:
            return ChannelRoutingDecision(
                primary_channel=RegulatoryChannel.CANAL_A_ESEF_XBRL,
                fallback_channel=RegulatoryChannel.CANAL_B_CNMV_PORTAL,
                rationale=f"ESEF es obligatorio en España a partir del ejercicio 2021. Descarga del paquete iXBRL oficial en filings.xbrl.org.",
                expected_mime_type="application/zip",
                is_esef_mandatory=True
            )

        # 4. Mercado Continuo e IBEX 35 (<= 2020: Moratoria COVID-19 / Pre-ESEF)
        return ChannelRoutingDecision(
            primary_channel=RegulatoryChannel.CANAL_B_CNMV_PORTAL,
            fallback_channel=RegulatoryChannel.CANAL_A_ESEF_XBRL,
            rationale=f"Ejercicio {yr} sujeto a moratoria COVID-19 o formato pre-ESEF. La fuente primaria es el depósito oficial de CCAA en PDF ante la CNMV.",
            expected_mime_type="application/pdf",
            is_esef_mandatory=False
        )
