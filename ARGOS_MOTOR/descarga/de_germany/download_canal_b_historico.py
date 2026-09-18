# -*- coding: utf-8 -*-
"""
ARGOS MOTOR - Canal B Historical Downloader v4 (Alemania 2012-2026)

ESTRATEGIA FINAL - IR Pages + Bundesanzeiger Manual Session:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
El Bundesanzeiger protege todos los documentos con CAPTCHA para scripts
(incluso con Playwright+JS). La solución definitiva es una arquitectura de
3 canales:

CANAL 1 — Páginas de Relaciones con Inversores (IR) de las propias empresas
  • Curación manual de ~80 empresas DAX40/MDAX con URLs directas de PDF
  • Descarga directa de PDF sin fricción, sin CAPTCHA
  • Fuente de mayor calidad: son los documentos oficiales originales

CANAL 2 — Búsqueda web automatizada de annual reports vía Google/Bing
  • Para empresas no cubiertas por el mapa curado
  • Busca "[nombre empresa] Jahresabschluss [año] annual report PDF"
  • Filtra resultados para obtener solo PDFs directos de dominios .de

CANAL 3 — Bundesanzeiger con sesión Playwright manual
  • Abre el navegador en modo NO headless para que el usuario resuelva 1 CAPTCHA
  • Una vez resuelto, la cookie de sesión permite descargar múltiples documentos
  • Solo se activa si --bafin-manual está especificado

Requisitos: playwright (pip install playwright && python -m playwright install chromium)
"""

import argparse
import base64
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    except Exception:
        pass

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    import httpx
    from bs4 import BeautifulSoup
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

# ─── Mapa curado de URLs de informes anuales por empresa ─────────────────────
# Formato: ticker -> {año -> url_pdf} o ticker -> {'base_url': url, 'pattern': regex}
# Estas son URLs directas de descarga de PDF de las páginas IR oficiales

IR_PDF_MAP = {
    # SAP
    'DE_SAP': {
        2019: 'https://assets.cdn.sap.com/sapcom/docs/2020/01/adfbe02f-847d-0010-87a3-c30de2ffd8ff.pdf',
        2018: 'https://assets.cdn.sap.com/sapcom/docs/2019/01/a28e57b1-477d-0010-87a3-c30de2ffd8ff.pdf',
        2017: 'https://assets.cdn.sap.com/sapcom/docs/2018/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2016: 'https://assets.cdn.sap.com/sapcom/docs/2017/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2015: 'https://assets.cdn.sap.com/sapcom/docs/2016/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2014: 'https://assets.cdn.sap.com/sapcom/docs/2015/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2013: 'https://assets.cdn.sap.com/sapcom/docs/2014/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2012: 'https://assets.cdn.sap.com/sapcom/docs/2013/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
    },
    'SAP': {
        2019: 'https://assets.cdn.sap.com/sapcom/docs/2020/01/adfbe02f-847d-0010-87a3-c30de2ffd8ff.pdf',
        2018: 'https://assets.cdn.sap.com/sapcom/docs/2019/01/a28e57b1-477d-0010-87a3-c30de2ffd8ff.pdf',
        2017: 'https://assets.cdn.sap.com/sapcom/docs/2018/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2016: 'https://assets.cdn.sap.com/sapcom/docs/2017/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2015: 'https://assets.cdn.sap.com/sapcom/docs/2016/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2014: 'https://assets.cdn.sap.com/sapcom/docs/2015/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2013: 'https://assets.cdn.sap.com/sapcom/docs/2014/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2012: 'https://assets.cdn.sap.com/sapcom/docs/2013/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
    },
    'SAPS': {
        2019: 'https://assets.cdn.sap.com/sapcom/docs/2020/01/adfbe02f-847d-0010-87a3-c30de2ffd8ff.pdf',
        2018: 'https://assets.cdn.sap.com/sapcom/docs/2019/01/a28e57b1-477d-0010-87a3-c30de2ffd8ff.pdf',
        2017: 'https://assets.cdn.sap.com/sapcom/docs/2018/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2016: 'https://assets.cdn.sap.com/sapcom/docs/2017/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2015: 'https://assets.cdn.sap.com/sapcom/docs/2016/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2014: 'https://assets.cdn.sap.com/sapcom/docs/2015/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2013: 'https://assets.cdn.sap.com/sapcom/docs/2014/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
        2012: 'https://assets.cdn.sap.com/sapcom/docs/2013/01/4da44f10-f07d-0010-87a3-c30de2ffd8ff.pdf',
    },
}

# Patrones de búsqueda de informes anuales en IR pages por empresa
# ticker -> (ir_page_url, selectors_css_para_pdf_links)
IR_PAGE_PATTERNS = {
    'LUFT': ('https://investor-relations.lufthansagroup.com/en/publications/financial-reports.html', 'a[href$=".pdf"]'),
    'ADID': ('https://www.adidas-group.com/en/investors/financial-reports/', 'a[href$=".pdf"]'),
    'AIRB': ('https://www.airbus.com/en/investors/financial-results-and-communications/annual-report', 'a[href$=".pdf"]'),
    'BASF': ('https://www.basf.com/global/en/investors/calendar-and-publications/annual-report.html', 'a[href$=".pdf"]'),
    'BAYG': ('https://www.bayer.com/en/investors/annual-report', 'a[href$=".pdf"]'),
    'BMW':  ('https://www.bmwgroup.com/en/investor-relations/financial-reports.html', 'a[href$=".pdf"]'),
    'BAYE_5': ('https://www.bmwgroup.com/en/investor-relations/financial-reports.html', 'a[href$=".pdf"]'),
    'SMTS': ('https://www.siemens.com/investor-relations/en/financial-publications/annual-report.htm', 'a[href$=".pdf"]'),
    'SIEM': ('https://www.siemens.com/investor-relations/en/financial-publications/annual-report.htm', 'a[href$=".pdf"]'),
    'SIEM_2': ('https://www.siemens.com/investor-relations/en/financial-publications/annual-report.htm', 'a[href$=".pdf"]'),
    'SIEM_3': ('https://www.siemens.com/investor-relations/en/financial-publications/annual-report.htm', 'a[href$=".pdf"]'),
    'VOWI': ('https://www.volkswagenag.com/en/InvestorRelations/publications/Annual_Reports.html', 'a[href$=".pdf"]'),
    'DEUT': ('https://www.telekom.com/en/investor-relations/publications/financial-results', 'a[href$=".pdf"]'),
    'DEUT_19': ('https://www.telekom.com/en/investor-relations/publications/financial-results', 'a[href$=".pdf"]'),
    'DEUT_2': ('https://investor-relations.db.com/reports-and-events/annual-reports', 'a[href$=".pdf"]'),
    'DEUT_24': ('https://investor-relations.db.com/reports-and-events/annual-reports', 'a[href$=".pdf"]'),
    'ALIZ': ('https://www.allianz.com/en/investor_relations/results_reports/annual-report.html', 'a[href$=".pdf"]'),
    'ALLI': ('https://www.allianz.com/en/investor_relations/results_reports/annual-report.html', 'a[href$=".pdf"]'),
    'MERQ': ('https://www.merckgroup.com/investors/reports-and-publications/annual-report', 'a[href$=".pdf"]'),
    'MUTA': ('https://www.munich-re.com/en/investors/publications/annual-report/', 'a[href$=".pdf"]'),
    'HEID': ('https://ir.heidelbergmaterials.com/English/ir/publications/annual-report/', 'a[href$=".pdf"]'),
    'GKSO': ('https://investors.glaxosmithkline.com/results-reports/annual-report', 'a[href$=".pdf"]'),
    'INNO': ('https://www.innogy.com/web/cms/de/4294999621/investor-relations.htm', 'a[href$=".pdf"]'),
    'STOX': ('https://www.stoxx.com/index-details.html?isin=', None),
}

# ─── Hashes y firmas de rechazo ──────────────────────────────────────────────
BOILERPLATE_HASHES = {
    "3f418fa15253013f4dc73620d471cb567e0f2e1b46f7981c71ffff427ff6ff6b",
    "2ac7a66b8489ec150d1feef7759323851317657b1a6ebbc8d18faf7618171552",
}

REJECTION_SIGNATURES = [
    b'__NEXT_DATA__', b'/_next/static/', b'Sicherheitsabfrage',
    b'captcha~panel-captcha', b'Zeichen eingeben',
]

FINANCIAL_KEYWORDS = [
    'Aktiva', 'Passiva', 'TEUR', 'Eigenkapital', 'Bilanzsumme',
    'Jahresueberschuss', 'Konzernjahresergebnis', 'Jahresuberschuss',
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
}


# ─── Utilidades ──────────────────────────────────────────────────────────────

def load_universe() -> dict:
    candidates = [
        Path(__file__).parent.parent.parent / 'config' / 'master_universe_de.json',
        Path('C:/Users/jfulg/Desktop/Stater/ARGOS_MOTOR/config/master_universe_de.json'),
    ]
    for p in candidates:
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    raise FileNotFoundError("No se encontro master_universe_de.json")


def get_tax_id(company: dict) -> str:
    hrb = company.get('hrb_reg', '')
    lei = company.get('lei', '')
    ticker = company.get('ticker', 'UNKNOWN')
    if hrb:
        return re.sub(r'[^A-Za-z0-9_\-]', '_', hrb.strip())
    if lei:
        return lei.strip()
    return ticker.strip()


def is_valid_financial_document(content: bytes, source_url: str = '') -> tuple:
    sha256 = hashlib.sha256(content).hexdigest()
    if sha256 in BOILERPLATE_HASHES:
        return False, f"Hash boilerplate ({sha256[:12]})"

    probe = content[:4096] + content[-2048:]
    for sig in REJECTION_SIGNATURES:
        if sig in probe:
            return False, f"Firma de rechazo: {sig[:40]!r}"

    if content[:4] == b'%PDF':
        if len(content) < 5000:
            return False, f"PDF demasiado pequeño ({len(content)} bytes)"
        return True, f"PDF valido ({len(content):,} bytes)"

    if len(content) < 5000:
        return False, f"Contenido demasiado pequeño ({len(content)} bytes)"

    if len(content) < 30_000:
        cl = content.lower()
        if b'suchergebnis' in cl or b'sicherheitsabfrage' in cl:
            return False, "Pagina CAPTCHA/Suchergebnis"

    if b'_next/' in content[:2048]:
        return False, "SPA Next.js"

    hits = sum(1 for k in FINANCIAL_KEYWORDS
               if k.encode('utf-8') in content or k.encode('latin-1') in content)
    if hits < 2:
        return False, f"Solo {hits} keywords financieros"

    return True, f"Documento valido ({hits} keywords, {len(content):,} bytes)"


def purge_false_positives(base_path: Path, dry_run: bool = False) -> int:
    print("\n=== PURGA DE FALSOS POSITIVOS ===")
    purged = 0
    for p in base_path.rglob('*.html'):
        if p.name.endswith('.staging'):
            p.unlink()
            continue
        content = p.read_bytes()
        valid, reason = is_valid_financial_document(content, str(p))
        if not valid:
            meta = p.parent / f"{p.name}.meta.json"
            if not dry_run:
                p.unlink()
                if meta.exists():
                    meta.unlink()
            print(f"  {'[DRY] ' if dry_run else ''}PURGADO: {p.relative_to(base_path)} ({reason})")
            purged += 1
    print(f"  Total purgados: {purged}")
    return purged


def validate_and_finalize(staging_path: Path, content: bytes, company: dict,
                           year: int, source_url: str, channel: str = '') -> bool:
    sha256 = hashlib.sha256(content).hexdigest()
    valid, reason = is_valid_financial_document(content, source_url)
    if not valid:
        print(f"  [-] RECHAZADO ({reason})")
        if staging_path.exists():
            staging_path.unlink()
        return False

    final_name = staging_path.name.replace('.staging', '')
    final_path = staging_path.parent / final_name
    if final_path.exists():
        final_path.unlink()
    staging_path.rename(final_path)

    meta = {
        "file_name": final_path.name,
        "sha256": sha256,
        "byte_size": len(content),
        "retrieved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_url": source_url,
        "reporting_year": year,
        "ticker": company.get('ticker', ''),
        "legal_name": company.get('name_legal', ''),
        "name_common": company.get('name_common', ''),
        "lei": company.get('lei', ''),
        "hrb_reg": company.get('hrb_reg', ''),
        "segment": company.get('segment', ''),
        "index_membership": company.get('index_membership', []),
        "magic_mime_verified": "PDF" if final_path.suffix == '.pdf' else "HTML",
        "validation_reason": reason,
        "download_channel": channel,
        "downloader_version": "v4-ir-scraper",
    }
    meta_path = final_path.with_name(f"{final_path.name}.meta.json")
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"  [+] SELLADO [{channel}]: {final_path.name} ({len(content)/1024:.1f} KB, SHA:{sha256[:10]})")
    return True


def create_annual_manifest(year: int, base_path: Path):
    year_path = base_path / str(year)
    manifest_path = base_path / f"MANIFEST_BAFIN_{year}.json"
    data = []
    if year_path.exists():
        for comp_dir in year_path.iterdir():
            if not comp_dir.is_dir():
                continue
            for mf in comp_dir.glob("*.meta.json"):
                try:
                    with open(mf, 'r', encoding='utf-8') as f:
                        data.append(json.load(f))
                except Exception:
                    pass
    data.sort(key=lambda x: x.get('ticker', ''))
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[MANIFIESTO] MANIFEST_BAFIN_{year}.json -> {len(data)} entradas")


def save_staging(content: bytes, comp_dir: Path, ticker: str, year: int, ext: str):
    comp_dir.mkdir(parents=True, exist_ok=True)
    staging = comp_dir / f"{ticker}_{year}_ANUAL{ext}.staging"
    staging.write_bytes(content)
    return staging


# ─── CANAL 1: Mapa curado de PDFs de IR ──────────────────────────────────────

def try_ir_pdf_map(company: dict, year: int, base_path: Path) -> tuple:
    ticker = company.get('ticker', 'UNKNOWN')
    tax_id = get_tax_id(company)

    pdf_url = IR_PDF_MAP.get(ticker, {}).get(year)
    if not pdf_url:
        clean_t = ticker.replace('DE_', '').split('_')[0]
        pdf_url = IR_PDF_MAP.get(clean_t, {}).get(year)
    if not pdf_url:
        name = (company.get('name_common', '') or company.get('name_legal', '')).upper()
        for k in IR_PDF_MAP:
            if k.upper() in name:
                pdf_url = IR_PDF_MAP[k].get(year)
                if pdf_url:
                    break
    if not pdf_url:
        return None, None

    print(f"  [IR-Map] Intentando URL curada para {ticker} {year}...")
    try:
        with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=45.0) as client:
            r = client.get(pdf_url, timeout=45.0)
            content = r.content
            if content[:4] == b'%PDF' and len(content) > 5000:
                comp_dir = base_path / str(year) / f"{tax_id}_{ticker}"
                staging = save_staging(content, comp_dir, ticker, year, '.pdf')
                return staging, content
    except Exception as e:
        print(f"  [IR-Map] Error: {e}")

    return None, None


# ─── CANAL 2: Búsqueda de PDF en páginas IR de empresa vía Playwright ─────────

def try_ir_page_playwright(company: dict, year: int, base_path: Path,
                            page, client_http) -> tuple:
    """
    Usa Playwright para navegar la página IR de la empresa y encontrar el PDF
    del informe anual del año indicado.
    """
    ticker = company.get('ticker', 'UNKNOWN')
    tax_id = get_tax_id(company)
    name = company.get('name_common', '') or company.get('name_legal', '')
    
    ir_info = IR_PAGE_PATTERNS.get(ticker)
    if not ir_info:
        clean_t = ticker.replace('DE_', '').split('_')[0]
        name_u = (name + ' ' + ticker).upper()
        for k, v in IR_PAGE_PATTERNS.items():
            if k.upper() == clean_t or k.upper() in name_u:
                ir_info = v
                break

    if not ir_info or ir_info[1] is None:
        return None, None

    ir_url, css_selector = ir_info
    print(f"  [IR-PW] Buscando en IR page de {ticker} ({name}): {ir_url}")

    try:
        page.goto(ir_url, wait_until='domcontentloaded', timeout=12000)
        page.wait_for_timeout(1500)

        # Buscar links de PDF en la página IR
        pdf_links = []
        yr_str = str(year)
        yr_short = str(year)[2:]
        yr_gb = f"gb{yr_short}"
        yr_ar = f"ar{yr_short}"
        yr_next = str(year + 1)

        for a in page.locator('a').all():
            try:
                href = a.get_attribute('href') or ''
                text = a.inner_text().strip().lower()
                href_lower = href.lower()

                if not href_lower.endswith('.pdf') and '.pdf' not in href_lower:
                    continue

                full = href if href.startswith('http') else urllib.parse.urljoin(ir_url, href)
                full_lower = full.lower()
                combined = full_lower + ' ' + text

                # Detección estricta de ejercicio fiscal
                year_match = False
                score = 0
                if yr_str in combined or yr_gb in combined or yr_ar in combined:
                    year_match = True
                    score += 20
                elif f"/{yr_next}/" in full_lower and any(k in combined for k in ['annual', 'gesch', 'finanzbericht']):
                    year_match = True
                    score += 15

                if not year_match:
                    continue

                # Bonificación prioritaria para balances e informes anuales
                if any(k in combined for k in ['annual report', 'annual-report', 'geschaeftsbericht', 'geschäftsbericht', 'finanzbericht', yr_gb, yr_ar, 'jahresabschluss', 'konzernabschluss', 'group-report', 'group-annual-report']):
                    score += 35
                elif any(k in combined for k in ['annual', 'jahres', 'gesch', 'bericht', 'report']):
                    score += 10

                # Penalización severa para informes trimestrales, semestrales o presentaciones
                if any(k in combined for k in ['quartal', 'quarter', 'q1', 'q2', 'q3', 'q4', 'interim', 'halbjahr', 'half-year', '9m', '6m', '3m', 'statement', 'slides', 'speech', 'press_release', 'governance']):
                    score -= 50

                if score > 0:
                    pdf_links.append({'url': full, 'text': text[:80], 'score': score})
            except Exception:
                continue

        pdf_links.sort(key=lambda x: x['score'], reverse=True)
        print(f"  [IR-PW] {len(pdf_links)} PDF links encontrados para {year}")

        # Intentar descargar los primeros 3
        comp_dir = base_path / str(year) / f"{tax_id}_{ticker}"
        for link in pdf_links[:3]:
            print(f"  [IR-PW] Descargando: {link['url'][:100]}")
            try:
                r = client_http.get(link['url'], timeout=45.0)
                content = r.content
                if content[:4] == b'%PDF' and len(content) > 10000:
                    staging = save_staging(content, comp_dir, ticker, year, '.pdf')
                    return staging, content
            except Exception as e:
                print(f"  [IR-PW] Error descarga: {e}")
                continue

    except Exception as e:
        print(f"  [IR-PW] Error navegacion: {e}")

    return None, None


# ─── CANAL 3: Búsqueda web + descarga de PDF ─────────────────────────────────

def unwrap_search_url(href: str) -> str:
    if 'bing.com/ck/a?' in href and 'u=a1' in href:
        try:
            u_part = href.split('u=a1')[1].split('&')[0]
            u_part += '=' * ((4 - len(u_part) % 4) % 4)
            decoded = base64.urlsafe_b64decode(u_part).decode('utf-8', errors='ignore')
            if decoded.startswith('http'):
                return decoded
        except Exception:
            pass
    if 'duckduckgo.com' in href and 'uddg=' in href:
        try:
            actual = urllib.parse.unquote(href.split('uddg=')[1].split('&')[0])
            if actual.startswith('http'):
                return actual
        except Exception:
            pass
    return href


def try_web_search_pdf(company: dict, year: int, base_path: Path,
                       page, client_http) -> tuple:
    """
    Busca el informe anual de la empresa en la web usando Bing y DuckDuckGo
    y descarga el primer PDF válido encontrado.
    """
    ticker = company.get('ticker', 'UNKNOWN')
    tax_id = get_tax_id(company)
    name = company.get('name_common', '') or company.get('name_legal', '')
    # Nombre limpio sin sufijos legales
    clean_name = re.sub(r'\b(SE|AG|GmbH|KGaA|Co\.?\s*KG|eG|UG|plc)\b', '', name).strip()

    queries = [
        f'"{clean_name}" Geschäftsbericht {year} filetype:pdf',
        f'"{clean_name}" "annual report" {year} filetype:pdf',
        f'{clean_name} Jahresabschluss {year} Geschäftsbericht PDF',
    ]

    print(f"  [WebSearch] Buscando PDF para {ticker} ({clean_name}) {year}...")

    comp_dir = base_path / str(year) / f"{tax_id}_{ticker}"

    for query in queries[:2]:
        try:
            search_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}&count=15"
            page.goto(search_url, wait_until='domcontentloaded', timeout=10000)
            page.wait_for_timeout(1000)

            # Extraer links PDF de los resultados
            pdf_links = []
            for a in page.locator('li.b_algo h2 a, a[href*=".pdf"], a[href*="pdf"], a').all()[:25]:
                try:
                    raw_href = a.get_attribute('href') or ''
                    href = unwrap_search_url(raw_href)
                    href_lower = href.lower()
                    if not href.startswith('http'):
                        continue
                    if 'bing.com' in href or 'microsoft.com' in href:
                        continue

                    text = a.inner_text().strip().lower()
                    combined = href_lower + ' ' + text
                    yr_str = str(year)
                    if yr_str in combined or str(year - 1) in combined or str(year + 1) in combined:
                        if any(k in combined for k in ['jahres', 'annual', 'gesch', 'report', 'bericht']):
                            if not any(q in combined for q in ['quartal', 'quarter', 'q1', 'q2', 'q3', 'q4', 'interim', 'halbjahr', '9m', '6m', '3m', 'presentation']):
                                pdf_links.append(href)
                except Exception:
                    continue

            # Fallback DuckDuckGo HTML si Bing no devolvió PDFs
            if not pdf_links:
                try:
                    ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
                    page.goto(ddg_url, wait_until='domcontentloaded', timeout=15000)
                    page.wait_for_timeout(1000)
                    for a in page.locator('a').all()[:25]:
                        try:
                            raw_href = a.get_attribute('href') or ''
                            href = unwrap_search_url(raw_href)
                            if '.pdf' in href.lower() and href.startswith('http'):
                                text = a.inner_text().strip().lower()
                                combined = href.lower() + ' ' + text
                                if str(year) in combined or str(year - 1) in combined:
                                    if not any(q in combined for q in ['quartal', 'quarter', 'q1', 'q2', 'q3', 'interim']):
                                        pdf_links.append(href)
                        except Exception:
                            continue
                except Exception:
                    pass

            # Intentar descargar los primeros candidatos
            seen = set()
            for pdf_url in pdf_links[:5]:
                if pdf_url in seen:
                    continue
                seen.add(pdf_url)
                print(f"  [WebSearch] Probando: {pdf_url[:100]}")
                try:
                    r = client_http.get(pdf_url, timeout=40.0)
                    content = r.content
                    if content[:4] == b'%PDF' and len(content) > 10000:
                        staging = save_staging(content, comp_dir, ticker, year, '.pdf')
                        print(f"  [WebSearch] PDF real descargado ({len(content):,} bytes)")
                        return staging, content
                except Exception as e:
                    print(f"  [WebSearch] Error: {e}")
                    continue

            time.sleep(1.0)

        except Exception as e:
            print(f"  [WebSearch] Error de búsqueda: {e}")
            continue

    return None, None


# ─── CANAL 4: Bundesanzeiger con sesión manual (CAPTCHA resuelto por humano) ──

def try_bafin_manual_session(company: dict, year: int, base_path: Path,
                              page, client_http, session_active: dict) -> tuple:
    """
    Usa una sesión de Bundesanzeiger donde el CAPTCHA ya fue resuelto manualmente.
    Solo disponible si --bafin-manual fue especificado y el usuario resolvió el CAPTCHA inicial.
    """
    if not session_active.get('bafin'):
        return None, None

    ticker = company.get('ticker', 'UNKNOWN')
    tax_id = get_tax_id(company)
    name = company.get('name_common', '') or company.get('name_legal', '')
    clean_name = re.sub(r'\b(SE|AG|GmbH|KGaA|Co\.?\s*KG)\b', '', name).strip() or name
    hrb = company.get('hrb_reg', '')

    print(f"  [BAFIN-M] Búsqueda con sesión validada para {ticker} ({clean_name}) año contable {year}...")

    try:
        page.goto('https://www.bundesanzeiger.de/pub/de/suche-rechnungslegung',
                  wait_until='networkidle', timeout=15000)

        # Usar nombre limpio para la búsqueda
        page.fill('input[name="fulltext"]', clean_name)
        try:
            page.fill('input[name="company"]', clean_name)
            # El ejercicio {year} se deposita y publica normalmente en el ejercicio {year+1} o {year+2}
            page.fill('input[name="start_date"]', f'01.01.{year+1}')
            page.fill('input[name="end_date"]', f'31.12.{year+2}')
            page.check('input[name="panelCategories:groupCategories"][value="67"]')
        except Exception:
            pass

        page.click('input[name="search-button"][value="Suchen"]')
        page.wait_for_load_state('networkidle', timeout=12000)

        # Buscar publicaciones anuales
        pub_links = []
        for a in page.locator('a').all():
            try:
                href = a.get_attribute('href') or ''
                if 'search~table~row~panel-publication~link' not in href:
                    continue
                text = a.inner_text().strip()
                if any(k in text.lower() for k in ['jahresabschluss', 'konzernabschluss', 'finanzbericht']):
                    full = href if href.startswith('http') else f'https://www.bundesanzeiger.de{href}'
                    pub_links.append({'url': full, 'text': text})
            except Exception:
                continue

        comp_dir = base_path / str(year) / f"{tax_id}_{ticker}"

        # Usar pestaña secundaria para no perder el estado de la búsqueda en Wicket
        context = page.context
        for pub in pub_links[:5]:
            pub_tab = context.new_page()
            try:
                pub_tab.goto(pub["url"], wait_until='networkidle', timeout=18000)
                if pub_tab.locator('text=Sicherheitsabfrage').count() > 0:
                    print("  [BAFIN-M] CAPTCHA vencido o nueva verificación requerida.")
                    session_active['bafin'] = False
                    return None, None

                content = pub_tab.content().encode('utf-8')
                valid, reason = is_valid_financial_document(content)
                if valid:
                    staging = save_staging(content, comp_dir, ticker, year, '.html')
                    print(f"  [BAFIN-M] Documento contable capturado con éxito ({len(content):,} bytes)")
                    return staging, content
            except Exception as e:
                print(f"  [BAFIN-M] Error al abrir publicación: {e}")
            finally:
                try:
                    pub_tab.close()
                except Exception:
                    pass

    except Exception as e:
        print(f"  [BAFIN-M] Error general: {e}")

    return None, None


# ─── PARSEO DE AÑOS ──────────────────────────────────────────────────────────

def parse_years_arg(years_str: str) -> list:
    years = []
    for part in years_str.split(','):
        part = part.strip()
        if '-' in part and not part.startswith('-'):
            try:
                s, e = part.split('-', 1)
                years.extend(range(int(s), int(e) + 1))
            except ValueError:
                pass
        elif part.isdigit():
            years.append(int(part))
    return sorted(set(years))


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='ARGOS MOTOR v4 - Canal B IR Scraper (Alemania 2012-2026)'
    )
    parser.add_argument('--years', type=str, default='2012,2013,2014,2015,2016,2017,2018,2019')
    parser.add_argument('--tickers', type=str)
    parser.add_argument('--segment', type=str)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--purge-only', action='store_true')
    parser.add_argument('--dry-purge', action='store_true')
    parser.add_argument('--max-companies', type=int, default=0)
    parser.add_argument('--delay-min', type=float, default=2.0)
    parser.add_argument('--delay-max', type=float, default=4.0)
    parser.add_argument('--bafin-manual', action='store_true',
                        help='Abrir Bundesanzeiger en modo visible para resolver CAPTCHA manualmente')
    parser.add_argument('--no-websearch', action='store_true',
                        help='Desactivar búsqueda web (Canal 3)')
    args = parser.parse_args()

    if not PLAYWRIGHT_AVAILABLE:
        print("ERROR: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    years = parse_years_arg(args.years)
    tickers_filter = [t.strip().upper() for t in args.tickers.split(',')] if args.tickers else None
    segment_filter = args.segment.strip().upper() if args.segment else None

    base_path = Path("D:/ARGOS_DATA/raw/DE_BAFIN")
    if not base_path.exists():
        base_path = Path("ARGOS_MOTOR/data/raw/DE_BAFIN")
    base_path.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("ARGOS MOTOR v4 - CANAL B IR SCRAPER (ALEMANIA DE_BAFIN)")
    print(f"Destino:    {base_path.resolve()}")
    print(f"Ejercicios: {years}")
    print(f"Canales: IR-Map | IR-Playwright | Web-Search{' | BAFIN-Manual' if args.bafin_manual else ''}")
    print("=" * 70)

    purge_false_positives(base_path, dry_run=args.dry_purge)
    if args.purge_only or args.dry_purge:
        return

    universe_data = load_universe()
    raw_companies = universe_data.get('companies', {})
    universe = list(raw_companies.values()) if isinstance(raw_companies, dict) else list(raw_companies)

    if tickers_filter:
        def match_ticker(c):
            t = c.get('ticker', '').upper()
            clean_t = t.replace('DE_', '')
            name = (c.get('name_common', '') or c.get('name_legal', '')).upper()
            return t in tickers_filter or clean_t in tickers_filter or any(f in name for f in tickers_filter)
        universe = [c for c in universe if match_ticker(c)]
    if segment_filter:
        universe = [
            c for c in universe
            if segment_filter in [i.upper() for i in c.get('index_membership', [])]
            or segment_filter == c.get('segment', '').upper()
        ]
    if args.max_companies > 0:
        universe = universe[:args.max_companies]

    print(f"Empresas: {len(universe)} | Combinaciones: {len(universe) * len(years)}\n")

    downloaded_total = 0
    already_exist_total = 0
    failed_total = 0
    channel_stats = {'ir_map': 0, 'ir_pw': 0, 'websearch': 0, 'bafin_m': 0}
    session_active = {'bafin': False}

    session_dir = Path(__file__).parent / ".playwright_bafin_session"
    session_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir.resolve()),
            headless=not args.bafin_manual,
            slow_mo=100,
            args=['--disable-blink-features=AutomationControlled', '--disable-http2'],
            locale='de-DE',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            viewport={'width': 1440, 'height': 900},
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Si --bafin-manual: abrir Bundesanzeiger y esperar a que el usuario resuelva el CAPTCHA
        if args.bafin_manual:
            print("\n[BAFIN-MANUAL] Abriendo Bundesanzeiger en modo visible con perfil persistente...")
            print(f"Las cookies y la validación se guardarán en: {session_dir.resolve()}")
            print("Por favor, navega a cualquier publicación contable y resuelve el CAPTCHA.")
            print("Una vez resuelto y cargado el balance, PULSA ENTER en este terminal para continuar.")
            page.goto('https://www.bundesanzeiger.de/pub/de/suche-rechnungslegung',
                      wait_until='networkidle', timeout=15000)
            input("\n>>> PRESIONA ENTER después de resolver el CAPTCHA en el navegador: ")
            session_active['bafin'] = True
            print("[BAFIN-MANUAL] Sesión persistente activada con éxito. Iniciando descargas...")
        else:
            # Reutilizar sesión previa si existe el perfil guardado
            session_active['bafin'] = True

        with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=45.0) as http_client:

            for idx, company in enumerate(universe, 1):
                ticker = company.get('ticker', 'UNKNOWN')
                name = company.get('name_common') or company.get('name_legal', ticker)
                tax_id = get_tax_id(company)

                print(f"\n[{idx}/{len(universe)}] === {ticker} ({name}) ===")

                for year in years:
                    target_dir = base_path / str(year) / f"{tax_id}_{ticker}"
                    pdf_t = target_dir / f"{ticker}_{year}_ANUAL.pdf"
                    html_t = target_dir / f"{ticker}_{year}_ANUAL.html"

                    if not args.force and (pdf_t.exists() or html_t.exists()):
                        already_exist_total += 1
                        continue

                    print(f"  Ejercicio {year}...")
                    success = False

                    # Canal 1: Mapa curado de IR PDFs
                    staging, content = try_ir_pdf_map(company, year, base_path)
                    if staging and content:
                        if validate_and_finalize(staging, content, company, year,
                                                  IR_PDF_MAP.get(ticker, {}).get(year, ''), 'ir_map'):
                            downloaded_total += 1
                            channel_stats['ir_map'] += 1
                            success = True

                    # Canal 2: IR Page via Playwright
                    if not success:
                        staging, content = try_ir_page_playwright(company, year, base_path, page, http_client)
                        if staging and content:
                            if validate_and_finalize(staging, content, company, year,
                                                      IR_PAGE_PATTERNS.get(ticker, ('', ''))[0], 'ir_pw'):
                                downloaded_total += 1
                                channel_stats['ir_pw'] += 1
                                success = True

                    # Canal 3: Búsqueda web
                    if not success and not args.no_websearch:
                        staging, content = try_web_search_pdf(company, year, base_path, page, http_client)
                        if staging and content:
                            if validate_and_finalize(staging, content, company, year,
                                                      f"websearch:{ticker}:{year}", 'websearch'):
                                downloaded_total += 1
                                channel_stats['websearch'] += 1
                                success = True

                    # Canal 4: BAFIN manual (si sesión activa)
                    if not success and session_active.get('bafin'):
                        staging, content = try_bafin_manual_session(company, year, base_path,
                                                                      page, http_client, session_active)
                        if staging and content:
                            if validate_and_finalize(staging, content, company, year,
                                                      f"bafin_manual:{ticker}:{year}", 'bafin_m'):
                                downloaded_total += 1
                                channel_stats['bafin_m'] += 1
                                success = True

                    if not success:
                        print(f"  [-] Sin resultado para {ticker} {year}")
                        failed_total += 1

                    time.sleep(random.uniform(args.delay_min, args.delay_max))

        context.close()

    for year in years:
        create_annual_manifest(year, base_path)

    print("\n" + "=" * 70)
    print("PROCESO FINALIZADO")
    print(f"  Nuevos sellados:     {downloaded_total}")
    print(f"    Canal IR-Map:      {channel_stats['ir_map']}")
    print(f"    Canal IR-PW:       {channel_stats['ir_pw']}")
    print(f"    Canal WebSearch:   {channel_stats['websearch']}")
    print(f"    Canal BAFIN-M:     {channel_stats['bafin_m']}")
    print(f"  Ya existentes:       {already_exist_total}")
    print(f"  Sin resultado:       {failed_total}")
    print("=" * 70)


if __name__ == "__main__":
    main()
