import requests
import json
import urllib.request
from pathlib import Path
import hashlib
import datetime

# ------------------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR.parent.parent / "config"
OUTPUT_UNIVERSE_PATH = CONFIG_DIR / "master_universe_de.json"
OUTPUT_MATRIX_PATH = CONFIG_DIR / "UNIVERSE_DE_ANNUAL_MATRIX.json"

BOERSE_FRANKFURT_API_URL = "https://api.boerse-frankfurt.de/v1/indices/CONSTITUENTS-{index_short_name}/composition"
GLEIF_API_URL = "https://api.gleif.org/api/v1/lei-records?filter[isin]={isin}"
ESEF_API_URL = "https://filings.xbrl.org/api/filings?include=entity"

# ------------------------------------------------------------------
# FUNCIONES DE ADQUISICIÓN DE DATOS
# ------------------------------------------------------------------

def get_companies_from_boerse_frankfurt(index_short_name: str, segment: str):
    """Obtiene la lista de empresas de la API de Boerse Frankfurt."""
    print(f"Descargando la lista de empresas para el índice {segment}...")
    companies = []
    url = BOERSE_FRANKFURT_API_URL.format(index_short_name=index_short_name)
    response = requests.get(url)
    data = response.json()
    print(data)
    for item in data['data']:
        companies.append({
            "name_legal": item['name'],
            "isin": item['isin'],
            "wkn": item['wkn'],
            "ticker": item['symbol'],
            "segment": segment
        })
    return companies

def get_lei_from_gleif(isin: str):
    """Obtiene el LEI de la API de GLEIF."""
    print(f"Buscando LEI para ISIN {isin}...")
    try:
        with urllib.request.urlopen(GLEIF_API_URL.format(isin=isin)) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data['data']:
                return data['data'][0]['attributes']['lei']
    except Exception as e:
        print(f"Error al buscar LEI para {isin}: {e}")
    return None

def get_esef_filings():
    """Obtiene los filings de ESEF para Alemania."""
    print("Descargando filings de ESEF...")
    filings = []
    url = ESEF_API_URL
    while url:
        print(f"Descargando desde {url}...")
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode('utf-8'))
            filings.extend(data['data'])
            url = data['links'].get('next')
            # For testing, limit to 2 pages
            if len(filings) > 500:
                break

    # Filter for German companies
    german_filings = []
    for filing in filings:
        entity = filing.get('relationships', {}).get('entity', {}).get('data', {})
        if entity and entity.get('id'):
            # The entity ID is the LEI
            lei = entity.get('id')
            # German LEIs start with 5299
            if lei.startswith('5299'):
                german_filings.append(filing)
                
    return german_filings

# ------------------------------------------------------------------
# FUNCIÓN PRINCIPAL
# ------------------------------------------------------------------

def build_universe():
    """Orquesta la construcción del universo."""
    print("Iniciando la construcción del universo alemán...")
    companies = {}

    # 1. Obtener la lista de empresas de Boerse Frankfurt
    dax_companies = get_companies_from_boerse_frankfurt("dax-40", "DAX40")
    mdax_companies = get_companies_from_boerse_frankfurt("mdax", "MDAX50")
    sdax_companies = get_companies_from_boerse_frankfurt("sdax", "SDAX70")
    tecdax_companies = get_companies_from_boerse_frankfurt("tecdax", "TECDAX30")

    all_companies = dax_companies + mdax_companies + sdax_companies + tecdax_companies

    for company in all_companies:
        companies[company['isin']] = company

    print(f"Encontradas {len(companies)} empresas en los índices alemanes.")

    # 2. Obtener LEIs de GLEIF
    for isin, company in companies.items():
        company['lei'] = get_lei_from_gleif(isin)

    # 3. Obtener historial de filings de ESEF
    esef_filings = get_esef_filings()
    print(f"Encontrados {len(esef_filings)} filings de ESEF para empresas alemanas.")
    # TODO: Procesar los datos de ESEF para determinar los años activos

    # 4. Clasificar y estructurar los datos
    # TODO: Unir toda la información y clasificar las empresas

    # 5. Generar archivos de salida
    # TODO: Escribir master_universe_de.json y UNIVERSE_DE_ANNUAL_MATRIX.json

    print("Universo alemán construido con éxito.")
    print(f"Total de empresas en el universo: {len(companies)}")
    # Print first 5 companies
    for i, (isin, company) in enumerate(companies.items()):
        if i >= 5:
            break
        print(company)

if __name__ == "__main__":
    build_universe()