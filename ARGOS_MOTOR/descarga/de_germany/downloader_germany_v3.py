# -*- coding: utf-8 -*-
"""
ARGOS MOTOR -- Motor Unificado de Descarga Institucional Alemania v3.0
====================================================================
Motor multicanal ultra-resiliente para la adquisicion y sellado criptografico
de cuentas anuales auditadas de las 1.011 sociedades cotizadas alemanas (2012-2025).

Canales jerarquicos:
  Canal 1: Cache local + ESEF fast-path (filings.xbrl.org / OAM)
  Canal 2: Paginas IR oficiales (mapa curado ~80 empresas DAX/MDAX)
  Canal 3: Bundesanzeiger Area 22 (Playwright, sesion persistente anti-Wicket)
  Canal 4: Busqueda web (DuckDuckGo) -> PDFs directos

Autor: ARGOS-MOTOR / STATER Financial Technologies
Version: 3.0.0 -- 2026-09-18
"""

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

# --- Dependencias opcionales ---
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("[WARN] httpx no disponible. Instalar: pip install httpx")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("[WARN] beautifulsoup4 no disponible. Instalar: pip install beautifulsoup4 lxml")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# --- Constantes ---
VERSION = "3.0.0"
DEFAULT_YEARS = list(range(2012, 2026))
RATE_LIMIT_DELAY = 1.2
PLAYWRIGHT_TIMEOUT = 30_000

BOILERPLATE_HASHES = {
    "3f418fa15253013f4dc73620d471cb567e0f2e1b46f7981c71ffff427ff6ff6b",
    "2ac7a66b8489ec150d1feef7759323851317657b1a6ebbc8d18faf7618171552",
}

REJECTION_SIGNATURES = [
    b'__NEXT_DATA__', b'/_next/static/', b'Sicherheitsabfrage',
    b'captcha~panel-captcha', b'Zeichen eingeben', b'Ich bin ein Mensch',
    b'suchergebnis-container', b'cf-browser-verification',
]

FINANCIAL_KEYWORDS = [
    'Aktiva', 'Passiva', 'TEUR', 'Eigenkapital', 'Bilanzsumme',
    'Jahresueberschuss', 'Konzernjahresergebnis', 'Konzernabschluss',
    'Jahresabschluss', 'Jahresbericht', 'Annual Report', 'Umsatzerlöse',
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

# --- Mapa curado de IR Pages (Canal 2) ---
IR_PAGE_PATTERNS = {
    'ADS':    ('https://www.adidas-group.com/en/investors/financial-reports/', 'a[href$=".pdf"]'),
    'ADID':   ('https://www.adidas-group.com/en/investors/financial-reports/', 'a[href$=".pdf"]'),
    'AIR':    ('https://www.airbus.com/en/investors/financial-results-and-communications/annual-report', 'a[href$=".pdf"]'),
    'AIRB':   ('https://www.airbus.com/en/investors/financial-results-and-communications/annual-report', 'a[href$=".pdf"]'),
    'ALV':    ('https://www.allianz.com/en/investor_relations/results_reports/annual-report.html', 'a[href$=".pdf"]'),
    'ALIZ':   ('https://www.allianz.com/en/investor_relations/results_reports/annual-report.html', 'a[href$=".pdf"]'),
    'ALLI':   ('https://www.allianz.com/en/investor_relations/results_reports/annual-report.html', 'a[href$=".pdf"]'),
    'BAS':    ('https://www.basf.com/global/en/investors/calendar-and-publications/annual-report.html', 'a[href$=".pdf"]'),
    'BASF':   ('https://www.basf.com/global/en/investors/calendar-and-publications/annual-report.html', 'a[href$=".pdf"]'),
    'BAYN':   ('https://www.bayer.com/en/investors/integrated-annual-reports', 'a[href$=".pdf"]'),
    'BAYG':   ('https://www.bayer.com/en/investors/integrated-annual-reports', 'a[href$=".pdf"]'),
    'BMW':    ('https://www.bmwgroup.com/en/investor-relations/financial-reports.html', 'a[href$=".pdf"]'),
    'BMWG':   ('https://www.bmwgroup.com/en/investor-relations/financial-reports.html', 'a[href$=".pdf"]'),
    'BAYE_5': ('https://www.bmwgroup.com/en/investor-relations/financial-reports.html', 'a[href$=".pdf"]'),  # BMW en universo
    'CON':    ('https://www.continental.com/en/investors/financial-publications/annual-reports/', 'a[href$=".pdf"]'),
    'CONTI':  ('https://www.continental.com/en/investors/financial-publications/annual-reports/', 'a[href$=".pdf"]'),
    'DTG':    ('https://ir.daimlertruck.com/reports-events/annual-reports', 'a[href$=".pdf"]'),
    'DMLR':   ('https://ir.daimlertruck.com/reports-events/annual-reports', 'a[href$=".pdf"]'),
    'DBK':    ('https://investor-relations.db.com/reports-and-events/annual-reports', 'a[href$=".pdf"]'),
    'DEUT_2': ('https://investor-relations.db.com/reports-and-events/annual-reports', 'a[href$=".pdf"]'),
    'DEUT_24':('https://investor-relations.db.com/reports-and-events/annual-reports', 'a[href$=".pdf"]'),
    'DHL':    ('https://www.dhl.com/global-en/home/about-us/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'DPW':    ('https://www.dhl.com/global-en/home/about-us/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'DTE':    ('https://www.telekom.com/en/investor-relations/publications/financial-results', 'a[href$=".pdf"]'),
    'DEUT':   ('https://www.telekom.com/en/investor-relations/publications/financial-results', 'a[href$=".pdf"]'),
    'DEUT_19':('https://www.telekom.com/en/investor-relations/publications/financial-results', 'a[href$=".pdf"]'),
    'ENR':    ('https://www.siemens-energy.com/global/en/company/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'SIEM':   ('https://www.siemens.com/global/en/company/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'SMTS':   ('https://www.siemens.com/global/en/company/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'SIEM_2': ('https://www.siemens.com/global/en/company/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'SIEM_3': ('https://www.siemens.com/global/en/company/investor-relations/annual-report.html', 'a[href$=".pdf"]'),
    'EOAN':   ('https://www.eon.com/en/investor-relations/financial-publications.html', 'a[href$=".pdf"]'),
    'FREG':   ('https://www.fresenius.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'FRE':    ('https://www.fresenius.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'HDAG':   ('https://www.heidelbergmaterials.com/en/investor-relations/reports-and-publications', 'a[href$=".pdf"]'),
    'HEID':   ('https://ir.heidelbergmaterials.com/English/ir/publications/annual-report/', 'a[href$=".pdf"]'),
    'HNR1':   ('https://www.henkel.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'HNKL':   ('https://www.henkel.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'IFX':    ('https://www.infineon.com/cms/en/about-infineon/investor/publications/', 'a[href$=".pdf"]'),
    'INFN':   ('https://www.infineon.com/cms/en/about-infineon/investor/publications/', 'a[href$=".pdf"]'),
    'LHA':    ('https://investor-relations.lufthansagroup.com/en/publications/financial-reports.html', 'a[href$=".pdf"]'),
    'LUFT':   ('https://investor-relations.lufthansagroup.com/en/publications/financial-reports.html', 'a[href$=".pdf"]'),
    'MRK':    ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'MERQ':   ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'MTX':    ('https://www.mtu.de/investors/financial-results-publications/', 'a[href$=".pdf"]'),
    'MUV2':   ('https://www.munich-re.com/en/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'MUTA':   ('https://www.munich-re.com/en/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'P911':   ('https://newsroom.porsche.com/en/press-releases/annual-reports.html', 'a[href$=".pdf"]'),
    'PORS':   ('https://newsroom.porsche.com/en/press-releases/annual-reports.html', 'a[href$=".pdf"]'),
    'PAH3':   ('https://www.porsche-se.com/investor-relations/reports/', 'a[href$=".pdf"]'),
    'PORH':   ('https://www.porsche-se.com/investor-relations/reports/', 'a[href$=".pdf"]'),
    'RHM':    ('https://www.rheinmetall.com/en/investor-relations/publications-events/', 'a[href$=".pdf"]'),
    'RHIN':   ('https://www.rheinmetall.com/en/investor-relations/publications-events/', 'a[href$=".pdf"]'),
    'RWE':    ('https://www.rwe.com/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'SAP':    ('https://www.sap.com/investors/en/reports/annual-reports.html', 'a[href$=".pdf"]'),
    'SAPS':   ('https://www.sap.com/investors/en/reports/annual-reports.html', 'a[href$=".pdf"]'),
    'SAR':    ('https://www.sartorius.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'SART':   ('https://www.sartorius.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'SHL':    ('https://www.siemens-healthineers.com/investor-relations/annual-report', 'a[href$=".pdf"]'),
    'SHLG':   ('https://www.siemens-healthineers.com/investor-relations/annual-report', 'a[href$=".pdf"]'),
    'SY1':    ('https://www.symrise.com/investors/reports-publications/', 'a[href$=".pdf"]'),
    'SYMR':   ('https://www.symrise.com/investors/reports-publications/', 'a[href$=".pdf"]'),
    'VBK':    ('https://www.volkswagen-group.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'VOW3':   ('https://www.volkswagen-group.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'VOWI':   ('https://www.volkswagenag.com/en/InvestorRelations/publications/Annual_Reports.html', 'a[href$=".pdf"]'),
    'COP':    ('https://www.covestro.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'COVS':   ('https://www.covestro.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'HLE':    ('https://www.hannover-re.com/investors/publications-presentations/', 'a[href$=".pdf"]'),
    'HNR':    ('https://www.hannover-re.com/investors/publications-presentations/', 'a[href$=".pdf"]'),
    'TKA':    ('https://www.thyssenkrupp.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'THYG':   ('https://www.thyssenkrupp.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'TTK':    ('https://www.talanx.com/investor-relations/financial-publications/', 'a[href$=".pdf"]'),
    'ZAL':    ('https://corporate.zalando.com/en/investor-relations/publications/annual-reports', 'a[href$=".pdf"]'),
    'ZALN':   ('https://corporate.zalando.com/en/investor-relations/publications/annual-reports', 'a[href$=".pdf"]'),
    'NGEN':   ('https://www.nemetschek.com/en/investor-relations/publications/', 'a[href$=".pdf"]'),
    'G1A':    ('https://www.gerresheimer.com/en/investor-relations/publications', 'a[href$=".pdf"]'),
    # --- Tickers reales del universo maestro (encontrados via analisis) ---
    'VOLK':   ('https://www.volkswagen-group.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'VOLK_2': ('https://www.volkswagen-group.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'VOLK_3': ('https://www.volkswagen-group.com/en/investor-relations/publications/annual-report.html', 'a[href$=".pdf"]'),
    'INFI':   ('https://www.infineon.com/cms/en/about-infineon/investor/publications/', 'a[href$=".pdf"]'),
    'BAYE_3': ('https://www.bayer.com/en/investors/integrated-annual-reports', 'a[href$=".pdf"]'),
    'MUNI':   ('https://www.munich-re.com/en/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'CONT':   ('https://www.continental.com/en/investors/financial-publications/annual-reports/', 'a[href$=".pdf"]'),
    'DE_RWE': ('https://www.rwe.com/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'DE_EON': ('https://www.eon.com/en/investor-relations/financial-publications.html', 'a[href$=".pdf"]'),
    'FRES':   ('https://www.fresenius.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'FRES_2': ('https://www.freseniusmedicalcare.com/en/investors/publications', 'a[href$=".pdf"]'),
    'FRES_3': ('https://www.fresenius.com/investors/reports-and-publications', 'a[href$=".pdf"]'),
    'MERC_2': ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'MERC_3': ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'MERC_4': ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'COVE':   ('https://www.covestro.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'COVE_2': ('https://www.covestro.com/en/investor-relations/financial-reports', 'a[href$=".pdf"]'),
    'THYS_2': ('https://www.thyssenkrupp.com/en/investors/reporting-and-publications/', 'a[href$=".pdf"]'),
    'SYMR_2': ('https://www.symrise.com/investors/reports-publications/', 'a[href$=".pdf"]'),
}


# PDFs directos curados (Canal 2 fast-path)
# NOTA: Las URLs de SAP en assets.cdn.sap.com retornan 404 desde 2024.
# Usando scraping via IR_PAGE_PATTERNS en su lugar.
IR_PDF_MAP = {
    # Lufthansa -- PDFs historicos estables en investor-relations.lufthansagroup.com
    'LUFT': {
        2019: 'https://investor-relations.lufthansagroup.com/en/publications/financial-reports/annual-report-2019.pdf',
        2018: 'https://investor-relations.lufthansagroup.com/en/publications/financial-reports/annual-report-2018.pdf',
        2017: 'https://investor-relations.lufthansagroup.com/en/publications/financial-reports/annual-report-2017.pdf',
    },
    'LHA': {
        2019: 'https://investor-relations.lufthansagroup.com/en/publications/financial-reports/annual-report-2019.pdf',
        2018: 'https://investor-relations.lufthansagroup.com/en/publications/financial-reports/annual-report-2018.pdf',
    },
    # Bayer AG -- PDFs directos historicos desde bayer.com
    'BAYE_3': {
        2019: 'https://www.bayer.com/sites/default/files/2020-11/bayer-ag-annual-report-2019_6.pdf',
        2018: 'https://www.bayer.com/sites/default/files/2020-04/bayer_ar18_entire.pdf',
        2017: 'https://www.bayer.com/sites/default/files/2020-05/bayer_ar17_entire.pdf',
        2016: 'https://www.bayer.com/sites/default/files/2020-05/ar-2016.pdf',
        2015: 'https://www.bayer.com/sites/default/files/2023-12/gb-2015-en.pdf',
        2014: 'https://www.bayer.com/sites/default/files/2023-12/ar-2014-0.pdf',
    },
    'BAYN': {
        2019: 'https://www.bayer.com/sites/default/files/2020-11/bayer-ag-annual-report-2019_6.pdf',
        2018: 'https://www.bayer.com/sites/default/files/2020-04/bayer_ar18_entire.pdf',
        2017: 'https://www.bayer.com/sites/default/files/2020-05/bayer_ar17_entire.pdf',
        2016: 'https://www.bayer.com/sites/default/files/2020-05/ar-2016.pdf',
        2015: 'https://www.bayer.com/sites/default/files/2023-12/gb-2015-en.pdf',
        2014: 'https://www.bayer.com/sites/default/files/2023-12/ar-2014-0.pdf',
    },
    # Thyssenkrupp AG -- PDFs directos historicos
    'THYS_2': {
        2019: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/86ac8d65-840b-44ad-96fd-c1b76fcf0a67/thyssenkrupp-gb-2018-2019-en-web_neu.pdf',
        2018: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/d696ce08-b7ec-4cf0-9183-145bbda093d1/thyssenkrupp-ag-ar-2017-2018-eng-web.pdf',
        2017: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/09db9818-ed64-46f5-a3c9-c793661ba69c/neu2-gb_2016-2017-thyssenkrupp-gb-eng-web.pdf',
        2016: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/08fb200e-8e4a-45b2-aac8-42f0e0ba6780/thyssenkrupp_gb_en_2015_2016.pdf',
    },
    'TKA': {
        2019: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/86ac8d65-840b-44ad-96fd-c1b76fcf0a67/thyssenkrupp-gb-2018-2019-en-web_neu.pdf',
        2018: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/d696ce08-b7ec-4cf0-9183-145bbda093d1/thyssenkrupp-ag-ar-2017-2018-eng-web.pdf',
        2017: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/09db9818-ed64-46f5-a3c9-c793661ba69c/neu2-gb_2016-2017-thyssenkrupp-gb-eng-web.pdf',
        2016: 'https://ucpcdn.thyssenkrupp.com/_binary/UCP5thyssenkruppAG/08fb200e-8e4a-45b2-aac8-42f0e0ba6780/thyssenkrupp_gb_en_2015_2016.pdf',
    },
}

# Spin-offs: primer anio de existencia como entidad cotizada independiente
SPINOFF_INCEPTION = {
    'ENR': 2020, 'SIEM_ENR': 2020,
    'DTG': 2021, 'DMLR': 2021,
    'P911': 2022, 'PORS': 2022,
    'SHL': 2018, 'SHLG': 2018,
    'SAR': 2021, 'ZAL': 2014, 'ZALN': 2014,
    'NGEN': 2014, 'RIO': 2022, 'PAH3': 2021,
}


# --- Deteccion automatica de ruta canonica ---

def resolve_data_root() -> Path:
    candidates = [
        os.environ.get("ARGOS_DATA_ROOT", ""),
        "/opt/argos_data",
        "D:/ARGOS_DATA",
        "ARGOS_DATA_DISK",
        "ARGOS_MOTOR/data",
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c) / "raw" / "DE_BAFIN"
        if p.exists():
            return p
    p = Path(__file__).resolve().parents[2] / "data" / "raw" / "DE_BAFIN"
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_universe() -> dict:
    candidates = [
        Path(__file__).resolve().parents[2] / "config" / "master_universe_de.json",
        Path("/opt/workspace_base/ARGOS_MOTOR/config/master_universe_de.json"),
        Path("ARGOS_MOTOR/config/master_universe_de.json"),
        Path("C:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/config/master_universe_de.json"),
    ]
    for p in candidates:
        if p.exists():
            data = json.loads(p.read_text(encoding='utf-8'))
            return data.get("companies", {})
    raise FileNotFoundError("master_universe_de.json no encontrado")


# --- Hashing y validacion ---

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_valid_financial_document(content: bytes, source_url: str = '') -> tuple:
    if len(content) < 3000:
        return False, f"Demasiado pequenio ({len(content)} bytes)"
    digest = sha256_bytes(content)
    if digest in BOILERPLATE_HASHES:
        return False, f"Hash boilerplate conocido ({digest[:12]})"
    probe = content[:4096] + content[-1024:]
    for sig in REJECTION_SIGNATURES:
        if sig in probe:
            return False, f"Firma rechazo: {sig[:30]!r}"
    if content[:4] == b'%PDF':
        if len(content) < 5000:
            return False, f"PDF demasiado pequenio ({len(content)} bytes)"
        return True, f"PDF valido ({len(content):,} bytes)"
    if content[:4] == b'PK\x03\x04':
        return True, f"ZIP ESEF valido ({len(content):,} bytes)"
    hits = sum(1 for kw in FINANCIAL_KEYWORDS
               if kw.encode('utf-8') in content or kw.encode('latin-1') in content)
    if hits < 2:
        return False, f"Solo {hits} keywords financieros (minimo 2)"
    return True, f"HTML valido ({hits} keywords, {len(content):,} bytes)"


def check_local_cache(comp_dir: Path, ticker: str, year: int) -> Optional[dict]:
    for ext in ['.pdf', '.zip', '.html', '.xhtml', '.htm']:
        for suffix in ['_ANUAL', '_ESEF']:
            fname = f"{ticker}_{year}{suffix}{ext}"
            fpath = comp_dir / fname
            meta_path = comp_dir / f"{fname}.meta.json"
            if fpath.exists() and meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding='utf-8'))
                    stored_hash = meta.get('sha256', '')
                    actual_hash = sha256_file(fpath)
                    if stored_hash == actual_hash:
                        return {'status': 'cache_hit', 'file': str(fpath), 'sha256': actual_hash}
                    else:
                        print(f"  [!] Hash mismatch en cache {fname} -- eliminando")
                        fpath.unlink()
                        meta_path.unlink()
                except Exception as e:
                    print(f"  [!] Error cache {fname}: {e}")
    return None


def seal_document(content: bytes, comp_dir: Path, ticker: str, year: int,
                  source_url: str, channel: str, company: dict, ext: str) -> Optional[Path]:
    valid, reason = is_valid_financial_document(content, source_url)
    if not valid:
        print(f"  [-] RECHAZADO [{channel}]: {reason}")
        return None
    suffix = "_ESEF" if ext == '.zip' else "_ANUAL"
    fname = f"{ticker}_{year}{suffix}{ext}"
    comp_dir.mkdir(parents=True, exist_ok=True)
    fpath = comp_dir / fname
    fpath.write_bytes(content)
    digest = sha256_bytes(content)
    meta = {
        "file_name": fname, "sha256": digest, "byte_size": len(content),
        "retrieved_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": source_url, "reporting_year": year, "ticker": ticker,
        "legal_name": company.get('name_legal', ''), "name_common": company.get('name_common', ''),
        "lei": company.get('lei', ''), "hrb_reg": company.get('hrb_reg', ''),
        "segment": company.get('segment', ''), "index_membership": company.get('index_membership', []),
        "magic_mime_verified": "PDF" if ext == '.pdf' else ("ZIP_ESEF" if ext == '.zip' else "HTML"),
        "validation_reason": reason, "download_channel": channel, "downloader_version": VERSION,
    }
    meta_path = comp_dir / f"{fname}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"  [+] SELLADO [{channel}]: {fname} ({len(content)/1024:.1f} KB, SHA256:{digest[:10]})")
    return fpath


def get_http_client():
    if not HTTPX_AVAILABLE:
        return None
    return httpx.Client(
        timeout=30.0, follow_redirects=True,
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }
    )


# --- CANAL 1: ESEF Fast-Path ---

def channel1_esef(company: dict, year: int, comp_dir: Path, dry_run: bool) -> Optional[str]:
    if year < 2020:
        return None
    ticker = company.get('ticker', '')
    lei = company.get('lei', '')
    if not lei or not HTTPX_AVAILABLE:
        return None
    client = get_http_client()
    if not client:
        return None
    try:
        resp = client.get("https://filings.xbrl.org/index.json", timeout=20)
        if resp.status_code == 200:
            idx = resp.json()
            filings = idx if isinstance(idx, list) else idx.get('filings', [])
            for filing in filings:
                f_lei = filing.get('lei', '')
                f_year = str(filing.get('period_of_report', ''))[:4]
                if f_lei == lei and f_year == str(year):
                    zip_url = filing.get('report_url') or filing.get('url', '')
                    if zip_url:
                        print(f"  [1] ESEF hit en xbrl.org: {zip_url}")
                        if dry_run:
                            return f"DRY_RUN:ESEF:{zip_url}"
                        time.sleep(RATE_LIMIT_DELAY)
                        r2 = client.get(zip_url, timeout=60)
                        if r2.status_code == 200:
                            return seal_document(r2.content, comp_dir, ticker, year,
                                                 zip_url, "CANAL1_ESEF", company, ".zip")
    except Exception as e:
        print(f"  [1] Error xbrl.org: {e}")
    finally:
        client.close()
    return None


# --- CANAL 2: IR Official PDF Crawler ---

def channel2_ir_crawler(company: dict, year: int, comp_dir: Path, dry_run: bool) -> Optional[str]:
    ticker = company.get('ticker', '')
    if not HTTPX_AVAILABLE or not BS4_AVAILABLE:
        return None

    # 2a: PDF directo mapeado (dedup para evitar doble intento cuando ticker ya esta en mayusculas)
    for key in dict.fromkeys([ticker, ticker.upper()]):
        year_map = IR_PDF_MAP.get(key, {})
        if year in year_map:
            url = year_map[year]
            print(f"  [2a] PDF directo mapeado: {url}")
            if dry_run:
                return f"DRY_RUN:PDF:{url}"
            client = get_http_client()
            try:
                time.sleep(RATE_LIMIT_DELAY)
                r = client.get(url, timeout=60)
                if r.status_code == 200 and r.content[:4] == b'%PDF' and len(r.content) > 5000:
                    return seal_document(r.content, comp_dir, ticker, year,
                                         url, "CANAL2a_PDF_DIRECTO", company, ".pdf")
                else:
                    print(f"  [2a] URL no valida (status={r.status_code}, size={len(r.content)})")
            except Exception as e:
                print(f"  [2a] Error: {e}")
            finally:
                client.close()

    # 2b: Scraping de IR page curada (dedup para evitar doble intento)
    for key in dict.fromkeys([ticker, ticker.upper()]):
        if key not in IR_PAGE_PATTERNS:
            continue
        ir_url, css_sel = IR_PAGE_PATTERNS[key]
        print(f"  [2b] Scraping IR page para {ticker}: {ir_url}")
        if dry_run:
            return f"DRY_RUN:IR:{ir_url}"
        client = get_http_client()
        try:
            time.sleep(RATE_LIMIT_DELAY)
            r = client.get(ir_url, timeout=30)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'lxml')
            pdf_links = []
            for a in soup.select(css_sel or 'a[href$=".pdf"]'):
                href = a.get('href', '')
                if not href:
                    continue
                if not href.startswith('http'):
                    base = '/'.join(ir_url.split('/')[:3])
                    href = base + ('' if href.startswith('/') else '/') + href
                link_text = a.get_text(strip=True).lower()
                year_str = str(year)
                prev_year = str(year - 1)
                if (year_str in link_text or year_str in href or
                        prev_year in link_text or prev_year in href):
                    score = 0
                    if year_str in href or year_str in link_text: score += 10
                    if 'konzern' in link_text or 'konzern' in href.lower(): score += 3
                    if 'annual' in link_text or 'bericht' in link_text: score += 2
                    pdf_links.append((score, href))
            pdf_links.sort(reverse=True)
            for _, pdf_url in pdf_links[:5]:
                try:
                    time.sleep(RATE_LIMIT_DELAY)
                    pr = client.get(pdf_url, timeout=60)
                    if pr.status_code == 200 and len(pr.content) > 10_000:
                        result = seal_document(pr.content, comp_dir, ticker, year,
                                               pdf_url, "CANAL2b_IR_SCRAPER", company, ".pdf")
                        if result:
                            return result
                except Exception as e:
                    print(f"  [2b] Error {pdf_url}: {e}")
        except Exception as e:
            print(f"  [2b] Error scraping {ir_url}: {e}")
        finally:
            client.close()
        break

    return None


# --- CANAL 3: Bundesanzeiger Area 22 (Playwright) ---

def channel3_bundesanzeiger(company: dict, year: int, comp_dir: Path,
                             dry_run: bool, manual_mode: bool) -> Optional[str]:
    """
    Canal 3: Bundesanzeiger Area 22 (Rechnungslegung/Finanzberichte).
    CRITICO: Nunca navegar atras en la misma pestania (Wicket session expiry).
    Abrir cada publicacion en pestania nueva e independiente.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("  [3] Playwright no disponible: pip install playwright && playwright install chromium")
        return None

    ticker = company.get('ticker', '')
    name_common = company.get('name_common', '')
    name_legal = company.get('name_legal', '')
    pub_year_from = year + 1
    pub_year_to = year + 2

    search_term = re.sub(r'\b(AG|SE|GmbH|KGaA|e\.V\.|plc|S\.A\.|NV|Holding)\b', '',
                         name_common or name_legal, flags=re.IGNORECASE).strip()
    search_term = re.sub(r'\s+', ' ', search_term).strip() or (name_legal or ticker)

    if dry_run:
        print(f"  [3] DRY-RUN Bundesanzeiger: '{search_term}' anio {year} (pub {pub_year_from}-{pub_year_to})")
        return f"DRY_RUN:BAFIN:{search_term}:{year}"

    print(f"  [3] Bundesanzeiger: '{search_term}' | anio fiscal {year}")

    with sync_playwright() as pw:
        headless = not manual_mode
        browser = pw.chromium.launch(headless=headless, slow_mo=150 if not headless else 50)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="de-DE",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        try:
            page.goto("https://www.bundesanzeiger.de/pub/de/start",
                      wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT)
            # Aceptar cookies
            try:
                btn = page.query_selector("button#cc_btn_accept_all, #onetrust-accept-btn-handler")
                if btn:
                    btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            if manual_mode:
                print("  [3] MODO MANUAL: Resuelve el CAPTCHA y pulsa Enter aqui cuando termine...")
                input()

            # Seleccionar area 22
            try:
                sel = page.query_selector("select[name='area_select'], select#area_select")
                if sel:
                    sel.select_option("22")
                    page.wait_for_timeout(500)
            except Exception:
                pass

            # Busqueda
            inp = page.query_selector("input[name='volltext'], input#volltext, input[type='search']")
            if not inp:
                inp = page.query_selector("input[type='text']")
            if not inp:
                print("  [3] Campo de busqueda no encontrado")
                return None

            inp.fill(search_term)
            page.wait_for_timeout(300)
            btn = page.query_selector("button[type='submit'], input[type='submit']")
            if btn:
                btn.click()
            else:
                inp.press("Enter")
            page.wait_for_load_state("networkidle", timeout=PLAYWRIGHT_TIMEOUT)

            html_content = page.content()
            if 'Sicherheitsabfrage' in html_content or 'captcha' in html_content.lower():
                print("  [3] CAPTCHA detectado. Usa --bafin-manual para resolver manualmente.")
                return None

            soup = BeautifulSoup(html_content, 'lxml')
            rows = soup.select(".result_container .result, li.result-item, div.result-row, table.result-table tr")
            print(f"  [3] {len(rows)} resultados en Bundesanzeiger")

            year_kw = [str(pub_year_from), str(pub_year_to), str(year)]
            doc_kw = ['Jahresabschluss', 'Konzernabschluss', 'Jahresfinanzbericht', 'Geschaeftsbericht', 'Finanzbericht']

            candidates = []
            for row in rows:
                text = row.get_text(' ', strip=True)
                has_year = any(y in text for y in year_kw)
                has_doc = any(dk.lower() in text.lower() for dk in doc_kw)
                if has_year and has_doc:
                    link = row.select_one('a[href]')
                    if link:
                        href = link.get('href', '')
                        score = (3 if 'konzern' in text.lower() else 1) + (2 if str(pub_year_from) in text else 0)
                        candidates.append((score, href, text[:80]))

            candidates.sort(reverse=True)
            print(f"  [3] {len(candidates)} candidatos relevantes")

            for score, href, text_preview in candidates[:5]:
                if not href.startswith('http'):
                    href = "https://www.bundesanzeiger.de" + href
                print(f"  [3] Candidato (score={score}): {text_preview[:60]}")

                # CRITICO: pestania nueva para evitar Wicket session expiry
                pub_page = context.new_page()
                try:
                    pub_page.goto(href, wait_until="networkidle", timeout=PLAYWRIGHT_TIMEOUT)
                    pub_html = pub_page.content()
                    pub_soup = BeautifulSoup(pub_html, 'lxml')

                    pdf_link = pub_soup.select_one('a[href$=".pdf"], a.pdf-download, a[title*="PDF"]')
                    if pdf_link and HTTPX_AVAILABLE:
                        pdf_href = pdf_link.get('href', '')
                        if not pdf_href.startswith('http'):
                            pdf_href = "https://www.bundesanzeiger.de" + pdf_href
                        client = get_http_client()
                        try:
                            time.sleep(RATE_LIMIT_DELAY)
                            r = client.get(pdf_href, timeout=90)
                            if r.status_code == 200 and len(r.content) > 5000:
                                result = seal_document(r.content, comp_dir, ticker, year,
                                                       pdf_href, "CANAL3_BUNDESANZEIGER", company, ".pdf")
                                if result:
                                    return str(result)
                        except Exception as e:
                            print(f"  [3] Error PDF {pdf_href}: {e}")
                        finally:
                            client.close()

                    # Fallback: HTML del documento
                    content_div = pub_soup.select_one('.publication-text, .content-container, main article')
                    if content_div:
                        html_bytes = pub_html.encode('utf-8')
                        valid, reason = is_valid_financial_document(html_bytes, href)
                        if valid:
                            result = seal_document(html_bytes, comp_dir, ticker, year,
                                                   href, "CANAL3_BAFIN_HTML", company, ".html")
                            if result:
                                return str(result)
                except Exception as e:
                    print(f"  [3] Error pestania {href}: {e}")
                finally:
                    pub_page.close()

            return None
        except PlaywrightTimeout:
            print(f"  [3] Timeout Bundesanzeiger {ticker} {year}")
            return None
        except Exception as e:
            print(f"  [3] Error general Bundesanzeiger: {e}")
            return None
        finally:
            browser.close()


DDG_DISABLED = False

def channel4_web_search(company: dict, year: int, comp_dir: Path, dry_run: bool) -> Optional[str]:
    global DDG_DISABLED
    if DDG_DISABLED:
        return None
    if not HTTPX_AVAILABLE or not BS4_AVAILABLE:
        return None
    ticker = company.get('ticker', '')
    name = company.get('name_common') or company.get('name_legal', ticker)
    pub_year = year + 1
    queries = [
        f'"{name}" Geschaeftsbericht {year} filetype:pdf',
        f'"{name}" annual report {year} pdf',
    ]
    if dry_run:
        print(f"  [4] DRY-RUN busqueda: {queries[0]}")
        return f"DRY_RUN:WEB:{queries[0]}"

    blocked = ['wikipedia.org', 'bloomberg.com', 'reuters.com', 'finanzen.net', 'boerse.de']
    client = get_http_client()
    found_urls = []
    try:
        for query in queries[:2]:
            encoded = urllib.parse.quote(query)
            try:
                time.sleep(RATE_LIMIT_DELAY)
                r = client.get(f"https://html.duckduckgo.com/html/?q={encoded}", timeout=5)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, 'lxml')
                    for link in soup.select("a.result__url, .result__title a"):
                        href = link.get('href', '')
                        if '/l/?uddg=' in href:
                            try:
                                params = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                                href = params.get('uddg', [href])[0]
                            except Exception:
                                pass
                        if not href.startswith('http'):
                            continue
                        if any(b in href.lower() for b in blocked):
                            continue
                        if href.lower().endswith('.pdf') and (str(year) in href or str(pub_year) in href):
                            found_urls.append(href)
            except Exception as e:
                print(f"  [4] Error DDG '{query[:40]}': {e}")
                if "10060" in str(e) or "ConnectError" in type(e).__name__ or "Timeout" in type(e).__name__:
                    print("  [4] DDG no accesible en esta red. Desactivando Canal 4 para evitar esperas.")
                    DDG_DISABLED = True
                    break

        for pdf_url in found_urls[:5]:
            try:
                print(f"  [4] PDF web: {pdf_url}")
                time.sleep(RATE_LIMIT_DELAY)
                r = client.get(pdf_url, timeout=90)
                if r.status_code == 200 and r.content[:4] == b'%PDF' and len(r.content) > 10_000:
                    result = seal_document(r.content, comp_dir, ticker, year,
                                           pdf_url, "CANAL4_WEB_SEARCH", company, ".pdf")
                    if result:
                        return str(result)
            except Exception as e:
                print(f"  [4] Error {pdf_url}: {e}")
    except Exception as e:
        print(f"  [4] Error general: {e}")
    finally:
        client.close()
    return None


# --- Orquestador principal ---

def process_company_year(company: dict, year: int, data_root: Path,
                          dry_run: bool = False, bafin_manual: bool = False,
                          skip_canal: list = None) -> dict:
    ticker = company.get('ticker', '')
    name = company.get('name_common', company.get('name_legal', ticker))
    skip_canal = skip_canal or []

    hrb = company.get('hrb_reg', '')
    lei = company.get('lei', '')
    tax_id = re.sub(r'[^A-Za-z0-9_\-]', '_', hrb.strip()) if hrb else (lei or ticker)
    comp_dir = data_root / str(year) / f"{tax_id}_{ticker}"
    result_base = {'ticker': ticker, 'year': year, 'company': name, 'comp_dir': str(comp_dir)}

    # Verificar spin-off
    inception = SPINOFF_INCEPTION.get(ticker) or SPINOFF_INCEPTION.get(ticker.upper())
    if inception and year < inception:
        print(f"  [SKIP] {ticker} {year}: spin-off (desde {inception}) -> NOT_INCORPORATED_YET")
        return {**result_base, 'status': 'NOT_INCORPORATED_YET', 'channel': None}

    print(f"\n{'='*60}\n  {ticker} | {name} | AÑO {year}\n  Dir: {comp_dir}")

    # Cache local
    cache = check_local_cache(comp_dir, ticker, year)
    if cache:
        print(f"  [CACHE] {Path(cache['file']).name} (SHA256:{cache['sha256'][:10]})")
        return {**result_base, 'status': 'cache_hit', 'channel': 'CACHE', 'file': cache['file']}

    if dry_run:
        print("  [DRY-RUN] Verificando canales...")

    # Canal 1: ESEF
    if 1 not in skip_canal:
        result = channel1_esef(company, year, comp_dir, dry_run)
        if result and not str(result).startswith('DRY_RUN'):
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL1_ESEF', 'file': result}

    # Canal 2: IR
    if 2 not in skip_canal:
        result = channel2_ir_crawler(company, year, comp_dir, dry_run)
        if result and not str(result).startswith('DRY_RUN'):
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL2_IR', 'file': result}

    # Canal 3: Bundesanzeiger
    if 3 not in skip_canal and PLAYWRIGHT_AVAILABLE:
        result = channel3_bundesanzeiger(company, year, comp_dir, dry_run, bafin_manual)
        if result and not str(result).startswith('DRY_RUN'):
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL3_BAFIN', 'file': result}

    # Canal 4: Web
    if 4 not in skip_canal:
        result = channel4_web_search(company, year, comp_dir, dry_run)
        if result and not str(result).startswith('DRY_RUN'):
            return {**result_base, 'status': 'downloaded', 'channel': 'CANAL4_WEB', 'file': result}

    status = 'dry_run_checked' if dry_run else 'missing'
    print(f"  [X] {status.upper()}: {ticker} {year} -- sin fuente encontrada")
    return {**result_base, 'status': status, 'channel': None}


def create_manifest(year: int, data_root: Path, results: list) -> Path:
    manifest_path = data_root / f"MANIFEST_BAFIN_{year}.json"
    entries = []
    year_dir = data_root / str(year)
    if year_dir.exists():
        for meta_file in year_dir.rglob("*.meta.json"):
            try:
                raw = json.loads(meta_file.read_text(encoding='utf-8'))
                # Soportar tanto lista como dict (legacy vs nuevo formato)
                if isinstance(raw, list):
                    entries.extend(raw)
                elif isinstance(raw, dict):
                    entries.append(raw)
            except Exception:
                pass
    existing_tickers = {e.get('ticker') for e in entries if isinstance(e, dict)}
    for r in results:
        if r.get('status') in ['missing', 'NOT_INCORPORATED_YET'] and r.get('ticker') not in existing_tickers:
            entries.append({
                'ticker': r.get('ticker'), 'company': r.get('company'), 'year': year,
                'status': r.get('status'), 'channel': None,
                'recorded_at': datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
    # Filtrar entradas no-dict por si acaso
    entries = [e for e in entries if isinstance(e, dict)]
    entries.sort(key=lambda x: x.get('ticker', ''))
    manifest_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\n[MANIFIESTO] MANIFEST_BAFIN_{year}.json -> {len(entries)} entradas")
    return manifest_path


def run_audit(data_root: Path):
    print(f"\n{'='*60}\nAUDITORIA DE DATA LAKE DE_BAFIN\n{'='*60}")
    if not data_root.exists():
        print(f"[!] Data root no existe: {data_root}")
        return
    pdfs = list(data_root.rglob("*.pdf"))
    zips = list(data_root.rglob("*.zip"))
    htmls = list(data_root.rglob("*.htm*"))
    metas = list(data_root.rglob("*.meta.json"))
    total_size = sum(f.stat().st_size for f in data_root.rglob("*") if f.is_file())
    print(f"  PDFs:         {len(pdfs):>6}\n  ZIPs (ESEF):  {len(zips):>6}\n  HTMLs:        {len(htmls):>6}")
    print(f"  Meta.jsons:   {len(metas):>6}\n  Tamanio:      {total_size/1024/1024:.1f} MB")
    print("\n  Por anio:")
    for year in range(2012, 2026):
        yd = data_root / str(year)
        if yd.exists():
            y_pdfs = list(yd.rglob("*.pdf"))
            y_zips = list(yd.rglob("*.zip"))
            y_htmls = list(yd.rglob("*.htm*"))
            total = len(y_pdfs) + len(y_zips) + len(y_htmls)
            print(f"    {year}: {total:>4} docs  (PDF={len(y_pdfs)}, ZIP={len(y_zips)}, HTML={len(y_htmls)})")
    print("\n  Manifiestos:")
    for year in range(2012, 2026):
        m = data_root / f"MANIFEST_BAFIN_{year}.json"
        if m.exists():
            try:
                ent = json.loads(m.read_text(encoding='utf-8'))
                ok = sum(1 for e in ent if e.get('sha256') or e.get('status') in ['cache_hit','downloaded'])
                miss = sum(1 for e in ent if e.get('status') == 'missing')
                spin = sum(1 for e in ent if e.get('status') == 'NOT_INCORPORATED_YET')
                print(f"    {year}: {len(ent):>4} registros  (ok={ok}, missing={miss}, spinoff={spin})")
            except Exception:
                print(f"    {year}: ERROR")


# --- CLI ---

def parse_years(years_str: str) -> list:
    years = []
    for part in years_str.split(','):
        part = part.strip()
        if '-' in part and len(part.split('-')) == 2:
            try:
                start, end = part.split('-')
                years.extend(range(int(start.strip()), int(end.strip()) + 1))
            except ValueError:
                pass
        elif part.isdigit():
            years.append(int(part))
    return sorted(set(years))


def main():
    parser = argparse.ArgumentParser(
        description=f"ARGOS MOTOR -- Descargador Institucional Alemania v{VERSION}"
    )
    parser.add_argument('--segment', type=str, default='')
    parser.add_argument('--years', type=str, default='2012-2025')
    parser.add_argument('--tickers', type=str, default='')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--bafin-manual', action='store_true')
    parser.add_argument('--skip-canal', type=str, default='')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()

    print(f"\n{'='*60}\nARGOS MOTOR -- DOWNLOADER GERMANY v{VERSION}\n{'='*60}")
    print(f"  Dry-run:      {args.dry_run}")
    print(f"  Bafin manual: {args.bafin_manual}")
    print(f"  Playwright:   {PLAYWRIGHT_AVAILABLE}")
    print(f"  httpx:        {HTTPX_AVAILABLE}")
    print(f"  bs4/lxml:     {BS4_AVAILABLE}")

    data_root = resolve_data_root()
    print(f"  Data root:    {data_root}")

    if args.audit:
        run_audit(data_root)
        return

    universe = resolve_universe()
    print(f"  Universo:     {len(universe)} empresas")

    companies = list(universe.values())

    if args.tickers:
        tickers_filter = [t.strip().upper() for t in args.tickers.split(',')]
        companies = [c for c in companies if c.get('ticker', '').upper() in tickers_filter]
        print(f"  Filtro tickers: {tickers_filter} -> {len(companies)} empresas")

    if args.segment:
        segments_filter = [s.strip().upper() for s in args.segment.split(',')]
        filtered = [c for c in companies if
                    c.get('segment', '').upper() in segments_filter or
                    any(s in [idx.upper() for idx in c.get('index_membership', [])] for s in segments_filter)]
        if filtered:
            companies = filtered
            print(f"  Filtro segmento: {segments_filter} -> {len(companies)} empresas")
        else:
            print(f"  [WARN] Segmento {segments_filter} sin matches. Procesando todo.")

    years = parse_years(args.years)
    print(f"  Anios:        {years[0]}-{years[-1]} ({len(years)} ejercicios)")
    print(f"  Combinaciones:{len(companies) * len(years):,}")

    skip_canal = [int(x.strip()) for x in args.skip_canal.split(',') if x.strip().isdigit()] if args.skip_canal else []
    if skip_canal:
        print(f"  Skip canales: {skip_canal}")

    if args.manifest_only:
        for year in years:
            create_manifest(year, data_root, [])
        print("\n[OK] Manifiestos regenerados.")
        return

    all_results = {y: [] for y in years}
    total = len(companies) * len(years)
    processed = downloaded = cached = missing = 0
    start_time = time.time()

    print(f"\n{'='*60}\nINICIO: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}\n")

    for company in companies:
        for year in years:
            processed += 1
            result = process_company_year(company, year, data_root,
                                          dry_run=args.dry_run,
                                          bafin_manual=args.bafin_manual,
                                          skip_canal=skip_canal)
            all_results[year].append(result)
            status = result.get('status', '')
            if status == 'cache_hit': cached += 1
            elif status == 'downloaded': downloaded += 1
            else: missing += 1

            if processed % 50 == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (total - processed) / rate if rate > 0 else 0
                print(f"\n[PROGRESO] {processed}/{total} ({100*processed/total:.1f}%) "
                      f"| ok={downloaded+cached} miss={missing} "
                      f"| {rate:.1f}/s ETA={eta/60:.1f}min")

    print(f"\n{'='*60}\nGENERANDO MANIFIESTOS\n{'='*60}")
    for year in years:
        create_manifest(year, data_root, all_results[year])

    elapsed = time.time() - start_time
    print(f"\n{'='*60}\nRESUMEN FINAL\n{'='*60}")
    print(f"  Total procesadas:   {processed:,}")
    print(f"  Cache hits:         {cached:,}")
    print(f"  Nuevas descargas:   {downloaded:,}")
    print(f"  Sin fuente:         {missing:,}")
    print(f"  Tasa exito:         {100*(cached+downloaded)/max(processed,1):.1f}%")
    print(f"  Tiempo total:       {elapsed/60:.1f} min")

    run_audit(data_root)
    print(f"\n[DONE] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
