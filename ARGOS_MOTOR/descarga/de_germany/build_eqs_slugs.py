"""
ARGOS MOTOR -- Generador del Mapa de Slugs Corporativos EQS / DGAP (Alemania)
Genera ARGOS_MOTOR/config/eqs_company_slugs.json a partir de las empresas de Prime Standard.
"""

import json
import re
from pathlib import Path

ARGOS_DIR = Path(__file__).resolve().parent.parent.parent
COS_FILE = ARGOS_DIR / 'config' / 'prime_standard_companies.json'
DEST_FILE = ARGOS_DIR / 'config' / 'eqs_company_slugs.json'

KNOWN_ALIASES = {
    'BASF': ['BASF'], 'BMW': ['BMW'], 'BAYE_5': ['BMW'],
    'SIEM': ['Siemens'], 'SIEM_2': ['Siemens'], 'SMTS': ['Siemens'],
    'RWE': ['RWE'], 'DE_RWE': ['RWE'],
    'MERC': ['Daimler', 'MercedesBenz', 'Mercedes-Benz'],
    'HEID': ['HeidelbergCement', 'HeidelbergMaterials'],
    'AIRB': ['eads', 'Airbus', 'EADS'], 'AIR': ['eads', 'Airbus'],
    'DHLG': ['DeutschePost', 'dhl', 'DHL'], 'DHL': ['DeutschePost', 'DHL'],
    'FRES': ['Fresenius'], 'FRES_2': ['FMC', 'FreseniusMedicalCare'],
    'MUV2': ['MunichRe', 'MuenchenerRueck'], 'MUTA': ['MunichRe', 'Mutares'],
    'HLE': ['HannoverRueck', 'HannoverRe'],
    'THYS': ['Thyssenkrupp', 'thyssenkrupp'], 'THYS_2': ['Thyssenkrupp'],
    'VOW3': ['Volkswagen'], 'VOLK': ['Volkswagen'], 'VOLK_2': ['Volkswagen'],
    'BAYN': ['Bayer'], 'BAYE_3': ['Bayer'],
    'ALV': ['Allianz'], 'ALLI': ['Allianz'],
    'DTE': ['DeutscheTelekom', 'Telekom'], 'DEUT': ['DeutscheTelekom', 'Telekom'],
    'DBK': ['DeutscheBank'], 'DEUT_2': ['DeutscheBank'],
    'CBK': ['Commerzbank'], 'COMM': ['Commerzbank'],
    'EOAN': ['EON', 'E.ON'], 'DE_EON': ['EON', 'E.ON'],
    'SAP': ['SAP'], 'SAPS': ['SAP'],
    'CON': ['Continental'], 'CONTI': ['Continental'], 'CONT': ['Continental'],
    'IFX': ['Infineon'], 'INFI': ['Infineon'],
    'ZAL': ['Zalando'], 'ZALN': ['Zalando'],
    'SY1': ['Symrise'], 'SYMR': ['Symrise'],
    'BEI': ['Beiersdorf'], 'BEI_2': ['Beiersdorf'],
    'BNR': ['Brenntag'],
    'COV': ['Covestro'], '1COV': ['Covestro'],
    'DHER': ['DeliveryHero'],
    'DB1': ['DeutscheBoerse'],
    'G1A': ['Gerresheimer'],
    'GXI': ['Gerresheimer'],
    'HFG': ['HelloFresh'],
    'HEN3': ['Henkel'], 'HNKL': ['Henkel'],
    'KBX': ['KnorrBremse'],
    'KCO': ['Kloeckner'],
    'LEG': ['LEG', 'LEGImmobilien'],
    'MRK': ['Merck'],
    'MTX': ['MTU'],
    'NEM': ['Nemetschek'], 'NGEN': ['Nemetschek'],
    'PUM': ['Puma'],
    'QIA': ['Qiagen'],
    'RHM': ['Rheinmetall'],
    'SRT3': ['Sartorius'], 'SRT': ['Sartorius'],
    'SDF': ['KplusS'],
    'TEG': ['TAGImmobilien'],
    'TKA': ['Thyssenkrupp'],
    'VNA': ['Vonovia'],
    'LUFT': ['Lufthansa', 'DeutscheLufthansa'],
    'LUFT_2': ['Lufthansa', 'DeutscheLufthansa'],
}

def generate_slugs():
    if not COS_FILE.exists():
        raise FileNotFoundError(f"Missing {COS_FILE}")
    companies = json.loads(COS_FILE.read_text(encoding='utf-8'))

    slug_map = {
        '_metadata': {
            'generated_at': '2026-09-23',
            'total_companies': len(companies),
            'purpose': 'EQS / DGAP corporate storage slug mappings for German Prime Standard issuers'
        },
        'companies': {}
    }

    for c in companies:
        ticker = c['ticker']
        isin = c.get('isin', '')
        name_com = c.get('name_common', '')
        name_leg = c.get('name_legal', '')

        slugs = []
        if ticker in KNOWN_ALIASES:
            slugs.extend(KNOWN_ALIASES[ticker])

        clean_com = re.sub(r'[^A-Za-z0-9]', '', name_com)
        if clean_com and clean_com not in slugs:
            slugs.append(clean_com)

        clean_leg = re.sub(r'\b(AG|SE|GmbH|KGaA|Co|KG|PLC|NV|Ltd|Inc)\b', '', name_leg, flags=re.I)
        clean_leg = re.sub(r'[^A-Za-z0-9]', '', clean_leg).strip()
        if clean_leg and clean_leg not in slugs:
            slugs.append(clean_leg)

        clean_ticker = ticker.split('_')[0]
        if clean_ticker not in slugs:
            slugs.append(clean_ticker)
        if ticker not in slugs:
            slugs.append(ticker)

        slug_map['companies'][ticker] = {
            'isin': isin,
            'name': name_leg or name_com,
            'slugs': slugs
        }

    DEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEST_FILE.write_text(json.dumps(slug_map, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Generated EQS slugs for {len(slug_map['companies'])} companies -> {DEST_FILE}")

if __name__ == '__main__':
    generate_slugs()
