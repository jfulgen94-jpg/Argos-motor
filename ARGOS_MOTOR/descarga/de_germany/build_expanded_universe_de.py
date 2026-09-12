import sys
import json
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path


# Configurar stdout en UTF-8 sin bloqueo de buffer
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass


OUTPUT_FILE = Path("ARGOS_MOTOR/config/master_universe_de.json")
AUDIT_FILE = Path("ARGOS_MOTOR/audits/AUDIT_UNIVERSE_DE_EXPANDIDO.md")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)


HEADERS = {
    'User-Agent': 'Argos-Institutional-Quantitative-Auditor/2.0 (Compliance; Regulatory Engine; dev@stater.es)',
    'Accept': 'application/json'
}


def fetch_sparql_universe():
    print("-> [1/4] Consultando Wikidata SPARQL Endpoint para el mercado XETRA / FWB...")
    query = """
    SELECT DISTINCT ?item ?itemLabel ?ticker ?isin ?lei ?wkn WHERE {
      { ?item wdt:P414 wd:Q151139. } UNION { ?item wdt:P414 wd:Q152953. }
      OPTIONAL { ?item wdt:P249 ?ticker. }
      OPTIONAL { ?item wdt:P946 ?isin. }
      OPTIONAL { ?item wdt:P1278 ?lei. }
      OPTIONAL { ?item wdt:P4345 ?wkn. }
      ?item rdfs:label ?itemLabel.
      FILTER(LANG(?itemLabel) = "de" || LANG(?itemLabel) = "en")
    }
    """
    url = f"https://query.wikidata.org/sparql?query={urllib.parse.quote(query)}&format=json"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            bindings = data.get('results', {}).get('bindings', [])
            print(f"   [OK] Entidades recibidas desde Financial Graph: {len(bindings)}")
            return bindings
    except Exception as e:
        print(f"   [-] Error en SPARQL query: {e}")
        return []


def fetch_mediawiki_indices():
    print("-> [2/4] Consultando composición oficial de DAX, MDAX, SDAX, TecDAX y Scale...")
    indices = {
        'DAX40': 'https://en.wikipedia.org/w/api.php?action=parse&page=DAX&prop=wikitext&format=json',
        'MDAX': 'https://en.wikipedia.org/w/api.php?action=parse&page=MDAX&prop=wikitext&format=json',
        'SDAX': 'https://de.wikipedia.org/w/api.php?action=parse&page=SDAX&prop=wikitext&format=json',
        'TECDAX': 'https://en.wikipedia.org/w/api.php?action=parse&page=TecDAX&prop=wikitext&format=json',
        'SCALE': 'https://de.wikipedia.org/w/api.php?action=parse&page=Scale_(B%C3%B6rsensegment)&prop=wikitext&format=json'
    }
    membership = {}
    for idx_name, url in indices.items():
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                wt = data.get('parse', {}).get('wikitext', {}).get('*', '')
                # Buscar enlaces de empresas [[Nombre|...]]
                links = re.findall(r'\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]', wt)
                for target, text in links:
                    name = (text or target).strip()
                    if not any(x in name.lower() for x in ['datei:', 'file:', 'kategorie:', 'category:', 'logo', 'px']):
                        k = name.lower()
                        if k not in membership:
                            membership[k] = []
                        if idx_name not in membership[k]:
                            membership[k].append(idx_name)
        except Exception as e:
            print(f"   [-] Aviso consultando {idx_name}: {e}")
    return membership


import asyncio
import httpx

async def resolve_gleif_legal(client, name, isin="", country="DE"):
    if isin and isin.startswith("DE"):
        url_isin = f"https://api.gleif.org/api/v1/lei-records?filter[isin]={isin}&page[size]=1"
        try:
            resp = await client.get(url_isin, timeout=15)
            d = resp.json()
            items = d.get('data', [])
            if items:
                lei = items[0].get('id', '')
                attrs = items[0].get('attributes', {}).get('entity', {})
                legal_name = attrs.get('legalName', {}).get('name', name)
                reg_as = attrs.get('registeredAs', '')
                return lei, legal_name, reg_as
        except Exception:
            pass


    # Búsqueda limpia por nombre
    cleaned = re.sub(r'[\(\)\[\]\.,]', ' ', name)
    for term in ['Stiftung & Co KGaA', 'Stiftung & Co', '& Co KGaA', 'KGaA', 'SE & Co', 'SE', 'AG', 'GmbH']:
        cleaned = re.sub(rf'\b{re.escape(term)}\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned: cleaned = name


    url_name = f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={urllib.parse.quote(cleaned)}&filter[entity.legalAddress.country]={country}&page[size]=3"
    try:
        resp = await client.get(url_name, timeout=15)
        d = resp.json()
        items = d.get('data', [])
        if items:
            best = items[0]
            for it in items:
                l_name = it.get('attributes', {}).get('entity', {}).get('legalName', {}).get('name', '')
                if any(f in l_name.upper() for f in [' AG', ' SE', ' KGAA']):
                    best = it
                    break
            lei = best.get('id', '')
            attrs = best.get('attributes', {}).get('entity', {})
            legal_name = attrs.get('legalName', {}).get('name', name)
            reg_as = attrs.get('registeredAs', '')
            return lei, legal_name, reg_as
    except Exception:
        pass


    return "", name, ""


async def main():
    bindings = fetch_sparql_universe()
    idx_memberships = fetch_mediawiki_indices()


    print("-> [3/4] Deduplicando, asignando segmentos y resolviendo LEI / HRB...")
    consolidated = {}
    
    for b in bindings:
        name = b.get('itemLabel', {}).get('value', '').strip()
        ticker = b.get('ticker', {}).get('value', '').strip()
        isin = b.get('isin', {}).get('value', '').strip()
        lei = b.get('lei', {}).get('value', '').strip()
        wkn = b.get('wkn', {}).get('value', '').strip()


        if not name or name.isdigit():
            continue


        # Clave de deduplicación
        key = isin if isin else name.lower()
        if key in consolidated:
            curr = consolidated[key]
            if not curr['ticker'] and ticker: curr['ticker'] = ticker
            if not curr['lei'] and lei: curr['lei'] = lei
            if not curr['wkn'] and wkn: curr['wkn'] = wkn
            continue


        consolidated[key] = {
            'name_raw': name,
            'ticker': ticker,
            'isin': isin,
            'lei': lei,
            'wkn': wkn
        }


    print(f"   [OK] Entidades únicas pre-filtradas: {len(consolidated)}")
    print("-> [4/4] Clasificando segmentos y verificando GLEIF...")


    final_universe = {}
    resolved_leis = 0
    prime_count = 0
    general_count = 0
    scale_count = 0

    async with httpx.AsyncClient() as client:
        tasks = []
        for idx, (k, item) in enumerate(consolidated.items(), 1):
            tasks.append(resolve_gleif_legal(client, item['name_raw'], isin=item['isin']))
        
        results = await asyncio.gather(*tasks)

    for idx, (k, item) in enumerate(consolidated.items(), 1):
        raw_name = item['name_raw']
        isin = item['isin']
        lei = item['lei']
        wkn = item['wkn']
        ticker = item['ticker']


        # Determinar índice y segmento
        matched_indices = []
        for name_frag, idx_list in idx_memberships.items():
            if name_frag in raw_name.lower():
                for idx_item in idx_list:
                    if idx_item not in matched_indices:
                        matched_indices.append(idx_item)


        if any(x in matched_indices for x in ['DAX40', 'MDAX', 'SDAX', 'TECDAX']):
            segment = "PRIME_STANDARD"
            prime_count += 1
        elif 'SCALE' in matched_indices:
            segment = "SCALE_GROWTH"
            scale_count += 1
        else:
            segment = "GENERAL_STANDARD"
            general_count += 1


        # Resolver LEI y HRB si falta
        hrb = ""
        legal_name = raw_name
        g_lei, g_name, g_hrb = results[idx-1]
        if not lei and g_lei:
            lei = g_lei
        if g_name:
            legal_name = g_name
        if g_hrb:
            hrb = g_hrb


        if lei:
            resolved_leis += 1


        # Ticker fallback
        if not ticker:
            ticker = re.sub(r'[^A-Z0-9]', '', raw_name.upper())[:4]


        # Evitar colisiones de clave ticker
        final_ticker = ticker
        counter = 1
        while final_ticker in final_universe:
            counter += 1
            final_ticker = f"{ticker}_{counter}"


        final_universe[final_ticker] = {
            "ticker": final_ticker,
            "isin": isin,
            "wkn": wkn,
            "lei": lei,
            "hrb_reg": hrb,
            "name_legal": legal_name,
            "name_common": raw_name,
            "segment": segment,
            "index_membership": matched_indices,
            "jurisdiction": "DE",
            "supervisor": "BaFin / Unternehmensregister",
            "currency": "EUR",
            "is_active": True
        }


        if idx % 50 == 0 or idx == len(consolidated):
            print(f"   [{idx:03d}/{len(consolidated):03d}] {final_ticker:<8} | {legal_name[:25]:<25} | Seg: {segment:<16} | LEI: {lei[:12]}...")


    doc = {
        "version": "2.0.0",
        "jurisdiction": "DE",
        "country_name": "Germany",
        "supervisor": "BaFin / Unternehmensregister",
        "market_operator": "Deutsche Börse AG (XETRA / Börse Frankfurt)",
        "total_entities": len(final_universe),
        "generated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "segments_breakdown": {
            "PRIME_STANDARD": prime_count,
            "GENERAL_STANDARD": general_count,
            "SCALE_GROWTH": scale_count
        },
        "stats": {
            "resolved_leis": resolved_leis,
            "resolution_rate": f"{(resolved_leis / len(final_universe) * 100):.1f}%" if final_universe else "0%"
        },
        "companies": final_universe
    }


    OUTPUT_FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding='utf-8')
    print("\n=========================================================================")
    print(f"[EXITO] UNIVERSO TOTAL ALEMÁN GENERADO: {len(final_universe)} EMPRESAS")
    print(f"        Archivo: {OUTPUT_FILE}")
    print(f"        Prime Standard:   {prime_count}")
    print(f"        General Standard: {general_count}")
    print(f"        Scale (Growth):   {scale_count}")
    print(f"        LEIs Oficiales:   {resolved_leis} ({doc['stats']['resolution_rate']})")
    print("=========================================================================")


if __name__ == '__main__':
    asyncio.run(main())
