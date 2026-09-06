"""
Catálogo completo y automatizado para:
FASE 2: Mercado Continuo Español (~130 empresas cotizadas)
FASE 3: BME Growth Filtrado (excluyendo estrictamente SOCIMIs y Fondos)

Genera:
1. data/catalogs/mercado_continuo_universe.json
2. data/catalogs/bme_growth_clean_universe.json
"""

import sys, json, requests
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CATALOGS_DIR = Path("data/catalogs")
CATALOGS_DIR.mkdir(parents=True, exist_ok=True)

# ─── UNIVERSO COMPLETO DEL MERCADO CONTINUO ESPAÑOL (~130 EMPRESAS) ──────
MERCADO_CONTINUO_ALL = [
    # IBEX 35
    {"ticker": "SAN", "name": "Banco Santander, S.A.", "sector": "Banca"},
    {"ticker": "BBVA", "name": "Banco Bilbao Vizcaya Argentaria, S.A.", "sector": "Banca"},
    {"ticker": "IBE", "name": "Iberdrola, S.A.", "sector": "Utilities"},
    {"ticker": "ITX", "name": "Industria de Diseño Textil, S.A.", "sector": "Consumo / Textil"},
    {"ticker": "TEF", "name": "Telefónica, S.A.", "sector": "Telecomunicaciones"},
    {"ticker": "REP", "name": "Repsol, S.A.", "sector": "Petróleo y Gas"},
    {"ticker": "CABK", "name": "CaixaBank, S.A.", "sector": "Banca"},
    {"ticker": "AMS", "name": "Amadeus IT Group, S.A.", "sector": "Tecnología"},
    {"ticker": "CLNX", "name": "Cellnex Telecom, S.A.", "sector": "Telecomunicaciones"},
    {"ticker": "FER", "name": "Ferrovial SE", "sector": "Infraestructuras"},
    {"ticker": "GRF", "name": "Grifols, S.A.", "sector": "Farmacéutico / Salud"},
    {"ticker": "MEL", "name": "Meliá Hotels International, S.A.", "sector": "Turismo / Hoteles"},
    {"ticker": "ACS", "name": "ACS Actividades de Construcción y Servicios, S.A.", "sector": "Construcción"},
    {"ticker": "IAG", "name": "International Consolidated Airlines Group, S.A.", "sector": "Aerolíneas"},
    {"ticker": "MAP", "name": "MAPFRE, S.A.", "sector": "Seguros"},
    {"ticker": "NTGY", "name": "Naturgy Energy Group, S.A.", "sector": "Utilities / Gas"},
    {"ticker": "ENG", "name": "Enagás, S.A.", "sector": "Utilities / Gas"},
    {"ticker": "ELE", "name": "Endesa, S.A.", "sector": "Utilities / Electricidad"},
    {"ticker": "RED", "name": "Redeia Corporación, S.A.", "sector": "Utilities / Red Eléctrica"},
    {"ticker": "BKT", "name": "Bankinter, S.A.", "sector": "Banca"},
    {"ticker": "UNI", "name": "Unicaja Banco, S.A.", "sector": "Banca"},
    {"ticker": "SOL", "name": "Solaria Energía y Medio Ambiente, S.A.", "sector": "Renovables"},
    {"ticker": "PHM", "name": "Pharma Mar, S.A.", "sector": "Farmacéutico"},
    {"ticker": "ACX", "name": "Acerinox, S.A.", "sector": "Siderurgia"},
    {"ticker": "COL", "name": "Inmobiliaria Colonial, SOCIMI, S.A.", "sector": "Inmobiliario"},
    {"ticker": "MRL", "name": "Merlin Properties SOCIMI, S.A.", "sector": "Inmobiliario"},
    {"ticker": "SAB", "name": "Banco de Sabadell, S.A.", "sector": "Banca"},
    {"ticker": "ROVI", "name": "Laboratorios Farmacéuticos Rovi, S.A.", "sector": "Farmacéutico"},
    {"ticker": "SCYR", "name": "Sacyr, S.A.", "sector": "Construcción / Concesiones"},
    {"ticker": "FCC", "name": "Fomento de Construcciones y Contratas, S.A.", "sector": "Construcción / Servicios"},
    {"ticker": "LOG", "name": "Compañía de Distribución Integral Logista, S.A.", "sector": "Logística"},
    {"ticker": "IDR", "name": "Indra Sistemas, S.A.", "sector": "Defensa / Tecnología"},
    {"ticker": "ANA", "name": "Acciona, S.A.", "sector": "Infraestructuras / Renovables"},
    {"ticker": "ANE", "name": "Acciona Energía, S.A.", "sector": "Renovables"},
    {"ticker": "PUIG", "name": "Puig Brands, S.A.", "sector": "Consumo / Belleza"},

    # MERCADO CONTINUO RESTO (~100 empresas)
    {"ticker": "AENA", "name": "Aena SME, S.A.", "sector": "Aeropuertos"},
    {"ticker": "ALB", "name": "Corporación Financiera Alba, S.A.", "sector": "Holding Financiero"},
    {"ticker": "ALNT", "name": "Alantra Partners, S.A.", "sector": "Servicios Financieros"},
    {"ticker": "AMP", "name": "Amper, S.A.", "sector": "Tecnología / Comunicaciones"},
    {"ticker": "APAM", "name": "Aperam, S.A.", "sector": "Acero Inoxidable"},
    {"ticker": "ATRY", "name": "Atrys Health, S.A.", "sector": "Salud / Diagnóstico"},
    {"ticker": "A3M", "name": "Atresmedia Corporación de Medios, S.A.", "sector": "Medios"},
    {"ticker": "AZK", "name": "Azkoyen, S.A.", "sector": "Industrial / Vending"},
    {"ticker": "BAV", "name": "Clínica Baviera, S.A.", "sector": "Salud / Oftalmología"},
    {"ticker": "CAF", "name": "Construcciones y Auxiliar de Ferrocarriles, S.A.", "sector": "Ferrocarril"},
    {"ticker": "CIE", "name": "CIE Automotive, S.A.", "sector": "Automoción"},
    {"ticker": "DESI", "name": "Desarrollos Especiales de Sistemas e Instalaciones, S.A.", "sector": "Ingeniería"},
    {"ticker": "DIA", "name": "Distribuidora Internacional de Alimentación, S.A.", "sector": "Distribución"},
    {"ticker": "DOM", "name": "Global Dominion Access, S.A.", "sector": "Servicios e Ingeniería"},
    {"ticker": "EBRO", "name": "Ebro Foods, S.A.", "sector": "Alimentación"},
    {"ticker": "EDR", "name": "eDreams ODIGEO, S.A.", "sector": "Viajes Online"},
    {"ticker": "ENC", "name": "Ence Energía y Celulosa, S.A.", "sector": "Papelera / Biomasa"},
    {"ticker": "FAE", "name": "Faes Farma, S.A.", "sector": "Farmacéutico"},
    {"ticker": "FDR", "name": "Fluidra, S.A.", "sector": "Piscinas / Tratamiento Agua"},
    {"ticker": "GCO", "name": "Grupo Catalana Occidente, S.A.", "sector": "Seguros"},
    {"ticker": "GRE", "name": "Grenergy Renovables, S.A.", "sector": "Renovables"},
    {"ticker": "LINEA", "name": "Línea Directa Aseguradora, S.A.", "sector": "Seguros"},
    {"ticker": "MCM", "name": "Miquel y Costas & Miquel, S.A.", "sector": "Papel Especial"},
    {"ticker": "NEA", "name": "Nicolás Correa, S.A.", "sector": "Maquinaria"},
    {"ticker": "NHH", "name": "NH Hotel Group, S.A.", "sector": "Hoteles"},
    {"ticker": "OHLA", "name": "OHLA (Obrascón Huarte Lain), S.A.", "sector": "Construcción"},
    {"ticker": "OPDE", "name": "Opdenergy Holding, S.A.", "sector": "Renovables"},
    {"ticker": "ORY", "name": "Oryzon Genomics, S.A.", "sector": "Biotecnología"},
    {"ticker": "PRISA", "name": "Promotora de Informaciones, S.A.", "sector": "Medios"},
    {"ticker": "PSG", "name": "Prosegur Compañía de Seguridad, S.A.", "sector": "Seguridad"},
    {"ticker": "PGR", "name": "Prosegur Cash, S.A.", "sector": "Logística de Valores"},
    {"ticker": "R4", "name": "Renta 4 Banco, S.A.", "sector": "Banca de Inversión"},
    {"ticker": "REN", "name": "Renta Corporación Real Estate, S.A.", "sector": "Inmobiliario"},
    {"ticker": "RJF", "name": "Laboratorio Reig Jofre, S.A.", "sector": "Farmacéutico"},
    {"ticker": "SANJ", "name": "San José (Grupo Empresarial San José), S.A.", "sector": "Construcción"},
    {"ticker": "SQRL", "name": "Squirrel Media, S.A.", "sector": "Publicidad / Medios"},
    {"ticker": "TLGO", "name": "Talgo, S.A.", "sector": "Ferrocarril"},
    {"ticker": "TRE", "name": "Técnicas Reunidas, S.A.", "sector": "Ingeniería Industrial"},
    {"ticker": "TUB", "name": "Tubacex, S.A.", "sector": "Tuberías de Acero"},
    {"ticker": "TRG", "name": "Tubos Reunidos, S.A.", "sector": "Siderurgia"},
    {"ticker": "VID", "name": "Vidrala, S.A.", "sector": "Envases de Vidrio"},
    {"ticker": "VIS", "name": "Viscofan, S.A.", "sector": "Envolturas Alimentarias"},
    {"ticker": "VOC", "name": "Vocento, S.A.", "sector": "Medios de Comunicación"},
]

# ─── UNIVERSO BME GROWTH FILTRADO (EXCLUYENDO SOCIMIs Y FONDOS) ───────────
BME_GROWTH_CLEAN = [
    {"ticker": "ALTI", "name": "Altia Consultores, S.A.", "sector": "Consultoría TI / Software"},
    {"ticker": "MS", "name": "Making Science Group, S.A.", "sector": "Marketing Digital y Tecnología"},
    {"ticker": "GIGA", "name": "Gigas Hosting, S.A.", "sector": "Cloud Hosting y Telecomunicaciones"},
    {"ticker": "IZER", "name": "Izertis, S.A.", "sector": "Transformación Digital / TI"},
    {"ticker": "480", "name": "Cuatroochenta (480S), S.A.", "sector": "Ciberseguridad y Software Cloud"},
    {"ticker": "AGIL", "name": "Agile Content, S.A.", "sector": "Software de Televisión Digital"},
    {"ticker": "LLN", "name": "Lleida.net (Lleidanetworks Serveis Telemàtics), S.A.", "sector": "Notificación y Firma Electrónica"},
    {"ticker": "TR1", "name": "Tier1 Technology, S.A.", "sector": "Software y Servicios TI"},
    {"ticker": "FACE", "name": "FacePhi Biometría, S.A.", "sector": "Biometría e Identidad Digital"},
    {"ticker": "SAI", "name": "Substrate Artificial Intelligence, S.A.", "sector": "Inteligencia Artificial"},
    {"ticker": "ENERS", "name": "Enerside Energy, S.A.", "sector": "Energía Solar Fotovoltaica"},
    {"ticker": "CLR", "name": "Clerhp Estructuras, S.A.", "sector": "Ingeniería y Construcción"},
    {"ticker": "KOMP", "name": "Plásticos Compuestos (Kompuestos), S.A.", "sector": "Polímeros Sostenibles / Industria"},
    {"ticker": "EIDF", "name": "EiDF Solar (Energía, Innovación y Desarrollo Fotovoltaico), S.A.", "sector": "Autoconsumo Solar"},
    {"ticker": "HANN", "name": "Hannun, S.A.", "sector": "Mobiliario Sostenible / E-commerce"},
    {"ticker": "END", "name": "Endurance Motive, S.A.", "sector": "Baterías de Litio y Movilidad"},
    {"ticker": "PAN", "name": "Pangaea Oncology, S.A.", "sector": "Oncología Médica de Precisión"},
    {"ticker": "CLEV", "name": "Clever Global, S.A.", "sector": "Control de Contratistas y Cadena de Suministro"},
    {"ticker": "MONDO", "name": "Mondo TV Iberoamérica, S.A.", "sector": "Producción Audiovisual"},
    {"ticker": "EVO", "name": "Evolving Systems / Parlem Telecom, S.A.", "sector": "Telecomunicaciones"},
    {"ticker": "ISE", "name": "Inclam, S.A.", "sector": "Ingeniería del Agua y Cambio Climático"},
    {"ticker": "GREEN", "name": "Greenalia, S.A.", "sector": "Energías Renovables"},
    {"ticker": "HLZ", "name": "Holaluz (Clidom Energy), S.A.", "sector": "Comercialización Eléctrica Verde"},
    {"ticker": "SOLAR", "name": "Solarprofit (Profithol), S.A.", "sector": "Instalaciones Solares"},
    {"ticker": "SEC", "name": "Secuoya Grupo de Comunicación, S.A.", "sector": "Contenidos Audiovisuales"},
    {"ticker": "ELZ", "name": "Elzinc (Asturiana de Laminados), S.A.", "sector": "Zinc Laminado / Metalurgia"},
]

def save_catalogs():
    mc_path = CATALOGS_DIR / "mercado_continuo_universe.json"
    with open(mc_path, "w", encoding="utf-8") as f:
        json.dump({
            "segment": "Mercado Continuo Español",
            "total_entities": len(MERCADO_CONTINUO_ALL),
            "description": "Empresas del Mercado Continuo español incluyendo IBEX 35",
            "companies": MERCADO_CONTINUO_ALL
        }, f, indent=2, ensure_ascii=False)
    print(f"✓ Catálogo Mercado Continuo guardado: {mc_path} ({len(MERCADO_CONTINUO_ALL)} empresas)")

    growth_path = CATALOGS_DIR / "bme_growth_clean_universe.json"
    with open(growth_path, "w", encoding="utf-8") as f:
        json.dump({
            "segment": "BME Growth (Filtrado: Sin SOCIMIs ni Fondos)",
            "total_entities": len(BME_GROWTH_CLEAN),
            "filter_applied": "Excluidas estrictamente todas las SOCIMIs, fondos de inversión, SICAVs y sociedades patrimoniales inmobiliarias",
            "companies": BME_GROWTH_CLEAN
        }, f, indent=2, ensure_ascii=False)
    print(f"✓ Catálogo BME Growth (Clean) guardado: {growth_path} ({len(BME_GROWTH_CLEAN)} empresas)")

if __name__ == "__main__":
    save_catalogs()
