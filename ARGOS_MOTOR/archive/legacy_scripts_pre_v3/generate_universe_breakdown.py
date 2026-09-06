"""
Generador de Informe Forense de Cobertura y Segmentación del Data Lake STATER.
Mapeo exhaustivo de LEI a denominación social y clasificación por capitalización:
- Blue Chips (IBEX 35 / Large Caps: > 4.000 M€)
- Mid Caps (Mercado Continuo Mediano: 500 M€ - 4.000 M€)
- Small Caps / BME Growth (Pequeña capitalización: < 500 M€)
"""

import sys, json, re
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_ES_CNMV = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV")
BASE_BME_GROWTH = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_BME_GROWTH")
BASE_INTERIM = Path(r"c:\Users\jfulg\Desktop\Stater\ARGOS_MOTOR\data\raw\ES_CNMV_INTERIM")

LEI_TO_INFO = {
    # BLUE CHIPS (IBEX 35)
    "5493006QMFDD": ("SAN", "Banco Santander SA", "Blue Chips (IBEX 35)"),
    "K8MS7FD7N5Z2": ("BBVA", "Banco Bilbao Vizcaya Argentaria SA", "Blue Chips (IBEX 35)"),
    "5QK37QC7NWOJ": ("IBE", "Iberdrola SA", "Blue Chips (IBEX 35)"),
    "549300E9PC50": ("ITX", "Industria de Diseño Textil SA (Inditex)", "Blue Chips (IBEX 35)"),
    "549300EEJH4F": ("TEF", "Telefónica SA", "Blue Chips (IBEX 35)"),
    "BSYCX13Y0NOT": ("REP", "Repsol SA", "Blue Chips (IBEX 35)"),
    "7CUNS533WID6": ("CABK", "CaixaBank SA", "Blue Chips (IBEX 35)"),
    "9598004A3FTY": ("AMS", "Amadeus IT Group SA", "Blue Chips (IBEX 35)"),
    "5493008T4YG3": ("CLNX", "Cellnex Telecom SA", "Blue Chips (IBEX 35)"),
    "959800HSSNXW": ("GRF", "Grifols SA", "Blue Chips (IBEX 35)"),
    "959800JRKSZ6": ("MEL", "Meliá Hotels International SA", "Blue Chips (IBEX 35)"),
    "959800TZHQRU": ("IAG", "International Airlines Group (IAG)", "Blue Chips (IBEX 35)"),
    "TL2N6M87CW97": ("NTGY", "Naturgy Energy Group SA", "Blue Chips (IBEX 35)"),
    "213800OU3FQK": ("ENG", "Enagás SA", "Blue Chips (IBEX 35)"),
    "549300LHK07F": ("ELE", "Endesa SA", "Blue Chips (IBEX 35)"),
    "5493009HMD0C": ("RED", "Redeia Corporación SA", "Blue Chips (IBEX 35)"),
    "VWMYAEQSTOPN": ("BKT", "Bankinter SA", "Blue Chips (IBEX 35)"),
    "5493007SJLLC": ("UNI", "Unicaja Banco SA", "Blue Chips (IBEX 35)"),
    "959800PM2YJU": ("SOL", "Solaria Energía y Medio Ambiente SA", "Blue Chips (IBEX 35)"),
    "959800QWKZ45": ("PHM", "PharmaMar SA", "Blue Chips (IBEX 35)"),
    "959800L8KD86": ("MRL", "Merlin Properties SOCIMI SA", "Blue Chips (IBEX 35)"),
    "SI5RG2M0WQQL": ("SAB", "Banco de Sabadell SA", "Blue Chips (IBEX 35)"),
    "959800XKAB9V": ("SCYR", "Sacyr SA", "Blue Chips (IBEX 35)"),
    "549300OVHNSX": ("PUIG", "Puig Brands SA", "Blue Chips (IBEX 35)"),
    "959800R7QMXK": ("AENA", "Aena SME SA", "Blue Chips (IBEX 35)"),
    "54930002KP75": ("ANA", "Acciona SA", "Blue Chips (IBEX 35)"),
    "254900UPX0OE": ("ANE", "Acciona Energía SA", "Blue Chips (IBEX 35)"),

    # MID CAPS (MERCADO CONTINUO)
    "959800FXZQY7": ("FAE", "Faes Farma SA", "Mid Caps"),
    "959800NW6DLQ": ("EBRO", "Ebro Foods SA", "Mid Caps"),
    "95980037JECH": ("TLGO", "Talgo SA", "Mid Caps"),
    "959800M1FVPL": ("GRE", "Grenergy Renovables SA", "Mid Caps"),
    "54930063C6K2": ("DIA", "Distribuidora Internacional de Alimentación (DIA)", "Mid Caps"),
    "959800H2P9S8": ("GCO", "Grupo Catalana Occidente SA", "Mid Caps"),
    "529900MUFAH0": ("EDPR", "EDP Renováveis SA", "Mid Caps"),
    "959800GZESQU": ("AMP", "Amper SA", "Mid Caps"),
    "959800AXZW3E": ("AZK", "Azkoyen SA", "Mid Caps"),
    "959800CR1BA4": ("BAV", "Clínica Baviera SA", "Mid Caps"),
    "959800U3NGPX": ("PRS", "Promotora de Informaciones SA (PRISA)", "Mid Caps"),
    "9598005HY5DE": ("PGR", "Prosegur Cash SA", "Mid Caps"),
    "549300N94L4D": ("PSG", "Prosegur Compañía de Seguridad SA", "Mid Caps"),
    "213800IMKAUV": ("R4", "Renta 4 Banco SA", "Mid Caps"),
    "959800N1575U": ("REN", "Renta Corporación Real Estate SA", "Mid Caps"),
    "9598003MRMJH": ("RJF", "Laboratorio Reig Jofre SA", "Mid Caps"),
    "9598002SMUBZ": ("SANJ", "Grupo Empresarial San José SA", "Mid Caps"),
    "959800NZ03Z4": ("SQRL", "Squirrel Media SA", "Mid Caps"),
    "213800JEZBUP": ("TRE", "Técnicas Reunidas SA", "Mid Caps"),
    "959800EXHG00": ("NEA", "Nicolás Correa SA", "Mid Caps"),
    "95980078NDTD": ("ALNT", "Alantra Partners SA", "Mid Caps"),
    "959800LM1RW3": ("NHH", "Minor Hotels Europe & Americas (NH)", "Mid Caps"),
    "959800JRJW1C": ("CEMT", "Cementos Molins SA", "Mid Caps"),
    "959800FW4JL6": ("NEIN", "Neinor Homes SA", "Mid Caps"),
    "959800L6L2B2": ("SOLT", "Soltec Power Holdings SA", "Mid Caps"),
    "959800HBGZWH": ("ECO", "Ecoener SA", "Mid Caps"),
    "213800M9XCA6": ("APPS", "Applus Services SA", "Mid Caps"),
    "959800FQZ6YA": ("INMO", "Inmocemento SA", "Mid Caps"),
    "95980079E2NB": ("LINEA", "Línea Directa Aseguradora SA", "Mid Caps"),
    "959800Z611RK": ("ERC", "Ercros SA", "Mid Caps"),
    "959800M75M81": ("PRM", "Prim SA", "Mid Caps"),
    "959800CJH35N": ("ALB", "Corporación Financiera Alba SA", "Mid Caps"),
    "959800ZQW44V": ("MVC", "Metrovacesa SA", "Mid Caps"),
    "959800WGUAJ7": ("ISUR", "Inmobiliaria del Sur SA", "Mid Caps"),
    "959800K5R280": ("ARIM", "Arima Real Estate SOCIMI SA", "Mid Caps"),
    "959800KT1FVN": ("OPDE", "Opdenergy Holding SA", "Mid Caps"),
    "959800RG37G8": ("IBP", "Iberpapel Gestión SA", "Mid Caps"),
    "959800PV7FH0": ("LGT", "Lingotes Especiales SA", "Mid Caps"),
    "549300TTCXZO": ("EDR", "eDreams ODIGEO SA", "Mid Caps"),
    "549300OLBL49": ("IBCA", "Ibercaja Banco SA", "Mid Caps"),
    "635400XT3V7W": ("LBK", "Liberbank SA", "Mid Caps"),
    "549300685QG7": ("BKIA", "Bankia SA", "Mid Caps"),
    "959800NAFTNQ": ("SLPK", "Solarpack Corporación Tecnológica SA", "Mid Caps"),
    "259400T6ZDQI": ("EAT", "AmRest Holdings SE", "Mid Caps"),
    "5493000LM0MZ": ("SCF", "Santander Consumer Finance SA", "Mid Caps"),
}

TICKER_MAP = {
    "SAN": ("Banco Santander SA", "Blue Chips (IBEX 35)"),
    "BBVA": ("Banco Bilbao Vizcaya Argentaria SA", "Blue Chips (IBEX 35)"),
    "IBE": ("Iberdrola SA", "Blue Chips (IBEX 35)"),
    "ITX": ("Industria de Diseño Textil SA", "Blue Chips (IBEX 35)"),
    "TEF": ("Telefónica SA", "Blue Chips (IBEX 35)"),
    "REP": ("Repsol SA", "Blue Chips (IBEX 35)"),
    "CABK": ("CaixaBank SA", "Blue Chips (IBEX 35)"),
    "AMS": ("Amadeus IT Group SA", "Blue Chips (IBEX 35)"),
    "CLNX": ("Cellnex Telecom SA", "Blue Chips (IBEX 35)"),
    "FER": ("Ferrovial SE", "Blue Chips (IBEX 35)"),
    "GRF": ("Grifols SA", "Blue Chips (IBEX 35)"),
    "MEL": ("Meliá Hotels International SA", "Blue Chips (IBEX 35)"),
    "ACS": ("ACS Actividades de Construcción SA", "Blue Chips (IBEX 35)"),
    "IAG": ("International Airlines Group", "Blue Chips (IBEX 35)"),
    "MAP": ("MAPFRE SA", "Blue Chips (IBEX 35)"),
    "NTGY": ("Naturgy Energy Group SA", "Blue Chips (IBEX 35)"),
    "ENG": ("Enagás SA", "Blue Chips (IBEX 35)"),
    "ELE": ("Endesa SA", "Blue Chips (IBEX 35)"),
    "RED": ("Redeia Corporación SA", "Blue Chips (IBEX 35)"),
    "BKT": ("Bankinter SA", "Blue Chips (IBEX 35)"),
    "UNI": ("Unicaja Banco SA", "Blue Chips (IBEX 35)"),
    "SOL": ("Solaria Energía y Medio Ambiente SA", "Blue Chips (IBEX 35)"),
    "PHM": ("PharmaMar SA", "Blue Chips (IBEX 35)"),
    "ACX": ("Acerinox SA", "Blue Chips (IBEX 35)"),
    "COL": ("Inmobiliaria Colonial SOCIMI SA", "Blue Chips (IBEX 35)"),
    "MRL": ("Merlin Properties SOCIMI SA", "Blue Chips (IBEX 35)"),
    "SAB": ("Banco de Sabadell SA", "Blue Chips (IBEX 35)"),
    "ROVI": ("Laboratorios Farmacéuticos Rovi SA", "Blue Chips (IBEX 35)"),
    "SCYR": ("Sacyr SA", "Blue Chips (IBEX 35)"),
    "LOG": ("Logista SA", "Blue Chips (IBEX 35)"),
    "IDR": ("Indra Sistemas SA", "Blue Chips (IBEX 35)"),
    "ANA": ("Acciona SA", "Blue Chips (IBEX 35)"),
    "ANE": ("Acciona Energía SA", "Blue Chips (IBEX 35)"),
    "PUIG": ("Puig Brands SA", "Blue Chips (IBEX 35)"),
    "AENA": ("Aena SME SA", "Blue Chips (IBEX 35)"),
}

def resolve_folder(folder_name):
    prefix = folder_name.split('_')[0].upper()
    if prefix in TICKER_MAP:
        name, cat = TICKER_MAP[prefix]
        return prefix, name, cat
    for lei, (t, n, c) in LEI_TO_INFO.items():
        if prefix.startswith(lei[:8]):
            return t, n, c
    return prefix, folder_name, "Small Caps / BME Growth"

def run_analysis():
    by_year = defaultdict(lambda: defaultdict(list))
    all_unique_companies = {}
    
    for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
        yd = BASE_ES_CNMV / y
        if not yd.exists():
            continue
        for d in yd.iterdir():
            if d.is_dir() and (d / 'extracted').exists() and any((d / 'extracted').iterdir()):
                ticker, comp_name, category = resolve_folder(d.name)
                by_year[y][category].append((ticker, comp_name))
                all_unique_companies[ticker] = (comp_name, category)
                
    print("=" * 80)
    print("INVENTARIO FORENSE DEL DATA LAKE: DISTRIBUCIÓN POR AÑOS Y CAPITALIZACIÓN")
    print("=" * 80)
    
    for y in sorted(by_year.keys()):
        bc = by_year[y]['Blue Chips (IBEX 35)']
        mc = by_year[y]['Mid Caps']
        sc = by_year[y]['Small Caps / BME Growth']
        tot = len(bc) + len(mc) + len(sc)
        
        print(f"\n📅 EJERCICIO {y} (Total: {tot} empresas)")
        print(f"   🏛  Blue Chips (IBEX 35):         {len(bc):2d} empresas")
        print(f"   🏢  Mid Caps (Mercado Continuo):  {len(mc):2d} empresas")
        print(f"   🌱  Small Caps / BME Growth:      {len(sc):2d} empresas")
        
    print("\n" + "=" * 80)
    print("TOTALES GLOBALES DE EMPRESAS ÚNICAS EN EL DATA LAKE:")
    
    cats = defaultdict(list)
    for t, (n, c) in all_unique_companies.items():
        cats[c].append((t, n))
        
    print(f"   🏛  Blue Chips únicas (IBEX 35):         {len(cats['Blue Chips (IBEX 35)']):2d} empresas")
    print(f"   🏢  Mid Caps únicas (Mercado Continuo):  {len(cats['Mid Caps']):2d} empresas")
    print(f"   🌱  Small Caps / Growth únicas:          {len(cats['Small Caps / BME Growth']):2d} empresas")
    print(f"   🌟  TOTAL EMPRESAS DISTINTAS EN DATA LAKE: {len(all_unique_companies):2d} empresas")
    print("=" * 80)
    
    return by_year, all_unique_companies

if __name__ == "__main__":
    run_analysis()
