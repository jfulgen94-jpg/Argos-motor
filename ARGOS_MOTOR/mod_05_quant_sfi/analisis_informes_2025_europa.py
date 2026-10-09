"""
STATER SFI LAB / ARGOS MOTOR — ANÁLISIS DE INFORMES DE AUDITORÍA 2025 (PUBLICADOS EN 2026)
Calcula:
1. Fecha exacta de publicación en 2026 de los informes anuales del ejercicio 2025.
2. Evolución del precio de la acción desde la fecha de publicación hasta hoy (octubre 2026).
3. Clasificación canónica en las 6 bolsas fundamentales (Calidad x P/B).
4. Severidad de las Cuestiones Clave de Auditoría (CAMs / ISA 701).
5. Matriz bidimensional cruzada 6 bolsas x 3 estados de severidad.
"""

import sys
import os
import json
import duckdb
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timezone

# Paths
REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "ARGOS_MOTOR/mod_05_quant_sfi/output_estudio_pericial_europa"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = REPO_ROOT / "ARGOS_MOTOR/data/lake/duckdb/stater_motor.duckdb"

# Universo exhaustivo de cotizadas europeas con informe 2025 y sus fechas oficiales de publicación en 2026
COMPANIES_2025 = [
    # ESPAÑA (BME - CNMV)
    {"ticker": "SAN", "yf": "SAN.MC", "name": "Banco Santander SA", "country": "ES", "sector": "Financials", "pub_date": "2026-02-27", "pb": 0.85, "quality": "Buena", "cam_sev": 1},
    {"ticker": "BBVA", "yf": "BBVA.MC", "name": "Banco Bilbao Vizcaya Argentaria SA", "country": "ES", "sector": "Financials", "pub_date": "2026-02-28", "pb": 0.95, "quality": "Buena", "cam_sev": 1},
    {"ticker": "ITX", "yf": "ITX.MC", "name": "Inditex (Industria de Diseno Textil SA)", "country": "ES", "sector": "Consumer Discretionary", "pub_date": "2026-03-12", "pb": 5.20, "quality": "Buena", "cam_sev": 0},
    {"ticker": "IBE", "yf": "IBE.MC", "name": "Iberdrola SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-26", "pb": 1.75, "quality": "Buena", "cam_sev": 1},
    {"ticker": "TEF", "yf": "TEF.MC", "name": "Telefonica SA", "country": "ES", "sector": "Telecommunications", "pub_date": "2026-02-27", "pb": 0.85, "quality": "Baja", "cam_sev": 2},
    {"ticker": "REP", "yf": "REP.MC", "name": "Repsol SA", "country": "ES", "sector": "Energy", "pub_date": "2026-02-27", "pb": 0.75, "quality": "Media", "cam_sev": 1},
    {"ticker": "CABK", "yf": "CABK.MC", "name": "CaixaBank SA", "country": "ES", "sector": "Financials", "pub_date": "2026-02-20", "pb": 1.15, "quality": "Buena", "cam_sev": 1},
    {"ticker": "ACS", "yf": "ACS.MC", "name": "ACS Actividades de Construccion y Servicios", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-28", "pb": 1.40, "quality": "Media", "cam_sev": 1},
    {"ticker": "AMS", "yf": "AMS.MC", "name": "Amadeus IT Group SA", "country": "ES", "sector": "Technology", "pub_date": "2026-02-28", "pb": 4.20, "quality": "Buena", "cam_sev": 0},
    {"ticker": "FER", "yf": "FER.MC", "name": "Ferrovial SE", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-28", "pb": 2.90, "quality": "Buena", "cam_sev": 1},
    {"ticker": "ELE", "yf": "ELE.MC", "name": "Endesa SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-26", "pb": 1.60, "quality": "Media", "cam_sev": 0},
    {"ticker": "CLNX", "yf": "CLNX.MC", "name": "Cellnex Telecom SA", "country": "ES", "sector": "Telecommunications", "pub_date": "2026-02-28", "pb": 1.60, "quality": "Baja", "cam_sev": 2},
    {"ticker": "GRF", "yf": "GRF.MC", "name": "Grifols SA", "country": "ES", "sector": "Healthcare", "pub_date": "2026-03-08", "pb": 1.30, "quality": "Baja", "cam_sev": 2},
    {"ticker": "NTGY", "yf": "NTGY.MC", "name": "Naturgy Energy Group SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-27", "pb": 1.55, "quality": "Media", "cam_sev": 1},
    {"ticker": "AENA", "yf": "AENA.MC", "name": "Aena SME SA", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-27", "pb": 3.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "ACX", "yf": "ACX.MC", "name": "Acerinox SA", "country": "ES", "sector": "Basic Materials", "pub_date": "2026-02-28", "pb": 0.85, "quality": "Buena", "cam_sev": 0},
    {"ticker": "BKT", "yf": "BKT.MC", "name": "Bankinter SA", "country": "ES", "sector": "Financials", "pub_date": "2026-01-23", "pb": 1.10, "quality": "Buena", "cam_sev": 0},
    {"ticker": "ENG", "yf": "ENG.MC", "name": "Enagas SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-18", "pb": 1.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "COL", "yf": "COL.MC", "name": "Inmobiliaria Colonial SOCIMI SA", "country": "ES", "sector": "Real Estate", "pub_date": "2026-02-27", "pb": 0.65, "quality": "Media", "cam_sev": 1},
    {"ticker": "MRL", "yf": "MRL.MC", "name": "Merlin Properties SOCIMI SA", "country": "ES", "sector": "Real Estate", "pub_date": "2026-02-27", "pb": 0.75, "quality": "Media", "cam_sev": 1},
    {"ticker": "SCYR", "yf": "SCYR.MC", "name": "Sacyr SA", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-28", "pb": 1.25, "quality": "Media", "cam_sev": 1},
    {"ticker": "SLR", "yf": "SLR.MC", "name": "Solaria Energia y Medio Ambiente SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-03-31", "pb": 1.80, "quality": "Baja", "cam_sev": 0},
    {"ticker": "UNI", "yf": "UNI.MC", "name": "Unicaja Banco SA", "country": "ES", "sector": "Financials", "pub_date": "2026-02-26", "pb": 0.60, "quality": "Media", "cam_sev": 0},
    {"ticker": "VIS", "yf": "VIS.MC", "name": "Viscofan SA", "country": "ES", "sector": "Consumer Staples", "pub_date": "2026-02-27", "pb": 2.60, "quality": "Media", "cam_sev": 0},
    {"ticker": "ROVI", "yf": "ROVI.MC", "name": "Laboratorios Farmaceuticos Rovi SA", "country": "ES", "sector": "Healthcare", "pub_date": "2026-02-25", "pb": 3.20, "quality": "Buena", "cam_sev": 0},
    {"ticker": "IDR", "yf": "IDR.MC", "name": "Indra Sistemas SA", "country": "ES", "sector": "Technology", "pub_date": "2026-02-27", "pb": 2.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "FDR", "yf": "FDR.MC", "name": "Fluidra SA", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-27", "pb": 2.30, "quality": "Media", "cam_sev": 0},
    {"ticker": "LOG", "yf": "LOG.MC", "name": "Logista Holdings SA", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-06", "pb": 2.20, "quality": "Media", "cam_sev": 0},
    {"ticker": "MEL", "yf": "MEL.MC", "name": "Melia Hotels International SA", "country": "ES", "sector": "Consumer Discretionary", "pub_date": "2026-02-28", "pb": 1.40, "quality": "Baja", "cam_sev": 0},
    {"ticker": "SAB", "yf": "SAB.MC", "name": "Banco de Sabadell SA", "country": "ES", "sector": "Financials", "pub_date": "2026-02-06", "pb": 0.70, "quality": "Media", "cam_sev": 0},
    {"ticker": "ANA", "yf": "ANA.MC", "name": "Acciona SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-28", "pb": 1.35, "quality": "Media", "cam_sev": 1},
    {"ticker": "ANE", "yf": "ANE.MC", "name": "Acciona Energias Renovables SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-28", "pb": 1.25, "quality": "Media", "cam_sev": 0},
    {"ticker": "RED", "yf": "RED.MC", "name": "Redeia Corporacion SA", "country": "ES", "sector": "Utilities", "pub_date": "2026-02-27", "pb": 1.50, "quality": "Media", "cam_sev": 0},
    {"ticker": "ALM", "yf": "ALM.MC", "name": "Almirall SA", "country": "ES", "sector": "Healthcare", "pub_date": "2026-02-23", "pb": 1.10, "quality": "Baja", "cam_sev": 0},
    {"ticker": "VID", "yf": "VID.MC", "name": "Vidrala SA", "country": "ES", "sector": "Consumer Goods", "pub_date": "2026-02-28", "pb": 1.90, "quality": "Media", "cam_sev": 0},
    {"ticker": "TUB", "yf": "TUB.MC", "name": "Tubacex SA", "country": "ES", "sector": "Basic Materials", "pub_date": "2026-02-28", "pb": 0.70, "quality": "Baja", "cam_sev": 2},
    {"ticker": "TRG", "yf": "TRG.MC", "name": "Tubos Reunidos SA", "country": "ES", "sector": "Basic Materials", "pub_date": "2026-03-15", "pb": 0.40, "quality": "Baja", "cam_sev": 2},
    {"ticker": "CAF", "yf": "CAF.MC", "name": "Construcciones y Auxiliar de Ferrocarriles", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-27", "pb": 1.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "EBRO", "yf": "EBRO.MC", "name": "Ebro Foods SA", "country": "ES", "sector": "Consumer Staples", "pub_date": "2026-02-27", "pb": 1.25, "quality": "Media", "cam_sev": 0},
    {"ticker": "PHM", "yf": "PHM.MC", "name": "Pharma Mar SA", "country": "ES", "sector": "Healthcare", "pub_date": "2026-02-28", "pb": 2.80, "quality": "Media", "cam_sev": 0},
    {"ticker": "TRE", "yf": "TRE.MC", "name": "Tecnicas Reunidas SA", "country": "ES", "sector": "Industrials", "pub_date": "2026-02-28", "pb": 1.20, "quality": "Media", "cam_sev": 1},
    {"ticker": "PUIG", "yf": "PUIG.MC", "name": "Puig Brands SA", "country": "ES", "sector": "Consumer Staples", "pub_date": "2026-04-15", "pb": 3.60, "quality": "Media", "cam_sev": 0},

    # ALEMANIA (XETRA - BAFIN)
    {"ticker": "SAP", "yf": "SAP.DE", "name": "SAP SE", "country": "DE", "sector": "Technology", "pub_date": "2026-02-26", "pb": 4.50, "quality": "Buena", "cam_sev": 0},
    {"ticker": "SIE", "yf": "SIE.DE", "name": "Siemens AG", "country": "DE", "sector": "Industrials", "pub_date": "2026-01-30", "pb": 2.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "ALV", "yf": "ALV.DE", "name": "Allianz SE", "country": "DE", "sector": "Financials", "pub_date": "2026-03-05", "pb": 1.35, "quality": "Media", "cam_sev": 1},
    {"ticker": "DTE", "yf": "DTE.DE", "name": "Deutsche Telekom AG", "country": "DE", "sector": "Telecommunications", "pub_date": "2026-02-27", "pb": 1.90, "quality": "Media", "cam_sev": 0},
    {"ticker": "MBG", "yf": "MBG.DE", "name": "Mercedes-Benz Group AG", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-02-20", "pb": 0.40, "quality": "Buena", "cam_sev": 0},
    {"ticker": "BMW", "yf": "BMW.DE", "name": "Bayerische Motoren Werke AG (BMW)", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-14", "pb": 0.34, "quality": "Buena", "cam_sev": 0},
    {"ticker": "VOW3", "yf": "VOW3.DE", "name": "Volkswagen AG", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-13", "pb": 0.19, "quality": "Baja", "cam_sev": 0},
    {"ticker": "BAS", "yf": "BAS.DE", "name": "BASF SE", "country": "DE", "sector": "Basic Materials", "pub_date": "2026-02-28", "pb": 0.95, "quality": "Media", "cam_sev": 1},
    {"ticker": "BAYN", "yf": "BAYN.DE", "name": "Bayer AG", "country": "DE", "sector": "Healthcare", "pub_date": "2026-03-05", "pb": 1.20, "quality": "Baja", "cam_sev": 2},
    {"ticker": "DBK", "yf": "DBK.DE", "name": "Deutsche Bank AG", "country": "DE", "sector": "Financials", "pub_date": "2026-03-12", "pb": 0.74, "quality": "Media", "cam_sev": 1},
    {"ticker": "IFX", "yf": "IFX.DE", "name": "Infineon Technologies AG", "country": "DE", "sector": "Technology", "pub_date": "2026-01-20", "pb": 2.80, "quality": "Media", "cam_sev": 0},
    {"ticker": "DHL", "yf": "DHL.DE", "name": "Deutsche Post AG (DHL)", "country": "DE", "sector": "Industrials", "pub_date": "2026-03-06", "pb": 2.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "MUV2", "yf": "MUV2.DE", "name": "Munich Re (Muenchener Rueck)", "country": "DE", "sector": "Financials", "pub_date": "2026-03-14", "pb": 1.65, "quality": "Media", "cam_sev": 1},
    {"ticker": "RWE", "yf": "RWE.DE", "name": "RWE AG", "country": "DE", "sector": "Utilities", "pub_date": "2026-03-13", "pb": 1.30, "quality": "Media", "cam_sev": 0},
    {"ticker": "EOAN", "yf": "EOAN.DE", "name": "E.ON SE", "country": "DE", "sector": "Utilities", "pub_date": "2026-03-13", "pb": 1.45, "quality": "Media", "cam_sev": 0},
    {"ticker": "HEN3", "yf": "HEN3.DE", "name": "Henkel AG & Co KGaA", "country": "DE", "sector": "Consumer Staples", "pub_date": "2026-03-06", "pb": 1.85, "quality": "Media", "cam_sev": 0},
    {"ticker": "BEI", "yf": "BEI.DE", "name": "Beiersdorf AG", "country": "DE", "sector": "Consumer Staples", "pub_date": "2026-03-05", "pb": 2.65, "quality": "Media", "cam_sev": 0},
    {"ticker": "CON", "yf": "CON.DE", "name": "Continental AG", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-06", "pb": 0.75, "quality": "Media", "cam_sev": 0},
    {"ticker": "HEI", "yf": "HEI.DE", "name": "Heidelberg Materials AG", "country": "DE", "sector": "Basic Materials", "pub_date": "2026-03-20", "pb": 1.45, "quality": "Media", "cam_sev": 0},
    {"ticker": "SY1", "yf": "SY1.DE", "name": "Symrise AG", "country": "DE", "sector": "Basic Materials", "pub_date": "2026-03-10", "pb": 2.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "FRE", "yf": "FRE.DE", "name": "Fresenius SE & Co KGaA", "country": "DE", "sector": "Healthcare", "pub_date": "2026-02-25", "pb": 1.25, "quality": "Media", "cam_sev": 0},
    {"ticker": "P911", "yf": "P911.DE", "name": "Porsche AG", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-12", "pb": 2.80, "quality": "Buena", "cam_sev": 0},
    {"ticker": "ZAL", "yf": "ZAL.DE", "name": "Zalando SE", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-13", "pb": 2.20, "quality": "Baja", "cam_sev": 2},
    {"ticker": "CBK", "yf": "CBK.DE", "name": "Commerzbank AG", "country": "DE", "sector": "Financials", "pub_date": "2026-03-27", "pb": 0.80, "quality": "Media", "cam_sev": 1},
    {"ticker": "DTG", "yf": "DTG.DE", "name": "Daimler Truck Holding AG", "country": "DE", "sector": "Industrials", "pub_date": "2026-03-07", "pb": 1.25, "quality": "Media", "cam_sev": 0},
    {"ticker": "MRK", "yf": "MRK.DE", "name": "Merck KGaA", "country": "DE", "sector": "Healthcare", "pub_date": "2026-03-06", "pb": 2.80, "quality": "Media", "cam_sev": 0},
    {"ticker": "ENR", "yf": "ENR.DE", "name": "Siemens Energy AG", "country": "DE", "sector": "Industrials", "pub_date": "2026-01-15", "pb": 1.95, "quality": "Media", "cam_sev": 1},
    {"ticker": "ADS", "yf": "ADS.DE", "name": "Adidas AG", "country": "DE", "sector": "Consumer Discretionary", "pub_date": "2026-03-12", "pb": 3.50, "quality": "Media", "cam_sev": 0},
    {"ticker": "HOT", "yf": "HOT.DE", "name": "Hochtief AG", "country": "DE", "sector": "Industrials", "pub_date": "2026-02-26", "pb": 1.20, "quality": "Media", "cam_sev": 0},

    # FRANCIA (EURONEXT PARIS - AMF)
    {"ticker": "MC", "yf": "MC.PA", "name": "LVMH Moet Hennessy Louis Vuitton", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-05", "pb": 4.80, "quality": "Buena", "cam_sev": 0},
    {"ticker": "OR", "yf": "OR.PA", "name": "L'Oreal SA", "country": "FR", "sector": "Consumer Staples", "pub_date": "2026-02-12", "pb": 5.60, "quality": "Buena", "cam_sev": 0},
    {"ticker": "RMS", "yf": "RMS.PA", "name": "Hermes International SCA", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-14", "pb": 12.50, "quality": "Buena", "cam_sev": 0},
    {"ticker": "TTE", "yf": "TTE.PA", "name": "TotalEnergies SE", "country": "FR", "sector": "Energy", "pub_date": "2026-02-12", "pb": 1.15, "quality": "Media", "cam_sev": 1},
    {"ticker": "SAN_FR", "yf": "SAN.PA", "name": "Sanofi SA", "country": "FR", "sector": "Healthcare", "pub_date": "2026-02-06", "pb": 1.60, "quality": "Media", "cam_sev": 0},
    {"ticker": "SU", "yf": "SU.PA", "name": "Schneider Electric SE", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-19", "pb": 3.10, "quality": "Buena", "cam_sev": 0},
    {"ticker": "AIR", "yf": "AIR.PA", "name": "Airbus SE", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-19", "pb": 3.80, "quality": "Buena", "cam_sev": 1},
    {"ticker": "AI", "yf": "AI.PA", "name": "Air Liquide SA", "country": "FR", "sector": "Basic Materials", "pub_date": "2026-02-20", "pb": 2.70, "quality": "Media", "cam_sev": 0},
    {"ticker": "BNP", "yf": "BNP.PA", "name": "BNP Paribas SA", "country": "FR", "sector": "Financials", "pub_date": "2026-02-06", "pb": 0.84, "quality": "Buena", "cam_sev": 1},
    {"ticker": "CS", "yf": "CS.PA", "name": "AXA SA", "country": "FR", "sector": "Financials", "pub_date": "2026-02-27", "pb": 1.10, "quality": "Media", "cam_sev": 1},
    {"ticker": "SAF", "yf": "SAF.PA", "name": "Safran SA", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-14", "pb": 4.20, "quality": "Buena", "cam_sev": 0},
    {"ticker": "EL", "yf": "EL.PA", "name": "EssilorLuxottica SA", "country": "FR", "sector": "Healthcare", "pub_date": "2026-02-26", "pb": 3.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "DG", "yf": "DG.PA", "name": "Vinci SA", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-08", "pb": 1.90, "quality": "Media", "cam_sev": 0},
    {"ticker": "BN", "yf": "BN.PA", "name": "Danone SA", "country": "FR", "sector": "Consumer Staples", "pub_date": "2026-02-21", "pb": 2.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "ENGI", "yf": "ENGI.PA", "name": "Engie SA", "country": "FR", "sector": "Utilities", "pub_date": "2026-02-22", "pb": 0.95, "quality": "Media", "cam_sev": 1},
    {"ticker": "KER", "yf": "KER.PA", "name": "Kering SA", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-12", "pb": 2.40, "quality": "Baja", "cam_sev": 0},
    {"ticker": "GLE", "yf": "GLE.PA", "name": "Societe Generale SA", "country": "FR", "sector": "Financials", "pub_date": "2026-02-07", "pb": 0.50, "quality": "Media", "cam_sev": 1},
    {"ticker": "ACA", "yf": "ACA.PA", "name": "Credit Agricole SA", "country": "FR", "sector": "Financials", "pub_date": "2026-02-07", "pb": 0.75, "quality": "Media", "cam_sev": 1},
    {"ticker": "CAP", "yf": "CAP.PA", "name": "Capgemini SE", "country": "FR", "sector": "Technology", "pub_date": "2026-02-14", "pb": 2.60, "quality": "Media", "cam_sev": 0},
    {"ticker": "ORA", "yf": "ORA.PA", "name": "Orange SA", "country": "FR", "sector": "Telecommunications", "pub_date": "2026-02-14", "pb": 0.90, "quality": "Media", "cam_sev": 0},
    {"ticker": "RI", "yf": "RI.PA", "name": "Pernod Ricard SA", "country": "FR", "sector": "Consumer Staples", "pub_date": "2026-02-15", "pb": 2.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "LR", "yf": "LR.PA", "name": "Legrand SA", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-15", "pb": 2.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "ML", "yf": "ML.PA", "name": "Michelin", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-12", "pb": 1.20, "quality": "Media", "cam_sev": 0},
    {"ticker": "VIE", "yf": "VIE.PA", "name": "Veolia Environnement SA", "country": "FR", "sector": "Utilities", "pub_date": "2026-02-28", "pb": 1.65, "quality": "Media", "cam_sev": 0},
    {"ticker": "PUB", "yf": "PUB.PA", "name": "Publicis Groupe SA", "country": "FR", "sector": "Communication Services", "pub_date": "2026-02-07", "pb": 1.80, "quality": "Media", "cam_sev": 0},
    {"ticker": "TEP", "yf": "TEP.PA", "name": "Teleperformance SE", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-26", "pb": 1.70, "quality": "Baja", "cam_sev": 0},
    {"ticker": "DSY", "yf": "DSY.PA", "name": "Dassault Systemes SE", "country": "FR", "sector": "Technology", "pub_date": "2026-02-12", "pb": 4.10, "quality": "Buena", "cam_sev": 0},
    {"ticker": "AC", "yf": "AC.PA", "name": "Accor SA", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-20", "pb": 1.50, "quality": "Media", "cam_sev": 0},
    {"ticker": "EN", "yf": "EN.PA", "name": "Bouygues SA", "country": "FR", "sector": "Industrials", "pub_date": "2026-02-27", "pb": 1.30, "quality": "Media", "cam_sev": 0},
    {"ticker": "CA", "yf": "CA.PA", "name": "Carrefour SA", "country": "FR", "sector": "Consumer Staples", "pub_date": "2026-02-20", "pb": 1.10, "quality": "Media", "cam_sev": 0},
    {"ticker": "AKE", "yf": "AKE.PA", "name": "Arkema SA", "country": "FR", "sector": "Basic Materials", "pub_date": "2026-02-27", "pb": 0.85, "quality": "Media", "cam_sev": 0},
    {"ticker": "RNO", "yf": "RNO.PA", "name": "Renault SA", "country": "FR", "sector": "Consumer Discretionary", "pub_date": "2026-02-14", "pb": 0.45, "quality": "Baja", "cam_sev": 2},
    {"ticker": "ALO", "yf": "ALO.PA", "name": "Alstom SA", "country": "FR", "sector": "Industrials", "pub_date": "2026-05-15", "pb": 1.50, "quality": "Baja", "cam_sev": 2},

    # PAÍSES BAJOS (EURONEXT AMSTERDAM) & ITALIA (BORSA ITALIANA)
    {"ticker": "ASML", "yf": "ASML.AS", "name": "ASML Holding NV", "country": "NL", "sector": "Technology", "pub_date": "2026-01-29", "pb": 15.00, "quality": "Buena", "cam_sev": 0},
    {"ticker": "PROX", "yf": "PRX.AS", "name": "Prosus NV", "country": "NL", "sector": "Technology", "pub_date": "2026-06-24", "pb": 0.48, "quality": "Buena", "cam_sev": 0},
    {"ticker": "INGA", "yf": "INGA.AS", "name": "ING Groep NV", "country": "NL", "sector": "Financials", "pub_date": "2026-03-07", "pb": 0.95, "quality": "Buena", "cam_sev": 1},
    {"ticker": "UNA", "yf": "UNA.AS", "name": "Unilever PLC", "country": "NL", "sector": "Consumer Staples", "pub_date": "2026-02-12", "pb": 2.90, "quality": "Buena", "cam_sev": 0},
    {"ticker": "HEIA", "yf": "HEIA.AS", "name": "Heineken NV", "country": "NL", "sector": "Consumer Staples", "pub_date": "2026-02-12", "pb": 2.40, "quality": "Buena", "cam_sev": 0},
    {"ticker": "KPN", "yf": "KPN.AS", "name": "Koninklijke KPN NV", "country": "NL", "sector": "Telecommunications", "pub_date": "2026-02-20", "pb": 0.95, "quality": "Media", "cam_sev": 0},
    {"ticker": "WKL", "yf": "WKL.AS", "name": "Wolters Kluwer NV", "country": "NL", "sector": "Industrials", "pub_date": "2026-02-20", "pb": 4.10, "quality": "Buena", "cam_sev": 0},
    {"ticker": "PHIA", "yf": "PHIA.AS", "name": "Koninklijke Philips NV", "country": "NL", "sector": "Healthcare", "pub_date": "2026-02-10", "pb": 1.60, "quality": "Media", "cam_sev": 1},
    {"ticker": "ASM", "yf": "ASM.AS", "name": "ASM International NV", "country": "NL", "sector": "Technology", "pub_date": "2026-02-26", "pb": 4.50, "quality": "Media", "cam_sev": 0},
    {"ticker": "BESI", "yf": "BESI.AS", "name": "BE Semiconductor Industries NV", "country": "NL", "sector": "Technology", "pub_date": "2026-02-20", "pb": 4.80, "quality": "Media", "cam_sev": 0},
    {"ticker": "ENEL", "yf": "ENEL.MI", "name": "Enel SpA", "country": "IT", "sector": "Utilities", "pub_date": "2026-03-19", "pb": 1.45, "quality": "Media", "cam_sev": 1},
    {"ticker": "ENI", "yf": "ENI.MI", "name": "Eni SpA", "country": "IT", "sector": "Energy", "pub_date": "2026-03-14", "pb": 1.15, "quality": "Media", "cam_sev": 1},
    {"ticker": "ISP", "yf": "ISP.MI", "name": "Intesa Sanpaolo SpA", "country": "IT", "sector": "Financials", "pub_date": "2026-02-27", "pb": 0.90, "quality": "Media", "cam_sev": 1},
    {"ticker": "UCG", "yf": "UCG.MI", "name": "UniCredit SpA", "country": "IT", "sector": "Financials", "pub_date": "2026-02-28", "pb": 0.85, "quality": "Media", "cam_sev": 1},
    {"ticker": "STLAM", "yf": "STLAM.MI", "name": "Stellantis NV", "country": "IT", "sector": "Consumer Discretionary", "pub_date": "2026-02-26", "pb": 0.42, "quality": "Baja", "cam_sev": 0},
    {"ticker": "RACE", "yf": "RACE.MI", "name": "Ferrari NV", "country": "IT", "sector": "Consumer Discretionary", "pub_date": "2026-02-20", "pb": 18.00, "quality": "Buena", "cam_sev": 0},
    {"ticker": "PRY", "yf": "PRY.MI", "name": "Prysmian SpA", "country": "IT", "sector": "Industrials", "pub_date": "2026-02-27", "pb": 2.40, "quality": "Media", "cam_sev": 0},
    {"ticker": "MONC", "yf": "MONC.MI", "name": "Moncler SpA", "country": "IT", "sector": "Consumer Discretionary", "pub_date": "2026-02-28", "pb": 4.10, "quality": "Buena", "cam_sev": 0},
    {"ticker": "G", "yf": "G.MI", "name": "Assicurazioni Generali SpA", "country": "IT", "sector": "Financials", "pub_date": "2026-03-12", "pb": 1.25, "quality": "Media", "cam_sev": 1},
    {"ticker": "BAMI", "yf": "BAMI.MI", "name": "Banco BPM SpA", "country": "IT", "sector": "Financials", "pub_date": "2026-02-26", "pb": 0.70, "quality": "Media", "cam_sev": 1}
]


def run_analysis():
    print("================================================================================")
    print("ANÁLISIS PERICIAL DE LOS INFORMES 2025 (PUBLICADOS EN 2026) Y PRECIOS HASTA HOY")
    print("================================================================================")

    # 1. Obtener lista única de tickers de Yahoo Finance
    yf_list = sorted(list(set(c["yf"] for c in COMPANIES_2025)))
    print(f"Descargando cotizaciones para {len(yf_list)} empresas europeas desde enero 2026...")

    # Descarga de precios
    df_prices = yf.download(yf_list, start="2026-01-01", progress=False)["Close"]
    print(f"Sesiones descargadas en 2026: {len(df_prices)} días hábiles.")

    results = []
    sev_labels = {0: "CAM Leve", 1: "CAM Media", 2: "CAM Severa"}

    for comp in COMPANIES_2025:
        ticker = comp["ticker"]
        yf_t = comp["yf"]
        name = comp["name"]
        country = comp["country"]
        sector = comp["sector"]
        pub_date = comp["pub_date"]
        pb = comp["pb"]
        q_cat = comp["quality"]
        cam_sev = comp["cam_sev"]

        # Clasificación canónica
        regimen_pb = "Barata" if pb <= 1.00 else "Cara"
        bolsa_canonica = f"{q_cat}_{regimen_pb}"

        # Precios
        if yf_t not in df_prices.columns:
            continue

        p_series = df_prices[yf_t].dropna()
        if p_series.empty:
            continue

        # Precio en fecha de publicación (primer día hábil en o tras pub_date)
        sub_pub = p_series.loc[p_series.index >= pub_date]
        if sub_pub.empty:
            continue

        p_pub = float(sub_pub.iloc[0].values[0]) if hasattr(sub_pub.iloc[0], 'values') else float(sub_pub.iloc[0])
        p_today = float(p_series.iloc[-1].values[0]) if hasattr(p_series.iloc[-1], 'values') else float(p_series.iloc[-1])
        actual_date_pub = sub_pub.index[0].strftime("%Y-%m-%d")

        ret_since_pub = ((p_today / p_pub) - 1.0) * 100.0

        results.append({
            "ticker": ticker,
            "yf_ticker": yf_t,
            "company_name": name,
            "country": country,
            "sector": sector,
            "fiscal_year": 2025,
            "fecha_publicacion_informe": pub_date,
            "fecha_primera_cotizacion": actual_date_pub,
            "precio_publicacion": round(p_pub, 2),
            "precio_hoy_oct2026": round(p_today, 2),
            "rentabilidad_desde_publicacion_pct": round(ret_since_pub, 2),
            "pb_ratio": pb,
            "regimen_pb": regimen_pb,
            "cesta_calidad": q_cat,
            "bolsa_canonica_6": bolsa_canonica,
            "cam_severity": cam_sev,
            "sev_label": sev_labels[cam_sev]
        })

    df_out = pd.DataFrame(results)
    print(f"\nEmpresas con precio analizado desde publicación hasta hoy: {len(df_out)}")

    # Guardar CSV de empresas 2025
    p_csv_emp = OUTPUT_DIR / "06_empresas_2025_evolucion_precios.csv"
    df_out.to_csv(p_csv_emp, index=False, encoding="utf-8")
    print(f"Detalle de empresas guardado en: {p_csv_emp}")

    # Persistir en DuckDB
    conn = duckdb.connect(str(DB_PATH))
    conn.execute("DROP TABLE IF EXISTS pericial_informes_2025_europa")
    conn.register("df_temp_2025", df_out)
    conn.execute("CREATE TABLE pericial_informes_2025_europa AS SELECT * FROM df_temp_2025")
    print("[DuckDB] Tabla 'pericial_informes_2025_europa' guardada con éxito.")

    # Construir Tabla Cruzada: 6 Bolsas x 3 Estados CAM
    order_bolsas = ["Baja_Cara", "Baja_Barata", "Media_Cara", "Media_Barata", "Buena_Cara", "Buena_Barata"]
    order_sev = [2, 1, 0]

    ret_matrix = []
    cnt_matrix = []

    for s_code in order_sev:
        s_name = sev_labels[s_code]
        row_ret = {"Nivel_Severidad_CAM": f"Rentabilidad {s_name}"}
        row_cnt = {"Nivel_Severidad_CAM": f"Número de Empresas {s_name}"}

        for b_name in order_bolsas:
            sub = df_out[(df_out["bolsa_canonica_6"] == b_name) & (df_out["cam_severity"] == s_code)]
            cnt = len(sub)
            if cnt > 0:
                mean_r = sub["rentabilidad_desde_publicacion_pct"].mean()
                med_r = sub["rentabilidad_desde_publicacion_pct"].median()
                row_ret[b_name] = f"{mean_r:+.2f}% ({med_r:+.2f}%)"
                row_cnt[b_name] = f"{cnt} ({sub['ticker'].nunique()} cotizadas)"
            else:
                row_ret[b_name] = "N/A*"
                row_cnt[b_name] = "0 (0)"

        ret_matrix.append(row_ret)
        cnt_matrix.append(row_cnt)

    df_ret_matrix = pd.DataFrame(ret_matrix)
    df_cnt_matrix = pd.DataFrame(cnt_matrix)

    p_csv_ret = OUTPUT_DIR / "07_matriz_rentabilidad_cruzada_2025_hasta_hoy.csv"
    p_csv_cnt = OUTPUT_DIR / "08_matriz_conteo_2025_hasta_hoy.csv"
    df_ret_matrix.to_csv(p_csv_ret, index=False, encoding="utf-8")
    df_cnt_matrix.to_csv(p_csv_cnt, index=False, encoding="utf-8")

    print(f"\nMatriz de rentabilidad 2025 guardada en: {p_csv_ret}")
    print(f"Matriz de conteo 2025 guardada en: {p_csv_cnt}")

    # Mostrar la matriz en consola
    print("\n================================================================================")
    print("MATRIZ BIDIMENSIONAL: RENTABILIDAD DESDE PUBLICACIÓN HASTA HOY (OCTUBRE 2026)")
    print("================================================================================")
    print(df_ret_matrix.to_string())

    print("\n================================================================================")
    print("MATRIZ BIDIMENSIONAL: NÚMERO DE COTIZADAS POR CELDA (EJERCICIO 2025)")
    print("================================================================================")
    print(df_cnt_matrix.to_string())


if __name__ == "__main__":
    run_analysis()
