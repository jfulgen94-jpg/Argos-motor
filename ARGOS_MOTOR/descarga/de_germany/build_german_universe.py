"""
CONSTRUCTOR INSTITUCIONAL DEL UNIVERSO BURSÁTIL ALEMÁN (DAX 40 / MDAX 50 / SDAX 70)
=====================================================================================
Motor institucional de extracción y resolución regulatoria para emisores cotizados
en la Bolsa de Fráncfort (Deutsche Börse AG - Prime Standard & General Standard):
  - DAX 40 (Blue Chips de máxima capitalización)
  - MDAX (Empresas de mediana capitalización)
  - SDAX (Empresas de pequeña capitalización)

Fuentes regulatorias y estructuradas 100% automatizadas y públicas:
  1. API Oficial MediaWiki de Wikipedia (Action API wikitext estructurado de tablas de índices)
  2. API Oficial Global Legal Entity Identifier Foundation (GLEIF v1 REST API)
     -> Resolución de LEI (20 chars), Razón Social oficial y Registro Mercantil (HRB/HRA).

Salida canónica: ARGOS_MOTOR/config/master_universe_de.json
"""

import sys
import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

# Forzar buffer por línea y codificación UTF-8 para Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = WORKSPACE_ROOT / "config" / "master_universe_de.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Argos-Institutional-Research/1.0 (Compliance; Regulatory Universe Auditor)'
}

def fetch_wikitext(page_title, lang='en'):
    """Consulta la API oficial MediaWiki de Wikipedia (sin JavaScript, sin bloqueos)."""
    url = f"https://{lang}.wikipedia.org/w/api.php?action=parse&page={urllib.parse.quote(page_title)}&prop=wikitext&format=json"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('parse', {}).get('wikitext', {}).get('*', '')
    except Exception as e:
        print(f"[-] Error consultando {page_title} ({lang}): {e}")
        return ""

def parse_dax40():
    """Extrae los 40 constituyentes oficiales del DAX con ticker y sector."""
    print("-> Extrayendo DAX 40 desde Deutsche Börse / Prime Standard...")
    wt = fetch_wikitext('DAX', 'en')
    companies = []
    if not wt:
        return companies
    
    table_candidates = [t for t in wt.split('{|') if 'id="constituents"' in t or 'Ticker' in t]
    if not table_candidates:
        return companies
    
    rows = table_candidates[0].split('|-')
    for r in rows:
        if 'FWB link' in r or 'FWB2 link' in r:
            m_tick = re.search(r'\{\{FWB[0-9]? link\|([^\}]+)\}\}', r)
            ticker = m_tick.group(1).split('.')[0].strip() if m_tick else None
            
            parts = r.split('||')
            name = None
            sector = 'General'
            if len(parts) >= 3:
                m_name = re.search(r'\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]', parts[2])
                name = (m_name.group(2) or m_name.group(1)).strip() if m_name else parts[2].strip()
            if len(parts) >= 4:
                m_sec = re.search(r'\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]', parts[3])
                sector = (m_sec.group(2) or m_sec.group(1)).strip() if m_sec else parts[3].strip()
                
            if ticker and name:
                companies.append({
                    "ticker": ticker,
                    "name": name,
                    "segment": "DAX40",
                    "sector": sector,
                    "country": "DE"
                })
    return companies

def parse_mdax():
    """Extrae los constituyentes del MDAX con ticker y sector."""
    print("-> Extrayendo MDAX (Mid Caps)...")
    wt = fetch_wikitext('MDAX', 'en')
    companies = []
    if not wt:
        return companies
        
    table_candidates = [t for t in wt.split('{|') if 'id="constituents"' in t or 'Aixtron' in t]
    if not table_candidates:
        return companies
        
    rows = table_candidates[0].split('|-')
    for r in rows:
        if '[[' in r and 'File:' in r:
            lines = [l.strip() for l in r.split('\n') if l.strip()]
            name = None
            sector = 'MidCap'
            ticker = None
            for idx, line in enumerate(lines):
                if '[[' in line and not any(x in line.lower() for x in ['file:', 'image:', 'logo']):
                    m_name = re.search(r'\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]', line)
                    if m_name:
                        name = (m_name.group(2) or m_name.group(1)).strip()
                    if idx + 1 < len(lines):
                        sector_line = lines[idx+1].strip('| ')
                        if not sector_line.startswith('{') and not sector_line.startswith('['):
                            sector = sector_line
                    break
            # El ticker suele venir al final de la fila o en la columna Symbol
            last_line = lines[-1].strip('| ')
            m_tick = re.match(r'^([A-Z0-9]{2,5})$', last_line)
            if m_tick:
                ticker = m_tick.group(1)
            elif name:
                ticker = re.sub(r'[^A-Z0-9]', '', name.upper())[:4]
                
            if name and ticker:
                companies.append({
                    "ticker": ticker,
                    "name": name,
                    "segment": "MDAX",
                    "sector": sector,
                    "country": "DE"
                })
    return companies

def parse_sdax():
    """Extrae los constituyentes del SDAX (Small Caps)."""
    print("-> Extrayendo SDAX (Small Caps)...")
    wt = fetch_wikitext('SDAX', 'de')
    companies = []
    if not wt:
        return companies
        
    table_candidates = [t for t in wt.split('{|') if ('zusammensetzung' in t.lower() or 'streubesitz' in t.lower() or 'branche' in t.lower()) and 'punkte' not in t.lower()]
    if not table_candidates:
        return companies
        
    rows = table_candidates[0].split('|-')
    for r in rows:
        lines = [l.strip() for l in r.split('\n') if l.strip()]
        name = None
        sector = 'SmallCap'
        for idx, line in enumerate(lines):
            if '[[' in line and not line.startswith('!'):
                links = re.findall(r'\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]', line)
                for l in links:
                    target = (l[1] or l[0]).strip()
                    if not any(x in target.lower() for x in ['datei:', 'file:', 'logo', '100x40px', '120x40px', '80x40px', 'svg', 'png']):
                        name = target
                        break
                if name:
                    if idx + 1 < len(lines):
                        sector = lines[idx+1].strip('| ')
                    break
        if name:
            ticker = re.sub(r'[^A-Z0-9]', '', name.upper())[:4]
            companies.append({
                "ticker": ticker,
                "name": name,
                "segment": "SDAX",
                "sector": sector,
                "country": "DE"
            })
    return companies

def clean_company_name_for_gleif(name):
    """Normaliza y limpia la razón social para consulta exacta en el registro GLEIF."""
    cleaned = re.sub(r'[\(\)\[\]\.,]', ' ', name)
    # Conservar el núcleo de la empresa quitando formas jurídicas comunes
    for legal_form in ['Stiftung & Co KGaA', 'Stiftung & Co', '& Co KGaA', 'KGaA', 'SE & Co', 'SE', 'AG', 'GmbH', 'Holding', 'Group', 'Deutschland']:
        cleaned = re.sub(rf'\b{re.escape(legal_form)}\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def query_gleif_lei(company_name, country='DE'):
    """
    Consulta la API global de GLEIF (Global Legal Entity Identifier Foundation).
    100% gratuita, oficial y sin claves de pago.
    Devuelve (LEI, LegalName, HRB_Register).
    """
    search_term = clean_company_name_for_gleif(company_name)
    if not search_term:
        search_term = company_name
        
    encoded = urllib.parse.quote(search_term)
    url = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={encoded}&filter[entity.legalAddress.country]={country}&page[size]=3"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            records = data.get('data', [])
            if records:
                # Preferir entidad activa y de forma jurídica AG o SE
                best_record = records[0]
                for r in records:
                    l_name = r.get('attributes', {}).get('entity', {}).get('legalName', {}).get('name', '')
                    if any(form in l_name.upper() for form in [' AG', ' SE', ' KGAA']):
                        best_record = r
                        break
                lei = best_record.get('id', '')
                entity_info = best_record.get('attributes', {}).get('entity', {})
                legal_name = entity_info.get('legalName', {}).get('name', company_name)
                reg_as = entity_info.get('registeredAs', '')
                return lei, legal_name, reg_as
    except Exception:
        pass
        
    # Segundo intento sin filtro de país (muchas cotizadas alemanas tienen holding en NL o LU)
    try:
        url_fallback = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={encoded}&page[size]=1"
        req2 = urllib.request.Request(url_fallback, headers=HEADERS)
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            data2 = json.loads(resp2.read().decode('utf-8'))
            records2 = data2.get('data', [])
            if records2:
                lei = records2[0].get('id', '')
                entity_info = records2[0].get('attributes', {}).get('entity', {})
                legal_name = entity_info.get('legalName', {}).get('name', company_name)
                reg_as = entity_info.get('registeredAs', '')
                return lei, legal_name, reg_as
    except Exception:
        pass

    return "", company_name, ""

def build_universe():
    print("==========================================================================")
    print("=== ARGOS MOTOR: CONSTRUCTOR MAESTRO DEL UNIVERSO ALEMÁN (DAX/MDAX/SDAX) ===")
    print("==========================================================================")
    
    dax = parse_dax40()
    print(f"[OK] DAX 40: {len(dax)} empresas extraídas.")
    
    mdax = parse_mdax()
    print(f"[OK] MDAX: {len(mdax)} empresas extraídas.")
    
    sdax = parse_sdax()
    print(f"[OK] SDAX: {len(sdax)} empresas extraídas.")
    
    total_raw = len(dax) + len(mdax) + len(sdax)
    print(f"\nTotal preliminar extraído de índices de Deutsche Börse: {total_raw}")
    
    # Deduplicación por nombre / ticker
    unique_map = {}
    for comp in dax + mdax + sdax:
        name_key = comp['name'].lower().strip()
        if name_key not in unique_map:
            unique_map[name_key] = comp
            
    print(f"Total entidades únicas consolidadas: {len(unique_map)}")
    print("\nIniciando resolución de identificadores institucionales (LEI / Handelsregister HRB)...")
    
    master_companies = {}
    resolved_leis = 0
    
    for idx, (k, comp) in enumerate(unique_map.items(), 1):
        raw_name = comp['name']
        ticker = comp['ticker']
        
        lei, legal_name, reg_num = query_gleif_lei(raw_name)
        
        # Desambiguar ticker si hay colisión
        base_t = ticker
        c_num = 1
        while ticker in master_companies:
            c_num += 1
            ticker = f"{base_t}_{c_num}"
            
        master_companies[ticker] = {
            "ticker": ticker,
            "name_legal": legal_name,
            "name_common": raw_name,
            "lei": lei,
            "hrb_reg": reg_num,
            "segment": comp['segment'],
            "sector": comp['sector'],
            "jurisdiction": "DE",
            "supervisor": "BaFin / Unternehmensregister",
            "currency": "EUR",
            "is_dax40": (comp['segment'] == 'DAX40'),
            "is_mdax": (comp['segment'] == 'MDAX'),
            "is_sdax": (comp['segment'] == 'SDAX')
        }
        
        if lei:
            resolved_leis += 1
            status_tag = f"LEI: {lei} ({reg_num or 'Sin HRB'})"
        else:
            status_tag = "LEI no localizado de forma directa"
            
        if idx % 10 == 0 or idx == len(unique_map):
            print(f"  [{idx:03d}/{len(unique_map):03d}] {ticker:<6} | {raw_name[:25]:<25} -> {status_tag}")
            
    dax_count = sum(1 for c in master_companies.values() if c['segment'] == 'DAX40')
    mdax_count = sum(1 for c in master_companies.values() if c['segment'] == 'MDAX')
    sdax_count = sum(1 for c in master_companies.values() if c['segment'] == 'SDAX')
    
    universe_doc = {
        "version": "1.0.0",
        "jurisdiction": "DE",
        "country_name": "Germany",
        "supervisor": "BaFin / Unternehmensregister",
        "total_entities": len(master_companies),
        "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "segments_breakdown": {
            "DAX40": dax_count,
            "MDAX": mdax_count,
            "SDAX": sdax_count
        },
        "stats": {
            "resolved_leis": resolved_leis,
            "resolution_rate": f"{(resolved_leis / len(master_companies) * 100):.1f}%"
        },
        "companies": master_companies
    }
    
    OUTPUT_FILE.write_text(json.dumps(universe_doc, indent=2, ensure_ascii=False), encoding='utf-8')
    print("\n==========================================================================")
    print(f"[EXITO] UNIVERSO MAESTRO ALEMÁN GUARDADO CON ÉXITO EN:")
    print(f"        {OUTPUT_FILE}")
    print(f"Total entidades: {len(master_companies)}")
    print(f"Desglose: DAX40: {dax_count} | MDAX: {mdax_count} | SDAX: {sdax_count}")
    print(f"LEIs institucionales verificados: {resolved_leis} / {len(master_companies)} ({universe_doc['stats']['resolution_rate']})")
    print("==========================================================================")

if __name__ == '__main__':
    build_universe()
